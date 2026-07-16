"""Versioned GitHub resource coverage policy."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gh_backup.process import CommandRunner, command_runner_from_environment


@dataclass(frozen=True)
class CoveragePolicy:
    schema_version: int
    tool_name: str
    pinned_version: str
    selection: tuple[str, ...]
    common: tuple[str, ...]
    user_only: tuple[str, ...]
    unsupported: dict[str, str]

    @classmethod
    def load_default(cls) -> CoveragePolicy:
        path = Path(__file__).with_name("coverage_policy.json")
        with path.open(encoding="utf-8") as handle:
            document: dict[str, Any] = json.load(handle)
        return cls(
            schema_version=int(document["schema_version"]),
            tool_name=str(document["tool"]["name"]),
            pinned_version=str(document["tool"]["pinned_version"]),
            selection=tuple(document["metadata"]["selection"]),
            common=tuple(document["metadata"]["common"]),
            user_only=tuple(document["metadata"]["user_only"]),
            unsupported=dict(document["unsupported"]),
        )

    @property
    def required_tool_options(self) -> set[str]:
        return {*self.selection, *self.common, *self.user_only, "--organization"}

    def metadata_arguments(self, target_kind: str) -> list[str]:
        arguments = [*self.selection, *self.common]
        if target_kind == "user":
            arguments.extend(self.user_only)
        return arguments


def missing_required_options(
    policy: CoveragePolicy, tool_help: str
) -> list[str]:
    return sorted(
        option for option in policy.required_tool_options if option not in tool_help
    )


def verify_installed_tool(
    policy: CoveragePolicy, *, run_command: CommandRunner
) -> list[str]:
    errors: list[str] = []
    version = run_command(
        [policy.tool_name, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if policy.pinned_version not in version:
        errors.append(
            f"{policy.tool_name} version is {version!r}; "
            f"expected {policy.pinned_version}"
        )
    help_text = run_command(
        [policy.tool_name, "--help"], check=True, capture_output=True, text=True
    ).stdout
    missing = missing_required_options(policy, help_text)
    if missing:
        errors.append(f"{policy.tool_name} is missing options: {', '.join(missing)}")
    return errors


def main() -> int:
    policy = CoveragePolicy.load_default()
    errors = verify_installed_tool(
        policy, run_command=command_runner_from_environment()
    )
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
