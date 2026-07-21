# Repository Instructions

## Validation

- Run `bash scripts/check.sh` after changing Python or shell code. This is the
  shared local and CI validation interface; do not replace it with only the
  Python unit tests.
- On Windows, run the check with Git Bash. Do not interpret a failure from the
  Windows WSL `bash.exe` stub as a repository test failure.
- After changing Docker or Compose files, also run
  `docker compose config --quiet`. Run the container validation when a Docker
  daemon is available, and report explicitly when it is not.

## Recovery invariants

- Work that can fail after a Backup Run receives its run ID must execute inside
  the Python orchestration so the Run Manifest reaches exactly one terminal
  state: `verified`, `failed`, or `degraded`.
- Keep shell responsible for container and process glue. Put structured state
  transitions, target normalization, verification, and publication in
  `gh_backup` and cover them through the backup-run interface.
- A failed run may update `last-run` but must never replace `last-success`.
  Error evidence and persisted logs must not contain tokens or other secrets.
- Treat changes to Recovery Point or publication semantics as contract changes:
  read `CONTEXT.md` and the relevant ADR first, then add a regression test that
  demonstrates the intended state transition.
