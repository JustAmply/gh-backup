import os
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
            self.assertIn("--file", commands.calls[0])
            self.assertNotIn("--global", commands.calls[0])
            self.assertIn("url.https://github.com/.insteadOf", commands.calls[0])
            self.assertEqual(commands.calls[1][:2], ["git", "config"])
            self.assertIn("--file", commands.calls[1])
            self.assertNotIn("--global", commands.calls[1])
            self.assertIn("credential.https://github.com/.helper", commands.calls[1])
            self.assertIn("GITHUB_TOKEN_FILE", commands.calls[1][-1])
            self.assertNotIn("secret-token", " ".join(sum(commands.calls, [])))
            token_file = Path(os.environ["GITHUB_TOKEN_FILE"])
            git_config = Path(os.environ["GIT_CONFIG_GLOBAL"])
            self.assertTrue(token_file.is_file())
            self.assertTrue(git_config.is_file())

            adapter.cleanup()

            self.assertFalse(token_file.exists())
            self.assertFalse(git_config.exists())

    def test_user_mirror_command_contains_the_required_backup_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "github-token"
            token_file.write_text("secret-token", encoding="utf-8")
            commands = RecordingCommandRunner()
            adapter = CommandBackupAdapter(
                BackupConfig(
                    owner="OctoCat",
                    orgs=(),
                    token="secret-token",
                    data_dir=Path(temp_dir),
                    include_submodules=True,
                    token_file=token_file,
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
                        f"--token={token_file}",
                        f"--path={Path(temp_dir) / 'mirrors'}",
                        "--output-dir=OctoCat_backup",
                        "--backup",
                        "--clone-wiki",
                        "--github-user-option=owner",
                        "--include-submodules",
                    ]
                ],
            )
            self.assertNotIn("secret-token", " ".join(commands.calls[0]))

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
            self.assertIn("--fork", commands.calls[0])
            self.assertIn("--security-advisories", commands.calls[0])
            self.assertIn("--pull-details", commands.calls[0])
            self.assertIn("--assets", commands.calls[0])
            self.assertIn("--attachments", commands.calls[0])
            token_argument = commands.calls[0][commands.calls[0].index("--token") + 1]
            self.assertTrue(token_argument.startswith("file://"))
            self.assertNotIn("secret-token", " ".join(commands.calls[0]))
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
            detail = adapter.verify_backup("OctoCat")

            lfs_calls = [call for call in commands.calls if call[-3:] == ["lfs", "fetch", "--all"]]
            fsck_calls = [call for call in commands.calls if call[-2:] == ["fsck", "--full"]]
            self.assertEqual(len(lfs_calls), 2)
            self.assertEqual(len(fsck_calls), 2)
            self.assertIn("2 mirrors passed git fsck", detail)
            self.assertIn("local restore drill matched 0 refs", detail)

    def test_verification_rejects_unreadable_metadata_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "mirrors" / "OctoCat_backup").mkdir(parents=True)
            metadata_dir = data_dir / "metadata" / "OctoCat"
            metadata_dir.mkdir(parents=True)
            (metadata_dir / "issues.json").write_text("not-json", encoding="utf-8")
            adapter = CommandBackupAdapter(
                BackupConfig(
                    owner="OctoCat",
                    orgs=(),
                    token="secret-token",
                    data_dir=data_dir,
                    include_submodules=True,
                ),
                run_command=RecordingCommandRunner(),
            )

            with self.assertRaisesRegex(ValueError, "Expecting value"):
                adapter.verify_backup("OctoCat")


if __name__ == "__main__":
    unittest.main()
