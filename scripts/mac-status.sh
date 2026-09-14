#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker/mac/compose.yml"
ENV_FILE="${QEO_MAC_ENV_FILE:-$HOME/Library/Application Support/QeoSkills/config/mac.env}"

[[ "$(uname -s)" == "Darwin" ]] || { echo "mac-status.sh requires macOS" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "Missing mac.env: $ENV_FILE" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker CLI not found" >&2; exit 1; }

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
