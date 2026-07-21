#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASH_BIN_DIR="$(cd "$(dirname "${BASH}")" && pwd)"

cd "${ROOT_DIR}"
export PATH="${BASH_BIN_DIR}:${PATH}"

for shell_file in scripts/*.sh tests/*.sh; do
  "${BASH}" -n "${shell_file}"
done

python3 -m unittest discover -s tests -p 'test_*.py'
"${BASH}" tests/run-backup-regression.sh
