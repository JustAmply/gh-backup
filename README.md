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
GITHUB_OWNER=your-github-username
GITHUB_TOKEN=your-token-here
```

Optional:

- `GITHUB_ORGS` for extra orgs, comma-separated
- `BACKUP_CRON` to change the schedule
- `TZ` to change the timezone

`GITHUB_OWNER` backs up repositories owned by the authenticated user behind `GITHUB_TOKEN`, including owned private repositories. Use `GITHUB_ORGS` to opt in additional organizations.

### 3. Start the Backup Container

```bash
docker compose up -d
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

- `GITHUB_OWNER`: your personal GitHub username, required
- `GITHUB_ORGS`: optional comma-separated organizations to back up in addition to the owner account
- `GITHUB_TOKEN`: your GitHub PAT, required
- `BACKUP_CRON`: cron schedule, default `17 2 * * *`
- `TZ`: timezone, default `Europe/Berlin`
- `RUN_ON_STARTUP`: `true` or `false`, default `true`
- `GHORG_INCLUDE_SUBMODULES`: `true` or `false`, default `true`

Example:

```dotenv
GITHUB_OWNER=octocat
GITHUB_ORGS=my-company,my-side-project-org
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
BACKUP_CRON=17 2 * * *
TZ=Europe/Berlin
RUN_ON_STARTUP=true
GHORG_INCLUDE_SUBMODULES=true
```

## Where the Backup Is Stored

All data is written to the Docker volume mounted at `/data`.

Inside the container, the layout looks like this:

- `/data/mirrors/<target>_backup/` for repo and wiki mirrors
- `/data/metadata/<target>/` for exported GitHub metadata
- `/data/state/last-success.json` for the last successful run
- `/data/logs/` for run logs

With the default Compose setup, Docker manages that storage in the `gh_backup_data` volume.

## What This Is Good For

Use this when you want:

- a local archive of your GitHub account
- a scheduled Docker-based backup instead of ad hoc exports
- repository mirrors plus metadata exports in one place

This is a backup and archive setup, not a one-click restore product. Git mirrors can later be pushed to a new remote with `git push --mirror`. Exported metadata is stored as archive data for recovery and reference.
