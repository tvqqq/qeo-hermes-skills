#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SH="${QEO_DEPLOY_SH:-$SCRIPT_DIR/deploy.sh}"

[[ $# -ge 1 ]] || { echo "Usage: install.sh qeo-<skill> [deploy options]" >&2; exit 2; }
[[ -x "$DEPLOY_SH" ]] || { echo "Deploy script is not executable: $DEPLOY_SH" >&2; exit 1; }

printf 'install: delegating to %s\n' "$DEPLOY_SH"
exec "$DEPLOY_SH" "$@"
