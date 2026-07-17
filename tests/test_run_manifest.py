import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from gh_backup.manifest import RunManifest


class RunManifestTests(unittest.TestCase):
    def test_run_identity_cannot_escape_or_overwrite_immutable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            started_at = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

            RunManifest.start(
                state_dir=state_dir,
                run_id="unique-run",
                started_at=started_at,
                log_file="/data/logs/unique-run.log",
            )

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                RunManifest.start(
                    state_dir=state_dir,
                    run_id="unique-run",
                    started_at=started_at,
                    log_file="/data/logs/duplicate.log",
                )
            with self.assertRaisesRegex(ValueError, "Invalid run ID"):
                RunManifest.start(
                    state_dir=state_dir,
                    run_id="../outside",
                    started_at=started_at,
                    log_file="/data/logs/unsafe.log",
                )

    def test_start_persists_a_running_manifest_for_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            started_at = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

            manifest = RunManifest.start(
                state_dir=state_dir,
                run_id="20260716T120000Z-a1b2c3d4",
                started_at=started_at,
                log_file="/data/logs/20260716T120000Z-a1b2c3d4.log",
            )

            persisted = json.loads(
                (state_dir / "runs" / f"{manifest.run_id}.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(persisted["schema_version"], 1)
            self.assertEqual(persisted["run_id"], "20260716T120000Z-a1b2c3d4")
            self.assertEqual(persisted["status"], "running")
            self.assertEqual(persisted["started_at"], "2026-07-16T12:00:00Z")
            self.assertIsNone(persisted["finished_at"])
            self.assertEqual(persisted["targets"], {})
            self.assertEqual(
                persisted["log_file"],
                "/data/logs/20260716T120000Z-a1b2c3d4.log",
            )

    def test_resolved_targets_and_completed_stages_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            manifest = RunManifest.start(
                state_dir=state_dir,
                run_id="20260716T120000Z-a1b2c3d4",
                started_at=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
                log_file="/data/logs/run.log",
            )

            manifest.set_targets(owner="OctoCat", orgs=["my-org"])
            manifest.set_run_context(
                configuration={
                    "include_submodules": True,
                    "offsite_enabled": False,
                },
                tool_versions={"ghorg": "ghorg version 1.11.10"},
            )
            manifest.record_stage(
                target="OctoCat",
                stage="repository_mirror",
                status="succeeded",
                started_at=datetime(2026, 7, 16, 12, 1, tzinfo=UTC),
                finished_at=datetime(2026, 7, 16, 12, 2, tzinfo=UTC),
            )

            persisted = json.loads(
                (state_dir / "runs" / f"{manifest.run_id}.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(persisted["owner"], "OctoCat")
            self.assertEqual(persisted["orgs"], ["my-org"])
            self.assertEqual(
                persisted["configuration"],
                {"include_submodules": True, "offsite_enabled": False},
            )
            self.assertEqual(
                persisted["tool_versions"],
                {"ghorg": "ghorg version 1.11.10"},
            )
            self.assertEqual(persisted["targets"]["OctoCat"]["kind"], "user")
            self.assertEqual(
                persisted["targets"]["my-org"]["kind"], "organization"
            )
            self.assertEqual(
                persisted["targets"]["OctoCat"]["stages"]["repository_mirror"],
                {
                    "status": "succeeded",
                    "started_at": "2026-07-16T12:01:00Z",
                    "finished_at": "2026-07-16T12:02:00Z",
                },
            )

    def test_failed_run_updates_last_run_but_preserves_last_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            successful = RunManifest.start(
                state_dir=state_dir,
                run_id="successful-run",
                started_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
                log_file="/data/logs/success.log",
            )
            successful.finish(
                status="verified",
                finished_at=datetime(2026, 7, 16, 10, 30, tzinfo=UTC),
            )

            failed = RunManifest.start(
                state_dir=state_dir,
                run_id="failed-run",
                started_at=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
                log_file="/data/logs/failed.log",
            )
            failed.finish(
                status="failed",
                finished_at=datetime(2026, 7, 16, 12, 5, tzinfo=UTC),
            )

            last_run = json.loads(
                (state_dir / "last-run.json").read_text(encoding="utf-8")
            )
            last_success = json.loads(
                (state_dir / "last-success.json").read_text(encoding="utf-8")
            )

            self.assertEqual(last_run["run_id"], "failed-run")
            self.assertEqual(last_run["status"], "failed")
            self.assertEqual(last_success["run_id"], "successful-run")
            self.assertEqual(last_success["status"], "verified")

            with self.assertRaisesRegex(RuntimeError, "terminal run manifest"):
                failed.record_stage(
                    target="missing",
                    stage="metadata",
                    status="succeeded",
                    started_at=datetime(2026, 7, 16, 12, 6, tzinfo=UTC),
                    finished_at=datetime(2026, 7, 16, 12, 7, tzinfo=UTC),
                )


if __name__ == "__main__":
    unittest.main()
