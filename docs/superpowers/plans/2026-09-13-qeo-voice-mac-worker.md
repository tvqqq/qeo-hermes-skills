# Qeo Voice Mac Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `qeo-voice` and Telegram `/qeovoice`, with all VieNeu v3 Turbo synthesis performed by a private Mac mini worker and no voice fallback on UpCloud.

**Architecture:** `qeo-shortcuts` handles `/qeovoice` on the UpCloud Hermes gateway and POSTs text over Tailscale to a long-lived Mac mini worker. The Mac worker keeps VieNeu v3 Turbo plus the default `Chi Chi` voice resident, returns WAV bytes, and UpCloud forwards the result as a Telegram native voice message. UpCloud owns routing only and never installs or executes VieNeu for this feature.

**Tech Stack:** Python 3.12 on the Mac worker, VieNeu `3.6.4`, FastAPI/Uvicorn, Python `unittest`, macOS LaunchAgent, Tailscale, Hermes Agent plugin hooks, Bash deployment scripts.

**Spec:** `docs/superpowers/specs/2026-09-13-qeo-voice-mac-worker-design.md`

## Global Constraints

- Canonical skill name is exactly `qeo-voice`; Telegram shortcut is exactly `/qeovoice`.
- `Chi Chi` is the default voice and uses VieNeu v3 Turbo with `denoise=true`, `use_ref_codes=true`, `temperature=0.55`, `top_k=20`, `top_p=0.90`, `repetition_penalty=1.20`, `max_chars=140`, `silence_p=0.10`, `crossfade_p=0.0`.
- Mac mini is the sole voice-compute authority. UpCloud is Telegram/Hermes routing only.
- No UpCloud fallback is permitted: no VieNeu Nano/Turbo, Edge TTS, Hermes default TTS, or another provider.
- Private reference audio is never committed to Git and is never deployed to UpCloud.
- Worker traffic is private Tailscale traffic; no public Mac endpoint is introduced.
- `QEO_VOICE_WORKER_URL`, `QEO_VOICE_TOKEN`, and `QEO_VOICE_TIMEOUT_SECONDS` are environment configuration, never repository secrets.
- `QEO_VOICE_TIMEOUT_SECONDS` defaults to 90 seconds.
- Worker inference is single-flight: a concurrent request returns HTTP `503` with `error=busy`; it does not start another model or queue indefinitely.
- Runtime Telegram requests POST directly to `/v1/tts`; `/health` is for deployment/operations checks only.
- The Mac worker binds to its Tailscale IPv4, not `0.0.0.0`.
- Unit tests must not download VieNeu models.

## Implementation Precondition

The repository migration plan is being implemented separately. Before Task 1 code changes begin, sync `feat/qeo-voice` onto the latest `main` and verify these foundation files exist:

```text
plugins/qeo-shortcuts/__init__.py
plugins/qeo-shortcuts/plugin.yaml
plugins/qeo-shortcuts/handlers/story.py
scripts/deploy-skill.sh
scripts/deploy.sh
scripts/verify.sh
tests/test_deploy_scripts.py
```

If the migration is not yet on `main`, do not create a second deployment/plugin framework on this branch. Wait for or integrate the foundation first, then continue this plan.

---

## File Map

