#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  echo "Usage: $0 qeo-<skill> [--hermes-home PATH] [--profiles all|a,b]" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage
SKILL="$1"
shift
HERMES_HOME_VALUE="${HERMES_HOME:-/opt/hermes/data}"
PROFILES="all"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hermes-home) [[ $# -ge 2 ]] || usage; HERMES_HOME_VALUE="$2"; shift 2 ;;
    --profiles) [[ $# -ge 2 ]] || usage; PROFILES="$2"; shift 2 ;;
    *) usage ;;
  esac
done

[[ "$SKILL" =~ ^qeo-[a-z0-9]+(-[a-z0-9]+)*$ ]] || {
  echo "Invalid Qeo skill name: $SKILL" >&2
  exit 2
}

SOURCE="$REPO_ROOT/skills/$SKILL"
SKILL_MD="$SOURCE/SKILL.md"
[[ -d "$SOURCE" && -f "$SKILL_MD" ]] || {
  echo "Missing skill source: $SOURCE" >&2
  exit 2
}

FRONTMATTER_NAME="$(awk '/^name:[[:space:]]*/ {print $2; exit}' "$SKILL_MD")"
[[ "$FRONTMATTER_NAME" == "$SKILL" ]] || {
  echo "SKILL.md name '$FRONTMATTER_NAME' does not match '$SKILL'" >&2
  exit 2
}

HERMES_HOME_VALUE="${HERMES_HOME_VALUE%/}"
mkdir -p "$HERMES_HOME_VALUE/skills"
BACKUP_ROOT="${QEO_BACKUP_ROOT:-$HERMES_HOME_VALUE/backups/qeo-hermes-skills/$(date +%Y%m%dT%H%M%S)-$$}"
mkdir -p "$BACKUP_ROOT"
BACKED_FILE="$BACKUP_ROOT/.backed"
CREATED_FILE="$BACKUP_ROOT/.created"
touch "$BACKED_FILE" "$CREATED_FILE"

TARGETS=("$HERMES_HOME_VALUE/skills/$SKILL")

add_profile_target() {
  local profile="$1"
  [[ "$profile" =~ ^[A-Za-z0-9_-]+$ ]] || {
    echo "Invalid profile name: $profile" >&2
    exit 2
  }
  TARGETS+=("$HERMES_HOME_VALUE/profiles/$profile/skills/$SKILL")
}

if [[ "$PROFILES" == "all" ]]; then
  if [[ -d "$HERMES_HOME_VALUE/profiles" ]]; then
    while IFS= read -r profile_dir; do
      add_profile_target "$(basename "$profile_dir")"
    done < <(find "$HERMES_HOME_VALUE/profiles" -mindepth 1 -maxdepth 1 -type d | sort)
  fi
elif [[ -n "$PROFILES" ]]; then
  IFS=',' read -r -a REQUESTED_PROFILES <<< "$PROFILES"
  for profile in "${REQUESTED_PROFILES[@]}"; do
    [[ -n "$profile" ]] || { echo "Empty profile selector" >&2; exit 2; }
    [[ -d "$HERMES_HOME_VALUE/profiles/$profile" ]] || {
      echo "Profile not found: $profile" >&2
      exit 2
    }
    add_profile_target "$profile"
  done
else
  echo "Profiles selector cannot be empty" >&2
  exit 2
fi

deploy_target() {
  local target="$1"
  local rel="${target#"$HERMES_HOME_VALUE"/}"
  local backup="$BACKUP_ROOT/$rel"
  local stage="${target}.qeo-stage.$$"

  mkdir -p "$(dirname "$target")" "$(dirname "$backup")"
  rm -rf "$stage"
  cp -R "$SOURCE" "$stage"

  local staged_name
  staged_name="$(awk '/^name:[[:space:]]*/ {print $2; exit}' "$stage/SKILL.md")"
  [[ "$staged_name" == "$SKILL" ]] || { echo "Staged skill validation failed: $target" >&2; exit 1; }

  if [[ -e "$target" ]]; then
    rm -rf "$backup"
    cp -R "$target" "$backup"
    printf '%s\n' "$rel" >> "$BACKED_FILE"
  else
    printf '%s\n' "$rel" >> "$CREATED_FILE"
  fi

  rm -rf "$target"
  mv "$stage" "$target"

  local owner="${QEO_DEPLOY_OWNER-hermes:hermes}"
  if [[ -n "$owner" ]]; then
    chown -R "$owner" "$target"
  fi
}

for target in "${TARGETS[@]}"; do
  deploy_target "$target"
done

printf 'skill=%s\n' "$SKILL"
printf 'backup_root=%s\n' "$BACKUP_ROOT"
printf 'targets=%s\n' "${#TARGETS[@]}"
