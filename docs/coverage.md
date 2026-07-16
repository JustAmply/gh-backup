# Backup Coverage

The machine-readable source of truth is
[`gh_backup/coverage_policy.json`](../gh_backup/coverage_policy.json). The
metadata adapter builds its command arguments from that file, and `validate`
checks that the installed `github-backup` version and command options still
match it.

## Included and verified

| Resource | Collection | Verification | Recovery quality |
| --- | --- | --- | --- |
| Repository and wiki Git refs | `ghorg` mirror | `git fsck` and local mirror restore drill | Restorable |
| Git LFS objects | `git lfs fetch --all` | Stage completion and repository integrity | Restorable when destination supports LFS |
| Issues and issue comments/events | `github-backup` | JSON parsing | Archival |
| Pull requests, commits, details, and review comments | `github-backup` | JSON parsing | Archival |
| Fork metadata | `github-backup --fork` | JSON parsing | Archival |
| Labels and milestones | `github-backup` | JSON parsing | Archival |
| Releases, assets, and attachments | `github-backup` | JSON parsing plus downloaded files | Archival files |
| Public security advisories available to the token | `github-backup` | JSON parsing | Archival |
| Personal gists, stars, watched repositories, followers, and following | `github-backup` | JSON parsing | Archival |

## Known exclusions

- Discussions and pull-request review decisions are not supported by the
  pinned `github-backup` 0.61.5 interface.
- GitHub Actions artifacts and packages require a separate storage adapter.
- Projects have no implemented backup adapter.
- Webhooks are intentionally outside the recovery contract.
- Metadata cannot be recreated with original GitHub identifiers, authors, and
  timestamps and is therefore not described as fully restorable.

## Change rule

A resource is added only when all four changes land together:

1. the machine-readable policy changes;
2. the pinned tool capability check passes;
3. the adapter contract test covers the required command option; and
4. this coverage table states its verification and recovery quality.