- `.gitignore` — blocks private voice samples, generated audio, local worker env/config artifacts.
- `skills/qeo-voice/SKILL.md` — Hermes-facing capability and no-fallback contract.
- `skills/qeo-voice/references/voices.md` — voice registry conventions and Chi Chi profile documentation.
- `workers/qeo-voice/__init__.py` — package marker.
- `workers/qeo-voice/registry.py` — typed registry loading and private asset validation.
- `workers/qeo-voice/engine.py` — VieNeu adapter, one-time enrollment, single-flight synthesis.
- `workers/qeo-voice/app.py` — authenticated FastAPI `/health` and `/v1/tts` API.
- `workers/qeo-voice/voices.json` — public voice registry; no audio bytes.
- `workers/qeo-voice/requirements.txt` — Mac worker dependencies only.
- `workers/qeo-voice/launchd/com.qeo.voice.plist.template` — user LaunchAgent template.
- `plugins/qeo-shortcuts/handlers/voice.py` — deterministic Telegram `/qeovoice` client/handler.
- `plugins/qeo-shortcuts/__init__.py` — register the new voice handler alongside story.
- `scripts/deploy-voice-worker.sh` — Mac-only worker bootstrap/update/health verification.
- `scripts/verify.sh` — add repository/runtime validation for `qeo-voice` without installing TTS on UpCloud.
- `docs/QEO-VOICE.md` — worker provisioning, secrets, Tailscale, deploy, failure behavior.
- `docs/TELEGRAM-COMMANDS.md` — document `qeo-voice -> /qeovoice`.
- `tests/test_qeo_voice_registry.py` — registry/asset validation.
- `tests/test_qeo_voice_worker.py` — worker API, auth, busy/error behavior with mocked engine.
- `tests/test_qeo_shortcuts_voice.py` — Telegram handler routing and exact failure messages.
- `tests/test_voice_deploy_contract.py` — static deployment/no-UpCloud-VieNeu contract tests.

---

### Task 1: Add the Public `qeo-voice` Contract and Voice Registry

**Files:**
- Create: `.gitignore` if absent, otherwise modify it.
- Create: `skills/qeo-voice/SKILL.md`
- Create: `skills/qeo-voice/references/voices.md`
- Create: `workers/qeo-voice/__init__.py`
- Create: `workers/qeo-voice/voices.json`
- Create: `tests/test_qeo_voice_registry.py`

**Interfaces:**
- Produces registry slug `chi-chi` and public profile values consumed by `registry.py`/`engine.py` in Task 2.
- Private asset root comes from `QEO_VOICE_ASSET_ROOT`; registry reference `chi-chi/reference.wav` is resolved beneath that root.

- [ ] **Step 1: Write failing registry/static tests**

Create `tests/test_qeo_voice_registry.py` to assert:

```python
registry = json.loads(Path("workers/qeo-voice/voices.json").read_text())
self.assertEqual(registry["default"], "chi-chi")
chi = registry["voices"]["chi-chi"]
self.assertEqual(chi["display_name"], "Chi Chi")
self.assertEqual(chi["engine"], "v3turbo")
self.assertEqual(chi["temperature"], 0.55)
self.assertEqual(chi["top_k"], 20)
self.assertEqual(chi["top_p"], 0.90)
self.assertTrue(chi["denoise"])
self.assertTrue(chi["use_ref_codes"])
```

Also assert `SKILL.md` frontmatter contains `name: qeo-voice`, docs mention `/qeovoice`, and `.gitignore` contains patterns preventing tracked `reference.wav`/generated worker audio.

- [ ] **Step 2: Run tests and confirm failure because files are absent**

Run:

```bash
python3 -m unittest tests.test_qeo_voice_registry -v
```

Expected: FAIL due to missing `workers/qeo-voice/voices.json` or skill files.

- [ ] **Step 3: Add the registry and skill docs**

Create `voices.json` exactly around this initial entry:

```json
{
  "default": "chi-chi",
  "voices": {
    "chi-chi": {
      "display_name": "Chi Chi",
      "engine": "v3turbo",
      "profile": "tight-denoised",
      "reference": "chi-chi/reference.wav",
      "denoise": true,
      "use_ref_codes": true,
      "temperature": 0.55,
      "top_k": 20,
      "top_p": 0.90,
      "repetition_penalty": 1.20,
      "max_chars": 140,
      "silence_p": 0.10,
      "crossfade_p": 0.0
    }
  }
}
```

`SKILL.md` must state the hard rule: Mac mini is the only voice compute host and UpCloud never falls back to another TTS engine.

- [ ] **Step 4: Add safe ignore rules**

Ignore private/local-only paths such as:

```gitignore
workers/qeo-voice/.venv/
workers/qeo-voice/.env
workers/qeo-voice/**/*.wav
workers/qeo-voice/**/*.mp3
workers/qeo-voice/**/*.ogg
workers/qeo-voice/private/
```

