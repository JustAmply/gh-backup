#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
TEST_BIN_DIR="${TMP_DIR}/bin"
TEST_LOG_DIR="${TMP_DIR}/logs"
TEST_DATA_DIR="${TMP_DIR}/data"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

fail() {
  printf 'TEST FAILED: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local file="$1"
  local expected="$2"
  grep -F -- "${expected}" "${file}" >/dev/null || fail "Expected '${expected}' in ${file}"
}

assert_not_contains() {
  local file="$1"
  local unexpected="$2"
  if grep -F -- "${unexpected}" "${file}" >/dev/null; then
    fail "Did not expect '${unexpected}' in ${file}"
  fi
}

reset_logs() {
  rm -rf "${TEST_LOG_DIR}" "${TEST_DATA_DIR}" "${TMP_DIR}/home"
  mkdir -p "${TEST_LOG_DIR}" "${TEST_DATA_DIR}" "${TEST_BIN_DIR}" "${TMP_DIR}/home"
}

write_stubs() {
  cat > "${TEST_BIN_DIR}/git" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
args=("$@")
if [[ "${args[0]:-}" == "-C" ]] && command -v cygpath >/dev/null 2>&1; then
  args[1]="$(cygpath -u "${args[1]}")"
  set -- "${args[@]}"
fi
printf '%s\n' "$*" >> "${TEST_LOG_DIR}/git.log"

if [[ "$1" == "config" ]]; then
  exit 0
fi

if [[ "$1" == "-C" ]]; then
  shift 2

  if [[ "$1" == "rev-parse" && "$2" == "--is-bare-repository" ]]; then
    echo true
    exit 0
  fi

  if [[ "$1" == "lfs" && "$2" == "fetch" ]]; then
    exit 0
  fi

  if [[ "$1" == "fsck" && "$2" == "--full" ]]; then
    exit 0
  fi
fi

printf 'unexpected git args: %s\n' "$*" >&2
exit 1
EOF

  cat > "${TEST_BIN_DIR}/ghorg" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

normalized_args=()
for arg in "$@"; do
  if [[ "${arg}" == --path=* ]] && command -v cygpath >/dev/null 2>&1; then
    normalized_args+=("--path=$(cygpath -u "${arg#--path=}")")
  else
    normalized_args+=("${arg}")
  fi
done
set -- "${normalized_args[@]}"
printf '%s\n' "$*" >> "${TEST_LOG_DIR}/ghorg.log"

scenario="${TEST_GHORG_SCENARIO:-success}"
target="${2:-}"
path=""
output_dir=""

for arg in "$@"; do
  case "${arg}" in
    --path=*)
      path="${arg#--path=}"
      ;;
    --output-dir=*)
      output_dir="${arg#--output-dir=}"
      ;;
  esac
done

case "${scenario}:${target}" in
  owner-fail:octocat|org-fail:my-org)
    printf 'simulated ghorg failure for %s\n' "${target}" >&2
    exit 1
    ;;
esac

mkdir -p "${path}/${output_dir}"

create_repo() {
  local repo_dir="$1"
  mkdir -p "${repo_dir}"
  touch "${repo_dir}/HEAD"
}

case "${target}" in
  octocat|OctoCat)
    create_repo "${path}/${output_dir}/public-repo"
    create_repo "${path}/${output_dir}/private-repo"
    create_repo "${path}/${output_dir}/public-repo.wiki"
    ;;
  my-org)
    create_repo "${path}/${output_dir}/org-seed"
    ;;
  *)
    create_repo "${path}/${output_dir}/misc-seed"
    ;;
esac
EOF

  cat > "${TEST_BIN_DIR}/github-backup" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
normalized_args=()
for arg in "$@"; do
  if [[ "${arg}" =~ ^[A-Za-z]:\\ ]] && command -v cygpath >/dev/null 2>&1; then
    normalized_args+=("$(cygpath -u "${arg}")")
  else
    normalized_args+=("${arg}")
  fi
