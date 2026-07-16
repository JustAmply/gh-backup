"""Encrypted offsite snapshots and retention through Restic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from gh_backup.process import CommandRunner, command_runner_from_environment


@dataclass(frozen=True)
class RetentionPolicy:
    daily: int
    weekly: int
    monthly: int


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


def offsite_adapter_from_environment(
    environment: Mapping[str, str],
) -> ResticOffsiteAdapter | None:
    if not environment.get("RESTIC_REPOSITORY", "").strip():
        return None
    retention = RetentionPolicy(
        daily=int(environment.get("BACKUP_RETENTION_DAILY", "7")),
        weekly=int(environment.get("BACKUP_RETENTION_WEEKLY", "5")),
        monthly=int(environment.get("BACKUP_RETENTION_MONTHLY", "12")),
    )
    return ResticOffsiteAdapter(retention=retention)
