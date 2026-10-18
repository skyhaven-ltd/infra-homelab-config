import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "ansible/roles/appdata_backup/files"
EXPORTER = ROOT / "ansible/roles/homelab_metrics/files/write-homelab-metrics.sh"
SPEC = importlib.util.spec_from_file_location(
    "bazarr_reconcile", ROOT / "kubernetes/apps/bazarr/files/reconcile-settings.py"
)
BAZARR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BAZARR)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.stage = self.root / "stage"
        self.stage.mkdir()
        (self.stage / "appdata_test.tar.gz").write_text("fixture")
        (self.stage / "manifest_test.json").write_text("{}")
        self.state = self.root / "state"
        self.state.mkdir()
        (self.state / "last-upload-success").write_text("100")
        self.config = self.root / "rclone.conf"
        self.config.touch()
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            BACKUP_STAGE=str(self.stage),
            BACKUP_REMOTE="onedrive:test backups",
            BACKUP_STATE_DIR=str(self.state),
            RCLONE_CONFIG=str(self.config),
            CALLS=str(self.root / "calls"),
            FAIL_COMMAND="",
        )
        self.command(
            "rclone",
            """printf '%s\\n' "$*" >>"$CALLS"
if [ "$1" = "$FAIL_COMMAND" ]; then exit 7; fi
""",
        )

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def run_script(self, path):
        script = self.root / path.name
        script.write_text(path.read_text())
        result = subprocess.run(
            ["bash", str(script)],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result

    def test_upload_and_remote_check_precede_success_and_safe_pruning(self):
        result = self.run_script(BACKUP / "sync-backups-to-onedrive.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(int((self.state / "last-upload-success").read_text()), 100)
        self.assertEqual((self.state / "last-prune-ok").read_text().strip(), "1")
        calls = (self.root / "calls").read_text().splitlines()
        self.assertEqual(
            [x.split()[0] for x in calls], ["copy", "check", "delete", "lsf"]
        )
        self.assertIn("--one-way", calls[1])
        for option in ("--min-age 30d", "--max-depth 1", "--max-delete 5"):
            self.assertIn(option, calls[2])

    def test_failed_copy_or_verification_preserves_previous_success(self):
        for command in ("copy", "check"):
            with self.subTest(command=command):
                self.env["FAIL_COMMAND"] = command
                result = self.run_script(BACKUP / "sync-backups-to-onedrive.sh")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    (self.state / "last-upload-success").read_text(), "100"
                )
                self.assertFalse((self.state / "last-prune-ok").exists())

    def test_prune_failure_does_not_mask_verified_upload(self):
        self.env["FAIL_COMMAND"] = "delete"
        result = self.run_script(BACKUP / "sync-backups-to-onedrive.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(int((self.state / "last-upload-success").read_text()), 100)
        self.assertEqual((self.state / "last-prune-ok").read_text().strip(), "0")

    def test_prune_timeout_is_warning_and_next_success_clears_it(self):
        self.command("timeout", "exit 124\n")
        result = self.run_script(BACKUP / "sync-backups-to-onedrive.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.state / "last-prune-ok").read_text().strip(), "0")
        (self.bin / "timeout").unlink()
        self.assertEqual(
            self.run_script(BACKUP / "sync-backups-to-onedrive.sh").returncode, 0
        )
        self.assertEqual((self.state / "last-prune-ok").read_text().strip(), "1")

    def test_failed_listing_does_not_mask_verified_upload(self):
        self.env["FAIL_COMMAND"] = "lsf"
        result = self.run_script(BACKUP / "sync-backups-to-onedrive.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("remote listing failed", result.stderr)

    def test_empty_stage_never_uploads_or_updates_success(self):
        for path in self.stage.iterdir():
            path.unlink()
        self.assertNotEqual(
            self.run_script(BACKUP / "sync-backups-to-onedrive.sh").returncode, 0
        )
        self.assertFalse((self.root / "calls").exists())
        self.assertEqual((self.state / "last-upload-success").read_text(), "100")

    def test_exporter_reports_failures_disabled_timer_and_persistent_success(self):
        self.command("tailscale", "printf '{}'\n")
        self.command(
            "systemctl",
            """case "$*" in
  *appdata-backup.timer*) exit 1;;
  *appdata-backup.service*) echo timeout;;
  *) echo success;;
esac
""",
        )
        self.env.update(
            TEXTFILE_DIR=str(self.root),
            SONARR_HOST="unused",
            SONARR_PROFILE="unused",
            SONARR_API_KEY="",
        )
        (self.state / "last-prune-ok").write_text("0")
        result = self.run_script(EXPORTER)
        self.assertEqual(result.returncode, 0, result.stderr)
        metrics = (self.root / "homelab.prom").read_text()
        for metric in (
            "timer_active 0",
            "last_run_ok 0",
            "last_upload_timestamp_seconds 100",
            "prune_ok 0",
        ):
            self.assertIn(f"homelab_backup_{metric}\n", metrics)
        (self.state / "last-upload-success").unlink()
        (self.state / "last-prune-ok").write_text("invalid")
        self.assertEqual(self.run_script(EXPORTER).returncode, 0)
        metrics = (self.root / "homelab.prom").read_text()
        self.assertIn("homelab_backup_last_upload_timestamp_seconds 0\n", metrics)
        self.assertIn("homelab_backup_prune_ok -1\n", metrics)


class BazarrTests(unittest.TestCase):
    def test_reconcile_preserves_other_profiles_and_assigns_only_unassigned_media(self):
        other = dict(
            profileId=7,
            name="French",
            items=[],
            cutoff=None,
            mustContain=[],
            mustNotContain=[],
            originalFormat=False,
        )
        profiles = [other]
        calls = []

        def request(path, key, payload=None):
            if payload:
                calls.append((path, copy.deepcopy(payload)))
                if "languages-profiles" in payload:
                    profiles[:] = json.loads(payload["languages-profiles"])
                return None
            return {
                "system/languages/profiles": copy.deepcopy(profiles),
                "system/languages": [{"code2": "fr", "enabled": True}],
                "system/settings": {"general": {"enabled_providers": []}},
                "series?length=-1": {
                    "data": [
                        {"sonarrSeriesId": 10, "profileId": None},
                        {"sonarrSeriesId": 11, "profileId": 7},
                    ]
                },
                "movies?length=-1": {"data": [{"radarrId": 20, "profileId": None}]},
            }[path]

        with (
            patch.object(BAZARR, "request", side_effect=request),
            patch.dict(
                os.environ, SONARR_API_KEY="sonarr-test", RADARR_API_KEY="radarr-test"
            ),
        ):
            BAZARR.reconcile("test")
            BAZARR.reconcile("test")
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0], other)
        self.assertEqual(profiles[1]["items"][0]["language"], "en")
        self.assertEqual(profiles[1]["items"][0]["audio_exclude"], "False")
        self.assertEqual(profiles[1]["items"][0]["audio_only_include"], "False")
        defaults = calls[0][1]
        self.assertEqual(defaults["languages-enabled"], ["en", "fr"])
        self.assertEqual(
            defaults["settings-general-enabled_providers"],
            ["tvsubtitles", "yifysubtitles"],
        )
        self.assertEqual(defaults["settings-general-serie_default_profile"], 8)
        self.assertEqual(defaults["settings-general-movie_default_profile"], 8)
        self.assertEqual(
            [p["seriesid"] for path, p in calls if path == "series"], [10, 10]
        )
        self.assertEqual(
            [p["radarrid"] for path, p in calls if path == "movies"], [20, 20]
        )

    def test_existing_providers_and_credentials_are_not_replaced(self):
        responses = [
            [],
            [],
            {"general": {"enabled_providers": ["custom"]}},
            None,
            None,
            None,
            {"data": []},
            {"data": []},
        ]
        with (
            patch.object(BAZARR, "request", side_effect=responses) as request,
            patch.dict(
                os.environ, SONARR_API_KEY="sonarr-test", RADARR_API_KEY="radarr-test"
            ),
        ):
            BAZARR.reconcile("test")
        settings = request.call_args_list[3].args[2]
        self.assertNotIn("settings-general-enabled_providers", settings)
        self.assertFalse(any(key.startswith("settings-auth-") for key in settings))


class AlertTests(unittest.TestCase):
    def test_alert_firing_recovery_missing_metrics_and_existing_ntfy_route(self):
        values = yaml.safe_load(
            (ROOT / "kubernetes/infrastructure/monitoring/values.yaml").read_text()
        )
        group = next(
            g
            for g in values["additionalPrometheusRulesMap"]["homelab"]["groups"]
            if g["name"] == "homelab-backups"
        )
        config = values["alertmanager"]["config"]
        self.assertEqual(config["route"]["receiver"], "ntfy-monitoring")
        receiver = next(
            r for r in config["receivers"] if r["name"] == "ntfy-monitoring"
        )
        self.assertEqual(
            receiver["webhook_configs"][0]["url"],
            "http://ntfy.stockalert.svc.cluster.local/monitoring?template=alertmanager",
        )
        self.assertTrue(receiver["webhook_configs"][0]["send_resolved"])
        rules = {r["alert"]: r for r in group["rules"]}
        metrics = {
            "homelab_backup_last_run_ok": "1+0x1800",
            "homelab_backup_timer_active": "1+0x1800",
            "homelab_backup_last_upload_timestamp_seconds": "0+0x1800",
            "homelab_backup_prune_ok": "1+0x1800",
        }
        cases = [
            (
                "AppdataBackupFailed",
                "homelab_backup_last_run_ok",
                "0+0x9 1+0x20",
                "3m",
                "12m",
            ),
            (
                "AppdataBackupTimerInactive",
                "homelab_backup_timer_active",
                "0+0x9 1+0x20",
                "6m",
                "12m",
            ),
            (
                "AppdataBackupPruneFailed",
                "homelab_backup_prune_ok",
                "0+0x9 1+0x20",
                "6m",
                "12m",
            ),
            (
                "AppdataBackupUploadStale",
                "homelab_backup_last_upload_timestamp_seconds",
                "0+0x1599 96000+0x100",
                "1590m",
                "1610m",
            ),
            (
                "AppdataBackupMetricsMissing",
                "homelab_backup_last_run_ok",
                None,
                "6m",
                None,
            ),
        ]
        tests = []
        for name, metric, series, firing, recovered in cases:
            inputs = dict(metrics)
            if series is None:
                inputs.pop(metric)
            else:
                inputs[metric] = series
            rule = rules[name]
            checks = [
                {
                    "eval_time": firing,
                    "alertname": name,
                    "exp_alerts": [
                        {
                            "exp_labels": rule["labels"],
                            "exp_annotations": rule["annotations"],
                        }
                    ],
                }
            ]
            if recovered:
                checks.append(
                    {"eval_time": recovered, "alertname": name, "exp_alerts": []}
                )
            tests.append(
                {
                    "interval": "1m",
                    "input_series": [
                        {"series": k, "values": v} for k, v in inputs.items()
                    ],
                    "alert_rule_test": checks,
                }
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "rules.yaml").write_text(yaml.safe_dump({"groups": [group]}))
            (root / "tests.yaml").write_text(
                yaml.safe_dump(
                    {
                        "rule_files": ["rules.yaml"],
                        "evaluation_interval": "1m",
                        "tests": tests,
                    }
                )
            )
            result = subprocess.run(
                [os.environ.get("PROMTOOL", "promtool"), "test", "rules", "tests.yaml"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
