"""Semantic preflight checks for backup configuration and storage."""

from __future__ import annotations

import os
import sys
from typing import Mapping, Sequence

from gh_backup.configuration import ConfigurationError, OperationalConfig


def validate_environment(environment: Mapping[str, str]) -> list[str]:
    try:
        OperationalConfig.from_environment(environment)
    except ConfigurationError as exc:
        return list(exc.errors)
    return []


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
