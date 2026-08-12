# Operations Runbook

## Local health

Use `status` for an informational report and `health` for monitoring:

```bash
docker compose run --rm gh-backup status --json
docker compose run --rm gh-backup health --json
```

`health` exits non-zero when no verified recovery point exists, the latest run
failed, or freshness exceeds `BACKUP_MAX_AGE_HOURS`.

## Encrypted offsite snapshots

Offsite storage is disabled unless `RESTIC_REPOSITORY` is set. Initialize the
repository once before enabling scheduled snapshots:

```bash
docker run --rm \
  -e RESTIC_REPOSITORY=/repository \
  -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  -v /offsite/repository:/repository \
  -v ./secrets/restic-password:/run/secrets/restic-password:ro \
  --entrypoint restic \
  ghcr.io/justamply/gh-backup:latest init
```

Restic supports local, SFTP, REST, S3-compatible, Azure, B2, and other
repositories. Backend-specific credentials are passed through their standard
Restic environment variables. Never put a repository password directly into a
command argument.

When enabled, a run becomes verified only after:

1. `restic backup` snapshots `mirrors/` and `metadata/`, tagged `gh-backup` and
   `run:<run-id>`;
2. `restic check` validates repository structure; and
3. `restic forget --prune` applies daily, weekly, and monthly retention; and
4. the run manifest records the machine-readable Restic snapshot identity.

Mutable files under `state/` and `logs/` are not part of the Restic snapshot.
The terminal run manifest and the immutable snapshot are linked by run ID and
snapshot ID instead of duplicating changing state into the snapshot.

Defaults retain seven daily, five weekly, and twelve monthly snapshots. The
repository needs read, write, and delete access for pruning. Append-only
repositories require a separate, more conservative maintenance workflow and
should not use this automatic prune policy.

## Offsite recovery drill

Read the exact snapshot identity from the latest recovery point and list its
Restic metadata:

```bash
snapshot_id="$(python3 -c 'import json; print(json.load(open("/data/state/last-success.json"))["run_stages"]["offsite"]["evidence"]["snapshot_id"])')"
restic snapshots "${snapshot_id}"
```

Restore one snapshot to disposable storage:

```bash
restic restore "${snapshot_id}" --target /tmp/gh-backup-restore
```

If the local state volume is unavailable, locate candidate snapshots with
`restic snapshots --tag gh-backup` and confirm the `run:<run-id>` tag before
restoring.

Then run the repository restore drill against mirrors under the restored data
tree. Do not restore directly over the active backup volume.

## Failure handling

- Preserve `state/last-run.json`, its referenced log, and the latest verified
  recovery point.
- Fix credentials, capacity, or repository integrity before retrying.
- Run `validate` after configuration changes.
- Never delete Restic locks manually until confirming that no Restic process is
  active.
- Treat repeated integrity failures as a recovery incident, not a scheduler
  issue.
