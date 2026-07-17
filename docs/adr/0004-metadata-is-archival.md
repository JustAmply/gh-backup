# ADR 0004: Treat exported GitHub metadata as archival evidence

- Status: Accepted
- Date: 2026-07-16

## Context

GitHub does not expose a restoration interface that can faithfully recreate all
issue and pull-request identifiers, authors, timestamps, relationships, and
other platform state.

## Decision

Describe exported metadata as archival evidence. Do not promise a faithful
GitHub restore unless a resource has a documented and tested restoration path.
Repository, wiki, gist, and LFS recovery remain distinct from metadata access.

## Consequences

- Coverage documentation states restoration quality per resource.
- Restore drills verify Git data and metadata readability, not fictional
  recreation of GitHub platform state.
- Future import tooling is optional and cannot silently broaden the recovery
  contract.
