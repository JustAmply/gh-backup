#!/usr/bin/env bash
set -Eeuo pipefail

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

write_crontab() {
  local cron_file="/tmp/gh-backup.crontab"

  cat >"${cron_file}" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${BACKUP_CRON:-17 2 * * *} /usr/local/bin/run-backup.sh
EOF

  supercronic -test "${cron_file}" >/dev/null
  printf '%s\n' "${cron_file}"
}

validate_configuration() {
  /usr/local/bin/validate.sh
}

run_backup() {
  /usr/local/bin/run-backup.sh "$@"
}

run_startup_backup() {
  local status
  if run_backup; then
    return 0
  else
    status=$?
  fi
  printf 'WARNING: Startup backup failed with exit code %s; scheduler remains active\n' "${status}" >&2
}

start_scheduler() {
  local cron_file="$1"
  exec supercronic -split-logs "${cron_file}"
}

main() {
  local cron_file runner_python
  local mode="${1:-scheduler}"
  if [[ $# -gt 0 ]]; then
    shift
  fi

  case "${mode}" in
    scheduler|"")
      validate_configuration
      cron_file="$(write_crontab)"
      if bool_is_true "${RUN_ON_STARTUP:-true}"; then
        run_startup_backup
      fi
      start_scheduler "${cron_file}"
      ;;
    backup-now)
      exec /usr/local/bin/run-backup.sh "$@"
      ;;
    validate)
      exec /usr/local/bin/validate.sh "$@"
      ;;
    status|health)
      runner_python="${GH_BACKUP_RUNNER_PYTHON:-/opt/venv/bin/python3}"
      exec "${runner_python}" -m gh_backup.health "${mode}" "$@"
      ;;
    *)
      exec "${mode}" "$@"
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
