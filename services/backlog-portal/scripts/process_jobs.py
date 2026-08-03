#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def request(base_url: str, token: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310
        return json.loads(response.read())


def run_codex(prompt: str, timeout: int) -> str:
    schema = ROOT / "scripts" / "refined_item.schema.json"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output:
        output_path = Path(output.name)
    try:
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
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
        completed = subprocess.run(  # nosec B603
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(f"codex exec failed: {completed.stderr[-2000:]}")
        return output_path.read_text()
    finally:
        output_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process Backlog Portal AI jobs")
    parser.add_argument(
        "--base-url",
        default=os.getenv("APP_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    token = os.getenv("WORKER_TOKEN", "")
    if not token:
        raise RuntimeError("WORKER_TOKEN is required")
    for _ in range(args.limit):
        job = request(args.base_url, token, "/worker/jobs/claim").get("job")
        if not job:
            return 0
        try:
            raw_output = run_codex(job["prompt"], args.timeout)
            request(
                args.base_url,
                token,
                f"/worker/jobs/{job['id']}/complete",
                {"raw_output": raw_output},
            )
        except Exception as exc:
            request(
                args.base_url,
                token,
                f"/worker/jobs/{job['id']}/fail",
                {"error": str(exc)},
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
