import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from gh_backup.runner import BackupConfig, BackupRunner


class RecordingBackupAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def configure_authentication(self) -> None:
        self.calls.append(("configure_authentication",))

    def mirror_repositories(self, target: str, target_kind: str) -> None:
        self.calls.append(("mirror_repositories", target, target_kind))

    def fetch_lfs(self, target: str) -> None:
        self.calls.append(("fetch_lfs", target))

    def export_metadata(self, target: str, target_kind: str) -> None:
        self.calls.append(("export_metadata", target, target_kind))

    def verify_backup(self, target: str) -> None:
        self.calls.append(("verify_backup", target))


class FailingOrganizationAdapter(RecordingBackupAdapter):
    def mirror_repositories(self, target: str, target_kind: str) -> None:
        super().mirror_repositories(target, target_kind)
        if target == "my-org":
            raise RuntimeError("simulated mirror failure")


class FailingAuthenticationAdapter(RecordingBackupAdapter):
    def configure_authentication(self) -> None:
        raise RuntimeError("authentication rejected secret-token")


class RecordingOffsiteAdapter:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def archive(self, *, run_id: str, data_dir: Path) -> str:
        self.run_ids.append(run_id)
        return "offsite verified"


class FailingOffsiteAdapter:
    def archive(self, *, run_id: str, data_dir: Path) -> str:
        del run_id, data_dir
        raise RuntimeError("offsite unavailable")


