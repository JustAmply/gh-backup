#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
TEST_BIN_DIR="${TMP_DIR}/bin"
TEST_LOG_DIR="${TMP_DIR}/logs"
TEST_DATA_DIR="${TMP_DIR}/data"
MOCK_API_PORT_FILE="${TMP_DIR}/mock-api.port"
MOCK_API_PID=""
TEST_API_URL=""

cleanup() {
  if [[ -n "${MOCK_API_PID}" ]]; then
    kill "${MOCK_API_PID}" >/dev/null 2>&1 || true
    wait "${MOCK_API_PID}" >/dev/null 2>&1 || true
  fi
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

stop_mock_api() {
  if [[ -n "${MOCK_API_PID}" ]]; then
    kill "${MOCK_API_PID}" >/dev/null 2>&1 || true
    wait "${MOCK_API_PID}" >/dev/null 2>&1 || true
    MOCK_API_PID=""
  fi
  rm -f "${MOCK_API_PORT_FILE}"
  TEST_API_URL=""
}

start_mock_api() {
  local scenario="$1"
  local api_log="${TMP_DIR}/mock-api-${scenario}.log"
  local port=""
  local attempt

  stop_mock_api

  env \
    MOCK_GITHUB_API_SCENARIO="${scenario}" \
    MOCK_GITHUB_API_PORT_FILE="${MOCK_API_PORT_FILE}" \
    python3 "${ROOT_DIR}/tests/mock-github-api.py" >"${api_log}" 2>&1 &
  MOCK_API_PID=$!

  for attempt in {1..50}; do
    if [[ -s "${MOCK_API_PORT_FILE}" ]]; then
      port="$(cat "${MOCK_API_PORT_FILE}")"
      TEST_API_URL="http://127.0.0.1:${port}"
      if curl -fsS "${TEST_API_URL}/healthz" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 0.1
  done

  cat "${api_log}" >&2 || true
  fail "Mock GitHub API server failed to start for scenario ${scenario}"
}

write_stubs() {
  cat > "${TEST_BIN_DIR}/git" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "${TEST_LOG_DIR}/git.log"
git_scenario="${TEST_GIT_SCENARIO:-success}"

if [[ "$1" == "config" ]]; then
  exit 0
fi

if [[ "$1" == "clone" && "$2" == "--mirror" ]]; then
  clone_url="$3"
  repo_dir="$4"

  if [[ "${clone_url}" == *.wiki.git ]]; then
    case "${git_scenario}" in
      wiki-missing)
        printf 'remote: Repository not found.\n' >&2
        printf 'fatal: repository %s not found\n' "${clone_url}" >&2
        exit 1
        ;;
      wiki-auth-failure)
        printf 'fatal: Authentication failed for %s\n' "${clone_url}" >&2
        exit 1
        ;;
    esac
  fi

  mkdir -p "${repo_dir}"
  touch "${repo_dir}/HEAD"
  printf '%s\n' "${clone_url}" > "${repo_dir}/.stub-remote-origin"
  exit 0
fi

if [[ "$1" == "-C" ]]; then
  repo_dir="$2"
  shift 2

  if [[ "$1" == "rev-parse" && "$2" == "--is-bare-repository" ]]; then
    echo true
    exit 0
  fi

  if [[ "$1" == "remote" && "$2" == "set-url" ]]; then
    printf '%s\n' "$4" > "${repo_dir}/.stub-remote-origin"
    exit 0
  fi

  if [[ "$1" == "remote" && "$2" == "update" ]]; then
    exit 0
  fi

  if [[ "$1" == "lfs" && "$2" == "fetch" ]]; then
    exit 0
  fi
fi

printf 'unexpected git args: %s\n' "$*" >&2
exit 1
EOF

  cat > "${TEST_BIN_DIR}/ghorg" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "${TEST_LOG_DIR}/ghorg.log"
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
mkdir -p "${path}/${output_dir}/org-seed"
touch "${path}/${output_dir}/org-seed/HEAD"
EOF

  cat > "${TEST_BIN_DIR}/github-backup" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "${TEST_LOG_DIR}/github-backup.log"
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

  cat > "${TEST_BIN_DIR}/curl" <<'EOF'
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

  chmod +x \
    "${TEST_BIN_DIR}/git" \
    "${TEST_BIN_DIR}/ghorg" \
    "${TEST_BIN_DIR}/github-backup" \
    "${TEST_BIN_DIR}/git-lfs" \
    "${TEST_BIN_DIR}/flock" \
    "${TEST_BIN_DIR}/curl" \
    "${TEST_BIN_DIR}/supercronic"
}

run_backup() {
  local output_file="$1"
  local api_scenario="$2"
  local git_scenario="${3:-success}"
  local owner="${4:-octocat}"

  start_mock_api "${api_scenario}"

  env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    HOME="${TMP_DIR}/home" \
    TEST_LOG_DIR="${TEST_LOG_DIR}" \
    TEST_GIT_SCENARIO="${git_scenario}" \
    GITHUB_OWNER="${owner}" \
    GITHUB_ORGS="my-org" \
    GITHUB_TOKEN="ghp_testtoken" \
    BACKUP_DATA_DIR="${TEST_DATA_DIR}" \
    GITHUB_API_HELPER="${ROOT_DIR}/scripts/github-api-helper.py" \
    GITHUB_API_URL="${TEST_API_URL}" \
    GHORG_INCLUDE_SUBMODULES="true" \
    bash "${ROOT_DIR}/scripts/run-backup.sh" >"${output_file}" 2>&1
}