Do not use a repository-wide `*.wav` ignore if another future skill may intentionally track public audio fixtures.

- [ ] **Step 5: Run tests**

```bash
python3 -m unittest tests.test_qeo_voice_registry -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .gitignore skills/qeo-voice workers/qeo-voice/voices.json workers/qeo-voice/__init__.py tests/test_qeo_voice_registry.py
git commit -m "feat: add qeo-voice registry contract"
```

---

### Task 2: Implement Registry Loading and VieNeu Engine Boundary

**Files:**
- Create: `workers/qeo-voice/registry.py`
- Create: `workers/qeo-voice/engine.py`
- Modify: `tests/test_qeo_voice_registry.py`

**Interfaces:**
- `load_registry(registry_path: Path, asset_root: Path) -> VoiceRegistry`
- `VoiceRegistry.default_slug: str`
- `VoiceRegistry.resolve(slug: str | None) -> VoiceConfig`
- `VieNeuVoiceEngine(registry: VoiceRegistry)`
- `VieNeuVoiceEngine.start() -> None`
- `VieNeuVoiceEngine.synthesize(text: str, voice: str | None = None) -> bytes`
- Raises `UnknownVoiceError`, `VoiceAssetError`, `VoiceBusyError`, `VoiceSynthesisError`.

- [ ] **Step 1: Add failing tests for asset and voice resolution**

Use `tempfile.TemporaryDirectory()` and a temporary fake `chi-chi/reference.wav`. Cover:

```python
self.assertEqual(registry.resolve(None).slug, "chi-chi")
self.assertEqual(registry.resolve("chi-chi").display_name, "Chi Chi")
with self.assertRaises(UnknownVoiceError):
    registry.resolve("missing")
with self.assertRaises(VoiceAssetError):
    load_registry(registry_path, empty_asset_root)
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
python3 -m unittest tests.test_qeo_voice_registry -v
```

Expected: import failure for `registry.py`.

- [ ] **Step 3: Implement typed registry loading**

Use dataclasses for `VoiceConfig` and `VoiceRegistry`. Validate the default slug exists, every reference resolves beneath `asset_root`, and every required reference file exists. Reject `..` traversal by verifying `resolved_reference.is_relative_to(asset_root.resolve())` on Python 3.12.

- [ ] **Step 4: Add engine tests with a fake VieNeu factory**

Patch the engine factory so tests never import/download a real model. Assert `start()` creates one backend and calls `add_voice()` once for Chi Chi. Assert `synthesize()` forwards the exact tight-denoised values and returns WAV bytes.

For overlap, hold the internal lock in the test and assert:

```python
with self.assertRaises(VoiceBusyError):
    engine.synthesize("second request")
```

- [ ] **Step 5: Implement the VieNeu adapter minimally**

Import `Vieneu` lazily inside the default factory, instantiate `Vieneu(mode="v3turbo")` once in `start()`, enroll registry voices once, and serialize calls with `threading.Lock().acquire(blocking=False)`.

Generate WAV bytes with `soundfile.write(io.BytesIO(), audio, 48000, format="WAV", subtype="PCM_16")`. Always release the lock in `finally`.

- [ ] **Step 6: Run tests**

```bash
python3 -m unittest tests.test_qeo_voice_registry -v
```

Expected: PASS without network/model downloads.

- [ ] **Step 7: Commit**

```bash
git add workers/qeo-voice/registry.py workers/qeo-voice/engine.py tests/test_qeo_voice_registry.py
git commit -m "feat: add qeo voice engine boundary"
```

---

### Task 3: Implement the Authenticated Mac Worker API

**Files:**
- Create: `workers/qeo-voice/app.py`
- Create: `workers/qeo-voice/requirements.txt`
- Create: `tests/test_qeo_voice_worker.py`

**Interfaces:**
- `create_app(engine, token: str) -> FastAPI`
- `GET /health` requires `Authorization: Bearer <token>`.
- `POST /v1/tts` body: `{"text": str, "voice": str | null}`.
- Success response: `audio/wav` bytes.
- Busy response: `503 {"error":"busy"}`.