class BackupRunnerTests(unittest.TestCase):
    def test_environment_config_normalizes_targets_and_boolean_values(self) -> None:
        config = BackupConfig.from_environment(
            {
                "GITHUB_OWNER": "OctoCat",
                "GITHUB_ORGS": " my-org,MY-ORG,octocat,other ",
                "GITHUB_TOKEN": "secret-token\r\n",
                "BACKUP_DATA_DIR": "/archive",
                "GHORG_INCLUDE_SUBMODULES": "YES",
            }
        )

        self.assertEqual(config.owner, "OctoCat")
        self.assertEqual(config.orgs, ("my-org", "other"))
        self.assertEqual(config.token, "secret-token")
        self.assertEqual(config.data_dir, Path("/archive"))
        self.assertTrue(config.include_submodules)

    def test_environment_config_reads_a_token_file_without_token_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "github-token"
            token_file.write_text("file-secret\n", encoding="utf-8")

            config = BackupConfig.from_environment(
                {
                    "GITHUB_OWNER": "OctoCat",
                    "GITHUB_TOKEN_FILE": str(token_file),
                    "BACKUP_DATA_DIR": temp_dir,
                }
            )

            self.assertEqual(config.token, "file-secret")
            self.assertEqual(config.token_file, token_file)

    def test_successful_run_executes_every_stage_and_publishes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            adapter = RecordingBackupAdapter()
            runner = BackupRunner(
                config=BackupConfig(
                    owner="OctoCat",
                    orgs=("my-org",),
                    token="secret-token",
                    data_dir=data_dir,
                    include_submodules=True,
                ),
                adapter=adapter,
                run_id="20260716T120000Z-a1b2c3d4",
                log_file=str(data_dir / "logs" / "run.log"),
                clock=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            )

            result = runner.run()

            self.assertEqual(result, 0)
            self.assertEqual(
                adapter.calls,
                [
                    ("configure_authentication",),
                    ("mirror_repositories", "OctoCat", "user"),
                    ("fetch_lfs", "OctoCat"),
                    ("export_metadata", "OctoCat", "user"),
                    ("verify_backup", "OctoCat"),
                    ("mirror_repositories", "my-org", "organization"),
                    ("fetch_lfs", "my-org"),
                    ("export_metadata", "my-org", "organization"),
                    ("verify_backup", "my-org"),
                ],
            )
            manifest = json.loads(
                (data_dir / "state" / "last-success.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["status"], "verified")
            self.assertEqual(manifest["owner"], "OctoCat")
            self.assertEqual(manifest["orgs"], ["my-org"])
            self.assertEqual(
                set(manifest["targets"]["OctoCat"]["stages"]),
                {"repository_mirror", "lfs", "metadata", "verification"},
            )

    def test_authentication_failure_finishes_the_run_without_leaking_the_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            runner = BackupRunner(
                config=BackupConfig(
                    owner="OctoCat",
                    orgs=(),
                    token="secret-token",
                    data_dir=data_dir,
                    include_submodules=True,
                ),
                adapter=FailingAuthenticationAdapter(),
                run_id="auth-failed-run",
                log_file=str(data_dir / "logs" / "failed.log"),
                clock=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            )

            with self.assertLogs("gh_backup.runner", level="ERROR"):
                result = runner.run()

            manifest = json.loads(
                (data_dir / "state" / "last-run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result, 1)
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(
                manifest["errors"], ["authentication rejected ***"]
            )
            self.assertNotIn("secret-token", json.dumps(manifest))

    def test_successful_local_verification_is_archived_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            offsite = RecordingOffsiteAdapter()
            runner = BackupRunner(
                config=BackupConfig(
                    owner="OctoCat",
                    orgs=(),
                    token="secret-token",
                    data_dir=data_dir,
                    include_submodules=True,
                ),
                adapter=RecordingBackupAdapter(),
                offsite_adapter=offsite,
                run_id="offsite-run",
                log_file=str(data_dir / "logs" / "offsite.log"),
                clock=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            )

            result = runner.run()

            manifest = json.loads(
                (data_dir / "state" / "last-success.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result, 0)
            self.assertEqual(offsite.run_ids, ["offsite-run"])
            self.assertEqual(
                manifest["run_stages"]["offsite"],
                {
                    "status": "succeeded",
                    "started_at": "2026-07-16T12:00:00Z",
                    "finished_at": "2026-07-16T12:00:00Z",
                    "detail": "offsite verified",
                },
            )

    def test_offsite_failure_prevents_recovery_point_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            runner = BackupRunner(
                config=BackupConfig(
                    owner="OctoCat",
                    orgs=(),
                    token="secret-token",
                    data_dir=data_dir,
                    include_submodules=True,
                ),
                adapter=RecordingBackupAdapter(),
                offsite_adapter=FailingOffsiteAdapter(),
                run_id="offsite-failed-run",
                log_file=str(data_dir / "logs" / "offsite-failed.log"),
                clock=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            )

            with self.assertLogs("gh_backup.runner", level="ERROR"):
                result = runner.run()

            manifest = json.loads(
                (data_dir / "state" / "last-run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result, 1)
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["run_stages"]["offsite"]["status"], "failed")
            self.assertFalse((data_dir / "state" / "last-success.json").exists())

    def test_failed_stage_is_recorded_and_later_stages_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            runner = BackupRunner(
                config=BackupConfig(
                    owner="OctoCat",
                    orgs=("my-org",),
                    token="secret-token",
                    data_dir=data_dir,
                    include_submodules=True,
                ),
                adapter=FailingOrganizationAdapter(),
                run_id="failed-run",
                log_file=str(data_dir / "logs" / "failed.log"),
                clock=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            )

            with self.assertLogs("gh_backup.runner", level="ERROR") as logs:
                result = runner.run()

            self.assertEqual(result, 1)
            self.assertIn("ghorg backup failed for my-org", logs.output[0])
            manifest = json.loads(
                (data_dir / "state" / "last-run.json").read_text(encoding="utf-8")
            )
            stages = manifest["targets"]["my-org"]["stages"]
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(stages["repository_mirror"]["status"], "failed")
            self.assertEqual(
                stages["repository_mirror"]["detail"], "simulated mirror failure"
            )
            self.assertEqual(stages["lfs"]["status"], "skipped")
            self.assertEqual(stages["metadata"]["status"], "skipped")
            self.assertEqual(stages["verification"]["status"], "skipped")
            self.assertFalse((data_dir / "state" / "last-success.json").exists())


if __name__ == "__main__":
    unittest.main()
