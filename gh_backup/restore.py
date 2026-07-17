"""Non-destructive local restore drills for Git mirror evidence."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RestoreEvidence:
    source: Path
    ref_count: int


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _refs(repository: Path, run_command: CommandRunner) -> tuple[str, ...]:
    result = run_command(
        [
            "git",
            "-C",
            str(repository),
            "for-each-ref",
            "--format=%(refname) %(objectname)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(sorted(line for line in result.stdout.splitlines() if line))


def verify_mirror_restore(
    *,
    source: Path,
    workspace: Path,
    run_command: CommandRunner = subprocess.run,
) -> RestoreEvidence:
    """Push a mirror locally and prove that every resulting ref is identical."""

    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="restore-drill-", dir=workspace) as temp_dir:
        destination = Path(temp_dir) / "restored.git"
        run_command(
            ["git", "init", "--bare", str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
        source_refs = _refs(source, run_command)
        run_command(
            ["git", "-C", str(source), "push", "--mirror", str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
        restored_refs = _refs(destination, run_command)
        if restored_refs != source_refs:
            raise RuntimeError(
                f"Local restore drill produced different refs for {source}"
            )
        return RestoreEvidence(source=source, ref_count=len(source_refs))
