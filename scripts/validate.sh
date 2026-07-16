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
: "${GITHUB_TOKEN:=}"
: "${GITHUB_TOKEN_FILE:=}"
: "${BACKUP_CRON:=17 2 * * *}"

for cmd in ghorg github-backup git git-lfs restic supercronic flock bash python3; do
  command -v "${cmd}" >/dev/null 2>&1 || die "Required command missing: ${cmd}"
done

if [[ -n "${GITHUB_TOKEN_FILE}" ]]; then
  [[ -r "${GITHUB_TOKEN_FILE}" ]] || die "GitHub token file is not readable: ${GITHUB_TOKEN_FILE}"
  token_value="$(tr -d '\r\n' < "${GITHUB_TOKEN_FILE}")"
else
  token_value="$(printf '%s' "${GITHUB_TOKEN}" | tr -d '\r\n')"
fi
[[ -n "${token_value}" ]] || die "GitHub token value is empty"

tmp_cron="$(mktemp)"
trap 'rm -f "${tmp_cron}"' EXIT

cat > "${tmp_cron}" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${BACKUP_CRON} /usr/local/bin/run-backup.sh
EOF

supercronic -test "${tmp_cron}" >/dev/null

runner_python="${GH_BACKUP_RUNNER_PYTHON:-/opt/venv/bin/python3}"
"${runner_python}" -m gh_backup.preflight
"${runner_python}" -m gh_backup.coverage
log "Validation succeeded"
