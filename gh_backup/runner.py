"""Backup-run orchestration independent of concrete command adapters."""

from __future__ import annotations

import logging
import os
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Protocol

from gh_backup.manifest import RunManifest


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupConfig:
    owner: str
    orgs: tuple[str, ...]
    token: str
    data_dir: Path
    include_submodules: bool

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> BackupConfig:
        owner = environment.get("GITHUB_OWNER", "").strip()
        token = environment.get("GITHUB_TOKEN", "").strip("\r\n")
        if not owner:
            raise ValueError("GITHUB_OWNER must contain the authenticated login")
        if not token:
            raise ValueError("GitHub token value is empty")

        orgs: list[str] = []
        seen = {owner.casefold()}
        for configured_org in environment.get("GITHUB_ORGS", "").split(","):
            org = configured_org.strip()
            normalized = org.casefold()
            if org and normalized not in seen:
                seen.add(normalized)
                orgs.append(org)

        include_submodules = environment.get(
            "GHORG_INCLUDE_SUBMODULES", "true"
        ).casefold() in {"1", "true", "yes", "on"}
        return cls(
            owner=owner,
            orgs=tuple(orgs),
            token=token,
            data_dir=Path(environment.get("BACKUP_DATA_DIR", "/data")),
            include_submodules=include_submodules,
        )


class BackupAdapter(Protocol):
    def configure_authentication(self) -> None: ...

    def mirror_repositories(self, target: str, target_kind: str) -> None: ...

    def fetch_lfs(self, target: str) -> None: ...

    def export_metadata(self, target: str, target_kind: str) -> None: ...

    def verify_backup(self, target: str) -> str | None: ...


class BackupRunner:
    """Execute the required stages and publish their recovery evidence."""

    def __init__(
        self,
        *,
        config: BackupConfig,
        adapter: BackupAdapter,
        run_id: str,
        log_file: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._run_id = run_id
        self._log_file = log_file
        self._clock = clock

    def run(self) -> int:
        manifest = RunManifest.start(
            state_dir=self._config.data_dir / "state",
            run_id=self._run_id,
            started_at=self._clock(),
            log_file=self._log_file,
        )
        manifest.set_targets(owner=self._config.owner, orgs=list(self._config.orgs))
        try:
            self._adapter.configure_authentication()
        except Exception as exc:
            detail = str(exc).replace(self._config.token, "***")
            LOGGER.error("backup authentication failed: %s", detail)
            manifest.record_error(detail)
            manifest.finish(status="failed", finished_at=self._clock())
            return 1

        all_targets_succeeded = True
        for target, target_kind in self._targets():
            target_succeeded = True
            stages: list[tuple[str, Callable[[], str | None]]] = [
                (
                    "repository_mirror",
                    lambda target=target, target_kind=target_kind: (
                        self._adapter.mirror_repositories(target, target_kind)
                    ),
                ),
                ("lfs", lambda target=target: self._adapter.fetch_lfs(target)),
                (
                    "metadata",
                    lambda target=target, target_kind=target_kind: (
                        self._adapter.export_metadata(target, target_kind)
                    ),
                ),
                (
                    "verification",
                    lambda target=target: self._adapter.verify_backup(target),
                ),
            ]
            for stage, operation in stages:
                if not target_succeeded:
                    timestamp = self._clock()
                    manifest.record_stage(
                        target=target,
                        stage=stage,
                        status="skipped",
                        started_at=timestamp,
                        finished_at=timestamp,
                        detail="A required earlier stage failed",
                    )
                    continue
                target_succeeded = self._run_stage(
                    manifest, target, stage, operation
                )
                all_targets_succeeded &= target_succeeded

        terminal_status = "verified" if all_targets_succeeded else "failed"
        manifest.finish(status=terminal_status, finished_at=self._clock())
        return 0 if all_targets_succeeded else 1

    def _targets(self) -> list[tuple[str, str]]:
        return [
            (self._config.owner, "user"),
            *((org, "organization") for org in self._config.orgs),
        ]

    def _run_stage(
        self,
        manifest: RunManifest,
        target: str,
        stage: str,
        operation: Callable[[], str | None],
    ) -> bool:
        started_at = self._clock()
        try:
            detail = operation()
        except Exception as exc:
            detail = str(exc).replace(self._config.token, "***")
            failure_names = {
                "repository_mirror": "ghorg backup",
                "lfs": "Git LFS fetch",
                "metadata": "github-backup metadata export",
                "verification": "backup verification",
            }
            LOGGER.error("%s failed for %s: %s", failure_names[stage], target, detail)
            manifest.record_stage(
                target=target,
                stage=stage,
                status="failed",
                started_at=started_at,
                finished_at=self._clock(),
                detail=detail,
            )
            return False
        manifest.record_stage(
            target=target,
            stage=stage,
            status="succeeded",
            started_at=started_at,
            finished_at=self._clock(),
            detail=detail,
        )
        return True


def main() -> int:
    from gh_backup.command_adapter import CommandBackupAdapter

    logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s")
    config = BackupConfig.from_environment(os.environ)
    now = datetime.now().astimezone()
    run_id = os.environ.get(
        "GH_BACKUP_RUN_ID",
        f"{now.astimezone().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}",
    )
    log_file = os.environ.get(
        "GH_BACKUP_LOG_FILE", str(config.data_dir / "logs" / f"{run_id}.log")
    )
    return BackupRunner(
        config=config,
        adapter=CommandBackupAdapter(config),
        run_id=run_id,
        log_file=log_file,
        clock=lambda: datetime.now().astimezone(),
    ).run()


if __name__ == "__main__":
    sys.exit(main())
