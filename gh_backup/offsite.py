"""Encrypted offsite snapshots and retention through Restic."""

from __future__ import annotations

from pathlib import Path

from gh_backup.configuration import OffsiteConfig, RetentionPolicy
from gh_backup.process import CommandRunner, command_runner_from_environment


class ResticOffsiteAdapter:
    def __init__(
        self,
        *,
        retention: RetentionPolicy,
        run_command: CommandRunner | None = None,
    ) -> None:
        self._retention = retention
        self._run_command = run_command or command_runner_from_environment()

    def archive(self, *, run_id: str, data_dir: Path) -> str:
        self._run_command(
            [
                "restic",
                "backup",
                str(data_dir),
                "--tag",
                "gh-backup",
                "--tag",
                f"run:{run_id}",
                "--exclude",
                str(data_dir / "state" / "restore-drills"),
            ],
            check=True,
            text=True,
        )
        self._run_command(["restic", "check"], check=True, text=True)
        self._run_command(
            [
                "restic",
                "forget",
                "--tag",
                "gh-backup",
                "--keep-daily",
                str(self._retention.daily),
                "--keep-weekly",
                str(self._retention.weekly),
                "--keep-monthly",
                str(self._retention.monthly),
                "--prune",
            ],
            check=True,
            text=True,
        )
        return "encrypted offsite snapshot verified and retained"


def offsite_adapter_from_config(
    config: OffsiteConfig | None,
) -> ResticOffsiteAdapter | None:
    if config is None:
        return None
    return ResticOffsiteAdapter(retention=config.retention)
