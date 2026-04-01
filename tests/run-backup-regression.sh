#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
TEST_BIN_DIR="${TMP_DIR}/bin"
TEST_LOG_DIR="${TMP_DIR}/logs"
TEST_DATA_DIR="${TMP_DIR}/data"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
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

start_mock_server() {
  local scenario="$1"
  local port_file="${TMP_DIR}/server-port"

  rm -f "${port_file}"
  MOCK_GITHUB_SCENARIO="${scenario}" python3 "${ROOT_DIR}/tests/mock-github-api.py" >"${port_file}" &
  SERVER_PID=$!

  for _ in {1..50}; do
    if [[ -s "${port_file}" ]]; then
      SERVER_PORT="$(<"${port_file}")"
      export GITHUB_API_URL="http://127.0.0.1:${SERVER_PORT}"
      return 0
    fi
    sleep 0.1
  done

  fail "Mock GitHub API server did not start"
}

reset_logs() {
  rm -rf "${TEST_LOG_DIR}" "${TEST_DATA_DIR}" "${TMP_DIR}/home"
  mkdir -p "${TEST_LOG_DIR}" "${TEST_DATA_DIR}" "${TEST_BIN_DIR}" "${TMP_DIR}/home"
}

write_stubs() {
  cat > "${TEST_BIN_DIR}/git" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "${TEST_LOG_DIR}/git.log"
if [[ "$1" == "config" ]]; then
  exit 0
fi
if [[ "$1" == "clone" && "$2" == "--mirror" ]]; then
  mkdir -p "$4"
  exit 0
fi
if [[ "$1" == "-C" ]]; then
  repo_dir="$2"
  shift 2
  case "$1 $2" in
    "rev-parse --is-bare-repository")
      echo true
      exit 0
      ;;
    "remote set-url")
      exit 0
      ;;
    "remote update")
      exit 0
      ;;
    "lfs fetch")
      exit 0
      ;;
  esac
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
EOF

  cat > "${TEST_BIN_DIR}/github-backup" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "${TEST_LOG_DIR}/github-backup.log"
EOF

  chmod +x "${TEST_BIN_DIR}/git" "${TEST_BIN_DIR}/ghorg" "${TEST_BIN_DIR}/github-backup"
}

run_backup_expect_success() {
  local output_file="${TMP_DIR}/success-output.log"
  env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    HOME="${TMP_DIR}/home" \
    TEST_LOG_DIR="${TEST_LOG_DIR}" \
    GITHUB_OWNER="octocat" \
    GITHUB_ORGS="my-org" \
    GITHUB_TOKEN="ghp_testtoken" \
    BACKUP_DATA_DIR="${TEST_DATA_DIR}" \
    GITHUB_API_HELPER="${ROOT_DIR}/scripts/github-api-helper.py" \
    GHORG_INCLUDE_SUBMODULES="true" \
    bash "${ROOT_DIR}/scripts/run-backup.sh" >"${output_file}" 2>&1 || fail "Expected success scenario to pass"
}

run_backup_expect_failure() {
  local token="$1"
  local output_file="$2"
  if env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    HOME="${TMP_DIR}/home" \
    TEST_LOG_DIR="${TEST_LOG_DIR}" \
    GITHUB_OWNER="octocat" \
    GITHUB_TOKEN="${token}" \
    BACKUP_DATA_DIR="${TEST_DATA_DIR}" \
    GITHUB_API_HELPER="${ROOT_DIR}/scripts/github-api-helper.py" \
    bash "${ROOT_DIR}/scripts/run-backup.sh" >"${output_file}" 2>&1; then
    fail "Expected failure scenario to fail"
  fi
}

main() {
  write_stubs

  reset_logs
  start_mock_server success
  run_backup_expect_success
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/public-repo.git ${TEST_DATA_DIR}/mirrors/octocat_backup/public-repo"
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/private-repo.git ${TEST_DATA_DIR}/mirrors/octocat_backup/private-repo"
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/public-repo.wiki.git ${TEST_DATA_DIR}/mirrors/octocat_backup/public-repo.wiki.git"
  assert_not_contains "${TEST_LOG_DIR}/git.log" "collab-repo.git"
  assert_not_contains "${TEST_LOG_DIR}/git.log" "org-repo.git"
  assert_contains "${TEST_LOG_DIR}/ghorg.log" "clone my-org --scm=github --clone-type=org"

  kill "${SERVER_PID}" >/dev/null 2>&1 || true
  unset SERVER_PID

  reset_logs
  run_backup_expect_failure "github_pat_finegrained" "${TMP_DIR}/fine-grained-output.log"
  assert_contains "${TMP_DIR}/fine-grained-output.log" "Detected a fine-grained PAT"

  reset_logs
  start_mock_server sso
  run_backup_expect_failure "ghp_testtoken" "${TMP_DIR}/sso-output.log"
  assert_contains "${TMP_DIR}/sso-output.log" "needs SSO authorization"
}

main "$@"
