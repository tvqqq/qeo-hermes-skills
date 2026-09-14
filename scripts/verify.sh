#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HERMES_HOME_VALUE="${HERMES_HOME:-/opt/hermes/data}"
PROFILES="all"
VERIFY_SKILL=""
REPO_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-only) REPO_ONLY=1; shift ;;
    --hermes-home) HERMES_HOME_VALUE="$2"; shift 2 ;;
    --profiles) PROFILES="$2"; shift 2 ;;
    --skill) VERIFY_SKILL="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

fail() { echo "verify: $*" >&2; exit 1; }
info() { echo "verify: $*"; }

STORY_SKILL="$REPO_ROOT/skills/qeo-story"
VOICE_SKILL="$REPO_ROOT/skills/qeo-voice"
VOICE_WORKER="$REPO_ROOT/workers/qeo-voice"
PLUGIN="$REPO_ROOT/plugins/qeo-shortcuts"
[[ -f "$STORY_SKILL/SKILL.md" ]] || fail "missing qeo-story/SKILL.md"
[[ -f "$VOICE_SKILL/SKILL.md" ]] || fail "missing qeo-voice/SKILL.md"
[[ -f "$VOICE_WORKER/voices.json" ]] || fail "missing qeo-voice voices.json"
[[ -f "$PLUGIN/plugin.yaml" ]] || fail "missing qeo-shortcuts/plugin.yaml"

grep -Eq '^name:[[:space:]]+qeo-story[[:space:]]*$' "$STORY_SKILL/SKILL.md" || fail "qeo-story frontmatter name mismatch"
grep -Eq '^name:[[:space:]]+qeo-voice[[:space:]]*$' "$VOICE_SKILL/SKILL.md" || fail "qeo-voice frontmatter name mismatch"
grep -Eq '^[[:space:]]*name:[[:space:]]+qeo-shortcuts[[:space:]]*$' "$PLUGIN/plugin.yaml" || fail "qeo-shortcuts manifest name mismatch"

PYTHON_BIN="${QEO_VERIFY_PYTHON:-python3}"
"$PYTHON_BIN" -m py_compile \
  "$STORY_SKILL/scripts/image_utils.py" \
  "$STORY_SKILL/scripts/presets.py" \
  "$STORY_SKILL/scripts/render_story.py" \
  "$PLUGIN/__init__.py" \
  "$PLUGIN/handlers/story.py" \
  "$PLUGIN/handlers/voice.py" \
  "$VOICE_WORKER/registry.py" \
  "$VOICE_WORKER/engine.py" \
  "$VOICE_WORKER/app.py" \
  "$VOICE_WORKER/healthcheck.py"

grep -qi '^Pillow' "$STORY_SKILL/requirements.txt" || fail "qeo-story requirements must declare Pillow"
grep -q '"qeostory"' "$PLUGIN/handlers/story.py" || fail "qeostory command registration not found"
grep -q '"qeovoice"' "$PLUGIN/handlers/voice.py" || fail "qeovoice command registration not found"
"$PYTHON_BIN" - "$VOICE_WORKER/voices.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
assert data.get("default") == "chi-chi", "default voice must be chi-chi"
assert "chi-chi" in data.get("voices", {}), "chi-chi registry entry missing"
assert data["voices"]["chi-chi"].get("reference") == "chi-chi/reference.wav"
PY

if git -C "$REPO_ROOT" ls-files 'workers/qeo-voice/*' | grep -Eqi '\.(wav|mp3|ogg|opus)$'; then
  fail "private qeo-voice audio must not be tracked"
fi

if grep -Eqi 'vieneu|workers/qeo-voice' \
  "$SCRIPT_DIR/deploy.sh" "$SCRIPT_DIR/deploy-skill.sh" "$SCRIPT_DIR/install.sh"; then
  fail "normal UpCloud deploy scripts must not contain voice compute"
fi

info "repository checks passed"
[[ "$REPO_ONLY" -eq 1 ]] && exit 0

if [[ -n "$VERIFY_SKILL" && "$VERIFY_SKILL" != qeo-* ]]; then
  fail "--skill must start with qeo-"
fi
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

verify_runtime_skill() {
  local skill="$1" profile path
  [[ -f "$HERMES_HOME_VALUE/skills/$skill/SKILL.md" ]] || fail "default profile missing $skill"
  for profile in "${selected_profiles[@]}"; do
    [[ -z "$profile" ]] && continue
    path="$HERMES_HOME_VALUE/profiles/$profile/skills/$skill/SKILL.md"
    [[ -f "$path" ]] || fail "profile $profile missing $skill"
  done
}

if [[ -n "$VERIFY_SKILL" ]]; then
  verify_runtime_skill "$VERIFY_SKILL"
else
  verify_runtime_skill qeo-story
  verify_runtime_skill qeo-voice
fi
HERMES_BIN_VALUE="${HERMES_BIN:-}"
if [[ -z "$HERMES_BIN_VALUE" && -x /opt/hermes/.local/bin/hermes ]]; then
  HERMES_BIN_VALUE="/opt/hermes/.local/bin/hermes"
fi

if [[ -n "$HERMES_BIN_VALUE" ]]; then
  RUNTIME_HOME="${HERMES_RUNTIME_HOME:-/opt/hermes}"
  RUNTIME_USER="${HERMES_RUN_USER:-hermes}"
  if [[ "$(id -u)" -eq 0 ]] && command -v sudo >/dev/null 2>&1 && id "$RUNTIME_USER" >/dev/null 2>&1; then
    sudo -n -u "$RUNTIME_USER" env HOME="$RUNTIME_HOME" HERMES_HOME="$HERMES_HOME_VALUE" \
      "$HERMES_BIN_VALUE" plugins doctor "$HERMES_HOME_VALUE/plugins/qeo-shortcuts" --ci
  else
    env HOME="$RUNTIME_HOME" HERMES_HOME="$HERMES_HOME_VALUE" \
      "$HERMES_BIN_VALUE" plugins doctor "$HERMES_HOME_VALUE/plugins/qeo-shortcuts" --ci
  fi
else
  info "Hermes CLI unavailable; runtime plugin doctor skipped"
fi

info "runtime filesystem checks passed"
