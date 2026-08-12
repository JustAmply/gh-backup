"""Encrypted offsite snapshots and retention through Restic."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from gh_backup.configuration import OffsiteConfig, RetentionPolicy
from gh_backup.process import CommandRunner, command_runner_from_environment


@dataclass(frozen=True)
class OffsiteEvidence:
    snapshot_id: str
    detail: str


class ResticOffsiteAdapter:
    def __init__(
        self,
        *,
        retention: RetentionPolicy,
        run_command: CommandRunner | None = None,
    ) -> None:
        self._retention = retention
        self._run_command = run_command or command_runner_from_environment()

    def archive(self, *, run_id: str, data_dir: Path) -> OffsiteEvidence:
        result = self._run_command(
            [
                "restic",
                "backup",
                str(data_dir / "mirrors"),
                str(data_dir / "metadata"),
                "--tag",
                "gh-backup",
                "--tag",
                f"run:{run_id}",
                "--json",
                "--quiet",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        snapshot_id = _snapshot_id(result.stdout)
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
        return OffsiteEvidence(
            snapshot_id=snapshot_id,
            detail=f"encrypted offsite snapshot {snapshot_id} verified and retained",
        )


def _snapshot_id(output: str) -> str:
    for line in output.splitlines():
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(document, dict) or document.get("message_type") != "summary":
            continue
        snapshot_id = document.get("snapshot_id")
        if isinstance(snapshot_id, str) and snapshot_id:
            return snapshot_id
    raise RuntimeError("Restic backup did not report a snapshot ID")


def offsite_adapter_from_config(
    config: OffsiteConfig | None,
) -> ResticOffsiteAdapter | None:
    if config is None:
        return None
    return ResticOffsiteAdapter(retention=config.retention)
