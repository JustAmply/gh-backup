#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

warn() {
  log "WARN: $*"
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

detect_token_type() {
  case "${GITHUB_TOKEN}" in
    ghp_*)
      printf '%s\n' "classic-pat"
      ;;
    github_pat_*)
      printf '%s\n' "fine-grained-pat"
      ;;
    *)
      printf '%s\n' "unknown"
      ;;
  esac
}

preflight_github_access() {
  local token_type
  local authenticated_login

  token_type="$(detect_token_type)"
  case "${token_type}" in
    classic-pat)
      ;;
    fine-grained-pat)
      if bool_is_true "${ALLOW_FINE_GRAINED_PAT:-false}"; then
        warn "Detected a fine-grained PAT. This backup stack is designed around classic PATs and may miss data."
      else
        die "Detected a fine-grained PAT. Use a classic PAT with repo, read:org, and gist scopes, or set ALLOW_FINE_GRAINED_PAT=true to continue anyway."
      fi
      ;;
    *)
      warn "Unrecognized GitHub token format. Classic PATs are recommended for full backups."
      ;;
  esac

  authenticated_login="$("${PYTHON_BIN}" "${GITHUB_API_HELPER}" get-user-login \
    --api-url "${GITHUB_API_URL:-https://api.github.com}" \
    --token "${GITHUB_TOKEN}")" || exit 1

  if [[ "${authenticated_login,,}" != "${GITHUB_OWNER,,}" ]]; then
    die "GITHUB_OWNER (${GITHUB_OWNER}) does not match the authenticated GitHub user (${authenticated_login}). Set GITHUB_OWNER to the token owner's username."
  fi
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
    --path="${BACKUP_DATA_DIR}/mirrors"
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

resolve_repo_dir() {
  local root="$1"
  local repo_name="$2"
  local candidate

  for candidate in \
    "${root}/${repo_name}" \
    "${root}/${repo_name}.git"; do
    if [[ -d "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  printf '%s\n' "${root}/${repo_name}"
}

resolve_wiki_dir() {
  local root="$1"
  local repo_name="$2"
  local candidate

  for candidate in \
    "${root}/${repo_name}.wiki.git" \
    "${root}/${repo_name}.wiki"; do
    if [[ -d "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  printf '%s\n' "${root}/${repo_name}.wiki.git"
}

update_or_clone_mirror() {
  local clone_url="$1"
  local repo_dir="$2"

  if [[ -d "${repo_dir}" ]]; then
    log "Updating mirror ${repo_dir}"
    git -C "${repo_dir}" remote set-url origin "${clone_url}"
    git -C "${repo_dir}" remote update --prune
  else
    log "Cloning mirror ${clone_url} -> ${repo_dir}"
    git clone --mirror "${clone_url}" "${repo_dir}"
  fi
}

update_or_clone_wiki_mirror() {
  local wiki_url="$1"
  local wiki_dir="$2"

  if [[ -d "${wiki_dir}" ]]; then
    log "Updating wiki mirror ${wiki_dir}"
    git -C "${wiki_dir}" remote set-url origin "${wiki_url}"
    if ! git -C "${wiki_dir}" remote update --prune; then
      warn "Wiki mirror update failed for ${wiki_url}; continuing"
    fi
  else
    log "Cloning wiki mirror ${wiki_url} -> ${wiki_dir}"
    if ! git clone --mirror "${wiki_url}" "${wiki_dir}"; then
      warn "Wiki mirror clone failed for ${wiki_url}; continuing"
    fi
  fi
}

run_owner_backup() {
  local mirror_root="${BACKUP_DATA_DIR}/mirrors/${GITHUB_OWNER}_backup"
  local repo_rows
  local repo_name
  local clone_url
  local has_wiki
  local repo_dir
  local wiki_dir
  local wiki_url

  mkdir -p "${mirror_root}"
  log "Starting owner backup for ${GITHUB_OWNER}"

  repo_rows="$("${PYTHON_BIN}" "${GITHUB_API_HELPER}" list-owner-repos \
    --api-url "${GITHUB_API_URL:-https://api.github.com}" \
    --token "${GITHUB_TOKEN}" \
    --owner "${GITHUB_OWNER}")"

  while IFS=$'\t' read -r repo_name clone_url has_wiki; do
    [[ -n "${repo_name}" ]] || continue

    repo_dir="$(resolve_repo_dir "${mirror_root}" "${repo_name}")"
    update_or_clone_mirror "${clone_url}" "${repo_dir}"

    if [[ "${has_wiki}" == "true" ]]; then
      wiki_dir="$(resolve_wiki_dir "${mirror_root}" "${repo_name}")"
      wiki_url="${clone_url%.git}.wiki.git"
      update_or_clone_wiki_mirror "${wiki_url}" "${wiki_dir}"
    fi
  done <<< "${repo_rows}"
}

fetch_lfs_for_target() {
  local target="$1"
  local mirror_root="${BACKUP_DATA_DIR}/mirrors/${target}_backup"
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
  local metadata_dir="${BACKUP_DATA_DIR}/metadata/${target}"
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
: "${ALLOW_FINE_GRAINED_PAT:=false}"
: "${BACKUP_DATA_DIR:=/data}"
: "${GITHUB_API_HELPER:=/usr/local/bin/github-api-helper.py}"
: "${PYTHON_BIN:=python3}"

[[ -n "${GITHUB_OWNER}" ]] || die "GITHUB_OWNER must be set"

GITHUB_TOKEN="$(printf '%s' "${GITHUB_TOKEN}" | tr -d '\r\n')"
[[ -n "${GITHUB_TOKEN}" ]] || die "GitHub token value is empty"

command -v "${PYTHON_BIN}" >/dev/null 2>&1 || die "Python runtime not found: ${PYTHON_BIN}"
[[ -f "${GITHUB_API_HELPER}" ]] || die "GitHub API helper is missing: ${GITHUB_API_HELPER}"

mkdir -p "${BACKUP_DATA_DIR}/logs" "${BACKUP_DATA_DIR}/metadata" "${BACKUP_DATA_DIR}/mirrors" "${BACKUP_DATA_DIR}/state"

configure_github_https_auth

run_id="$(date -u +%Y%m%dT%H%M%SZ)"
run_log="${BACKUP_DATA_DIR}/logs/${run_id}.log"
touch "${run_log}"
exec > >(tee -a "${run_log}") 2>&1

exec 9>"${BACKUP_DATA_DIR}/state/backup.lock"
if ! flock -n 9; then
  die "Another backup run is already in progress"
fi

preflight_github_access

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
  if [[ "${target}" == "${GITHUB_OWNER}" ]]; then
    if ! run_owner_backup; then
      log "ERROR: owner backup failed for ${target}"
      overall_status=1
      continue
    fi
  else
    if ! run_ghorg_backup "${target}" "org"; then
      log "ERROR: ghorg backup failed for ${target}"
      overall_status=1
      continue
    fi
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

  cat > "${BACKUP_DATA_DIR}/state/last-success.json" <<EOF
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
