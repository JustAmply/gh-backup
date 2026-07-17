# ADR 0001: Use ghorg and python-github-backup as complementary adapters

- Status: Accepted
- Date: 2026-07-16

## Context

Repository mirrors and GitHub metadata have different collection semantics.
`ghorg` is optimized for discovering and updating many repository and wiki
mirrors. `python-github-backup` exports GitHub metadata and attachments.

## Decision

Keep both tools. Treat them as external adapters behind the backup-run seam:

- `ghorg` owns repository and wiki discovery and mirroring;
- Git owns LFS collection and repository verification;
- `python-github-backup` owns metadata and attachment export.

The orchestration module, not either adapter, owns target ordering, stage
results, failure semantics, and publication.

## Consequences

- Coverage overlaps and gaps must be recorded explicitly.
- Tool-specific flags stay local to their adapter.
- Updates require adapter contract tests against the pinned version.
- Removing either tool remains possible without changing recovery semantics.
