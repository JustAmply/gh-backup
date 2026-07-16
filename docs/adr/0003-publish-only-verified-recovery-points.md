# ADR 0003: Publish only verified recovery points

- Status: Accepted
- Date: 2026-07-16

## Context

External tools can exit successfully while producing incomplete or unusable
data. A failed later target can also leave partially updated data while the old
success marker remains in place.

## Decision

Every attempt produces a run manifest. `last-run` points to the latest terminal
attempt. `last-success` changes only after all required stages and verification
have succeeded. Pointer files are replaced atomically.

The implementation initially guarantees atomic publication of evidence. Full
point-in-time data snapshots require a storage adapter that can provide them
without copying every mirror on every run.

## Consequences

- Scheduler liveness is not treated as backup health.
- Failed and stale attempts become observable.
- The project does not claim transactional rollback for in-place mirror updates
  until a snapshot-capable storage adapter exists.
