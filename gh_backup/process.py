"""Process execution policy shared by external command adapters."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import Mapping


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def command_runner_from_environment(
    environment: Mapping[str, str] = os.environ,
) -> CommandRunner:
    command_shell = environment.get("GH_BACKUP_COMMAND_SHELL")
    if not command_shell:
        return subprocess.run

    def run_through_shell(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [command_shell, "-c", 'exec "$@"', "gh-backup", *args],
            **kwargs,
        )

    return run_through_shell
