# Domain Context

`gh-backup` creates verifiable recovery points for one authenticated GitHub
account and explicitly configured organizations.

## Ubiquitous Language

### Backup Target

A GitHub user or organization whose repositories and metadata are included in a
backup run. The authenticated user is always a target. Configured organizations
are additional targets.

### Backup Run

One scheduled or manually triggered attempt to collect all configured backup
targets. A backup run has its own identity, timestamps, per-target results, log,
and terminal state.

### Backup Stage

One observable part of a backup run: repository mirroring, LFS collection,
metadata export, verification, or publication.

### Run Manifest

The immutable machine-readable evidence for a backup run. It records the input
configuration without secrets, tool versions, target and stage results,
verification evidence, and the terminal state.

### Recovery Point

A backup run that completed every required stage and passed verification. A
successful tool exit alone is not a recovery point.

### Coverage Policy

The versioned declaration of which GitHub resources are required, optional, or
excluded, including known restoration limitations.

### Verification

Checks that establish whether a backup run is complete and internally
consistent enough to become a recovery point.

### Restore Drill

A non-destructive restoration rehearsal against disposable local storage. It
proves that repository mirrors can recreate their Git references without
changing GitHub.

### Freshness

The age of the latest recovery point. Freshness is independent of whether the
scheduler process is alive.

### Publication

The atomic state change that makes a verified backup run the latest recovery
point. Failed or partially completed runs are never published.

## Invariants

- Secrets never appear in run manifests or persisted command logs.
- Every backup run reaches exactly one terminal state: `verified`, `failed`, or
  `degraded`.
- `last-run` describes the latest attempt; `last-success` describes the latest
  verified recovery point.
- A failed run never replaces the latest recovery point.
- GitHub metadata is archival evidence unless the coverage policy explicitly
  documents a faithful restoration path.
- Restore drills are local and non-destructive by default.