done
printf '%s\n' "${normalized_args[*]}" >> "${TEST_LOG_DIR}/github-backup.log"
EOF

  cat > "${TEST_BIN_DIR}/git-lfs" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
exit 0
EOF

  cat > "${TEST_BIN_DIR}/flock" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
exit 0
EOF

  cat > "${TEST_BIN_DIR}/supercronic" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == "-test" ]]; then
  exit 0
fi
printf 'unexpected supercronic args: %s\n' "$*" >&2
exit 1
EOF

  cat > "${TEST_BIN_DIR}/python3" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" != "-" ]]; then
  printf 'unexpected python3 args: %s\n' "$*" >&2
  exit 1
fi
cat >/dev/null
printf '%s' "${TEST_GITHUB_AUTH_LOGIN:-octocat}"
EOF

  chmod +x \
    "${TEST_BIN_DIR}/git" \
    "${TEST_BIN_DIR}/ghorg" \
    "${TEST_BIN_DIR}/github-backup" \
    "${TEST_BIN_DIR}/git-lfs" \
    "${TEST_BIN_DIR}/flock" \
    "${TEST_BIN_DIR}/supercronic" \
    "${TEST_BIN_DIR}/python3"
}

run_backup() {
  local output_file="$1"
  local ghorg_scenario="${2:-success}"
  local orgs="${3:-my-org}"
  local owner="${4:-octocat}"
  local auth_login="${5:-${owner}}"

  env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    HOME="${TMP_DIR}/home" \
    TEST_LOG_DIR="${TEST_LOG_DIR}" \
    TEST_GHORG_SCENARIO="${ghorg_scenario}" \
    TEST_GITHUB_AUTH_LOGIN="${auth_login}" \
    GH_BACKUP_RUNNER_PYTHON="python" \
    GH_BACKUP_COMMAND_SHELL="$(cygpath -w /usr/bin/bash 2>/dev/null || true)" \
    PYTHONPATH="${ROOT_DIR}" \
    GITHUB_OWNER="${owner}" \
    GITHUB_ORGS="${orgs}" \
    GITHUB_TOKEN="ghp_testtoken" \
    BACKUP_DATA_DIR="${TEST_DATA_DIR}" \
    GHORG_INCLUDE_SUBMODULES="true" \
    bash "${ROOT_DIR}/scripts/run-backup.sh" >"${output_file}" 2>&1
}

run_backup_expect_success() {
  local output_file="$1"
  local ghorg_scenario="${2:-success}"
  local orgs="${3:-my-org}"
  local owner="${4:-octocat}"
  local auth_login="${5:-${owner}}"

  if ! run_backup "${output_file}" "${ghorg_scenario}" "${orgs}" "${owner}" "${auth_login}"; then
    cat "${output_file}" >&2 || true
    fail "Expected backup scenario ${ghorg_scenario}/${orgs} to pass"
  fi
}

run_backup_expect_failure() {
  local output_file="$1"
  local ghorg_scenario="${2:-success}"
  local orgs="${3:-my-org}"
  local owner="${4:-octocat}"
  local auth_login="${5:-${owner}}"

  if run_backup "${output_file}" "${ghorg_scenario}" "${orgs}" "${owner}" "${auth_login}"; then
    fail "Expected backup scenario ${ghorg_scenario}/${orgs} to fail"
  fi
}

run_validate_expect_success() {
  local output_file="${TMP_DIR}/validate-success.log"
  local owner="${1:-octocat}"

  env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    GITHUB_OWNER="${owner}" \
    GITHUB_TOKEN="ghp_testtoken" \
    bash "${ROOT_DIR}/scripts/validate.sh" >"${output_file}" 2>&1 || fail "Expected validate scenario to pass"
}

run_validate_expect_failure() {
  local output_file="$1"
  local owner="$2"
  local token="$3"

  if env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    GITHUB_OWNER="${owner}" \
    GITHUB_TOKEN="${token}" \
    bash "${ROOT_DIR}/scripts/validate.sh" >"${output_file}" 2>&1; then
    fail "Expected validate scenario owner='${owner}' token='${token}' to fail"
  fi
}

