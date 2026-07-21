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
    token_file: Path | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> BackupConfig:
        owner = environment.get("GITHUB_OWNER", "").strip()
        configured_token_file = environment.get("GITHUB_TOKEN_FILE", "").strip()
        token_file = Path(configured_token_file) if configured_token_file else None
        if token_file is not None:
            token = token_file.read_text(encoding="utf-8").strip("\r\n")
        else:
            token = environment.get("GITHUB_TOKEN", "").strip("\r\n")
        if owner == "change-me":
            owner = ""
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
            token_file=token_file,
        )


class BackupAdapter(Protocol):
    def resolve_authenticated_login(self) -> str: ...

    def describe_tools(self) -> dict[str, str]: ...

    def configure_authentication(self) -> None: ...

    def mirror_repositories(self, target: str, target_kind: str) -> None: ...

    def fetch_lfs(self, target: str) -> None: ...

    def export_metadata(self, target: str, target_kind: str) -> None: ...

    def verify_backup(self, target: str) -> str | None: ...


class OffsiteAdapter(Protocol):
    def archive(self, *, run_id: str, data_dir: Path) -> str: ...


class BackupRunner:
    """Execute the required stages and publish their recovery evidence."""

    def __init__(
        self,
        *,
        config: BackupConfig,
        adapter: BackupAdapter,
        offsite_adapter: OffsiteAdapter | None = None,
        run_id: str,
        log_file: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._offsite_adapter = offsite_adapter
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
        try:
            owner = self._adapter.resolve_authenticated_login()
        except Exception as exc:
            detail = str(exc).replace(self._config.token, "***")
            LOGGER.error("GitHub login resolution failed: %s", detail)
            manifest.record_error(detail)
            manifest.finish(status="failed", finished_at=self._clock())
            return 1
        if self._config.owner and self._config.owner.casefold() != owner.casefold():
            detail = (
                f"GITHUB_OWNER ({self._config.owner}) must match the GitHub account "
                f"behind GITHUB_TOKEN ({owner})"
            )
            LOGGER.error("%s", detail)
            manifest.record_error(detail)
            manifest.finish(status="failed", finished_at=self._clock())
            return 1
        if self._config.owner and self._config.owner != owner:
            LOGGER.warning(
                "Normalizing GITHUB_OWNER from %s to %s", self._config.owner, owner
            )
        targets = self._targets(owner)
        manifest.set_targets(
            owner=owner,
            orgs=[
                target
                for target, target_kind in targets
                if target_kind == "organization"
            ],
        )
        try:
            tool_versions = self._adapter.describe_tools()
        except Exception as exc:
            detail = str(exc).replace(self._config.token, "***")
            LOGGER.error("backup tool inspection failed: %s", detail)
            manifest.record_error(detail)
            manifest.finish(status="failed", finished_at=self._clock())
            return 1
        manifest.set_run_context(
            configuration={
                "include_submodules": self._config.include_submodules,
                "offsite_enabled": self._offsite_adapter is not None,
            },
            tool_versions=tool_versions,
        )
        try:
            self._adapter.configure_authentication()
        except Exception as exc:
            detail = str(exc).replace(self._config.token, "***")
            LOGGER.error("backup authentication failed: %s", detail)
            manifest.record_error(detail)
            manifest.finish(status="failed", finished_at=self._clock())
            return 1

        all_targets_succeeded = True
        for target, target_kind in targets:
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

        if all_targets_succeeded and self._offsite_adapter is not None:
            started_at = self._clock()
            try:
                detail = self._offsite_adapter.archive(
                    run_id=self._run_id, data_dir=self._config.data_dir
                )
            except Exception as exc:
                detail = str(exc).replace(self._config.token, "***")
                LOGGER.error("offsite archive failed: %s", detail)
                manifest.record_run_stage(
                    stage="offsite",
                    status="failed",
                    started_at=started_at,
                    finished_at=self._clock(),
                    detail=detail,
                )
                all_targets_succeeded = False
            else:
                manifest.record_run_stage(
                    stage="offsite",
                    status="succeeded",
                    started_at=started_at,
                    finished_at=self._clock(),
                    detail=detail,
                )

        terminal_status = "verified" if all_targets_succeeded else "failed"
        manifest.finish(status=terminal_status, finished_at=self._clock())
        return 0 if all_targets_succeeded else 1

    def _targets(self, owner: str) -> list[tuple[str, str]]:
        targets = [(owner, "user")]
        seen = {owner.casefold()}
        for org in self._config.orgs:
            if org.casefold() not in seen:
                seen.add(org.casefold())
                targets.append((org, "organization"))
        return targets

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
    from gh_backup.offsite import offsite_adapter_from_environment

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
    adapter = CommandBackupAdapter(config)
    offsite_adapter = offsite_adapter_from_environment(os.environ)
    try:
        return BackupRunner(
            config=config,
            adapter=adapter,
            offsite_adapter=offsite_adapter,
            run_id=run_id,
            log_file=log_file,
            clock=lambda: datetime.now().astimezone(),
        ).run()
    finally:
        adapter.cleanup()
        if os.environ.get("GH_BACKUP_EPHEMERAL_TOKEN_FILE") == "true":
            Path(os.environ["GITHUB_TOKEN_FILE"]).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
