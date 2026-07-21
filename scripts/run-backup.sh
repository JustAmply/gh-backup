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
: "${GITHUB_ORGS:=}"
: "${GITHUB_TOKEN:=}"
: "${GITHUB_TOKEN_FILE:=}"
: "${BACKUP_DATA_DIR:=/data}"

if [[ -n "${GITHUB_TOKEN_FILE}" ]]; then
  [[ -r "${GITHUB_TOKEN_FILE}" ]] || die "GitHub token file is not readable: ${GITHUB_TOKEN_FILE}"
  GITHUB_TOKEN="$(tr -d '\r\n' < "${GITHUB_TOKEN_FILE}")"
fi
GITHUB_TOKEN="$(printf '%s' "${GITHUB_TOKEN}" | tr -d '\r\n')"
[[ -n "${GITHUB_TOKEN}" ]] || die "GitHub token value is empty"

mkdir -p "${BACKUP_DATA_DIR}/logs" "${BACKUP_DATA_DIR}/metadata" "${BACKUP_DATA_DIR}/mirrors" "${BACKUP_DATA_DIR}/state"

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
run_log="${BACKUP_DATA_DIR}/logs/${run_id}.log"
touch "${run_log}"
exec > >(tee -a "${run_log}") 2>&1

exec 9>"${BACKUP_DATA_DIR}/state/backup.lock"
if ! flock -n 9; then
  die "Another backup run is already in progress"
fi

if [[ -z "${GITHUB_TOKEN_FILE}" ]]; then
  GITHUB_TOKEN_FILE="$(mktemp)"
  chmod 600 "${GITHUB_TOKEN_FILE}"
  printf '%s' "${GITHUB_TOKEN}" > "${GITHUB_TOKEN_FILE}"
  export GH_BACKUP_EPHEMERAL_TOKEN_FILE=true
fi
export GITHUB_OWNER GITHUB_ORGS GITHUB_TOKEN_FILE BACKUP_DATA_DIR GHORG_INCLUDE_SUBMODULES
export GH_BACKUP_RUN_ID="${run_id}"
export GH_BACKUP_LOG_FILE="${run_log}"
unset GITHUB_TOKEN

runner_python="${GH_BACKUP_RUNNER_PYTHON:-/opt/venv/bin/python3}"
exec "${runner_python}" -m gh_backup.runner
