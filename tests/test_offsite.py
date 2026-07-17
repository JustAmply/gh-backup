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
        return subprocess.CompletedProcess(args, 0, "", "")


class ResticOffsiteAdapterTests(unittest.TestCase):
    def test_verified_run_is_archived_checked_and_pruned_by_retention_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            commands = RecordingResticRunner()
            adapter = ResticOffsiteAdapter(
                retention=RetentionPolicy(daily=7, weekly=5, monthly=12),
                run_command=commands,
            )

            detail = adapter.archive(
                run_id="verified-run", data_dir=Path(temp_dir)
            )

            self.assertEqual(
                commands.calls[0],
                [
                    "restic",
                    "backup",
                    temp_dir,
                    "--tag",
                    "gh-backup",
                    "--tag",
                    "run:verified-run",
                    "--exclude",
                    str(Path(temp_dir) / "state" / "restore-drills"),
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
            self.assertEqual(detail, "encrypted offsite snapshot verified and retained")


if __name__ == "__main__":
    unittest.main()
