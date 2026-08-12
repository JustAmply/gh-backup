import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from gh_backup.configuration import BackupConfig, OffsiteConfig
from gh_backup.runner import BackupApplication


FIXED_TIME = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


class SuccessfulAdapter:
    def __init__(self) -> None:
        self.cleanup_calls = 0

    def resolve_authenticated_login(self) -> str:
        return "OctoCat"

    def describe_tools(self) -> dict[str, str]:
        return {"git": "git version 2.47.3"}

    def configure_authentication(self) -> None:
        pass

    def mirror_repositories(self, target: str, target_kind: str) -> None:
        del target, target_kind

    def fetch_lfs(self, target: str) -> None:
        del target

    def export_metadata(self, target: str, target_kind: str) -> None:
        del target, target_kind

    def verify_backup(self, target: str) -> str:
        return f"verified {target}"

    def cleanup(self) -> None:
        self.cleanup_calls += 1


class FailingCleanupAdapter(SuccessfulAdapter):
    def cleanup(self) -> None:
        super().cleanup()
        raise RuntimeError("cleanup rejected secret-token")


class BackupApplicationTests(unittest.TestCase):
    def test_application_owns_manifest_and_adapter_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            environment = {
                "GITHUB_OWNER": "OctoCat",
                "GITHUB_TOKEN": "secret-token",
                "BACKUP_DATA_DIR": temp_dir,
                "BACKUP_MIN_FREE_GB": "0",
                "GH_BACKUP_RUN_ID": "application-run",
            }
            adapter = SuccessfulAdapter()
            application = BackupApplication(
                environment=environment,
                adapter_factory=lambda config: self._return_adapter(config, adapter),
                offsite_adapter_factory=self._no_offsite,
                clock=lambda: FIXED_TIME,
            )

            result = application.run()

            last_success = json.loads(
                (data_dir / "state" / "last-success.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result, 0)
            self.assertEqual(last_success["run_id"], "application-run")
            self.assertEqual(adapter.cleanup_calls, 1)
            self.assertNotIn("GITHUB_TOKEN", environment)
            self.assertTrue((data_dir / "logs" / "application-run.log").is_file())

    def test_all_configuration_errors_become_one_failed_backup_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            environment = {
                "GITHUB_TOKEN": "",
                "BACKUP_DATA_DIR": temp_dir,
                "BACKUP_MIN_FREE_GB": "-1",
                "GHORG_INCLUDE_SUBMODULES": "perhaps",
                "GH_BACKUP_RUN_ID": "invalid-configuration-run",
            }
            application = BackupApplication(
                environment=environment,
                adapter_factory=lambda config: self.fail(
                    f"adapter must not be created for {config!r}"
                ),
                offsite_adapter_factory=self._no_offsite,
                clock=lambda: FIXED_TIME,
            )

            with self.assertLogs("gh_backup.runner", level="ERROR"):
                result = application.run()

            last_run = json.loads(
                (data_dir / "state" / "last-run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result, 1)
            self.assertEqual(last_run["status"], "failed")
            self.assertEqual(
                last_run["errors"],
                [
                    "GitHub token value is empty",
                    "GHORG_INCLUDE_SUBMODULES must be a boolean value",
                    "BACKUP_MIN_FREE_GB must not be negative",
                ],
            )
            self.assertFalse((data_dir / "state" / "last-success.json").exists())

    def test_adapter_construction_failure_is_terminal_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            environment = {
                "GITHUB_TOKEN": "secret-token",
                "BACKUP_DATA_DIR": temp_dir,
                "BACKUP_MIN_FREE_GB": "0",
                "GH_BACKUP_RUN_ID": "adapter-construction-failed",
            }
            application = BackupApplication(
                environment=environment,
                adapter_factory=lambda _: self._raise_adapter_error(),
                offsite_adapter_factory=self._no_offsite,
                clock=lambda: FIXED_TIME,
            )

            with self.assertLogs("gh_backup.runner", level="ERROR"):
                result = application.run()

            last_run_text = (data_dir / "state" / "last-run.json").read_text(
                encoding="utf-8"
            )
            self.assertEqual(result, 1)
            self.assertNotIn("secret-token", last_run_text)
            self.assertIn("adapter setup rejected ***", last_run_text)
            self.assertNotIn("GITHUB_TOKEN", environment)

    def test_cleanup_failure_prevents_recovery_point_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            environment = {
                "GITHUB_OWNER": "OctoCat",
                "GITHUB_TOKEN": "secret-token",
                "BACKUP_DATA_DIR": temp_dir,
                "BACKUP_MIN_FREE_GB": "0",
                "GH_BACKUP_RUN_ID": "cleanup-failed-run",
            }
            adapter = FailingCleanupAdapter()
            application = BackupApplication(
                environment=environment,
                adapter_factory=lambda config: self._return_adapter(config, adapter),
                offsite_adapter_factory=self._no_offsite,
                clock=lambda: FIXED_TIME,
            )

            with self.assertLogs("gh_backup.runner", level="ERROR"):
                result = application.run()

            last_run_text = (data_dir / "state" / "last-run.json").read_text(
                encoding="utf-8"
            )
            self.assertEqual(result, 1)
            self.assertIn("cleanup rejected ***", last_run_text)
            self.assertNotIn("secret-token", last_run_text)
            self.assertFalse((data_dir / "state" / "last-success.json").exists())

    @staticmethod
    def _return_adapter(
        config: BackupConfig, adapter: SuccessfulAdapter
    ) -> SuccessfulAdapter:
        if config.token != "secret-token":
            raise AssertionError("configuration token was not parsed")
        return adapter

    @staticmethod
    def _no_offsite(config: OffsiteConfig | None) -> None:
        if config is not None:
            raise AssertionError("offsite must be disabled")
        return None

    @staticmethod
    def _raise_adapter_error() -> SuccessfulAdapter:
        raise RuntimeError("adapter setup rejected secret-token")


if __name__ == "__main__":
    unittest.main()
