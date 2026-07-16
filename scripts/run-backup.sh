#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

trim() {
  local value="${1:-}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

resolve_authenticated_github_login() {
  GITHUB_TOKEN="${GITHUB_TOKEN}" python3 - <<'PY'
import json, os, sys, urllib.request
try:
    response = urllib.request.urlopen(urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "User-Agent": "gh-backup",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    ))
    sys.stdout.write(json.load(response)["login"])
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
PY
}

: "${GITHUB_OWNER:=}"
: "${GITHUB_ORGS:=}"
: "${GITHUB_TOKEN:=}"
: "${BACKUP_DATA_DIR:=/data}"

GITHUB_TOKEN="$(printf '%s' "${GITHUB_TOKEN}" | tr -d '\r\n')"
[[ -n "${GITHUB_TOKEN}" ]] || die "GitHub token value is empty"

mkdir -p "${BACKUP_DATA_DIR}/logs" "${BACKUP_DATA_DIR}/metadata" "${BACKUP_DATA_DIR}/mirrors" "${BACKUP_DATA_DIR}/state"

run_id="$(date -u +%Y%m%dT%H%M%SZ)"
run_log="${BACKUP_DATA_DIR}/logs/${run_id}.log"
touch "${run_log}"
exec > >(tee -a "${run_log}") 2>&1

exec 9>"${BACKUP_DATA_DIR}/state/backup.lock"
if ! flock -n 9; then
  die "Another backup run is already in progress"
fi

configured_owner="$(trim "${GITHUB_OWNER}")"
[[ "${configured_owner}" == "change-me" ]] && configured_owner=""

authenticated_login="$(resolve_authenticated_github_login)" || die "Unable to resolve the authenticated GitHub login"
if [[ -n "${configured_owner}" && "${configured_owner,,}" != "${authenticated_login,,}" ]]; then
  die "GITHUB_OWNER (${configured_owner}) must match the GitHub account behind GITHUB_TOKEN (${authenticated_login})"
fi
if [[ -n "${configured_owner}" && "${configured_owner}" != "${authenticated_login}" ]]; then
  log "Normalizing GITHUB_OWNER from ${configured_owner} to ${authenticated_login}"
fi
GITHUB_OWNER="${authenticated_login}"
export GITHUB_OWNER GITHUB_ORGS GITHUB_TOKEN BACKUP_DATA_DIR GHORG_INCLUDE_SUBMODULES
export GH_BACKUP_RUN_ID="${run_id}"
export GH_BACKUP_LOG_FILE="${run_log}"

runner_python="${GH_BACKUP_RUNNER_PYTHON:-/opt/venv/bin/python3}"
exec "${runner_python}" -m gh_backup.runner
