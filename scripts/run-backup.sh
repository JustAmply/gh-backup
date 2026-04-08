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

  mkdir -p "$(dirname "${repo_dir}")"

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

  mkdir -p "$(dirname "${wiki_dir}")"

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

clone_repo_for_submodule_scan() {
  local repo_dir="$1"
  local commitish="$2"
  local temp_dir

  temp_dir="$(mktemp -d)"

  if ! git clone --quiet --no-checkout --shared "${repo_dir}" "${temp_dir}" >/dev/null 2>&1; then
    rm -rf "${temp_dir}"
    return 1
  fi

  if ! git -C "${temp_dir}" checkout --quiet --detach "${commitish}" >/dev/null 2>&1; then
    rm -rf "${temp_dir}"
    return 1
  fi

  printf '%s\n' "${temp_dir}"
}

mirror_repo_submodules() {
  local repo_dir="$1"
  local mirror_root="$2"
  local namespace="$3"
  local commitish="${4:-HEAD}"
  local temp_dir
  local submodule_keys=()
  local key
  local module_name
  local submodule_path
  local submodule_url
  local submodule_commit
  local submodule_repo_dir

  temp_dir="$(clone_repo_for_submodule_scan "${repo_dir}" "${commitish}")" || {
    log "ERROR: failed to inspect submodules for ${namespace} at ${commitish}"
    return 1
  }

  git -C "${temp_dir}" submodule init >/dev/null 2>&1 || true
  mapfile -t submodule_keys < <(git -C "${temp_dir}" config --file .gitmodules --name-only --get-regexp '^submodule\..*\.path$' 2>/dev/null || true)

  if [[ "${#submodule_keys[@]}" -eq 0 ]]; then
    rm -rf "${temp_dir}"
    return 0
  fi

  for key in "${submodule_keys[@]}"; do
    module_name="${key#submodule.}"
    module_name="${module_name%.path}"
    submodule_path="$(git -C "${temp_dir}" config --file .gitmodules --get "${key}")"
    submodule_url="$(git -C "${temp_dir}" config --get "submodule.${module_name}.url")"
    submodule_commit="$(git -C "${temp_dir}" rev-parse "HEAD:${submodule_path}")"
    submodule_repo_dir="${mirror_root}/.submodules/${namespace}/${submodule_path}"

    [[ -n "${submodule_path}" && -n "${submodule_url}" ]] || {
      rm -rf "${temp_dir}"
      log "ERROR: failed to resolve submodule metadata for ${namespace}/${module_name}"
      return 1
    }

    update_or_clone_mirror "${submodule_url}" "${submodule_repo_dir}"
    mirror_repo_submodules "${submodule_repo_dir}" "${mirror_root}" "${namespace}/${submodule_path}" "${submodule_commit}"
  done

  rm -rf "${temp_dir}"
}

run_owner_backup() {
  local mirror_root="${BACKUP_DATA_DIR}/mirrors/${GITHUB_OWNER}_backup"
  local repo_rows=""
  local repo_name
  local clone_url
  local has_wiki
  local repo_dir
  local wiki_dir
  local wiki_url

  mkdir -p "${mirror_root}"
  log "Starting owner backup for ${GITHUB_OWNER}"

  repo_rows="$("${PYTHON_BIN}" "${GITHUB_API_HELPER}" list-owner-repos --token "${GITHUB_TOKEN}" --owner "${GITHUB_OWNER}")" || return 1

  while IFS=$'\t' read -r repo_name clone_url has_wiki; do
    [[ -n "${repo_name}" ]] || continue

    repo_dir="$(resolve_repo_dir "${mirror_root}" "${repo_name}")"
    update_or_clone_mirror "${clone_url}" "${repo_dir}"

    if bool_is_true "${GHORG_INCLUDE_SUBMODULES:-true}"; then
      mirror_repo_submodules "${repo_dir}" "${mirror_root}" "${repo_name}"
    fi

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
  local submodule_root="${mirror_root}/.submodules"
  local repo_dirs=()

  if [[ ! -d "${mirror_root}" ]]; then
    die "Expected mirror directory missing: ${mirror_root}"
  fi

  shopt -s nullglob dotglob
  for repo_dir in "${mirror_root}"/*; do
    [[ "$(basename "${repo_dir}")" == ".submodules" ]] && continue
    repo_dirs+=("${repo_dir}")
  done
  shopt -u nullglob dotglob

  if [[ -d "${submodule_root}" ]]; then
    while IFS= read -r repo_dir; do
      repo_dirs+=("${repo_dir}")
    done < <(find "${submodule_root}" -type f -name HEAD -printf '%h\n' | sort -u)
  fi

  for repo_dir in "${repo_dirs[@]}"; do
    if [[ -d "${repo_dir}" ]] && git -C "${repo_dir}" rev-parse --is-bare-repository >/dev/null 2>&1; then
      log "Fetching Git LFS objects for ${repo_dir}"
      git -C "${repo_dir}" lfs fetch --all
    fi
  done
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