run_backup_expect_success() {
  local output_file="$1"
  local api_scenario="$2"
  local git_scenario="${3:-success}"

  if ! run_backup "${output_file}" "${api_scenario}" "${git_scenario}"; then
    cat "${output_file}" >&2 || true
    fail "Expected ${api_scenario}/${git_scenario} backup scenario to pass"
  fi
}

run_backup_expect_failure() {
  local output_file="$1"
  local api_scenario="$2"
  local git_scenario="${3:-success}"
  local owner="${4:-octocat}"

  if run_backup "${output_file}" "${api_scenario}" "${git_scenario}" "${owner}"; then
    fail "Expected ${api_scenario}/${git_scenario} backup scenario to fail"
  fi
}

run_validate_expect_success() {
  local output_file="${TMP_DIR}/validate-success.log"

  env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    GITHUB_OWNER="octocat" \
    GITHUB_TOKEN="ghp_testtoken" \
    GITHUB_API_HELPER="${ROOT_DIR}/scripts/github-api-helper.py" \
    PYTHON_BIN="python3" \
    bash "${ROOT_DIR}/scripts/validate.sh" >"${output_file}" 2>&1 || fail "Expected validate scenario to pass"
}

run_validate_expect_failure() {
  local output_file="$1"
  local python_bin="$2"
  local helper_path="$3"

  if env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    GITHUB_OWNER="octocat" \
    GITHUB_TOKEN="ghp_testtoken" \
    GITHUB_API_HELPER="${helper_path}" \
    PYTHON_BIN="${python_bin}" \
    bash "${ROOT_DIR}/scripts/validate.sh" >"${output_file}" 2>&1; then
    fail "Expected validate scenario with PYTHON_BIN=${python_bin} and helper=${helper_path} to fail"
  fi
}

main() {
  reset_logs
  write_stubs

  run_validate_expect_success
  run_validate_expect_failure "${TMP_DIR}/validate-missing-python.log" "missing-python" "${ROOT_DIR}/scripts/github-api-helper.py"
  assert_contains "${TMP_DIR}/validate-missing-python.log" "Required command missing: missing-python"
  run_validate_expect_failure "${TMP_DIR}/validate-missing-helper.log" "python3" "${TMP_DIR}/missing-helper.py"
  assert_contains "${TMP_DIR}/validate-missing-helper.log" "Required helper missing: ${TMP_DIR}/missing-helper.py"

  reset_logs
  write_stubs
  run_backup_expect_success "${TMP_DIR}/success-output.log" "success"
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/public-repo.git ${TEST_DATA_DIR}/mirrors/octocat_backup/public-repo"
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/private-repo.git ${TEST_DATA_DIR}/mirrors/octocat_backup/private-repo"
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/public-repo.wiki.git ${TEST_DATA_DIR}/mirrors/octocat_backup/public-repo.wiki.git"
  assert_contains "${TEST_LOG_DIR}/git.log" "-C ${TEST_DATA_DIR}/mirrors/octocat_backup/public-repo lfs fetch --all"
  assert_contains "${TEST_LOG_DIR}/git.log" "-C ${TEST_DATA_DIR}/mirrors/octocat_backup/private-repo lfs fetch --all"
  assert_not_contains "${TEST_LOG_DIR}/git.log" "private-dependency.git"
  assert_contains "${TEST_LOG_DIR}/ghorg.log" "clone my-org --scm=github --clone-type=org"
  assert_contains "${TEST_LOG_DIR}/github-backup.log" "--output-directory ${TEST_DATA_DIR}/metadata/octocat"
  assert_contains "${TEST_LOG_DIR}/github-backup.log" "--output-directory ${TEST_DATA_DIR}/metadata/my-org"

  reset_logs
  write_stubs
  run_backup_expect_success "${TMP_DIR}/wiki-missing.log" "success" "wiki-missing"
  assert_contains "${TMP_DIR}/wiki-missing.log" "WARN: Wiki mirror clone failed"

  reset_logs
  write_stubs
  run_backup_expect_failure "${TMP_DIR}/wiki-auth-failure.log" "success" "wiki-auth-failure"
  assert_contains "${TMP_DIR}/wiki-auth-failure.log" "Authentication failed"

  reset_logs
  write_stubs
  run_backup_expect_failure "${TMP_DIR}/owner-mismatch.log" "owner-mismatch"
  assert_contains "${TMP_DIR}/owner-mismatch.log" "GITHUB_OWNER 'octocat' does not match the authenticated GitHub user 'somebody-else'"

  reset_logs
  write_stubs
  run_backup_expect_failure "${TMP_DIR}/sso-failure.log" "sso-failure"
  assert_contains "${TMP_DIR}/sso-failure.log" "GitHub repo discovery failed (403)"
}

main "$@"
