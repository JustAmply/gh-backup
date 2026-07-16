"""Adapters for the external backup command-line tools."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from gh_backup.runner import BackupConfig


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class CommandBackupAdapter:
    def __init__(
        self,
        config: BackupConfig,
        *,
        run_command: CommandRunner | None = None,
    ) -> None:
        self._config = config
        self._run_command = run_command or self._command_runner_from_environment()

    @staticmethod
    def _command_runner_from_environment() -> CommandRunner:
        command_shell = os.environ.get("GH_BACKUP_COMMAND_SHELL")
        if not command_shell:
            return subprocess.run

        def run_through_shell(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [command_shell, "-c", 'exec "$@"', "gh-backup", *args],
                **kwargs,
            )

        return run_through_shell

    def configure_authentication(self) -> None:
        os.environ["GHORG_GITHUB_TOKEN"] = self._config.token
        self._run_command(
            [
                "git",
                "config",
                "--global",
                "url.https://github.com/.insteadOf",
                "git@github.com:",
            ],
            check=True,
            text=True,
        )
        self._run_command(
            [
                "git",
                "config",
                "--global",
                "credential.https://github.com/.helper",
                (
                    "!f() { echo username=x-access-token; "
                    "echo password=$GHORG_GITHUB_TOKEN; }; f"
                ),
            ],
            check=True,
            text=True,
        )

    def mirror_repositories(self, target: str, target_kind: str) -> None:
        clone_type = "user" if target_kind == "user" else "org"
        args = [
            "ghorg",
            "clone",
            target,
            "--scm=github",
            f"--clone-type={clone_type}",
            f"--token={self._config.token}",
            f"--path={self._config.data_dir / 'mirrors'}",
            f"--output-dir={target}_backup",
            "--backup",
            "--clone-wiki",
        ]
        if target_kind == "user":
            args.append("--github-user-option=owner")
        if self._config.include_submodules:
            args.append("--include-submodules")
        self._run_command(args, check=True, text=True)

    def export_metadata(self, target: str, target_kind: str) -> None:
        metadata_dir = self._config.data_dir / "metadata" / target
        metadata_dir.mkdir(parents=True, exist_ok=True)
        args = [
            "github-backup",
            "--token",
            self._config.token,
            "--output-directory",
            str(metadata_dir),
            "--private",
            "--issues",
            "--issue-comments",
            "--issue-events",
            "--pulls",
            "--pull-comments",
            "--pull-commits",
            "--pull-details",
            "--labels",
            "--milestones",
            "--releases",
            "--assets",
            "--attachments",
        ]
        if target_kind == "organization":
            args.append("--organization")
        else:
            args.extend(
                [
                    "--gists",
                    "--starred-gists",
                    "--starred",
                    "--watched",
                    "--followers",
                    "--following",
                ]
            )
        args.append(target)
        self._run_command(args, check=True, text=True)

    def fetch_lfs(self, target: str) -> None:
        for repository in self._bare_repositories(target):
            self._run_command(
                ["git", "-C", str(repository), "lfs", "fetch", "--all"],
                check=True,
                text=True,
            )

    def verify_backup(self, target: str) -> None:
        metadata_dir = self._config.data_dir / "metadata" / target
        if not metadata_dir.is_dir():
            raise RuntimeError(f"Metadata directory missing: {metadata_dir}")
        for repository in self._bare_repositories(target):
            self._run_command(
                ["git", "-C", str(repository), "fsck", "--full"],
                check=True,
                text=True,
            )

    def _bare_repositories(self, target: str) -> list[Path]:
        mirror_root = self._config.data_dir / "mirrors" / f"{target}_backup"
        if not mirror_root.is_dir():
            raise RuntimeError(f"Mirror directory missing: {mirror_root}")

        repositories: list[Path] = []
        for candidate in sorted(mirror_root.iterdir()):
            if not candidate.is_dir():
                continue
            result = self._run_command(
                ["git", "-C", str(candidate), "rev-parse", "--is-bare-repository"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                repositories.append(candidate)
        return repositories
