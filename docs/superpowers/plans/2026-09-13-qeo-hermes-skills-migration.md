# Qeo Hermes Skills Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the proven `qeo-story` and `/qeostory` implementation from the Hermes VPS into `tvqqq/qeo-hermes-skills`, add repeatable deployment/rollback tooling, and document the standard workflow for future `qeo-*` skills.

**Architecture:** GitHub becomes the canonical source. `skills/qeo-story` owns the renderer, `plugins/qeo-shortcuts` owns Telegram-native fast paths, and repository scripts deploy validated copies into the default Hermes profile plus selected multiplex profiles. Deployment backs up affected targets, stages replacements, validates them, swaps them into place, verifies Hermes discovery/plugin health, restarts the gateway once, and restores the backup if post-deploy validation fails.

**Tech Stack:** Python 3.11, Pillow `>=10,<14`, Python `unittest`, Bash, Hermes Agent native skill/plugin APIs, Telegram gateway adapter.

**Spec:** `docs/superpowers/specs/2026-09-13-qeo-hermes-skills-repository-design.md`

## Global Constraints

- Every Qeo-owned skill name uses `qeo-<skill-name>` in lowercase kebab-case.
- Telegram shortcuts start with `/qeo`, use lowercase characters, and contain no hyphens.
- `qeo-story` keeps PNG 1080x1920 output, default `qeo-green`, source aspect ratio, no default crop/stretch, footer `@QeoQeo`.
- Supported presets remain `qeo-green`, `qeo`, `mango`, `mojito`, `stellar`, `midnight-city`.
- Runtime code prefers `HERMES_HOME`, falling back to `/opt/hermes/data` only when absent.
- `--profiles all` discovers profile directories dynamically; no public source hardcodes profile names.
- Deployment never modifies unrelated Hermes skills, plugins, or configuration.
- Existing production targets are backed up before replacement.
- Gateway restarts only after staged validation passes; rollback restarts only after restoration.
- No CI/CD, release automation, containers, extra package manager, or framework is added in this migration.

---

## File Map

- `skills/qeo-story/SKILL.md` — instructions aligned with the actual native Telegram flow.
- `skills/qeo-story/requirements.txt` — `Pillow>=10,<14`.
- `skills/qeo-story/scripts/__init__.py` — package marker.
- `skills/qeo-story/scripts/image_utils.py` — image sizing, gradient, mask, font, downscale helpers.
- `skills/qeo-story/scripts/presets.py` — approved gradient presets.
- `skills/qeo-story/scripts/render_story.py` — deterministic renderer CLI/API.
- `skills/qeo-story/references/style-guide.md` — visual constants.
- `plugins/qeo-shortcuts/plugin.yaml` — Hermes plugin manifest.
- `plugins/qeo-shortcuts/__init__.py` — registration only.
- `plugins/qeo-shortcuts/handlers/__init__.py` — package marker.
- `plugins/qeo-shortcuts/handlers/story.py` — `/qeostory` native handler.
- `scripts/install.sh` — first-time bootstrap wrapper.
- `scripts/deploy-skill.sh` — deploy one skill to default + selected profiles; no restart.
- `scripts/deploy.sh` — backup/deploy/verify/restart/rollback orchestrator.
- `scripts/verify.sh` — read-only repository/runtime validation.
- `tests/test_story_renderer.py` — renderer contract tests.
- `tests/test_qeo_shortcuts_story.py` — handler tests.
- `tests/test_deploy_scripts.py` — deployment/profile/rollback tests.
- `README.md`, `docs/ADDING-A-QEO-SKILL.md`, `docs/DEPLOYMENT.md`, `docs/TELEGRAM-COMMANDS.md` — operational docs.

---

### Task 1: Migrate and Verify `qeo-story`

**Files:**
- Create all files under `skills/qeo-story/` listed above.
- Create `tests/test_story_renderer.py`.

**Interfaces:**
- Produces `render_story(input_path, output_path, options=None) -> pathlib.Path` and `StoryRenderOptions`.
- CLI accepts `--input`, `--output`, `--preset`, `--footer`, `--safe-margin`, `--card-radius`, `--list-presets`.

- [ ] **Step 1: Write failing renderer tests**

Create `tests/test_story_renderer.py` using `unittest`, `tempfile`, `importlib.util`, and Pillow. Tests must cover:

```python
with Image.open(output) as image:
    self.assertEqual(image.format, "PNG")
    self.assertEqual(image.size, (1080, 1920))
```

Also assert the preset set equals:

```python
{"qeo-green", "qeo", "mango", "mojito", "stellar", "midnight-city"}
```

Add tests for unknown preset rejection, `fit_inside()` preserving aspect ratio, and unsupported input format rejection.

