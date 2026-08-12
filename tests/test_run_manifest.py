import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from gh_backup.manifest import RunManifest


def qualify_manifest(
    manifest: RunManifest,
    *,
    timestamp: datetime,
    offsite_enabled: bool = False,
) -> None:
    manifest.set_targets(owner="OctoCat", orgs=[])
    manifest.set_run_context(
        configuration={"offsite_enabled": offsite_enabled},
        tool_versions={"git": "git version 2.47.3"},
    )
    for stage in ("repository_mirror", "lfs", "metadata", "verification"):
        manifest.record_stage(
            target="OctoCat",
            stage=stage,
            status="succeeded",
            started_at=timestamp,
            finished_at=timestamp,
        )


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
            successful_finished_at = datetime(2026, 7, 16, 10, 30, tzinfo=UTC)
            qualify_manifest(successful, timestamp=successful_finished_at)
            successful.finish(finished_at=successful_finished_at)

            failed = RunManifest.start(
                state_dir=state_dir,
                run_id="failed-run",
                started_at=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
                log_file="/data/logs/failed.log",
            )
            failed.fail(
                errors="simulated backup failure",
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

    def test_incomplete_run_cannot_become_a_recovery_point(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            timestamp = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
            manifest = RunManifest.start(
                state_dir=state_dir,
                run_id="incomplete-run",
                started_at=timestamp,
                log_file="/data/logs/incomplete.log",
            )
            manifest.set_targets(owner="OctoCat", orgs=[])
            manifest.set_run_context(
                configuration={"offsite_enabled": False},
                tool_versions={"git": "git version 2.47.3"},
            )
            for stage in ("repository_mirror", "lfs", "metadata"):
                manifest.record_stage(
                    target="OctoCat",
                    stage=stage,
                    status="succeeded",
                    started_at=timestamp,
                    finished_at=timestamp,
                )

            status = manifest.finish(finished_at=timestamp)

            last_run = json.loads(
                (state_dir / "last-run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status, "failed")
            self.assertEqual(last_run["status"], "failed")
            self.assertIn("OctoCat/verification", last_run["errors"][0])
            self.assertFalse((state_dir / "last-success.json").exists())

    def test_offsite_enabled_run_requires_successful_offsite_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            timestamp = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
            manifest = RunManifest.start(
                state_dir=state_dir,
                run_id="missing-offsite-run",
                started_at=timestamp,
                log_file="/data/logs/missing-offsite.log",
            )
            qualify_manifest(
                manifest,
                timestamp=timestamp,
                offsite_enabled=True,
            )
            manifest.record_run_stage(
                stage="offsite",
                status="succeeded",
                started_at=timestamp,
                finished_at=timestamp,
            )

            status = manifest.finish(finished_at=timestamp)

            last_run = json.loads(
                (state_dir / "last-run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status, "failed")
            self.assertIn("snapshot identity", last_run["errors"][0])
            self.assertFalse((state_dir / "last-success.json").exists())


if __name__ == "__main__":
    unittest.main()
