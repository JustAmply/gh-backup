#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
TEST_BIN_DIR="${TMP_DIR}/bin"
TEST_LOG_DIR="${TMP_DIR}/logs"
TEST_DATA_DIR="${TMP_DIR}/data"
TEST_HELPER="${TMP_DIR}/helper.py"

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
  shift 2
  case "$1 $2" in
    "rev-parse --is-bare-repository")
      echo true
      exit 0
      ;;
    "remote set-url"|"remote update"|"lfs fetch")
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

write_helper() {
  cat > "${TEST_HELPER}" <<'EOF'
#!/usr/bin/env python3
import os
import sys

scenario = os.environ.get("TEST_HELPER_SCENARIO", "success")

if scenario == "success":
    sys.stdout.write("public-repo\thttps://github.com/octocat/public-repo.git\ttrue\n")
    sys.stdout.write("private-repo\thttps://github.com/octocat/private-repo.git\tfalse\n")
    sys.exit(0)

sys.stderr.write("GitHub repo discovery failed (403): Resource protected by organization SAML enforcement.\n")
sys.exit(1)
EOF

  chmod +x "${TEST_HELPER}"
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
    GITHUB_API_HELPER="${TEST_HELPER}" \
    GHORG_INCLUDE_SUBMODULES="true" \
    bash "${ROOT_DIR}/scripts/run-backup.sh" >"${output_file}" 2>&1 || fail "Expected success scenario to pass"
}

run_backup_expect_failure() {
  local output_file="$1"
  if env \
    PATH="${TEST_BIN_DIR}:${PATH}" \
    HOME="${TMP_DIR}/home" \
    TEST_LOG_DIR="${TEST_LOG_DIR}" \
    TEST_HELPER_SCENARIO="failure" \
    GITHUB_OWNER="octocat" \
    GITHUB_TOKEN="ghp_testtoken" \
    BACKUP_DATA_DIR="${TEST_DATA_DIR}" \
    GITHUB_API_HELPER="${TEST_HELPER}" \
    bash "${ROOT_DIR}/scripts/run-backup.sh" >"${output_file}" 2>&1; then
    fail "Expected failure scenario to fail"
  fi
}

main() {
  reset_logs
  write_stubs
  write_helper

  run_backup_expect_success
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/public-repo.git ${TEST_DATA_DIR}/mirrors/octocat_backup/public-repo"
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/private-repo.git ${TEST_DATA_DIR}/mirrors/octocat_backup/private-repo"
  assert_contains "${TEST_LOG_DIR}/git.log" "clone --mirror https://github.com/octocat/public-repo.wiki.git ${TEST_DATA_DIR}/mirrors/octocat_backup/public-repo.wiki.git"
  assert_contains "${TEST_LOG_DIR}/ghorg.log" "clone my-org --scm=github --clone-type=org"

  reset_logs
  write_stubs
  write_helper
  run_backup_expect_failure "${TMP_DIR}/failure-output.log"
  assert_contains "${TMP_DIR}/failure-output.log" "GitHub repo discovery failed"
}

main "$@"