- [ ] **Step 1: Write failing API tests using FastAPI TestClient**

Cover missing/wrong auth on both endpoints, healthy response, empty text rejection, successful WAV body, unknown voice 400, busy 503, synthesis failure 500, and ensure error JSON never includes a traceback/token.

Expected healthy payload:

```python
{"status": "ok", "engine": "v3turbo", "default_voice": "chi-chi"}
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
python3 -m unittest tests.test_qeo_voice_worker -v
```

- [ ] **Step 3: Implement `create_app`**

Use `hmac.compare_digest()` for bearer-token comparison. Map domain exceptions explicitly:

```text
UnknownVoiceError -> 400 {"error":"unknown_voice"}
VoiceBusyError -> 503 {"error":"busy"}
VoiceSynthesisError -> 500 {"error":"synthesis_failed"}
```

Do not expose exception strings for 500 responses.

- [ ] **Step 4: Add the process entrypoint**

When `app.py` runs as a module/script, require:

```text
QEO_VOICE_TOKEN
QEO_VOICE_ASSET_ROOT
QEO_VOICE_BIND_HOST
```

Optional:

```text
QEO_VOICE_PORT=8765
QEO_VOICE_REGISTRY=<repo>/workers/qeo-voice/voices.json
```

Startup loads the registry, creates/starts the engine before serving, then invokes Uvicorn on the supplied private bind host.

- [ ] **Step 5: Pin worker dependencies**

Use:

```text
vieneu==3.6.4
fastapi>=0.140,<1
uvicorn>=0.40,<1
soundfile>=0.14,<1
```

The worker dependencies live only under `workers/qeo-voice`; do not add them to Hermes/UpCloud requirements.

- [ ] **Step 6: Run worker tests and compile**

```bash
python3 -m unittest tests.test_qeo_voice_worker -v
python3 -m py_compile workers/qeo-voice/*.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add workers/qeo-voice/app.py workers/qeo-voice/requirements.txt tests/test_qeo_voice_worker.py
git commit -m "feat: add qeo voice Mac worker API"
```

---

### Task 4: Add LaunchAgent and Mac Worker Deployment

**Files:**
- Create: `workers/qeo-voice/launchd/com.qeo.voice.plist.template`
- Create: `scripts/deploy-voice-worker.sh`
- Create: `tests/test_voice_deploy_contract.py`

**Interfaces:**

```text
QEO_VOICE_ASSET_ROOT=/private/path \
QEO_VOICE_TOKEN=... \
./scripts/deploy-voice-worker.sh
```

Optional overrides:

```text
QEO_VOICE_BIND_HOST=<tailscale-ip>
QEO_VOICE_PORT=8765
QEO_VOICE_INSTALL_ROOT=$HOME/Library/Application Support/QeoVoice/runtime
```

- [ ] **Step 1: Write failing deployment-contract tests**

Static/subprocess tests must verify the script:

- refuses non-macOS hosts;
- requires `QEO_VOICE_TOKEN` and `QEO_VOICE_ASSET_ROOT`;
- checks `chi-chi/reference.wav` exists;
- resolves `tailscale ip -4` when `QEO_VOICE_BIND_HOST` is absent;
- never contains `/opt/hermes/data` as a worker install destination;
- template contains `RunAtLoad` and `KeepAlive` set true;
- generated worker program uses the dedicated worker venv Python.

- [ ] **Step 2: Run and confirm failure**

```bash
python3 -m unittest tests.test_voice_deploy_contract -v
```

- [ ] **Step 3: Implement the LaunchAgent template**

Use placeholders for Python executable, worker source path, registry path, asset root, bind host, port, and token. Store stdout/stderr under the local QeoVoice runtime/log directory, not the Git checkout.

- [ ] **Step 4: Implement deployment script**

The script must:

