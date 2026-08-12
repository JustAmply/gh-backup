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

The local data volume keeps in-place mirrors and metadata. When encrypted
offsite storage is enabled, the Restic adapter creates an immutable snapshot of
those recovery data directories only. Mutable run state and logs are not
included. Restic returns a stable snapshot identity, verifies the repository,
and applies retention before the run manifest records that identity and the
backup run is qualified for publication.

The terminal run manifest and the offsite snapshot are linked evidence, not two
copies of the same state. The snapshot carries a `run:<run-id>` tag; the run
manifest records the Restic snapshot identity. `last-success` remains the local
atomic publication pointer.

## Consequences

- Scheduler liveness is not treated as backup health.
- Failed and stale attempts become observable.
- The active local volume still does not provide transactional rollback for
  in-place mirror updates.
- An enabled Restic adapter provides a point-in-time offsite copy of recovery
  data, but not of mutable run state or logs.
- Publication fails if Restic does not return a machine-readable snapshot
  identity.
