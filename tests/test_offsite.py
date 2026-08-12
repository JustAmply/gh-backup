import subprocess
import tempfile
import unittest
from pathlib import Path

from gh_backup.offsite import ResticOffsiteAdapter, RetentionPolicy


class RecordingResticRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        stdout = ""
        if args[1] == "backup":
            stdout = (
                '{"message_type":"status","seconds_elapsed":1}\n'
                '{"message_type":"summary","snapshot_id":"abc123def456"}\n'
            )
        return subprocess.CompletedProcess(args, 0, stdout, "")


class ResticOffsiteAdapterTests(unittest.TestCase):
    def test_verified_run_is_archived_checked_and_pruned_by_retention_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "mirrors").mkdir()
            (data_dir / "metadata").mkdir()
            commands = RecordingResticRunner()
            adapter = ResticOffsiteAdapter(
                retention=RetentionPolicy(daily=7, weekly=5, monthly=12),
                run_command=commands,
            )

            evidence = adapter.archive(
                run_id="verified-run", data_dir=data_dir
            )

            self.assertEqual(
                commands.calls[0],
                [
                    "restic",
                    "backup",
                    str(data_dir / "mirrors"),
                    str(data_dir / "metadata"),
                    "--tag",
                    "gh-backup",
                    "--tag",
                    "run:verified-run",
                    "--json",
                    "--quiet",
                ],
            )
            self.assertEqual(commands.calls[1], ["restic", "check"])
            self.assertEqual(
                commands.calls[2],
                [
                    "restic",
                    "forget",
                    "--tag",
                    "gh-backup",
                    "--keep-daily",
                    "7",
                    "--keep-weekly",
                    "5",
                    "--keep-monthly",
                    "12",
                    "--prune",
                ],
            )
            self.assertEqual(evidence.snapshot_id, "abc123def456")
            self.assertEqual(
                evidence.detail,
                "encrypted offsite snapshot abc123def456 verified and retained",
            )

    def test_snapshot_without_machine_readable_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "mirrors").mkdir()
            (data_dir / "metadata").mkdir()

            with self.assertRaisesRegex(RuntimeError, "snapshot ID"):
                ResticOffsiteAdapter(
                    retention=RetentionPolicy(daily=7, weekly=5, monthly=12),
                    run_command=lambda args, **kwargs: subprocess.CompletedProcess(
                        args, 0, "backup complete without JSON", ""
                    ),
                ).archive(run_id="missing-id", data_dir=data_dir)


if __name__ == "__main__":
    unittest.main()