1. verify `uname -s` is `Darwin`;
2. validate private asset and token;
3. resolve Tailscale IPv4 unless overridden;
4. create a dedicated Python 3.12 venv under the install root;
5. install `workers/qeo-voice/requirements.txt`;
6. copy worker source/registry into the install root while never copying private audio;
7. render `~/Library/LaunchAgents/com.qeo.voice.plist`;
8. `launchctl bootout gui/$UID/...` if already loaded, tolerating not-loaded;
9. `launchctl bootstrap gui/$UID ...`;
10. poll authenticated `http://<tailscale-ip>:8765/health` until healthy or timeout;
11. fail with a useful message without printing the bearer token.

- [ ] **Step 5: Run deployment tests**

```bash
python3 -m unittest tests.test_voice_deploy_contract -v
bash -n scripts/deploy-voice-worker.sh
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add workers/qeo-voice/launchd scripts/deploy-voice-worker.sh tests/test_voice_deploy_contract.py
git commit -m "feat: deploy qeo voice worker on macOS"
```

---

### Task 5: Add `/qeovoice` to `qeo-shortcuts`

**Files:**
- Create: `plugins/qeo-shortcuts/handlers/voice.py`
- Modify: `plugins/qeo-shortcuts/__init__.py`
- Modify: `plugins/qeo-shortcuts/plugin.yaml` only if command metadata is declared there by the migrated plugin pattern.
- Create: `tests/test_qeo_shortcuts_voice.py`

**Interfaces:**
- `register_voice(ctx) -> None`
- Handler command: `qeovoice` only.
- Worker env: `QEO_VOICE_WORKER_URL`, `QEO_VOICE_TOKEN`, optional `QEO_VOICE_TIMEOUT_SECONDS`.
- Exact user messages:

```text
Usage: /qeovoice <text>
⚠️ Qeo Voice unavailable — Mac mini voice worker is offline.
⚠️ Qeo Voice is busy. Please try again in a moment.
⚠️ Qeo Voice failed to generate audio. Please try again.
```

- [ ] **Step 1: Write failing handler tests**

Follow the existing `story.py` hook/adapter test style after syncing main. Cover:

- `/qeovoice Xin chào` recognized;
- empty text sends usage and skips LLM dispatch;
- successful worker response writes a temporary `.wav`, awaits adapter `send_voice`, then deletes the file;
- URL timeout, DNS/connect refusal -> exact offline alert;
- worker HTTP 503 with `{"error":"busy"}` -> exact busy alert;
- other worker 5xx -> exact generation-failed alert;
- missing `QEO_VOICE_WORKER_URL` or token -> offline alert without secret leakage;
- handler never imports/calls Hermes `tts_tool` and never executes a local synthesis command.

- [ ] **Step 2: Run and confirm failure**

```bash
python3 -m unittest tests.test_qeo_shortcuts_voice -v
```

- [ ] **Step 3: Implement the worker HTTP client**

Use Python stdlib `urllib.request` inside `asyncio.to_thread()` so the gateway event loop is not blocked and no new UpCloud Python dependency is needed. POST JSON directly to `${QEO_VOICE_WORKER_URL.rstrip('/')}/v1/tts` with bearer auth and timeout `float(os.getenv("QEO_VOICE_TIMEOUT_SECONDS", "90"))`.

Classify `URLError`, `TimeoutError`, socket timeout, and connection errors as offline. Parse 503 JSON for `busy`; classify all other 5xx as generation failure.

- [ ] **Step 4: Implement Telegram voice delivery**

Write bytes under:

```text
${HERMES_HOME:-/opt/hermes/data}/audio_cache/qeovoice/<uuid>.wav
```

Use the same conversation/topic/reply metadata convention as `handlers/story.py`, call the adapter's native `send_voice(...)`, and unlink the file in `finally` after the awaited send completes.

- [ ] **Step 5: Register the handler**

Keep root plugin composition small:

```python
from .handlers.story import register_story
from .handlers.voice import register_voice


def register(ctx):
    register_story(ctx)
    register_voice(ctx)
```

Preserve existing story behavior exactly.

- [ ] **Step 6: Run handler regression tests**

```bash
python3 -m unittest tests.test_qeo_shortcuts_story tests.test_qeo_shortcuts_voice -v
python3 -m py_compile plugins/qeo-shortcuts/__init__.py plugins/qeo-shortcuts/handlers/*.py
```

