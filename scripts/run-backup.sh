#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

bool_is_true() {
  local value="${1:-}"
  shopt -s nocasematch
  if [[ "${value}" =~ ^(1|true|yes|on)$ ]]; then
    shopt -u nocasematch
    return 0
  fi
  shopt -u nocasematch
  return 1
}

trim() {
  local value="${1:-}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

dedupe_targets() {
  declare -A seen=()
  local target
  for target in "$@"; do
    if [[ -n "${target}" && -z "${seen[${target}]:-}" ]]; then
      seen["${target}"]=1
      printf '%s\n' "${target}"
    fi
  done
}

configure_github_https_auth() {
  export GHORG_GITHUB_TOKEN="${GITHUB_TOKEN}"

  # ghorg uses git for cloning. Configure a non-interactive credential helper so
  # private HTTPS clones succeed inside the container as well.
  git config --global url."https://github.com/".insteadOf git@github.com:
  git config --global credential.https://github.com/.helper \
    '!f() { echo username=x-access-token; echo password=$GHORG_GITHUB_TOKEN; }; f'
}

run_ghorg_backup() {
  local target="$1"
  local clone_type="$2"
  local output_dir="${target}_backup"
  local args=(
    clone
    "${target}"
    --scm=github
    --clone-type="${clone_type}"
    --token="${GITHUB_TOKEN}"
    --path=/data/mirrors
    --output-dir="${output_dir}"
    --backup
    --clone-wiki
  )

  if bool_is_true "${GHORG_INCLUDE_SUBMODULES:-true}"; then
    args+=(--include-submodules)
  fi

  log "Starting ghorg backup for ${target} (${clone_type})"
  ghorg "${args[@]}"
}

fetch_lfs_for_target() {
  local target="$1"
  local mirror_root="/data/mirrors/${target}_backup"
  local repo_dir

  if [[ ! -d "${mirror_root}" ]]; then
    die "Expected mirror directory missing: ${mirror_root}"
  fi

  shopt -s nullglob
  for repo_dir in "${mirror_root}"/*; do
    if [[ -d "${repo_dir}" ]] && git -C "${repo_dir}" rev-parse --is-bare-repository >/dev/null 2>&1; then
      log "Fetching Git LFS objects for ${repo_dir}"
      git -C "${repo_dir}" lfs fetch --all
    fi
  done
  shopt -u nullglob
}

run_metadata_backup() {
  local target="$1"
  local metadata_dir="/data/metadata/${target}"
  local args=(
    --token "${GITHUB_TOKEN}"
    --output-directory "${metadata_dir}"
    --private
    --issues
    --issue-comments
    --issue-events
    --pulls
    --pull-comments
    --pull-commits
    --pull-details
    --labels
    --milestones
    --releases
    --assets
    --attachments
  )

  if [[ "${target}" != "${GITHUB_OWNER}" ]]; then
    args+=(--organization)
  fi

  if [[ "${target}" == "${GITHUB_OWNER}" ]]; then
    args+=(
      --gists
      --starred-gists
      --starred
      --watched
      --followers
      --following
    )
  fi

  mkdir -p "${metadata_dir}"
  log "Starting metadata backup for ${target}"
  github-backup "${args[@]}" "${target}"
}

: "${GITHUB_OWNER:=}"
: "${GITHUB_ORGS:=}"
: "${GITHUB_TOKEN:=}"

[[ -n "${GITHUB_OWNER}" ]] || die "GITHUB_OWNER must be set"

GITHUB_TOKEN="$(printf '%s' "${GITHUB_TOKEN}" | tr -d '\r\n')"
[[ -n "${GITHUB_TOKEN}" ]] || die "GitHub token value is empty"

mkdir -p /data/logs /data/metadata /data/mirrors /data/state

configure_github_https_auth

run_id="$(date -u +%Y%m%dT%H%M%SZ)"
run_log="/data/logs/${run_id}.log"
touch "${run_log}"
exec > >(tee -a "${run_log}") 2>&1

exec 9>/data/state/backup.lock
if ! flock -n 9; then
  die "Another backup run is already in progress"
fi

targets=("${GITHUB_OWNER}")
if [[ -n "${GITHUB_ORGS}" ]]; then
  IFS=',' read -r -a org_values <<< "${GITHUB_ORGS}"
  for org in "${org_values[@]}"; do
    org="$(trim "${org}")"
    if [[ -n "${org}" ]]; then
      targets+=("${org}")
    fi
  done
fi

mapfile -t targets < <(dedupe_targets "${targets[@]}")
[[ "${#targets[@]}" -gt 0 ]] || die "No backup targets resolved"

log "Resolved targets: ${targets[*]}"

overall_status=0
for target in "${targets[@]}"; do
  clone_type="org"
  if [[ "${target}" == "${GITHUB_OWNER}" ]]; then
    clone_type="user"
  fi

  if ! run_ghorg_backup "${target}" "${clone_type}"; then
    log "ERROR: ghorg backup failed for ${target}"
    overall_status=1
    continue
  fi

  if ! fetch_lfs_for_target "${target}"; then
    log "ERROR: Git LFS fetch failed for ${target}"
    overall_status=1
    continue
  fi

  if ! run_metadata_backup "${target}"; then
    log "ERROR: github-backup metadata export failed for ${target}"
    overall_status=1
    continue
  fi
done

if [[ "${overall_status}" -eq 0 ]]; then
  orgs_json="[]"
  if [[ -n "${GITHUB_ORGS}" ]]; then
    orgs_json="["
    first=1
    for target in "${targets[@]}"; do
      if [[ "${target}" != "${GITHUB_OWNER}" ]]; then
        if [[ "${first}" -eq 0 ]]; then
          orgs_json+=", "
        fi
        orgs_json+="\"${target}\""
        first=0
      fi
    done
    orgs_json+="]"
  fi

  cat > /data/state/last-success.json <<EOF
{
  "run_id": "${run_id}",
  "finished_at": "$(date -u --iso-8601=seconds)",
  "owner": "${GITHUB_OWNER}",
  "orgs": ${orgs_json},
  "log_file": "${run_log}"
}
EOF
  log "Backup run finished successfully"
else
  log "Backup run finished with errors"
fi

exit "${overall_status}"
