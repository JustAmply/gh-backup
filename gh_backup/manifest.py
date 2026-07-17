"""Persistent evidence for a backup run."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


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

    state_dir: Path
    document: dict[str, Any]

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
            state_dir=state_dir,
            document={
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
        return str(self.document["run_id"])

    def set_targets(self, *, owner: str, orgs: list[str]) -> None:
        self._ensure_running()
        self.document["owner"] = owner
        self.document["orgs"] = list(orgs)
        self.document["targets"] = {
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
        self.document["configuration"] = dict(configuration)
        self.document["tool_versions"] = dict(tool_versions)
        self._persist()

    def record_error(self, detail: str) -> None:
        self._ensure_running()
        self.document["errors"].append(detail)
        self._persist()

    def record_run_stage(
        self,
        *,
        stage: str,
        status: str,
        started_at: datetime,
        finished_at: datetime,
        detail: str | None = None,
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
        self.document["run_stages"][stage] = stage_document
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
        target_document = self.document["targets"][target]
        stage_document = {
            "status": status,
            "started_at": _format_timestamp(started_at),
            "finished_at": _format_timestamp(finished_at),
        }
        if detail is not None:
            stage_document["detail"] = detail
        target_document["stages"][stage] = stage_document
        self._persist()

    def finish(self, *, status: str, finished_at: datetime) -> None:
        if status not in {"verified", "failed", "degraded"}:
            raise ValueError(f"Invalid terminal run status: {status}")
        if self.document["status"] != "running":
            raise RuntimeError("A terminal run manifest cannot transition again")

        self.document["status"] = status
        self.document["finished_at"] = _format_timestamp(finished_at)
        self._persist()
        _write_json_atomically(self.state_dir / "last-run.json", self.document)
        if status == "verified":
            _write_json_atomically(self.state_dir / "last-success.json", self.document)

    def _persist(self) -> None:
        _write_json_atomically(
            self.state_dir / "runs" / f"{self.run_id}.json", self.document
        )

    def _ensure_running(self) -> None:
        if self.document["status"] != "running":
            raise RuntimeError("A terminal run manifest cannot transition again")
