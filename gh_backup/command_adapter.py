"""Adapters for the external backup command-line tools."""

from __future__ import annotations

import atexit
import json
import os
import tempfile
from pathlib import Path

from gh_backup.coverage import CoveragePolicy
from gh_backup.process import CommandRunner, command_runner_from_environment
from gh_backup.runner import BackupConfig
from gh_backup.restore import verify_mirror_restore


class CommandBackupAdapter:
    def __init__(
        self,
        config: BackupConfig,
        *,
        run_command: CommandRunner | None = None,
    ) -> None:
        self._config = config
        self._run_command = run_command or command_runner_from_environment()
        self._coverage = CoveragePolicy.load_default()
        self._owned_token_file: Path | None = None
        self._owned_git_config: Path | None = None
        self._token_file = self._resolve_token_file()

    def _resolve_token_file(self) -> Path:
        if self._config.token_file is not None:
            token_file = self._config.token_file.resolve()
            if not token_file.is_file():
                raise RuntimeError(f"GitHub token file is missing: {token_file}")
            return token_file
        descriptor, path_value = tempfile.mkstemp(prefix="gh-backup-token-")
        token_file = Path(path_value)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(self._config.token)
            handle.flush()
            os.fsync(handle.fileno())
        token_file.chmod(0o600)
        self._owned_token_file = token_file
        atexit.register(self.cleanup)
        return token_file

    def cleanup(self) -> None:
        if self._owned_token_file is not None:
            self._owned_token_file.unlink(missing_ok=True)
            self._owned_token_file = None
        if self._owned_git_config is not None:
            self._owned_git_config.unlink(missing_ok=True)
            self._owned_git_config = None

    def describe_tools(self) -> dict[str, str]:
        commands = {
            "ghorg": ["ghorg", "version"],
            "github-backup": ["github-backup", "--version"],
            "git": ["git", "--version"],
            "git-lfs": ["git-lfs", "version"],
            "restic": ["restic", "version"],
        }
        versions: dict[str, str] = {}
        for name, args in commands.items():
            result = self._run_command(
                args, check=True, capture_output=True, text=True
            )
            version = result.stdout.strip()
            if not version:
                raise RuntimeError(f"{name} returned an empty version")
            versions[name] = version
        return versions

    def configure_authentication(self) -> None:
        descriptor, path_value = tempfile.mkstemp(prefix="gh-backup-gitconfig-")
        os.close(descriptor)
        self._owned_git_config = Path(path_value)
        self._owned_git_config.chmod(0o600)
        os.environ["GITHUB_TOKEN_FILE"] = str(self._token_file)
        os.environ["GIT_CONFIG_GLOBAL"] = str(self._owned_git_config)
        config_args = ["git", "config", "--file", str(self._owned_git_config)]
        self._run_command(
            [
                *config_args,
                "url.https://github.com/.insteadOf",
                "git@github.com:",
            ],
            check=True,
            text=True,
        )
        self._run_command(
            [
                *config_args,
                "credential.https://github.com/.helper",
                (
                    "!f() { echo username=x-access-token; "
                    "echo password=$(cat \"$GITHUB_TOKEN_FILE\"); }; f"
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
            f"--token={self._token_file}",
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
            self._token_file.as_uri(),
            "--output-directory",
            str(metadata_dir),
            *self._coverage.metadata_arguments(target_kind),
        ]
        if target_kind == "organization":
            args.append("--organization")
        args.append(target)
        self._run_command(args, check=True, text=True)

    def fetch_lfs(self, target: str) -> None:
        for repository in self._bare_repositories(target):
            self._run_command(
                ["git", "-C", str(repository), "lfs", "fetch", "--all"],
                check=True,
                text=True,
            )

    def verify_backup(self, target: str) -> str:
        metadata_dir = self._config.data_dir / "metadata" / target
        if not metadata_dir.is_dir():
            raise RuntimeError(f"Metadata directory missing: {metadata_dir}")
        json_files = sorted(metadata_dir.rglob("*.json"))
        if not json_files:
            raise RuntimeError(f"No metadata JSON files found: {metadata_dir}")
        for json_file in json_files:
            with json_file.open(encoding="utf-8") as handle:
                json.load(handle)

        repositories = self._bare_repositories(target)
        for repository in repositories:
            self._run_command(
                ["git", "-C", str(repository), "fsck", "--full"],
                check=True,
                text=True,
            )
        restore_detail = "no repository mirror required a restore drill"
        if repositories:
            evidence = verify_mirror_restore(
                source=repositories[0],
                workspace=self._config.data_dir / "state" / "restore-drills",
                run_command=self._run_command,
            )
            restore_detail = (
                f"local restore drill matched {evidence.ref_count} refs for "
                f"{evidence.source.name}"
            )
        return (
            f"{len(repositories)} mirrors passed git fsck; "
            f"{len(json_files)} metadata JSON files parsed; {restore_detail}"
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
