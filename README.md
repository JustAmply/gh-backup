# GitHub Backup Container

A single-container GitHub backup stack built with:

- `ghorg` for repository and wiki Git mirrors
- `github-backup` for issues, pull requests, releases, attachments, gists, and other GitHub metadata
- `supercronic` for in-container scheduling

All backup data is written to a Docker volume mounted at `/data`.

## Scope

This setup backs up:

- full Git history for all mirrored repositories
- wikis as Git mirrors
- Git LFS objects for mirrored repositories
- issues, issue comments, and issue events
- pull requests, review comments, pull commits, and pull details
- labels and milestones
- releases and release assets
- issue and pull request attachments
- personal gists, starred gists, starred repos, watched repos, followers, and following for `GITHUB_OWNER`

Not included in v1:

- discussions
- projects
- packages
- GitHub Actions artifacts
- webhooks

## Requirements

- Docker 29+ with Compose
- a GitHub Personal Access Token provided either by environment variable or an optional mounted token file

The default and recommended setup is a Classic PAT with these scopes:

- `repo`
- `read:org`
- `gist`

A Fine-Grained PAT may work for some cases, but it is not the default because `github-backup` documents limitations around private attachments.

## Quick Start

1. Copy `.env.example` to `.env`.
2. Set `GITHUB_OWNER` and `GITHUB_TOKEN` in `.env`.
3. Start the stack:

```bash
docker compose up -d --build
```

Run a one-off backup immediately:

```bash
docker compose run --rm gh-backup backup-now
```

Only validate configuration and installed tooling:

```bash
docker compose run --rm gh-backup validate
```

## Configuration

The Compose file reads these environment variables:

- `GITHUB_OWNER`: personal account name, required
- `GITHUB_ORGS`: optional comma-separated list of additional organizations
- `GITHUB_TOKEN`: GitHub token, default and preferred authentication method
- `GITHUB_TOKEN_FILE`: optional path to a mounted token file; used only when `GITHUB_TOKEN` is not set
- `BACKUP_CRON`: default `17 2 * * *`
- `TZ`: default `Europe/Berlin`
- `RUN_ON_STARTUP`: `true` or `false`
- `GHORG_INCLUDE_SUBMODULES`: `true` or `false`

If `RUN_ON_STARTUP=true`, the container runs one backup immediately after startup and then switches to scheduler mode.

## Authentication Modes

### Default: environment variable

Store the token in `.env`:

```dotenv
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

### Optional: token file

If you prefer a mounted file, leave `GITHUB_TOKEN` empty, set `GITHUB_TOKEN_FILE`, and mount the file yourself through a Compose override or `docker run`.

Example:

```bash
docker run --rm \
  -e GITHUB_OWNER=your-user \
  -e GITHUB_TOKEN_FILE=/run/secrets/github_token \
  -v "$PWD/secrets/github_token.txt:/run/secrets/github_token:ro" \
  gh-backup:local validate
```

## Data Layout

The container writes this structure under `/data`:

- `/data/mirrors/<target>_backup/` for repository and wiki mirrors
- `/data/metadata/<target>/` for `github-backup` exports
- `/data/state/last-success.json` for the last successful full run
- `/data/logs/` for run logs

## GitHub Actions

The workflow in `.github/workflows/docker-image.yml`:

- builds the image on pull requests
- runs `validate` inside the built container
- publishes multi-arch images for `linux/amd64` and `linux/arm64` to GHCR on `main` and `v*` tags

On `main`, it publishes `edge` and `sha-<shortsha>`. On semver tags `vX.Y.Z`, it publishes `X.Y.Z`, `X.Y`, `X`, and `latest`.

## Restore Notes

This project is a backup and archive stack, not a restore product. Git mirrors can later be restored with `git push --mirror` to a new remote. GitHub metadata is exported as archive data.
