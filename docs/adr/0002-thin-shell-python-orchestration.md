# ADR 0002: Keep shell thin and move structured orchestration to Python

- Status: Accepted
- Date: 2026-07-16

## Context

The container requires shell for its entrypoint and scheduler. Backup planning,
structured manifests, state transitions, JSON serialization, and verification
are substantially easier to make reliable and testable in Python. Python is
already present because `python-github-backup` requires it.

## Decision

Shell remains responsible for container process glue. A standard-library-first
Python module owns configuration normalization, backup plans, stage execution,
run manifests, verification, health evaluation, and publication.

External commands remain adapters. Their process exit status and structured
results are translated into domain stage results before reaching callers.

## Consequences

- The public container commands remain stable during migration.
- JSON is produced by a serializer rather than shell string concatenation.
- Tests target the command and manifest seams rather than private functions or
  exact orchestration internals.
- New Python dependencies require explicit justification.