- [ ] **Step 2: Run the tests and confirm failure because source files are absent**

Run:

```bash
python3 -m unittest tests.test_story_renderer -v
```

Expected: import/file failure.

- [ ] **Step 3: Copy the proven VPS renderer into the repository**

Copy the current working versions of `requirements.txt`, `scripts/__init__.py`, `scripts/image_utils.py`, `scripts/presets.py`, `scripts/render_story.py`, and `references/style-guide.md` without changing visual constants.

- [ ] **Step 4: Rewrite `SKILL.md` to match real runtime behavior**

Keep `name: qeo-story` and the media tags. Remove obsolete statements that `/qeostory` needs an agent terminal tool or must emit `MEDIA:`. Document two flows:

```text
Telegram fast path: image + /qeostory [preset] -> qeo-shortcuts native handler
Manual/non-gateway path: python render_story.py --input ... --output ...
```

Keep the rule that an agent must not claim success unless an output file was actually produced.

- [ ] **Step 5: Run renderer validation**

Run:

```bash
python3 -m unittest tests.test_story_renderer -v
python3 skills/qeo-story/scripts/render_story.py --list-presets --input ignored --output ignored
```

Expected: tests pass; CLI lists all six approved presets and exits 0.

- [ ] **Step 6: Commit**

```bash
git add skills/qeo-story tests/test_story_renderer.py
git commit -m "feat: migrate qeo-story skill"
```

---

### Task 2: Refactor the Working `/qeostory` Native Fast Path

**Files:**
- Create `plugins/qeo-shortcuts/plugin.yaml`.
- Create `plugins/qeo-shortcuts/__init__.py`.
- Create `plugins/qeo-shortcuts/handlers/__init__.py`.
- Create `plugins/qeo-shortcuts/handlers/story.py`.
- Create `tests/test_qeo_shortcuts_story.py`.

**Interfaces:**
- Root plugin exposes `register(ctx) -> None`.
- Story module exposes `register_story(ctx) -> None`.
- Handler consumes the Hermes event/gateway by duck typing and returns a `skip` action only after it owns the request.

- [ ] **Step 1: Write failing handler tests**

Use `unittest.mock` to test:

```python
_extract_preset("mango") == "mango"
_extract_preset("unknown") is None
```

With `HERMES_HOME=/tmp/hermes`, assert profile path resolution is:

```text
/tmp/hermes/profiles/qeo-personal/skills/qeo-story
```

and default profile path is:

```text
/tmp/hermes/skills/qeo-story
```

Also test that `/qeostory`, `/qeo_story`, and `/qeo-story` match for compatibility; success schedules image send and returns `qeostory-rendered`; render failure schedules text error and returns `qeostory-render-failed`; no attached image returns `None` so the slash help handler can answer.

- [ ] **Step 2: Run the tests and confirm failure because plugin source is absent**

```bash
python3 -m unittest tests.test_qeo_shortcuts_story -v
```

- [ ] **Step 3: Implement plugin manifest and registration shell**

Use manifest:

```yaml
name: qeo-shortcuts
version: 1.0.1
description: Telegram shortcuts for Qeo custom skills
provides_hooks:
  - pre_gateway_dispatch
```

Keep root `__init__.py` minimal:

```python
from .handlers.story import register_story


def register(ctx):
    register_story(ctx)
```

- [ ] **Step 4: Move the proven handler into `handlers/story.py`**

Port current VPS behavior, but resolve runtime root with:

```python
Path(os.environ.get("HERMES_HOME") or "/opt/hermes/data")
```

Keep `sys.executable` subprocess rendering, Pillow output validation, same-topic metadata, `send_image_file`, and `pre_gateway_dispatch` skip behavior. Register visible Telegram command `qeostory`.

- [ ] **Step 5: Run handler tests and compile plugin source**

```bash
python3 -m unittest tests.test_qeo_shortcuts_story -v
python3 -m py_compile plugins/qeo-shortcuts/__init__.py plugins/qeo-shortcuts/handlers/*.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/qeo-shortcuts tests/test_qeo_shortcuts_story.py
git commit -m "feat: migrate qeostory gateway shortcut"
```

---

### Task 3: Add Profile-Aware Deployment, Verification, and Rollback

**Files:**
- Create `scripts/deploy-skill.sh`.
- Create `scripts/verify.sh`.
- Create `scripts/deploy.sh`.
- Create `scripts/install.sh`.
- Create `tests/test_deploy_scripts.py`.

**Interfaces:**

