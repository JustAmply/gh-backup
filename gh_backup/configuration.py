"""One interpretation of operational configuration for every caller."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Mapping


BOOLEAN_VALUES = {
    "0": False,
    "1": True,
    "false": False,
    "true": True,
    "no": False,
    "yes": True,
    "off": False,
    "on": True,
}


class ConfigurationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class BackupConfig:
    owner: str
    orgs: tuple[str, ...]
    token: str = field(repr=False)
    data_dir: Path
    include_submodules: bool
    token_file: Path | None = None


@dataclass(frozen=True)
class RetentionPolicy:
    daily: int
    weekly: int
    monthly: int


@dataclass(frozen=True)
class OffsiteConfig:
    repository: str
    retention: RetentionPolicy


@dataclass(frozen=True)
class HealthConfig:
    data_dir: Path
    maximum_age: timedelta

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> HealthConfig:
        errors: list[str] = []
        maximum_age_hours = _number(
            environment, "BACKUP_MAX_AGE_HOURS", "26", errors
        )
        if maximum_age_hours is not None and maximum_age_hours <= 0:
            errors.append("BACKUP_MAX_AGE_HOURS must be greater than zero")
        if errors:
            raise ConfigurationError(errors)
        assert maximum_age_hours is not None
        return cls(
            data_dir=Path(environment.get("BACKUP_DATA_DIR", "/data")),
            maximum_age=timedelta(hours=maximum_age_hours),
        )


@dataclass(frozen=True)
class OperationalConfig:
    backup: BackupConfig
    offsite: OffsiteConfig | None
    health: HealthConfig
    minimum_free_gb: float
    run_on_startup: bool

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> OperationalConfig:
        errors: list[str] = []
        owner = environment.get("GITHUB_OWNER", "").strip()
        if owner == "change-me":
            owner = ""

        token_file_value = environment.get("GITHUB_TOKEN_FILE", "").strip()
        token_file = Path(token_file_value) if token_file_value else None
        token = ""
        if token_file is not None:
            try:
                token = token_file.read_text(encoding="utf-8").strip("\r\n")
            except OSError as exc:
                errors.append(
                    f"GitHub token file is not readable: {token_file} ({exc})"
                )
        else:
            token = environment.get("GITHUB_TOKEN", "").strip("\r\n")
        if not token and not any(
            error.startswith("GitHub token file is not readable:") for error in errors
        ):
            errors.append("GitHub token value is empty")

        orgs: list[str] = []
        seen = {owner.casefold()}
        for configured_org in environment.get("GITHUB_ORGS", "").split(","):
            org = configured_org.strip()
            normalized = org.casefold()
            if org and normalized not in seen:
                seen.add(normalized)
                orgs.append(org)

        offsite = _offsite_config(environment, errors)
        run_on_startup = _boolean(environment, "RUN_ON_STARTUP", "true", errors)
        include_submodules = _boolean(
            environment, "GHORG_INCLUDE_SUBMODULES", "true", errors
        )

        maximum_age_hours = _number(
            environment, "BACKUP_MAX_AGE_HOURS", "26", errors
        )
        if maximum_age_hours is not None and maximum_age_hours <= 0:
            errors.append("BACKUP_MAX_AGE_HOURS must be greater than zero")

        minimum_free_gb = _number(
            environment, "BACKUP_MIN_FREE_GB", "1", errors
        )
        if minimum_free_gb is not None and minimum_free_gb < 0:
            errors.append("BACKUP_MIN_FREE_GB must not be negative")

        data_dir = Path(environment.get("BACKUP_DATA_DIR", "/data"))
        _validate_storage(data_dir, minimum_free_gb, errors)

        if errors:
            raise ConfigurationError(errors)
        assert include_submodules is not None
        assert run_on_startup is not None
        assert maximum_age_hours is not None
        assert minimum_free_gb is not None
        return cls(
            backup=BackupConfig(
                owner=owner,
                orgs=tuple(orgs),
                token=token,
                data_dir=data_dir,
                include_submodules=include_submodules,
                token_file=token_file,
            ),
            offsite=offsite,
            health=HealthConfig(
                data_dir=data_dir,
                maximum_age=timedelta(hours=maximum_age_hours),
            ),
            minimum_free_gb=minimum_free_gb,
            run_on_startup=run_on_startup,
        )


def _boolean(
    environment: Mapping[str, str],
    name: str,
    default: str,
    errors: list[str],
) -> bool | None:
    value = BOOLEAN_VALUES.get(environment.get(name, default).casefold())
    if value is None:
        errors.append(f"{name} must be a boolean value")
    return value


def _number(
    environment: Mapping[str, str],
    name: str,
    default: str,
    errors: list[str],
) -> float | None:
    try:
        return float(environment.get(name, default))
    except ValueError:
        errors.append(f"{name} must be a number")
        return None


def _positive_integer(
    environment: Mapping[str, str],
    name: str,
    default: str,
    errors: list[str],
) -> int | None:
    try:
        value = int(environment.get(name, default))
    except ValueError:
        errors.append(f"{name} must be an integer")
        return None
    if value <= 0:
        errors.append(f"{name} must be greater than zero")
        return None
    return value


def _offsite_config(
    environment: Mapping[str, str], errors: list[str]
) -> OffsiteConfig | None:
    repository = environment.get("RESTIC_REPOSITORY", "").strip()
    if not repository:
        return None

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

    daily = _positive_integer(
        environment, "BACKUP_RETENTION_DAILY", "7", errors
    )
    weekly = _positive_integer(
        environment, "BACKUP_RETENTION_WEEKLY", "5", errors
    )
    monthly = _positive_integer(
        environment, "BACKUP_RETENTION_MONTHLY", "12", errors
    )
    if daily is None or weekly is None or monthly is None:
        return None
    return OffsiteConfig(
        repository=repository,
        retention=RetentionPolicy(daily=daily, weekly=weekly, monthly=monthly),
    )


def _validate_storage(
    data_dir: Path,
    minimum_free_gb: float | None,
    errors: list[str],
) -> None:
    if not data_dir.is_dir():
        errors.append(f"Backup data directory does not exist: {data_dir}")
        return
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
