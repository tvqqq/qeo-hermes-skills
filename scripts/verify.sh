#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HERMES_HOME_VALUE="${HERMES_HOME:-/opt/hermes/data}"
PROFILES="all"
REPO_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-only) REPO_ONLY=1; shift ;;
    --hermes-home) HERMES_HOME_VALUE="$2"; shift 2 ;;
    --profiles) PROFILES="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

fail() { echo "verify: $*" >&2; exit 1; }
info() { echo "verify: $*"; }

SKILL="$REPO_ROOT/skills/qeo-story"
PLUGIN="$REPO_ROOT/plugins/qeo-shortcuts"
[[ -f "$SKILL/SKILL.md" ]] || fail "missing qeo-story/SKILL.md"
[[ -f "$PLUGIN/plugin.yaml" ]] || fail "missing qeo-shortcuts/plugin.yaml"
grep -Eq '^name:[[:space:]]+qeo-story[[:space:]]*$' "$SKILL/SKILL.md" || fail "qeo-story frontmatter name mismatch"
grep -Eq '^[[:space:]]*name:[[:space:]]+qeo-shortcuts[[:space:]]*$' "$PLUGIN/plugin.yaml" || fail "qeo-shortcuts manifest name mismatch"
PYTHON_BIN="${QEO_VERIFY_PYTHON:-}"
if [[ -z "$PYTHON_BIN" && -x "$HERMES_HOME_VALUE/hermes-agent/venv/bin/python" ]]; then
  PYTHON_BIN="$HERMES_HOME_VALUE/hermes-agent/venv/bin/python"
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m py_compile \
  "$SKILL/scripts/image_utils.py" \
  "$SKILL/scripts/presets.py" \
  "$SKILL/scripts/render_story.py" \
  "$PLUGIN/__init__.py" \
  "$PLUGIN/handlers/story.py"

"$PYTHON_BIN" - <<'PY'
from PIL import Image
print(f"verify: Pillow {Image.__version__}")
PY

grep -q '"qeostory"' "$PLUGIN/handlers/story.py" || fail "qeostory command registration not found"
info "repository checks passed"

if [[ "$REPO_ONLY" -eq 1 ]]; then
  exit 0
fi

[[ -f "$HERMES_HOME_VALUE/skills/qeo-story/SKILL.md" ]] || fail "default profile missing qeo-story"

selected_profiles=()
if [[ "$PROFILES" == "all" ]]; then
  if [[ -d "$HERMES_HOME_VALUE/profiles" ]]; then
    while IFS= read -r dir; do
      selected_profiles+=("$(basename "$dir")")
    done < <(find "$HERMES_HOME_VALUE/profiles" -mindepth 1 -maxdepth 1 -type d ! -name ".*" | sort)
  fi
else
  IFS=',' read -r -a selected_profiles <<< "$PROFILES"
fi
for profile in "${selected_profiles[@]}"; do
  [[ -z "$profile" ]] && continue
  path="$HERMES_HOME_VALUE/profiles/$profile/skills/qeo-story/SKILL.md"
  [[ -f "$path" ]] || fail "profile $profile missing qeo-story"
done

HERMES_BIN_VALUE="${HERMES_BIN:-}"
if [[ -z "$HERMES_BIN_VALUE" ]] && [[ -x /opt/hermes/.local/bin/hermes ]]; then
  HERMES_BIN_VALUE="/opt/hermes/.local/bin/hermes"
fi

if [[ -n "$HERMES_BIN_VALUE" ]]; then
  RUNTIME_HOME="${HERMES_RUNTIME_HOME:-/opt/hermes}"
  RUNTIME_USER="${HERMES_RUN_USER:-hermes}"
  if [[ "$(id -u)" -eq 0 ]] && command -v sudo >/dev/null 2>&1 && id "$RUNTIME_USER" >/dev/null 2>&1; then
    sudo -n -u "$RUNTIME_USER" env HOME="$RUNTIME_HOME" HERMES_HOME="$HERMES_HOME_VALUE"       "$HERMES_BIN_VALUE" plugins doctor "$HERMES_HOME_VALUE/plugins/qeo-shortcuts" --ci
  else
    env HOME="$RUNTIME_HOME" HERMES_HOME="$HERMES_HOME_VALUE"       "$HERMES_BIN_VALUE" plugins doctor "$HERMES_HOME_VALUE/plugins/qeo-shortcuts" --ci
  fi
else
  info "Hermes CLI unavailable; runtime plugin doctor skipped"
fi

info "runtime filesystem checks passed"
