"""Persistent evidence for a backup run."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
REQUIRED_TARGET_STAGES = (
    "repository_mirror",
    "lfs",
    "metadata",
    "verification",
)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_json_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@dataclass
class RunManifest:
    """A backup run whose current state is persisted after every transition."""

    _state_dir: Path
    _document: dict[str, Any]

    @classmethod
    def start(
        cls,
        *,
        state_dir: Path,
        run_id: str,
        started_at: datetime,
        log_file: str,
    ) -> RunManifest:
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError(f"Invalid run ID: {run_id!r}")
        run_path = state_dir / "runs" / f"{run_id}.json"
        if run_path.exists():
            raise FileExistsError(f"Run manifest already exists: {run_path}")
        manifest = cls(
            _state_dir=state_dir,
            _document={
                "schema_version": 1,
                "run_id": run_id,
                "status": "running",
                "started_at": _format_timestamp(started_at),
                "finished_at": None,
                "log_file": log_file,
                "errors": [],
                "run_stages": {},
                "targets": {},
            },
        )
        manifest._persist()
        return manifest

    @property
    def run_id(self) -> str:
        return str(self._document["run_id"])

    @property
    def is_running(self) -> bool:
        return self._document["status"] == "running"

    def set_targets(self, *, owner: str, orgs: list[str]) -> None:
        self._ensure_running()
        self._document["owner"] = owner
        self._document["orgs"] = list(orgs)
        self._document["targets"] = {
            owner: {"kind": "user", "stages": {}},
            **{
                org: {"kind": "organization", "stages": {}}
                for org in orgs
            },
        }
        self._persist()

    def set_run_context(
        self,
        *,
        configuration: dict[str, Any],
        tool_versions: dict[str, str],
    ) -> None:
        self._ensure_running()
        self._document["configuration"] = dict(configuration)
        self._document["tool_versions"] = dict(tool_versions)
        self._persist()

    def fail(
        self,
        *,
        errors: str | Iterable[str],
        finished_at: datetime,
    ) -> str:
        self._ensure_running()
        details = [errors] if isinstance(errors, str) else list(errors)
        self._document["errors"].extend(detail for detail in details if detail)
        return self._finish(status="failed", finished_at=finished_at)

    def record_run_stage(
        self,
        *,
        stage: str,
        status: str,
        started_at: datetime,
        finished_at: datetime,
        detail: str | None = None,
        evidence: dict[str, str] | None = None,
    ) -> None:
        self._ensure_running()
        if status not in {"succeeded", "failed", "skipped"}:
            raise ValueError(f"Invalid run stage status: {status}")
        stage_document = {
            "status": status,
            "started_at": _format_timestamp(started_at),
            "finished_at": _format_timestamp(finished_at),
        }
        if detail is not None:
            stage_document["detail"] = detail
        if evidence is not None:
            stage_document["evidence"] = dict(evidence)
        self._document["run_stages"][stage] = stage_document
        self._persist()

    def record_stage(
        self,
        *,
        target: str,
        stage: str,
        status: str,
        started_at: datetime,
        finished_at: datetime,
        detail: str | None = None,
    ) -> None:
        self._ensure_running()
        if status not in {"succeeded", "failed", "skipped"}:
            raise ValueError(f"Invalid stage status: {status}")
        target_document = self._document["targets"][target]
        stage_document = {
            "status": status,
            "started_at": _format_timestamp(started_at),
            "finished_at": _format_timestamp(finished_at),
        }
        if detail is not None:
            stage_document["detail"] = detail
        target_document["stages"][stage] = stage_document
        self._persist()

    def finish(self, *, finished_at: datetime) -> str:
        self._ensure_running()
        qualification_errors = self._qualification_errors()
        if qualification_errors:
            self._document["errors"].extend(qualification_errors)
            status = "failed"
        else:
            status = "verified"
        return self._finish(status=status, finished_at=finished_at)

    def _finish(self, *, status: str, finished_at: datetime) -> str:
        self._document["status"] = status
        self._document["finished_at"] = _format_timestamp(finished_at)
        self._persist()
        _write_json_atomically(self._state_dir / "last-run.json", self._document)
        if status == "verified":
            _write_json_atomically(
                self._state_dir / "last-success.json", self._document
            )
        return status

    def _qualification_errors(self) -> list[str]:
        errors: list[str] = []
        targets = self._document.get("targets")
        if not isinstance(targets, dict) or not targets:
            errors.append("Recovery qualification requires at least one backup target")
        else:
            for target, target_document in targets.items():
                stages = target_document.get("stages", {})
                for stage in REQUIRED_TARGET_STAGES:
                    stage_document = stages.get(stage)
                    status = (
                        stage_document.get("status")
                        if isinstance(stage_document, dict)
                        else None
                    )
                    if status != "succeeded":
                        errors.append(
                            f"Recovery qualification requires {target}/{stage} "
                            "to succeed"
                        )

        configuration = self._document.get("configuration")
        if not isinstance(configuration, dict):
            errors.append("Recovery qualification requires run configuration")
        elif configuration.get("offsite_enabled") is True:
            offsite = self._document["run_stages"].get("offsite")
            if not isinstance(offsite, dict) or offsite.get("status") != "succeeded":
                errors.append("Recovery qualification requires offsite to succeed")
            else:
                evidence = offsite.get("evidence")
                snapshot_id = (
                    evidence.get("snapshot_id")
                    if isinstance(evidence, dict)
                    else None
                )
                if not isinstance(snapshot_id, str) or not snapshot_id:
                    errors.append(
                        "Recovery qualification requires an offsite snapshot identity"
                    )

        tool_versions = self._document.get("tool_versions")
        if not isinstance(tool_versions, dict) or not tool_versions:
            errors.append("Recovery qualification requires backup tool versions")
        return errors

    def _persist(self) -> None:
        _write_json_atomically(
            self._state_dir / "runs" / f"{self.run_id}.json", self._document
        )

    def _ensure_running(self) -> None:
        if not self.is_running:
            raise RuntimeError("A terminal run manifest cannot transition again")
