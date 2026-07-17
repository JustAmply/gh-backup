import contextlib
import io
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gh_backup.health import evaluate_health, main
from gh_backup.manifest import RunManifest


class HealthTests(unittest.TestCase):
    def test_health_command_emits_json_and_uses_health_as_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
            manifest = RunManifest.start(
                state_dir=data_dir / "state",
                run_id="verified-run",
                started_at=now - timedelta(hours=2),
                log_file="/data/logs/verified.log",
            )
            manifest.finish(
                status="verified", finished_at=now - timedelta(hours=1)
            )
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                exit_code = main(
                    ["health", "--json"],
                    environment={
                        "BACKUP_DATA_DIR": str(data_dir),
                        "BACKUP_MAX_AGE_HOURS": "26",
                    },
                    now=lambda: now,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "healthy")

    def test_recent_verified_recovery_point_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
            manifest = RunManifest.start(
                state_dir=state_dir,
                run_id="verified-run",
                started_at=now - timedelta(hours=2, minutes=10),
                log_file="/data/logs/verified-run.log",
            )
            manifest.finish(
                status="verified", finished_at=now - timedelta(hours=2)
            )

            report = evaluate_health(
                state_dir=state_dir,
                now=now,
                maximum_age=timedelta(hours=26),
            )

            self.assertEqual(report.status, "healthy")
            self.assertEqual(report.reason, "latest recovery point is current")
            self.assertEqual(report.last_run_id, "verified-run")
            self.assertEqual(report.recovery_point_run_id, "verified-run")
            self.assertEqual(report.recovery_age_seconds, 7200)

    def test_failed_latest_run_is_unhealthy_even_with_a_current_recovery_point(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
            verified = RunManifest.start(
                state_dir=state_dir,
                run_id="verified-run",
                started_at=now - timedelta(hours=3),
                log_file="/data/logs/verified.log",
            )
            verified.finish(
                status="verified", finished_at=now - timedelta(hours=2)
            )
            failed = RunManifest.start(
                state_dir=state_dir,
                run_id="failed-run",
                started_at=now - timedelta(minutes=30),
                log_file="/data/logs/failed.log",
            )
            failed.finish(status="failed", finished_at=now - timedelta(minutes=20))

            report = evaluate_health(
                state_dir=state_dir,
                now=now,
                maximum_age=timedelta(hours=26),
            )

            self.assertEqual(report.status, "unhealthy")
            self.assertEqual(report.reason, "latest backup run failed")
            self.assertEqual(report.last_run_id, "failed-run")
            self.assertEqual(report.recovery_point_run_id, "verified-run")

    def test_recovery_point_older_than_the_freshness_objective_is_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
            manifest = RunManifest.start(
                state_dir=state_dir,
                run_id="stale-run",
                started_at=now - timedelta(hours=28),
                log_file="/data/logs/stale.log",
            )
            manifest.finish(
                status="verified", finished_at=now - timedelta(hours=27)
            )

            report = evaluate_health(
                state_dir=state_dir,
                now=now,
                maximum_age=timedelta(hours=26),
            )

            self.assertEqual(report.status, "unhealthy")
            self.assertEqual(report.reason, "latest recovery point is stale")
            self.assertEqual(report.recovery_age_seconds, 27 * 60 * 60)

    def test_corrupt_recovery_state_is_reported_as_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            (state_dir / "last-success.json").write_text("not-json", encoding="utf-8")

            report = evaluate_health(
                state_dir=state_dir,
                now=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
                maximum_age=timedelta(hours=26),
            )

            self.assertEqual(report.status, "unhealthy")
            self.assertEqual(
                report.reason, "recovery state is unreadable: last-success.json"
            )

    def test_structurally_invalid_recovery_state_is_reported_as_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            (state_dir / "last-success.json").write_text(
                json.dumps({"status": "verified", "finished_at": "not-a-date"}),
                encoding="utf-8",
            )

            report = evaluate_health(
                state_dir=state_dir,
                now=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
                maximum_age=timedelta(hours=26),
            )

            self.assertEqual(report.status, "unhealthy")
            self.assertEqual(
                report.reason, "recovery state is invalid: last-success.json"
            )

    def test_non_object_recovery_state_is_reported_as_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            (state_dir / "last-success.json").write_text("[]", encoding="utf-8")

            report = evaluate_health(
                state_dir=state_dir,
                now=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
                maximum_age=timedelta(hours=26),
            )

            self.assertEqual(report.status, "unhealthy")
            self.assertEqual(
                report.reason, "recovery state is unreadable: last-success.json"
            )


if __name__ == "__main__":
    unittest.main()
