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
    token_file_value = environment.get("GITHUB_TOKEN_FILE", "").strip()
    token_file = Path(token_file_value) if token_file_value else None
    token_present = bool(environment.get("GITHUB_TOKEN", "").strip("\r\n"))
    if token_file is not None:
        try:
            token_present = bool(
                token_file.read_text(encoding="utf-8").strip("\r\n")
            )
        except OSError as exc:
            errors.append(f"GitHub token file is not readable: {token_file} ({exc})")
    if not token_present:
        errors.append("GitHub token value is empty")

    if environment.get("RESTIC_REPOSITORY", "").strip():
        password_file = Path(environment.get("RESTIC_PASSWORD_FILE", ""))
        try:
            password_present = bool(
                password_file.read_text(encoding="utf-8").strip("\r\n")
            )
        except OSError as exc:
            password_present = False
            errors.append(f"RESTIC_PASSWORD_FILE is not readable: {exc}")
        if not password_present and password_file.is_file():
            errors.append("RESTIC_PASSWORD_FILE is empty")

        for name, default in (
            ("BACKUP_RETENTION_DAILY", "7"),
            ("BACKUP_RETENTION_WEEKLY", "5"),
            ("BACKUP_RETENTION_MONTHLY", "12"),
        ):
            try:
                value = int(environment.get(name, default))
            except ValueError:
                errors.append(f"{name} must be an integer")
                continue
            if value <= 0:
                errors.append(f"{name} must be greater than zero")

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
