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
        return json.load(handle)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def evaluate_health(
    *, state_dir: Path, now: datetime, maximum_age: timedelta
) -> HealthReport:
    last_run_path = state_dir / "last-run.json"
    recovery_point_path = state_dir / "last-success.json"
    try:
        last_run = _read_json(last_run_path)
    except (OSError, json.JSONDecodeError):
        return HealthReport(
            status="unhealthy",
            reason=f"recovery state is unreadable: {last_run_path.name}",
            last_run_id=None,
            recovery_point_run_id=None,
            recovery_age_seconds=None,
        )
    try:
        recovery_point = _read_json(recovery_point_path)
    except (OSError, json.JSONDecodeError):
        return HealthReport(
            status="unhealthy",
            reason=f"recovery state is unreadable: {recovery_point_path.name}",
            last_run_id=last_run.get("run_id") if last_run else None,
            recovery_point_run_id=None,
            recovery_age_seconds=None,
        )
    if recovery_point is None:
        return HealthReport(
            status="unhealthy",
            reason="no verified recovery point exists",
            last_run_id=last_run.get("run_id") if last_run else None,
            recovery_point_run_id=None,
            recovery_age_seconds=None,
        )

    finished_at = _parse_timestamp(str(recovery_point["finished_at"]))
    age = now.astimezone(UTC) - finished_at
    if last_run and last_run.get("status") == "failed":
        return HealthReport(
            status="unhealthy",
            reason="latest backup run failed",
            last_run_id=str(last_run["run_id"]),
            recovery_point_run_id=str(recovery_point["run_id"]),
            recovery_age_seconds=int(age.total_seconds()),
        )
    if age > maximum_age:
        return HealthReport(
            status="unhealthy",
            reason="latest recovery point is stale",
            last_run_id=last_run.get("run_id") if last_run else None,
            recovery_point_run_id=str(recovery_point["run_id"]),
            recovery_age_seconds=int(age.total_seconds()),
        )
    return HealthReport(
        status="healthy",
        reason="latest recovery point is current",
        last_run_id=last_run.get("run_id") if last_run else None,
        recovery_point_run_id=str(recovery_point["run_id"]),
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
