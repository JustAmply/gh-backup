import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from gh_backup.configuration import BackupConfig
from gh_backup.manifest import RunManifest
from gh_backup.offsite import OffsiteEvidence
from gh_backup.runner import BackupRunner


FIXED_TIME = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def start_manifest(data_dir: Path, run_id: str, log_name: str) -> RunManifest:
    return RunManifest.start(
        state_dir=data_dir / "state",
        run_id=run_id,
        started_at=FIXED_TIME,
        log_file=str(data_dir / "logs" / log_name),
    )


def execute_runner(runner: BackupRunner, manifest: RunManifest) -> int:
    execution = runner.run(manifest)
    if execution.errors:
        manifest.fail(errors=execution.errors, finished_at=FIXED_TIME)
        return 1
    status = manifest.finish(finished_at=FIXED_TIME)
    return 0 if status == "verified" else 1


class RecordingBackupAdapter:
    def __init__(self, authenticated_login: str = "OctoCat") -> None:
        self.calls: list[tuple[str, ...]] = []
        self.authenticated_login = authenticated_login

    def resolve_authenticated_login(self) -> str:
        self.calls.append(("resolve_authenticated_login",))
        return self.authenticated_login

    def configure_authentication(self) -> None:
        self.calls.append(("configure_authentication",))

    def describe_tools(self) -> dict[str, str]:
        self.calls.append(("describe_tools",))
        return {
            "ghorg": "ghorg version 1.11.10",
            "github-backup": "github-backup 0.61.5",
        }

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

    def archive(self, *, run_id: str, data_dir: Path) -> OffsiteEvidence:
        self.run_ids.append(run_id)
        return OffsiteEvidence(
            snapshot_id="abc123def456",
            detail="offsite verified",
        )


class FailingOffsiteAdapter:
    def archive(self, *, run_id: str, data_dir: Path) -> OffsiteEvidence:
        del run_id, data_dir
        raise RuntimeError("offsite unavailable")


class BackupRunnerTests(unittest.TestCase):
    def test_authenticated_owner_is_not_repeated_as_an_organization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            adapter = RecordingBackupAdapter(authenticated_login="OctoCat")
            runner = BackupRunner(
                config=BackupConfig(
                    owner="",
                    orgs=("octocat", "my-org"),
                    token="secret-token",
                    data_dir=data_dir,
                    include_submodules=True,
                ),
                adapter=adapter,
                clock=lambda: FIXED_TIME,
            )

            result = execute_runner(
                runner,
                start_manifest(data_dir, "deduplicated-owner-run", "run.log")
            )

            self.assertEqual(result, 0)
            manifest = json.loads(
                (data_dir / "state" / "last-success.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["owner"], "OctoCat")
            self.assertEqual(manifest["orgs"], ["my-org"])

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
                clock=lambda: FIXED_TIME,
            )

            result = execute_runner(
                runner,
                start_manifest(
                    data_dir, "20260716T120000Z-a1b2c3d4", "run.log"
                )
            )

            self.assertEqual(result, 0)
            self.assertEqual(
                adapter.calls,
                [
                    ("resolve_authenticated_login",),
                    ("describe_tools",),
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
                manifest["configuration"],
                {"include_submodules": True, "offsite_enabled": False},
            )
            self.assertEqual(
                manifest["tool_versions"],
                {
                    "ghorg": "ghorg version 1.11.10",
                    "github-backup": "github-backup 0.61.5",
                },
            )
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
                clock=lambda: FIXED_TIME,
            )

            with self.assertLogs("gh_backup.runner", level="ERROR"):
                result = execute_runner(
                    runner,
                    start_manifest(data_dir, "auth-failed-run", "failed.log")
                )

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
                clock=lambda: FIXED_TIME,
            )

            result = execute_runner(
                runner,
                start_manifest(data_dir, "offsite-run", "offsite.log")
            )

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
                    "evidence": {"snapshot_id": "abc123def456"},
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
                clock=lambda: FIXED_TIME,
            )

            with self.assertLogs("gh_backup.runner", level="ERROR"):
                result = execute_runner(
                    runner,
                    start_manifest(
                        data_dir, "offsite-failed-run", "offsite-failed.log"
                    )
                )

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
                clock=lambda: FIXED_TIME,
            )

            with self.assertLogs("gh_backup.runner", level="ERROR") as logs:
                result = execute_runner(
                    runner,
                    start_manifest(data_dir, "failed-run", "failed.log")
                )

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