Expected: both story and voice suites PASS.

- [ ] **Step 7: Commit**

```bash
git add plugins/qeo-shortcuts tests/test_qeo_shortcuts_voice.py
git commit -m "feat: add qeovoice telegram shortcut"
```

---

### Task 6: Extend Repository Verification and Documentation

**Files:**
- Modify: `scripts/verify.sh`
- Modify: `README.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TELEGRAM-COMMANDS.md`
- Create: `docs/QEO-VOICE.md`
- Modify: `tests/test_deploy_scripts.py` and/or `tests/test_voice_deploy_contract.py`

**Interfaces:**
- Normal UpCloud deployment remains `scripts/deploy.sh qeo-voice ...`.
- Worker deployment remains separate: `scripts/deploy-voice-worker.sh` on the Mac.

- [ ] **Step 1: Add failing verification tests**

Assert repo validation catches:

- missing `skills/qeo-voice/SKILL.md`;
- wrong frontmatter name;
- wrong Telegram shortcut form containing `-`;
- registry default not `chi-chi`;
- accidental tracked/private reference path under `workers/qeo-voice`;
- any UpCloud deployment script that installs `vieneu` or copies worker/private asset directories into Hermes home.

- [ ] **Step 2: Run and confirm failure for the new checks**

```bash
python3 -m unittest tests.test_deploy_scripts tests.test_voice_deploy_contract -v
```

- [ ] **Step 3: Extend `verify.sh` minimally**

Reuse the existing validation framework. Add `qeo-voice` static checks, but do not make normal UpCloud verification import VieNeu or contact the Mac worker unless a dedicated voice-worker verification option is explicitly invoked.

- [ ] **Step 4: Document the exact operating model**

`docs/QEO-VOICE.md` must cover:

```text
Telegram -> UpCloud -> Tailscale -> Mac mini -> VieNeu Turbo -> WAV -> Telegram
```

Document private variables without values, private asset provisioning, LaunchAgent lifecycle, health curl example with `$QEO_VOICE_TOKEN`, `/qeovoice` usage, busy/offline behavior, and the explicit no-fallback rule.

`docs/TELEGRAM-COMMANDS.md` adds:

```text
qeo-voice -> /qeovoice
```

- [ ] **Step 5: Run full repository tests**

```bash
python3 -m unittest discover -s tests -v
./scripts/verify.sh --repo-only
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify.sh README.md docs tests/test_deploy_scripts.py tests/test_voice_deploy_contract.py
git commit -m "docs: add qeo voice deployment workflow"
```

---

### Task 7: Deploy the Mac Worker and Verify From UpCloud

**Production action; no code is considered complete before these checks pass.**

- [ ] **Step 1: Provision the private Chi Chi reference on the Mac**

Place the approved sample outside the repo, e.g.:

```text
~/Library/Application Support/QeoVoice/voices/chi-chi/reference.wav
```

Verify it exists and is not under the Git checkout.

- [ ] **Step 2: Ensure Tailscale is connected on Mac and UpCloud**

On Mac, record only into local configuration the result of:

```bash
tailscale ip -4
```

On UpCloud, verify the Mac Tailscale address is reachable. Do not commit it.

- [ ] **Step 3: Generate/store the bearer token privately**

Use a high-entropy token. Put the token in Mac LaunchAgent/private env and UpCloud Hermes private environment only. Never print it in logs or commit it.

- [ ] **Step 4: Deploy worker on the Mac**

Run from the repository checkout:

```bash
QEO_VOICE_ASSET_ROOT="$HOME/Library/Application Support/QeoVoice/voices" \
QEO_VOICE_TOKEN="$QEO_VOICE_TOKEN" \
./scripts/deploy-voice-worker.sh
```

Expected: LaunchAgent loads and authenticated `/health` reports `status=ok`, `engine=v3turbo`, `default_voice=chi-chi`.

- [ ] **Step 5: Run real Mac synthesis smoke**

POST:

```json
{"text":"Xin chào anh Qeo. Đây là Chi Chi.","voice":"chi-chi"}
```

