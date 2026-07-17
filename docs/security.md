# Security Model

## Token handling

`GITHUB_TOKEN_FILE` is the preferred input. It should point to a read-only file
mounted into the container. `GITHUB_TOKEN` remains a compatibility input; after
the authenticated login has been resolved, the entrypoint writes it to a mode
`0600` temporary file, exports only that path, and removes the token value from
the runner environment.

`ghorg` receives a token file path. `github-backup` receives a `file://` token
reference. The token value therefore does not appear in their process
arguments. Git uses a run-local configuration file and a credential helper that
reads the token file when invoked. The global Git configuration is not changed.

Temporary token and Git configuration files are deleted when the runner exits.
Run manifests redact the configured token if an external command includes it in
an error message.

## Container privileges

The runtime uses the unprivileged `gh-backup` account with UID and GID `10001`.
The default named Docker volume is initialized with matching ownership. When a
host bind mount is used instead, the operator must make it writable by UID/GID
`10001` without making it world-writable.

The container needs outbound HTTPS access to GitHub and write access only to the
configured backup volume, its home directory, and temporary storage. It does
not require the Docker socket or privileged mode.

## Persisted evidence

Logs, manifests, metadata, and repository content may themselves contain
sensitive private data. Offsite storage must be encrypted, access-controlled,
and covered by the same retention and deletion policy as the source account.