```text
scripts/deploy-skill.sh qeo-story --hermes-home PATH --profiles all
scripts/deploy-skill.sh qeo-story --hermes-home PATH --profiles qeo-personal,qeo-stock
scripts/verify.sh --repo-only
scripts/verify.sh --hermes-home PATH --profiles all
scripts/deploy.sh qeo-story --hermes-home PATH --profiles all [--no-restart]
scripts/install.sh qeo-story --hermes-home PATH --profiles all
```

`QEO_DEPLOY_OWNER=hermes:hermes` is the production default; empty value skips `chown` in test environments. `deploy-skill.sh` never restarts. `deploy.sh` owns plugin deployment, restart, and rollback.

- [ ] **Step 1: Write failing deployment tests against a temporary Hermes home**

Create a fake layout:

```text
hermes/
├── skills/qeo-story/old.txt
└── profiles/
    ├── qeo-personal/skills/qeo-story/old.txt
    └── qeo-stock/skills/
```

Run scripts with `QEO_DEPLOY_OWNER=""` and assert:

- default + discovered profiles receive the repo skill;
- existing targets are backed up under `backups/qeo-hermes-skills/<timestamp>/`;
- `--profiles qeo-personal` updates only default + that profile;
- missing/non-`qeo-` skill names fail before modification;
- plugin is copied by `deploy.sh`;
- failed post-deploy verification restores old skill/plugin content;
- `install.sh` delegates to `deploy.sh` instead of duplicating copy logic.

Support `QEO_VERIFY_COMMAND` only for tests so a deterministic failing verifier can exercise rollback.

- [ ] **Step 2: Run tests and confirm failure because scripts are absent**

```bash
python3 -m unittest tests.test_deploy_scripts -v
```

- [ ] **Step 3: Implement `deploy-skill.sh`**

Use `set -euo pipefail`. Validation order:

```text
skill starts qeo-
source exists
SKILL.md exists
frontmatter name equals directory name
Hermes target directories are safe to create
profile selector is valid
```

For each target: back up if present, copy into sibling staging directory, verify staged `SKILL.md`, then replace target. No gateway restart.

- [ ] **Step 4: Implement `verify.sh`**

Repository checks:

```text
qeo-story SKILL.md exists and name matches
Python files compile
Pillow imports
qeo-shortcuts manifest exists
Telegram handler registers qeostory
```

Runtime checks, when Hermes runtime is available:

```text
plugin doctor passes
/qeo-story is discovered
resolve_skill_command_key("qeo_story") resolves to /qeo-story
selected multiplex profiles contain qeo-story
```

When Hermes modules are unavailable locally, report those runtime-only checks as skipped while still failing on repository/filesystem errors.

- [ ] **Step 5: Implement `deploy.sh` orchestration**

Exact lifecycle:

```text
verify repository
create one backup root
backup existing plugin
call deploy-skill.sh
stage + replace qeo-shortcuts
install skill requirements in Hermes venv when present
run post-deploy verify
restore backup and fail if verify fails
restart gateway once unless --no-restart
verify gateway health
restore backup + restart once more if gateway health fails
```

Allow `HERMES_PYTHON` and `HERMES_BIN` overrides; otherwise derive executables from the Hermes environment. Do not change unrelated config.

- [ ] **Step 6: Implement thin `install.sh` wrapper**

It checks required local commands/repository paths, prints target/profile selection, then executes `deploy.sh` with the same arguments. No duplicate backup/copy/restart logic.

- [ ] **Step 7: Run deployment tests and repository verification**

```bash
python3 -m unittest tests.test_deploy_scripts -v
scripts/verify.sh --repo-only
```

Expected: all tests and repository checks pass.

- [ ] **Step 8: Commit**

```bash
git add scripts tests/test_deploy_scripts.py
git commit -m "feat: add validated deploy and rollback workflow"
```

---

### Task 4: Add Documentation for Future `qeo-*` Skills

**Files:**
- Create `README.md`.
- Create `docs/ADDING-A-QEO-SKILL.md`.
- Create `docs/DEPLOYMENT.md`.
- Create `docs/TELEGRAM-COMMANDS.md`.

**Interfaces:** documentation must match the implemented script flags exactly.

- [ ] **Step 1: Write `README.md`**

Sections in order:

```text
Qeo Hermes Skills
Purpose
Repository layout
Naming convention
Quick start
Current skills
Deployment summary
Documentation links
```

Quick start includes:

```bash
./scripts/verify.sh --repo-only
sudo ./scripts/deploy.sh qeo-story --profiles all
```

State explicitly that GitHub is source of truth and production copies are deployment artifacts.

- [ ] **Step 2: Write `docs/ADDING-A-QEO-SKILL.md`**

Include an execution-model decision table:

```text
Agent skill — LLM reasoning or Hermes tools are required
Deterministic utility — repeatable local transform/parser/renderer
Telegram native fast-path — deterministic Telegram command should bypass LLM/tool availability
```

