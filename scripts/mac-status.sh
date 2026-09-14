#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker/mac/compose.yml"
GIT_COMMON_DIR="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir)"
CANONICAL_REPO_ROOT="$(dirname "$GIT_COMMON_DIR")"
ENV_FILE="${QEO_MAC_ENV_FILE:-$CANONICAL_REPO_ROOT/.local/qeo-mac/config/mac.env}"

[[ "$(uname -s)" == "Darwin" ]] || { echo "mac-status.sh requires macOS" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "Missing mac.env: $ENV_FILE" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker CLI not found" >&2; exit 1; }

QEO_MAC_DATA_ROOT="${QEO_MAC_DATA_ROOT:-$CANONICAL_REPO_ROOT/.local/qeo-mac}"
export QEO_MAC_DATA_ROOT

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
