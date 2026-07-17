# Recovery Contract

This document defines what `gh-backup` promises. It distinguishes current
guarantees from planned capabilities so operational documentation cannot imply
protection that the implementation does not provide.

## Recovery Objectives

- Default backup schedule: once per day at `02:17` in the configured timezone.
- Freshness objective: a verified recovery point no older than 26 hours.
- Single-repository recovery objective: recover Git references and available
  LFS objects to a prepared destination within four hours.
- Full-account recovery objective: make all verified repository mirrors and
  archived metadata accessible within 24 hours.

These are project defaults, not guarantees about GitHub availability, network
throughput, repository size, or the operator's destination environment.

## Required Recovery Evidence

A backup run becomes a recovery point only after all required targets have:

1. completed repository and wiki mirroring;
2. completed LFS collection for discovered bare repositories;
3. completed the configured metadata export;
4. passed repository and manifest verification; and
5. written and atomically published a verified run manifest.

The latest attempt and the latest recovery point are tracked separately.

## Recovery Scope

### Recoverable

- Repository Git references and history through mirror push.
- Wiki Git references and history through mirror push.
- Available Git LFS objects when the destination supports Git LFS.
- Gist Git data when it is present in the backup.

### Archival, not faithfully recoverable

- Issues, pull requests, reviews, discussions, comments, labels, milestones,
  releases, followers, stars, and other exported GitHub metadata.
- Attachments and release assets are recoverable as files, but their original
  GitHub relationships and identifiers are not guaranteed to be recreatable.

### Excluded until a coverage decision is implemented

- GitHub Actions artifacts and logs.
- Packages and container images.
- Projects, webhooks, deployment keys, secrets, and environment configuration.

## Failure Semantics

- A required-stage failure makes the run `failed`.
- A documented optional-stage failure may make the run `degraded`, but a
  degraded run is not published as `last-success` unless the coverage policy
  explicitly permits it.
- Partial data may be retained for diagnosis but must never be presented as a
  recovery point.
- A previous recovery point remains authoritative after a later failure.

## Storage Scope

Working data is stored in the configured Docker volume. That volume alone is one
local copy, not an offsite guarantee. When `RESTIC_REPOSITORY` and a password
file are configured, encrypted Restic snapshot creation, repository checking,
and retention become required stages for publishing a verified recovery point.

## Operator Responsibilities

- Provide a token with access to every resource required by the coverage policy.
- Monitor freshness and failed runs.
- Provide enough storage for mirrors, metadata, logs, and retained recovery
  points.
- Keep encryption and destination credentials outside the backup data.
- Perform scheduled restore drills and investigate every failed drill.