Document lifecycle:

```text
choose qeo- name
create minimum package
write SKILL.md
add deterministic script only when required
add qeo-shortcuts handler only when a Telegram fast-path is required
write targeted unittest coverage
run verify.sh --repo-only
deploy with deploy.sh
run Telegram smoke after gateway behavior changes
```

Include mappings:

```text
qeo-story -> /qeostory
qeo-stock-chart -> /qeostockchart
```

- [ ] **Step 3: Write `docs/DEPLOYMENT.md`**

Document `HERMES_HOME` precedence, default/multiplex target paths, `--profiles all`, backup path, responsibilities of the four scripts, production examples, rollback semantics, and the live Telegram smoke requirement.

- [ ] **Step 4: Write `docs/TELEGRAM-COMMANDS.md`**

Explain:

```text
canonical skill identity: qeo-story
canonical Hermes slash form: /qeo-story
Telegram compact shortcut: /qeostory
```

State that `qeo-shortcuts` is shared infrastructure and normal agent skills do not need Telegram shortcuts.

- [ ] **Step 5: Verify docs match executable flags**

```bash
grep -R --line-number -- '--profiles\|--hermes-home\|--no-restart' README.md docs scripts
scripts/verify.sh --repo-only
```

Expected: docs use only implemented flags; verification passes.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/ADDING-A-QEO-SKILL.md docs/DEPLOYMENT.md docs/TELEGRAM-COMMANDS.md
git commit -m "docs: add qeo skill authoring and deployment guides"
```

---

### Task 5: Final Review and Production Sync

**Files:** review all files from Tasks 1-4. Introduce no new behavior unless verification finds a defect.

**Interfaces:** produces a VPS deployment reproducible from the GitHub checkout.

- [ ] **Step 1: Run the complete validation suite**

```bash
python3 -m unittest discover -s tests -v
scripts/verify.sh --repo-only
python3 -m py_compile skills/qeo-story/scripts/*.py plugins/qeo-shortcuts/*.py plugins/qeo-shortcuts/handlers/*.py
```

Expected: all pass.

- [ ] **Step 2: Review diff and repository contents for scope and accidental environment-specific data**

```bash
git status --short
git diff --stat HEAD~4..HEAD
```

Manually confirm there are no credentials, chat IDs, tokens, or unrelated source files.

- [ ] **Step 3: Update or clone the repository on the VPS in a non-production source directory**

Use a normal operator-owned checkout such as `~/qeo-hermes-skills`. Production files under Hermes remain deployment targets only.

- [ ] **Step 4: Verify repository source on the VPS before deployment**

```bash
./scripts/verify.sh --repo-only
```

Expected: success before touching Hermes production paths.

- [ ] **Step 5: Deploy to all current profiles from the repository checkout**

```bash
sudo ./scripts/deploy.sh qeo-story --hermes-home /opt/hermes/data --profiles all
```

Expected: backup created, skill/plugin deployed, runtime verification passes, gateway restarts once, gateway health is running.

- [ ] **Step 6: Verify Hermes discovery**

Run the repository/runtime verification and confirm `/qeo-story` is discovered for default and selected multiplex profiles and `qeo_story` resolves to the canonical command.

- [ ] **Step 7: Perform required Telegram smoke**

Send a fresh image with caption:

```text
/qeostory
```

Then a fresh image with:

```text
/qeostory mango
```

Expected: both return PNG story images; default uses Qeo green, second uses Mango; neither asks to enable terminal/code tools.

- [ ] **Step 8: Report final state**

Report repository commit SHA deployed, profiles discovered/deployed, gateway PID/status, plugin doctor result, Hermes discovery result, and Telegram smoke result. Do not commit generated runtime logs.

- [ ] **Step 9: Create a focused correction commit only if final verification required a repository change**

If no source/docs/test correction is needed, do not create an empty commit.

---

## Plan Self-Review

**Spec coverage:** Tasks 1-5 cover canonical GitHub ownership, `qeo-*` naming, compact Telegram shortcuts, renderer migration, native fast-path, multiplex profiles, backup/rollback, `HERMES_HOME`, docs, and live Telegram verification.

**Placeholder scan:** No implementation step depends on unspecified future behavior. Test cases, script interfaces, expected outputs, and file responsibilities are explicit.

**Type/interface consistency:** `render_story(...)->Path`, `register(ctx)`, `register_story(ctx)`, script flags, and profile selectors are named consistently across tasks.

**Scope:** The plan migrates one proven skill plus its shared gateway integration and the minimal deployment/documentation foundation required to make GitHub authoritative. It introduces no unrelated skill or infrastructure.