Verify response is a playable mono WAV and a second sequential request works without worker PID change, proving the model remains resident.

- [ ] **Step 6: Verify UpCloud can synthesize through Tailscale**

From UpCloud, call the Mac `/v1/tts` endpoint using private env configuration and write the response to a temporary file. Verify WAV validity. Do not install any TTS dependency on UpCloud.

- [ ] **Step 7: Only after remote Mac synthesis passes, remove prior UpCloud voice experiments**

Remove the experimental `/opt/hermes/data/qeo-voice-venv`, experimental `qeovoice` skill directory created outside this repo, and temporary smoke WAVs. Inspect model cache paths first and remove only VieNeu/MOSS artifacts attributable to this experiment; do not delete a shared cache wholesale if unrelated Hermes features use it.

Verify afterward:

```text
no qeo-voice-venv
no active vieneu process
no private Chi Chi reference audio
no Nano/Turbo local fallback command/config for /qeovoice
```

- [ ] **Step 8: Configure UpCloud private worker variables**

Set, without committing values:

```text
QEO_VOICE_WORKER_URL=http://<mac-tailscale-ip>:8765
QEO_VOICE_TOKEN=<same-private-token>
QEO_VOICE_TIMEOUT_SECONDS=90
```

- [ ] **Step 9: Deploy `qeo-voice` and updated `qeo-shortcuts` through repository scripts**

Use the existing production deployment workflow from `docs/DEPLOYMENT.md`, targeting the intended profiles. Let the repository deploy script own backup, plugin replacement, one gateway restart, and verification.

- [ ] **Step 10: Verify gateway health and command discovery**

Confirm gateway remains running, canonical `qeo-voice` is discovered, and Telegram menu/command registration exposes `qeovoice` according to the plugin's established command mechanism.

---

### Task 8: End-to-End Telegram Acceptance and Failure Test

- [ ] **Step 1: Online success smoke**

Send in Telegram:

```text
/qeovoice Xin chào anh Qeo. Đây là Chi Chi.
```

Acceptance: Telegram receives a native voice message generated by the Mac worker; no LLM response or second TTS provider is involved.

- [ ] **Step 2: Offline/no-fallback smoke**

Temporarily stop the Mac LaunchAgent or make the worker unreachable, then send the same `/qeovoice` command.

Acceptance: Telegram responds exactly:

```text
⚠️ Qeo Voice unavailable — Mac mini voice worker is offline.
```

Acceptance additionally requires that UpCloud produces no audio file via Edge, Nano, Turbo, Hermes default TTS, or any other local provider.

- [ ] **Step 3: Restore Mac worker and re-test**

Start the LaunchAgent, wait for authenticated `/health=ok`, resend `/qeovoice`, and verify native voice delivery recovers without restarting the Hermes gateway.

- [ ] **Step 4: Final regression suite**

Run:

```bash
python3 -m unittest discover -s tests -v
./scripts/verify.sh --repo-only
```

Also run production verification from `docs/DEPLOYMENT.md` against the deployed Hermes home.

- [ ] **Step 5: Review full diff and prepare merge**

Confirm the diff contains no token, Tailscale IP, Telegram/chat ID, `reference.wav`, generated audio, `.env`, or private LaunchAgent output. Confirm no unrelated repository refactor is present.

- [ ] **Step 6: Commit any verification-only doc corrections, push branch, and open PR**

PR description must state the no-fallback rule and include evidence for Mac health, UpCloud-to-Mac synthesis, online Telegram smoke, and offline Telegram smoke.

---

## Self-Review Result

- **Spec coverage:** worker ownership, Chi Chi profile, private assets, authenticated API, single-flight busy behavior, Tailscale-only binding, `/qeovoice` fast path, exact error copy, Mac deployment, UpCloud no-fallback rule, cleanup, unit tests, and both Telegram acceptance paths are each mapped to a task.
- **Placeholder scan:** no implementation step relies on `TBD`, `TODO`, or unspecified generic error handling.
- **Interface consistency:** registry slugs, environment variable names, API endpoints, timeout default, busy semantics, exact user messages, asset root, and deployment ownership match the approved spec.
