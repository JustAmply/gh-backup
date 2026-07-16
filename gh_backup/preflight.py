"""Semantic preflight checks for backup configuration and storage."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


BOOLEAN_VALUES = {"0", "1", "false", "true", "no", "yes", "off", "on"}


def _number(
    environment: Mapping[str, str], name: str, default: str, errors: list[str]
) -> float | None:
    try:
        return float(environment.get(name, default))
    except ValueError:
        errors.append(f"{name} must be a number")
        return None


def validate_environment(environment: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    if not environment.get("GITHUB_TOKEN", "").strip("\r\n"):
        errors.append("GitHub token value is empty")

    for name, default in (
        ("RUN_ON_STARTUP", "true"),
        ("GHORG_INCLUDE_SUBMODULES", "true"),
    ):
        if environment.get(name, default).casefold() not in BOOLEAN_VALUES:
            errors.append(f"{name} must be a boolean value")

    maximum_age = _number(
        environment, "BACKUP_MAX_AGE_HOURS", "26", errors
    )
    if maximum_age is not None and maximum_age <= 0:
        errors.append("BACKUP_MAX_AGE_HOURS must be greater than zero")

    minimum_free_gb = _number(
        environment, "BACKUP_MIN_FREE_GB", "1", errors
    )
    if minimum_free_gb is not None and minimum_free_gb < 0:
        errors.append("BACKUP_MIN_FREE_GB must not be negative")

    data_dir = Path(environment.get("BACKUP_DATA_DIR", "/data"))
    if not data_dir.is_dir():
        errors.append(f"Backup data directory does not exist: {data_dir}")
        return errors

    try:
        with tempfile.TemporaryFile(dir=data_dir):
            pass
    except OSError as exc:
        errors.append(f"Backup data directory is not writable: {data_dir} ({exc})")

    if minimum_free_gb is not None and minimum_free_gb >= 0:
        free_gb = shutil.disk_usage(data_dir).free / (1024**3)
        if free_gb < minimum_free_gb:
            errors.append(
                f"Backup data directory has {free_gb:.2f} GiB free; "
                f"{minimum_free_gb:.2f} GiB required"
            )
    return errors


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] = os.environ,
) -> int:
    del argv
    errors = validate_environment(environment)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
