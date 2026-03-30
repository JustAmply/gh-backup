#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

: "${GITHUB_OWNER:=}"
: "${GITHUB_TOKEN_FILE:=/run/secrets/github_token}"
: "${BACKUP_CRON:=17 2 * * *}"

for cmd in ghorg github-backup git git-lfs supercronic flock bash curl; do
  command -v "${cmd}" >/dev/null 2>&1 || die "Required command missing: ${cmd}"
done

[[ -n "${GITHUB_OWNER}" ]] || die "GITHUB_OWNER must be set"
[[ "${GITHUB_OWNER}" != "change-me" ]] || die "GITHUB_OWNER must be configured with a real account name"
[[ -r "${GITHUB_TOKEN_FILE}" ]] || die "GitHub token file is not readable: ${GITHUB_TOKEN_FILE}"

token_value="$(tr -d '\r\n' < "${GITHUB_TOKEN_FILE}")"
[[ -n "${token_value}" ]] || die "GitHub token file is empty: ${GITHUB_TOKEN_FILE}"

tmp_cron="$(mktemp)"
trap 'rm -f "${tmp_cron}"' EXIT

cat > "${tmp_cron}" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${BACKUP_CRON} /usr/local/bin/run-backup.sh
EOF

supercronic -test "${tmp_cron}" >/dev/null
log "Validation succeeded"

