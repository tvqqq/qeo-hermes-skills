#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL="${1:-}"
[[ -n "$SKILL" ]] || { echo "Usage: deploy.sh qeo-<skill> [options]" >&2; exit 2; }
shift

HERMES_HOME_VALUE="${HERMES_HOME:-/opt/hermes/data}"
PROFILES="all"
NO_RESTART=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hermes-home) HERMES_HOME_VALUE="$2"; shift 2 ;;
    --profiles) PROFILES="$2"; shift 2 ;;
    --no-restart) NO_RESTART=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "$SKILL" == qeo-* ]] || { echo "Skill must start with qeo-" >&2; exit 2; }
"$SCRIPT_DIR/verify.sh" --repo-only

BACKUP_ROOT="$HERMES_HOME_VALUE/backups/qeo-hermes-skills/$(date +%Y%m%dT%H%M%S)-$$"
mkdir -p "$BACKUP_ROOT"
touch "$BACKUP_ROOT/.backed" "$BACKUP_ROOT/.created"
PLUGIN_SOURCE="$REPO_ROOT/plugins/qeo-shortcuts"
PLUGIN_TARGET="$HERMES_HOME_VALUE/plugins/qeo-shortcuts"

record_target() {
  local target="$1"
  local rel="${target#"$HERMES_HOME_VALUE"/}"
  local backup="$BACKUP_ROOT/$rel"
  mkdir -p "$(dirname "$backup")"
  if [[ -e "$target" ]]; then
    cp -R "$target" "$backup"
    printf '%s\n' "$rel" >> "$BACKUP_ROOT/.backed"
  else
    printf '%s\n' "$rel" >> "$BACKUP_ROOT/.created"
  fi
}

restore_backup() {
  local rel target backup
  if [[ -f "$BACKUP_ROOT/.created" ]]; then
    while IFS= read -r rel; do
      [[ -z "$rel" ]] && continue
      target="$HERMES_HOME_VALUE/$rel"
      rm -rf "$target"
    done < "$BACKUP_ROOT/.created"
  fi
  if [[ -f "$BACKUP_ROOT/.backed" ]]; then
    while IFS= read -r rel; do
      [[ -z "$rel" ]] && continue
      target="$HERMES_HOME_VALUE/$rel"
      backup="$BACKUP_ROOT/$rel"
      rm -rf "$target"
      mkdir -p "$(dirname "$target")"
      cp -R "$backup" "$target"
      if [[ -n "${OWNER:-}" ]]; then
        chown -R "$OWNER" "$target"
      fi
    done < "$BACKUP_ROOT/.backed"
  fi
}

OWNER="${QEO_DEPLOY_OWNER-hermes:hermes}"
RUNTIME_HOME="${HERMES_RUNTIME_HOME:-/opt/hermes}"
RUNTIME_USER="${HERMES_RUN_USER:-hermes}"

runtime_exec() {
  if [[ "$(id -u)" -eq 0 ]] && command -v sudo >/dev/null 2>&1 && id "$RUNTIME_USER" >/dev/null 2>&1; then
    sudo -n -u "$RUNTIME_USER" env HOME="$RUNTIME_HOME" HERMES_HOME="$HERMES_HOME_VALUE" "$@"
  else
    env HOME="$RUNTIME_HOME" HERMES_HOME="$HERMES_HOME_VALUE" "$@"
  fi
}

on_error() {
  local status=$?
  trap - ERR
  echo "Deployment command failed; restoring backup" >&2
  restore_backup || true
  exit "$status"
}
trap on_error ERR

record_target "$PLUGIN_TARGET"
PLUGIN_STAGE="${PLUGIN_TARGET}.qeo-stage.$$"
rm -rf "$PLUGIN_STAGE"
mkdir -p "$(dirname "$PLUGIN_TARGET")"
cp -R "$PLUGIN_SOURCE" "$PLUGIN_STAGE"
[[ -f "$PLUGIN_STAGE/plugin.yaml" ]] || { echo "Plugin staging validation failed" >&2; restore_backup; exit 1; }
rm -rf "$PLUGIN_TARGET"
mv "$PLUGIN_STAGE" "$PLUGIN_TARGET"
if [[ -n "$OWNER" ]]; then
  chown -R "$OWNER" "$PLUGIN_TARGET"
fi

QEO_BACKUP_ROOT="$BACKUP_ROOT" QEO_DEPLOY_OWNER="$OWNER" \
  "$SCRIPT_DIR/deploy-skill.sh" "$SKILL" \
  --hermes-home "$HERMES_HOME_VALUE" --profiles "$PROFILES"

REQ="$REPO_ROOT/skills/$SKILL/requirements.txt"
HERMES_PYTHON_VALUE="${HERMES_PYTHON:-}"
if [[ -z "$HERMES_PYTHON_VALUE" && -x "$HERMES_HOME_VALUE/hermes-agent/venv/bin/python" ]]; then
  HERMES_PYTHON_VALUE="$HERMES_HOME_VALUE/hermes-agent/venv/bin/python"
fi
if [[ -n "$HERMES_PYTHON_VALUE" && -f "$REQ" ]]; then
  runtime_exec "$HERMES_PYTHON_VALUE" -m pip install -r "$REQ"
fi

set +e
if [[ -n "${QEO_VERIFY_COMMAND:-}" ]]; then
  sh -c "$QEO_VERIFY_COMMAND"
  VERIFY_STATUS=$?
else
  "$SCRIPT_DIR/verify.sh" --hermes-home "$HERMES_HOME_VALUE" --profiles "$PROFILES"
  VERIFY_STATUS=$?
fi
set -e

if [[ "$VERIFY_STATUS" -ne 0 ]]; then
  echo "Post-deploy verification failed; restoring backup" >&2
  restore_backup
  exit "$VERIFY_STATUS"
fi

if [[ "$NO_RESTART" -eq 0 ]]; then
  HERMES_BIN_VALUE="${HERMES_BIN:-/opt/hermes/.local/bin/hermes}"
  RUNTIME_HOME="${HERMES_RUNTIME_HOME:-/opt/hermes}"
  if [[ ! -x "$HERMES_BIN_VALUE" ]]; then
    echo "Hermes CLI not executable: $HERMES_BIN_VALUE" >&2
    restore_backup
    exit 1
  fi

  set +e
  runtime_exec "$HERMES_BIN_VALUE" gateway restart
  RESTART_STATUS=$?
  set -e
  if [[ "$RESTART_STATUS" -ne 0 ]]; then
    echo "Gateway restart failed; restoring backup" >&2
    restore_backup
    runtime_exec "$HERMES_BIN_VALUE" gateway restart || true
    exit "$RESTART_STATUS"
  fi

  sleep "${QEO_GATEWAY_HEALTH_DELAY:-2}"
  set +e
  runtime_exec "$HERMES_BIN_VALUE" gateway status >/dev/null
  HEALTH_STATUS=$?
  set -e
  if [[ "$HEALTH_STATUS" -ne 0 ]]; then
    echo "Gateway health check failed; restoring backup" >&2
    restore_backup
    runtime_exec "$HERMES_BIN_VALUE" gateway restart || true
    exit "$HEALTH_STATUS"
  fi
fi

trap - ERR
printf 'deploy: skill=%s\n' "$SKILL"
printf 'deploy: backup_root=%s\n' "$BACKUP_ROOT"
printf 'deploy: profiles=%s\n' "$PROFILES"
