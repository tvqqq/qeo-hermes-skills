#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker/mac/compose.yml"
ENV_FILE="${QEO_MAC_ENV_FILE:-$HOME/Library/Application Support/QeoSkills/config/mac.env}"

[[ "$(uname -s)" == "Darwin" ]] || { echo "mac-up.sh requires macOS" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "Missing mac.env: $ENV_FILE" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker CLI not found" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

[[ -n "${QEO_VOICE_TOKEN:-}" ]] || { echo "QEO_VOICE_TOKEN is required" >&2; exit 1; }
[[ -n "${QEO_MAC_DATA_ROOT:-}" ]] || { echo "QEO_MAC_DATA_ROOT is required" >&2; exit 1; }
[[ -d "$QEO_MAC_DATA_ROOT" ]] || { echo "QEO_MAC_DATA_ROOT does not exist" >&2; exit 1; }
REFERENCE="$QEO_MAC_DATA_ROOT/voices/chi-chi/reference.wav"
[[ -f "$REFERENCE" ]] || { echo "Missing chi-chi/reference.wav: $REFERENCE" >&2; exit 1; }

PORT="${QEO_VOICE_PORT:-8765}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${COMPOSE[@]}" up -d --build

HEALTH_TIMEOUT="${QEO_MAC_HEALTH_TIMEOUT_SECONDS:-600}"
DEADLINE=$((SECONDS + HEALTH_TIMEOUT))
while (( SECONDS < DEADLINE )); do
  STATUS="$(${COMPOSE[@]} ps --format json qeo-voice-worker 2>/dev/null || true)"
  if printf '%s' "$STATUS" | grep -Eq '"Health"[[:space:]]*:[[:space:]]*"healthy"'; then
    break
  fi
  sleep 2
done

STATUS="$(${COMPOSE[@]} ps --format json qeo-voice-worker 2>/dev/null || true)"
if ! printf '%s' "$STATUS" | grep -Eq '"Health"[[:space:]]*:[[:space:]]*"healthy"'; then
  echo "qeo-voice-worker did not become healthy" >&2
  "${COMPOSE[@]}" ps qeo-voice-worker >&2 || true
  exit 1
fi
