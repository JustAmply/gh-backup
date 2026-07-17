import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gh_backup.restore import verify_mirror_restore


def run_git(*args: str, cwd: Path | None = None) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Backup Test",
            "GIT_AUTHOR_EMAIL": "backup@example.invalid",
            "GIT_COMMITTER_NAME": "Backup Test",
            "GIT_COMMITTER_EMAIL": "backup@example.invalid",
        }
    )
    subprocess.run(
        ["git", *args], cwd=cwd, env=environment, check=True, capture_output=True
    )


class RestoreDrillTests(unittest.TestCase):
    def test_mirror_can_be_pushed_to_a_local_bare_target_with_identical_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.git"
            work = root / "work"
            drill_workspace = root / "drill"
            run_git("init", "--bare", str(source))
            run_git("init", "-b", "main", str(work))
            (work / "README.md").write_text("recovery evidence\n", encoding="utf-8")
            run_git("add", "README.md", cwd=work)
            run_git("commit", "-m", "seed", cwd=work)
            run_git("remote", "add", "origin", str(source), cwd=work)
            run_git("push", "origin", "main", cwd=work)

            evidence = verify_mirror_restore(
                source=source, workspace=drill_workspace
            )

            self.assertEqual(evidence.ref_count, 1)
            self.assertEqual(evidence.source, source)
            self.assertFalse(any(drill_workspace.iterdir()))


if __name__ == "__main__":
    unittest.main()
