# GitHub Backup Container

Ein einzelner Container fuer regelmaessige GitHub-Backups mit:

- `ghorg` fuer Git-Mirrors von Repositories und Wikis
- `github-backup` fuer Issues, Pull Requests, Releases, Attachments, Gists und weitere GitHub-Metadaten
- `supercronic` fuer den internen Scheduler

Der Container schreibt alle Daten in ein Docker-Volume unter `/data`.

## Scope

Dieses Setup sichert standardmaessig:

- vollstaendige Git-Historie aller gespiegelten Repositories
- Wikis als Git-Mirror
- Git LFS Inhalte fuer gespiegelte Repositories
- Issues, Issue-Comments und Issue-Events
- Pull Requests, Review-Kommentare, Pull-Commits und Pull-Details
- Labels und Milestones
- Releases inklusive Assets
- Attachments aus Issues und Pull Requests
- persoenliche Gists, Starred Gists, Starred, Watched, Followers und Following fuer den `GITHUB_OWNER`

Nicht enthalten in v1:

- Discussions
- Projects
- Packages
- Actions-Artefakte
- Webhooks

## Voraussetzungen

- Docker 29+ mit Compose
- Ein GitHub Personal Access Token in `secrets/github_token.txt`

Empfohlener Default ist ein Classic PAT mit diesen Scopes:

- `repo`
- `read:org`
- `gist`

Ein Fine-Grained PAT kann fuer manche Faelle funktionieren, ist hier aber nicht der Default, weil `github-backup` bei privaten Attachments Einschränkungen dokumentiert.

## Schnellstart

1. `.env.example` nach `.env` kopieren und Werte anpassen.
2. `secrets/github_token.txt` mit dem PAT anlegen.
3. Container starten:

```bash
docker compose up -d --build
```

Ein Einmallauf fuer einen direkten Test:

```bash
docker compose run --rm gh-backup backup-now
```

Nur Konfiguration und Binaerdateien pruefen:

```bash
docker compose run --rm gh-backup validate
```

## Konfiguration

Die Compose-Datei liest diese Umgebungsvariablen:

- `GITHUB_OWNER`: persoenlicher Accountname, Pflichtwert
- `GITHUB_ORGS`: optionale kommaseparierte Liste zusaetzlicher Orgs
- `GITHUB_TOKEN_FILE`: Default `/run/secrets/github_token`
- `BACKUP_CRON`: Default `17 2 * * *`
- `TZ`: Default `Europe/Berlin`
- `RUN_ON_STARTUP`: `true` oder `false`
- `GHORG_INCLUDE_SUBMODULES`: `true` oder `false`

Wenn `RUN_ON_STARTUP=true` gesetzt ist, fuehrt der Container direkt nach dem Start einen Backup-Lauf aus und wechselt danach in den Scheduler-Modus.

## Datenlayout

Unter `/data` wird folgende Struktur aufgebaut:

- `/data/mirrors/<target>_backup/` fuer Repo- und Wiki-Mirrors
- `/data/metadata/<target>/` fuer `github-backup` Exporte
- `/data/state/last-success.json` fuer den letzten erfolgreichen Gesamtlauf
- `/data/logs/` fuer Laufprotokolle

## GitHub Actions

Der Workflow in `.github/workflows/docker-image.yml`:

- baut das Image auf Pull Requests
- fuehrt `validate` im gebauten Container aus
- published Multi-Arch Images fuer `linux/amd64` und `linux/arm64` nach GHCR auf `main` und `v*` Tags

Auf `main` werden `edge` und `sha-<shortsha>` veroeffentlicht. Semver-Tags `vX.Y.Z` erzeugen `X.Y.Z`, `X.Y`, `X` und `latest`.

## Restore-Hinweis

Dieses Projekt ist ein Backup/Archiv-Stack, kein Restore-Produkt. Git-Mirror koennen spaeter mit `git push --mirror` in ein neues Remote zurueckgespielt werden. GitHub-Metadaten werden als Archivdaten exportiert.

