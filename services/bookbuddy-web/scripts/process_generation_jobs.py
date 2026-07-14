#!/usr/bin/env python3
"""Host-side generation worker.

Claims pending generation jobs from a running BookBuddy instance (over the
tailnet), runs each prompt through a subscription-billed CLI (codex exec by
default), and posts the JSON output back. This keeps LLM usage on an existing
subscription seat instead of per-token API billing, and keeps all credentials
off the cluster.

Usage:
    python scripts/process_generation_jobs.py --base-url https://bookbuddy.lab.skyhaven.ltd

Requires WORKER_TOKEN in the environment or .env (must match the server's).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "scripts" / "generated_questions.schema.json"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        # The base URL is trusted operator configuration, not remote input.
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{method} {path} failed: HTTP {exc.code}: {detail}"
        ) from exc
    return json.loads(body) if body else {}


def run_codex(
    prompt: str,
    *,
    codex_bin: str,
    schema: Path,
    timeout_seconds: int,
    cwd: Path,
) -> str:
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as out:
        output_path = Path(out.name)
    try:
        command = [
            codex_bin,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--cd",
            str(cwd),
            "-c",
            'approval_policy="never"',
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        # Every argument is passed as an argv element and shell execution is disabled.
        completed = subprocess.run(  # nosec B603
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        last_message = (
            output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"codex exec failed with exit code {completed.returncode}\n"
                f"STDOUT:\n{completed.stdout}\n"
                f"STDERR:\n{completed.stderr}\n"
                f"LAST MESSAGE:\n{last_message}"
            )
        return last_message.strip() or completed.stdout.strip()
    finally:
        output_path.unlink(missing_ok=True)


def process_jobs(args: argparse.Namespace) -> int:
    load_dotenv(ROOT / ".env")
    base_url = args.base_url or os.getenv("APP_BASE_URL") or "http://127.0.0.1:8080"
    token = args.token or os.getenv("WORKER_TOKEN")
    if not token:
        raise RuntimeError("WORKER_TOKEN is required")
    processed = 0
    fake_output = (
        Path(args.fake_output).read_text(encoding="utf-8") if args.fake_output else None
    )
    for _ in range(args.limit):
        claimed = api_request(base_url, token, "POST", "/worker/generation-jobs/claim")
        job = claimed.get("job")
        if not job:
            print("No pending generation jobs")
            break
        job_id = int(job["id"])
        print(f"Processing job {job_id}: {job['book_title']} / {job['chapter_title']}")
        try:
            raw_output = (
                fake_output
                if fake_output is not None
                else run_codex(
                    job["prompt"],
                    codex_bin=args.codex_bin,
                    schema=Path(args.schema),
                    timeout_seconds=args.timeout_seconds,
                    cwd=ROOT,
                )
            )
            completed = api_request(
                base_url,
                token,
                "POST",
                f"/worker/generation-jobs/{job_id}/complete",
                {"raw_output": raw_output},
            )
            print(
                f"Completed job {job_id}; created "
                f"{completed.get('questions_created', 0)} questions"
            )
            processed += 1
        except Exception as exc:
            error_text = str(exc)
            print(f"Job {job_id} failed: {error_text}", file=sys.stderr)
            try:
                api_request(
                    base_url,
                    token,
                    "POST",
                    f"/worker/generation-jobs/{job_id}/fail",
                    {"error": error_text},
                )
            except Exception as report_exc:
                print(
                    f"Could not report failure for job {job_id}: {report_exc}",
                    file=sys.stderr,
                )
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None, help="BookBuddy base URL")
    parser.add_argument("--token", default=None, help="Worker token (or WORKER_TOKEN)")
    parser.add_argument("--limit", type=int, default=10, help="Max jobs per run")
    parser.add_argument("--codex-bin", default="codex", help="codex binary")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument(
        "--fake-output",
        default=None,
        help="Path to a JSON file used instead of calling codex (testing)",
    )
    args = parser.parse_args()
    processed = process_jobs(args)
    print(f"Processed {processed} job(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
