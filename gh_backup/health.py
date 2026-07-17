"""Operational status derived from persisted backup-run evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO


@dataclass(frozen=True)
class HealthReport:
    status: str
    reason: str
    last_run_id: str | None
    recovery_point_run_id: str | None
    recovery_age_seconds: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError("recovery state root must be an object")
    return document


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def evaluate_health(
    *, state_dir: Path, now: datetime, maximum_age: timedelta
) -> HealthReport:
    last_run_path = state_dir / "last-run.json"
    recovery_point_path = state_dir / "last-success.json"
    try:
        last_run = _read_json(last_run_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return HealthReport(
            status="unhealthy",
            reason=f"recovery state is unreadable: {last_run_path.name}",
            last_run_id=None,
            recovery_point_run_id=None,
            recovery_age_seconds=None,
        )
    last_run_id: str | None = None
    if last_run is not None:
        run_id = last_run.get("run_id")
        if (
            not isinstance(run_id, str)
            or not run_id
            or last_run.get("status") not in {"verified", "failed", "degraded"}
        ):
            return HealthReport(
                status="unhealthy",
                reason=f"recovery state is invalid: {last_run_path.name}",
                last_run_id=None,
                recovery_point_run_id=None,
                recovery_age_seconds=None,
            )
        last_run_id = run_id
    try:
        recovery_point = _read_json(recovery_point_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return HealthReport(
            status="unhealthy",
            reason=f"recovery state is unreadable: {recovery_point_path.name}",
            last_run_id=last_run_id,
            recovery_point_run_id=None,
            recovery_age_seconds=None,
        )
    if recovery_point is None:
        return HealthReport(
            status="unhealthy",
            reason="no verified recovery point exists",
            last_run_id=last_run_id,
            recovery_point_run_id=None,
            recovery_age_seconds=None,
        )

    try:
        run_id = recovery_point.get("run_id")
        finished_at_value = recovery_point.get("finished_at")
        if (
            recovery_point.get("status") != "verified"
            or not isinstance(run_id, str)
            or not run_id
            or not isinstance(finished_at_value, str)
        ):
            raise ValueError("recovery point is not verified")
        recovery_point_run_id = run_id
        finished_at = _parse_timestamp(finished_at_value)
    except (KeyError, TypeError, ValueError):
        return HealthReport(
            status="unhealthy",
            reason=f"recovery state is invalid: {recovery_point_path.name}",
            last_run_id=last_run_id,
            recovery_point_run_id=None,
            recovery_age_seconds=None,
        )
    age = now.astimezone(UTC) - finished_at
    if age.total_seconds() < 0:
        return HealthReport(
            status="unhealthy",
            reason="latest recovery point timestamp is in the future",
            last_run_id=last_run_id,
            recovery_point_run_id=recovery_point_run_id,
            recovery_age_seconds=int(age.total_seconds()),
        )
    if last_run and last_run.get("status") == "failed":
        return HealthReport(
            status="unhealthy",
            reason="latest backup run failed",
            last_run_id=last_run_id,
            recovery_point_run_id=recovery_point_run_id,
            recovery_age_seconds=int(age.total_seconds()),
        )
    if age > maximum_age:
        return HealthReport(
            status="unhealthy",
            reason="latest recovery point is stale",
            last_run_id=last_run_id,
            recovery_point_run_id=recovery_point_run_id,
            recovery_age_seconds=int(age.total_seconds()),
        )
    return HealthReport(
        status="healthy",
        reason="latest recovery point is current",
        last_run_id=last_run_id,
        recovery_point_run_id=recovery_point_run_id,
        recovery_age_seconds=int(age.total_seconds()),
    )


def _write_human_report(report: HealthReport, output: TextIO) -> None:
    print(f"health: {report.status}", file=output)
    print(f"reason: {report.reason}", file=output)
    print(f"last run: {report.last_run_id or 'none'}", file=output)
    print(
        f"recovery point: {report.recovery_point_run_id or 'none'}", file=output
    )
    if report.recovery_age_seconds is not None:
        print(f"recovery age seconds: {report.recovery_age_seconds}", file=output)


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] = os.environ,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    output: TextIO | None = None,
) -> int:
    output = output or sys.stdout
    parser = argparse.ArgumentParser(description="Inspect backup recovery health")
    parser.add_argument("command", choices=("status", "health"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args(argv)

    data_dir = Path(environment.get("BACKUP_DATA_DIR", "/data"))
    maximum_age_hours = float(environment.get("BACKUP_MAX_AGE_HOURS", "26"))
    report = evaluate_health(
        state_dir=data_dir / "state",
        now=now(),
        maximum_age=timedelta(hours=maximum_age_hours),
    )
    if arguments.as_json:
        json.dump(report.to_dict(), output, sort_keys=True)
        output.write("\n")
    else:
        _write_human_report(report, output)

    if arguments.command == "status":
        return 0
    return 0 if report.status == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
