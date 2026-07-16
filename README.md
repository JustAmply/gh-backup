# GitHub Backup

Run a scheduled GitHub backup in Docker.

This container creates a local archive of the GitHub account and organizations you choose. It mirrors repositories and wikis, pulls Git LFS objects, and exports GitHub metadata such as issues, pull requests, releases, comments, and attachments.

## What You Get

- repository mirrors with full Git history
- wiki mirrors
- Git LFS objects
- issues, pull requests, comments, labels, milestones, and releases
- release assets and issue / pull request attachments
- personal gists, starred items, watched repos, followers, and following for your main account
- automatic scheduled runs inside the container

Not included:

- Discussions
- Projects
- Packages
- GitHub Actions artifacts
- Webhooks

## Quick Start Guide

### 1. Prerequisites

- Docker with Compose
- a GitHub Personal Access Token in `GITHUB_TOKEN`

### 2. Create Your `.env`

Copy the example file to `.env`:

```bash
cp .env.example .env
```

On PowerShell:

```powershell
Copy-Item .env.example .env
```

Set at least these values:

```dotenv
GITHUB_TOKEN=your-token-here
```

Optional:

- `GITHUB_OWNER` if you want an explicit sanity check that the token belongs to that user
- `GITHUB_ORGS` for extra orgs, comma-separated
- `BACKUP_CRON` to change the schedule
- `TZ` to change the timezone

The backup always resolves the personal account from `GITHUB_TOKEN`, including the correct GitHub letter casing, before it starts. If you also set `GITHUB_OWNER`, it is treated as a sanity check and must match that authenticated account.

### 3. Start the Backup Container

```bash
docker compose up -d --build
```

What happens next:

- the container validates the config
- it runs one backup immediately if `RUN_ON_STARTUP=true`
- it keeps running and executes future backups on the cron schedule

### 4. Run a Backup Right Now

```bash
docker compose run --rm gh-backup backup-now
```

### 5. Validate Without Running a Backup

```bash
docker compose run --rm gh-backup validate
```

## How To Create the GitHub PAT

This project is designed around a **Personal Access Token (Classic)**.

GitHub docs:

- [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Creating a personal access token (classic)](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic)

### Recommended Token Type

Choose **Tokens (classic)**, not fine-grained, for the default setup here.

Reason:

- this backup stack combines `ghorg` and `github-backup`
- classic tokens are the most predictable choice for full-account backups
- fine-grained tokens can be more restrictive and may not cover every backup case cleanly

### Steps

1. Open GitHub.
2. Go to `Settings`.
3. Go to `Developer settings`.
4. Open `Personal access tokens`.
5. Select `Tokens (classic)`.
6. Click `Generate new token`, then `Generate new token (classic)`.
7. Give it a note like `gh-backup`.
8. Choose an expiration that fits your risk tolerance.
9. Select the scopes below.
10. Click `Generate token`.
11. Copy the token immediately and put it into `.env` as `GITHUB_TOKEN`.

### What To Select

Select these classic PAT scopes:

- `repo`
- `read:org`
- `gist`

Why these scopes:

- `repo`: backs up repositories, issues, pull requests, releases, and private repo data
- `read:org`: lets the backup read organization membership and org-owned resources you can access
- `gist`: backs up your gists

If your organization uses SSO, GitHub may also require you to authorize the token for that organization after creation.

## Configuration

The container reads these environment variables from `.env`:

- `GITHUB_OWNER`: optional sanity-check username for the personal account behind `GITHUB_TOKEN`
- `GITHUB_ORGS`: optional comma-separated organizations to back up in addition to the owner account
- `GITHUB_TOKEN`: your GitHub PAT, required
- `BACKUP_CRON`: cron schedule, default `17 2 * * *`
- `BACKUP_DATA_DIR`: backup root inside the container, default `/data`
- `TZ`: timezone, default `Europe/Berlin`
- `RUN_ON_STARTUP`: `true` or `false`, default `true`
- `GHORG_INCLUDE_SUBMODULES`: `true` or `false`, default `true`
- `BACKUP_MAX_AGE_HOURS`: maximum healthy recovery-point age, default `26`
- `BACKUP_MIN_FREE_GB`: minimum free backup storage checked by `validate`, default `1`

Example:

```dotenv
GITHUB_OWNER=octocat
GITHUB_ORGS=my-company,my-side-project-org
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
BACKUP_CRON=17 2 * * *
TZ=Europe/Berlin
RUN_ON_STARTUP=true
GHORG_INCLUDE_SUBMODULES=true
BACKUP_MAX_AGE_HOURS=26
BACKUP_MIN_FREE_GB=1
```

Inspect the latest attempt and recovery point without changing backup data:

```bash
docker compose run --rm gh-backup status
docker compose run --rm gh-backup status --json
```

The `health` command returns a non-zero exit code when the latest run failed,
no verified recovery point exists, or the latest recovery point is older than
`BACKUP_MAX_AGE_HOURS`. The image uses the same command for Docker health:

```bash
docker compose run --rm gh-backup health
```

## Where the Backup Is Stored

All data is written to the Docker volume mounted at `BACKUP_DATA_DIR` inside the container. The default is `/data`.

Inside the container, the layout looks like this:

- `<BACKUP_DATA_DIR>/mirrors/<target>_backup/` for repo and wiki mirrors
- `<BACKUP_DATA_DIR>/metadata/<target>/` for exported GitHub metadata
- `<BACKUP_DATA_DIR>/state/runs/<run-id>.json` for immutable run evidence
- `<BACKUP_DATA_DIR>/state/last-run.json` for the latest completed attempt
- `<BACKUP_DATA_DIR>/state/last-success.json` for the latest verified recovery point
- `<BACKUP_DATA_DIR>/logs/` for run logs

Every required target records repository mirroring, LFS collection, metadata
export, and Git integrity verification separately. A failed run updates
`last-run.json` but never replaces the previous `last-success.json`.

Verification parses every exported JSON file, runs `git fsck --full` for every
discovered mirror, and performs a non-destructive local `git push --mirror`
restore drill for one mirror per target. The drill compares every restored ref
and object ID before its temporary destination is removed.

With the default Compose setup, Docker manages that storage in the `gh_backup_data` volume.

## What This Is Good For

Use this when you want:

- a local archive of your GitHub account
- a scheduled Docker-based backup instead of ad hoc exports
- repository mirrors plus metadata exports in one place

This is a backup and archive setup, not a one-click restore product. Git mirrors can later be pushed to a new remote with `git push --mirror`. Exported metadata is stored as archive data for recovery and reference.

## Recovery Contract and Architecture

The precise recovery promises, limitations, and objectives are documented in
[`docs/recovery-contract.md`](docs/recovery-contract.md). Domain terminology is
defined in [`CONTEXT.md`](CONTEXT.md), and architectural decisions are recorded
under [`docs/adr/`](docs/adr/).