main() {
  reset_logs
  write_stubs

  run_validate_expect_success
  run_validate_expect_success ""
  run_validate_expect_success "change-me"
  run_validate_expect_failure "${TMP_DIR}/validate-empty-token.log" "octocat" ""
  assert_contains "${TMP_DIR}/validate-empty-token.log" "GitHub token value is empty"

  reset_logs
  write_stubs
  run_backup_expect_success "${TMP_DIR}/success-output.log"
  assert_contains "${TEST_LOG_DIR}/ghorg.log" "clone octocat --scm=github --clone-type=user --token=ghp_testtoken --path=${TEST_DATA_DIR}/mirrors --output-dir=octocat_backup --backup --clone-wiki --github-user-option=owner --include-submodules"
  assert_contains "${TEST_LOG_DIR}/ghorg.log" "clone my-org --scm=github --clone-type=org --token=ghp_testtoken --path=${TEST_DATA_DIR}/mirrors --output-dir=my-org_backup --backup --clone-wiki --include-submodules"
  assert_contains "${TEST_LOG_DIR}/git.log" "-C ${TEST_DATA_DIR}/mirrors/octocat_backup/public-repo lfs fetch --all"
  assert_contains "${TEST_LOG_DIR}/git.log" "-C ${TEST_DATA_DIR}/mirrors/octocat_backup/private-repo lfs fetch --all"
  assert_contains "${TEST_LOG_DIR}/git.log" "-C ${TEST_DATA_DIR}/mirrors/my-org_backup/org-seed lfs fetch --all"
  assert_contains "${TEST_LOG_DIR}/github-backup.log" "--output-directory ${TEST_DATA_DIR}/metadata/octocat"
  assert_contains "${TEST_LOG_DIR}/github-backup.log" "--output-directory ${TEST_DATA_DIR}/metadata/my-org"
  assert_contains "${TEST_DATA_DIR}/state/last-success.json" "\"owner\": \"octocat\""
  assert_contains "${TEST_DATA_DIR}/state/last-success.json" "\"orgs\": ["
  assert_contains "${TEST_DATA_DIR}/state/last-success.json" "\"my-org\""

  reset_logs
  write_stubs
  run_backup_expect_success "${TMP_DIR}/normalized-owner.log" "success" "" "octocat" "OctoCat"
  assert_contains "${TMP_DIR}/normalized-owner.log" "Normalizing GITHUB_OWNER from octocat to OctoCat"
  assert_contains "${TEST_LOG_DIR}/ghorg.log" "clone OctoCat --scm=github --clone-type=user --token=ghp_testtoken --path=${TEST_DATA_DIR}/mirrors --output-dir=OctoCat_backup --backup --clone-wiki --github-user-option=owner --include-submodules"
  assert_contains "${TEST_LOG_DIR}/github-backup.log" "--output-directory ${TEST_DATA_DIR}/metadata/OctoCat"
  assert_contains "${TEST_DATA_DIR}/state/last-success.json" "\"owner\": \"OctoCat\""

  reset_logs
  write_stubs
  run_backup_expect_failure "${TMP_DIR}/owner-mismatch.log" "success" "" "octocat" "someoneelse"
  assert_contains "${TMP_DIR}/owner-mismatch.log" "GITHUB_OWNER (octocat) must match the GitHub account behind GITHUB_TOKEN (someoneelse)"

  reset_logs
  write_stubs
  run_backup_expect_failure "${TMP_DIR}/owner-failure.log" "owner-fail" ""
  assert_contains "${TMP_DIR}/owner-failure.log" "ERROR: ghorg backup failed for octocat"

  reset_logs
  write_stubs
  run_backup_expect_failure "${TMP_DIR}/org-failure.log" "org-fail"
  assert_contains "${TMP_DIR}/org-failure.log" "ERROR: ghorg backup failed for my-org"
  assert_not_contains "${TMP_DIR}/org-failure.log" "ERROR: ghorg backup failed for octocat"
}

main "$@"
