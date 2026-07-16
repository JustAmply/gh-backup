import subprocess
import tempfile
import unittest
from pathlib import Path

from gh_backup.command_adapter import CommandBackupAdapter
from gh_backup.runner import BackupConfig


class RecordingCommandRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")


class CommandBackupAdapterTests(unittest.TestCase):
    def test_authentication_configures_noninteractive_github_https_clones(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            commands = RecordingCommandRunner()
            adapter = CommandBackupAdapter(
                BackupConfig(
                    owner="OctoCat",
                    orgs=(),
                    token="secret-token",
                    data_dir=Path(temp_dir),
                    include_submodules=True,
                ),
                run_command=commands,
            )

            adapter.configure_authentication()

            self.assertEqual(commands.calls[0][:2], ["git", "config"])
            self.assertIn("url.https://github.com/.insteadOf", commands.calls[0])
            self.assertEqual(commands.calls[1][:2], ["git", "config"])
            self.assertIn("credential.https://github.com/.helper", commands.calls[1])

    def test_user_mirror_command_contains_the_required_backup_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            commands = RecordingCommandRunner()
            adapter = CommandBackupAdapter(
                BackupConfig(
                    owner="OctoCat",
                    orgs=(),
                    token="secret-token",
                    data_dir=Path(temp_dir),
                    include_submodules=True,
                ),
                run_command=commands,
            )

            adapter.mirror_repositories("OctoCat", "user")

            self.assertEqual(
                commands.calls,
                [
                    [
                        "ghorg",
                        "clone",
                        "OctoCat",
                        "--scm=github",
                        "--clone-type=user",
                        "--token=secret-token",
                        f"--path={Path(temp_dir) / 'mirrors'}",
                        "--output-dir=OctoCat_backup",
                        "--backup",
                        "--clone-wiki",
                        "--github-user-option=owner",
                        "--include-submodules",
                    ]
                ],
            )

    def test_organization_metadata_command_uses_the_archival_resource_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            commands = RecordingCommandRunner()
            adapter = CommandBackupAdapter(
                BackupConfig(
                    owner="OctoCat",
                    orgs=("my-org",),
                    token="secret-token",
                    data_dir=Path(temp_dir),
                    include_submodules=True,
                ),
                run_command=commands,
            )

            adapter.export_metadata("my-org", "organization")

            self.assertEqual(commands.calls[0][0], "github-backup")
            self.assertEqual(commands.calls[0][-2:], ["--organization", "my-org"])
            self.assertIn("--private", commands.calls[0])
            self.assertIn("--pull-details", commands.calls[0])
            self.assertIn("--assets", commands.calls[0])
            self.assertIn("--attachments", commands.calls[0])
            self.assertEqual(
                commands.calls[0][
                    commands.calls[0].index("--output-directory") + 1
                ],
                str(Path(temp_dir) / "metadata" / "my-org"),
            )

    def test_lfs_collection_and_verification_check_each_discovered_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            mirror_root = data_dir / "mirrors" / "OctoCat_backup"
            (mirror_root / "first.git").mkdir(parents=True)
            (mirror_root / "second.wiki").mkdir()
            (data_dir / "metadata" / "OctoCat").mkdir(parents=True)
            commands = RecordingCommandRunner()
            adapter = CommandBackupAdapter(
                BackupConfig(
                    owner="OctoCat",
                    orgs=(),
                    token="secret-token",
                    data_dir=data_dir,
                    include_submodules=True,
                ),
                run_command=commands,
            )

            adapter.fetch_lfs("OctoCat")
            adapter.verify_backup("OctoCat")

            lfs_calls = [call for call in commands.calls if call[-3:] == ["lfs", "fetch", "--all"]]
            fsck_calls = [call for call in commands.calls if call[-2:] == ["fsck", "--full"]]
            self.assertEqual(len(lfs_calls), 2)
            self.assertEqual(len(fsck_calls), 2)


if __name__ == "__main__":
    unittest.main()
