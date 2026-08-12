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
from typing import MutableMapping, Protocol

from gh_backup.configuration import (
    BackupConfig,
    ConfigurationError,
    OffsiteConfig,
    OperationalConfig,
)
from gh_backup.manifest import RunManifest
from gh_backup.offsite import OffsiteEvidence


LOGGER = logging.getLogger(__name__)


class BackupAdapter(Protocol):
    def resolve_authenticated_login(self) -> str: ...

    def describe_tools(self) -> dict[str, str]: ...

    def configure_authentication(self) -> None: ...

    def mirror_repositories(self, target: str, target_kind: str) -> None: ...

    def fetch_lfs(self, target: str) -> None: ...

    def export_metadata(self, target: str, target_kind: str) -> None: ...

    def verify_backup(self, target: str) -> str | None: ...


class ManagedBackupAdapter(BackupAdapter, Protocol):
    def cleanup(self) -> None: ...


class OffsiteAdapter(Protocol):
    def archive(self, *, run_id: str, data_dir: Path) -> OffsiteEvidence: ...


AdapterFactory = Callable[[BackupConfig], ManagedBackupAdapter]
OffsiteAdapterFactory = Callable[[OffsiteConfig | None], OffsiteAdapter | None]


@dataclass(frozen=True)
class BackupExecution:
    errors: tuple[str, ...] = ()


class BackupRunner:
    """Execute the required stages and publish their recovery evidence."""

    def __init__(
        self,
        *,
        config: BackupConfig,
        adapter: BackupAdapter,
        offsite_adapter: OffsiteAdapter | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._offsite_adapter = offsite_adapter
        self._clock = clock

    def run(self, manifest: RunManifest) -> BackupExecution:
        try:
            owner = self._adapter.resolve_authenticated_login()
        except Exception as exc:
            detail = str(exc).replace(self._config.token, "***")
            LOGGER.error("GitHub login resolution failed: %s", detail)
            return BackupExecution(errors=(detail,))
        if self._config.owner and self._config.owner.casefold() != owner.casefold():
            detail = (
                f"GITHUB_OWNER ({self._config.owner}) must match the GitHub account "
                f"behind GITHUB_TOKEN ({owner})"
            )
            LOGGER.error("%s", detail)
            return BackupExecution(errors=(detail,))
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
            return BackupExecution(errors=(detail,))
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
            return BackupExecution(errors=(detail,))

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
                evidence = self._offsite_adapter.archive(
                    run_id=manifest.run_id, data_dir=self._config.data_dir
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
                    detail=evidence.detail,
                    evidence={"snapshot_id": evidence.snapshot_id},
                )

        return BackupExecution()

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


class BackupApplication:
    """Own one backup run from manifest creation through adapter cleanup."""

    def __init__(
        self,
        *,
        environment: MutableMapping[str, str],
        adapter_factory: AdapterFactory,
        offsite_adapter_factory: OffsiteAdapterFactory,
        clock: Callable[[], datetime],
    ) -> None:
        self._environment = environment
        self._adapter_factory = adapter_factory
        self._offsite_adapter_factory = offsite_adapter_factory
        self._clock = clock

    def run(self) -> int:
        started_at = self._clock()
        run_id = self._environment.get(
            "GH_BACKUP_RUN_ID",
            f"{started_at.astimezone().strftime('%Y%m%dT%H%M%SZ')}-"
            f"{secrets.token_hex(4)}",
        )
        data_dir = Path(self._environment.get("BACKUP_DATA_DIR", "/data"))
        log_file = self._environment.get(
            "GH_BACKUP_LOG_FILE", str(data_dir / "logs" / f"{run_id}.log")
        )
        manifest = RunManifest.start(
            state_dir=data_dir / "state",
            run_id=run_id,
            started_at=started_at,
            log_file=log_file,
        )

        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch(exist_ok=True)
        except OSError as exc:
            detail = f"Backup log cannot be created: {exc}"
            LOGGER.error("%s", detail)
            manifest.fail(errors=detail, finished_at=self._clock())
            return 1

        try:
            operational_config = OperationalConfig.from_environment(
                self._environment
            )
        except ConfigurationError as exc:
            for detail in exc.errors:
                LOGGER.error("backup configuration invalid: %s", detail)
            manifest.fail(errors=exc.errors, finished_at=self._clock())
            return 1

        config = operational_config.backup
        self._environment.pop("GITHUB_TOKEN", None)
        adapter: ManagedBackupAdapter | None = None
        execution = BackupExecution()
        lifecycle_errors: list[str] = []
        try:
            adapter = self._adapter_factory(config)
            offsite_adapter = self._offsite_adapter_factory(
                operational_config.offsite
            )
            execution = BackupRunner(
                config=config,
                adapter=adapter,
                offsite_adapter=offsite_adapter,
                clock=self._clock,
            ).run(manifest)
        except Exception as exc:
            detail = str(exc).replace(config.token, "***")
            LOGGER.error("backup run failed unexpectedly: %s", detail)
            lifecycle_errors.append(detail)
        finally:
            if adapter is not None:
                try:
                    adapter.cleanup()
                except Exception as exc:
                    detail = str(exc).replace(config.token, "***")
                    LOGGER.error("backup adapter cleanup failed: %s", detail)
                    lifecycle_errors.append(detail)

        errors = [*execution.errors, *lifecycle_errors]
        if errors:
            manifest.fail(errors=errors, finished_at=self._clock())
            return 1
        terminal_status = manifest.finish(finished_at=self._clock())
        return 0 if terminal_status == "verified" else 1


def main() -> int:
    from gh_backup.command_adapter import CommandBackupAdapter
    from gh_backup.offsite import offsite_adapter_from_config

    logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s")
    return BackupApplication(
        environment=os.environ,
        adapter_factory=CommandBackupAdapter,
        offsite_adapter_factory=offsite_adapter_from_config,
        clock=lambda: datetime.now().astimezone(),
    ).run()


if __name__ == "__main__":
    sys.exit(main())
