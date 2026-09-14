# Qeo Mac Docker Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package every Mac-local Qeo worker in Docker Compose, starting with `qeo-voice-worker`, while keeping UpCloud Hermes native and preserving the hard no-fallback voice contract.

**Architecture:** Mac-local application workers run as one-container-per-worker services in `docker/mac/compose.yml`. `qeo-voice-worker` publishes only to macOS loopback, host-native Tailscale Serve proxies that loopback endpoint to the tailnet, and UpCloud continues to run Hermes skills/plugins natively. Private assets, model caches, and secrets remain outside Git.

**Tech Stack:** Docker Desktop, Docker Compose, Linux ARM64, Python 3.12, VieNeu 3.6.4, ffmpeg/libopus, FastAPI/Uvicorn, Tailscale Serve, Bash, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-14-qeo-mac-docker-runtime-design.md`

## Global Constraints

- UpCloud remains native; do not containerize Hermes or production gateway deployment.
- Every Mac-local Qeo application worker runs in Docker after migration.
- Tailscale remains host-native on macOS; no Tailscale sidecar in v1.
- `qeo-voice-worker` host publish is exactly loopback-only: `127.0.0.1:8765 -> container:8765`.
- Compose service uses `restart: unless-stopped`.
- Chi Chi reference audio is mounted read-only from outside Git.
- Model/cache storage persists across container replacement.
- Worker success transport is `audio/ogg` with OGG/Opus payload.
- UpCloud never runs VieNeu, ffmpeg for qeo-voice synthesis, Edge TTS, Hermes TTS fallback, or any other fallback provider.
- `QEO_VOICE_TOKEN`, private paths, Tailscale identifiers, and Telegram identifiers are never committed.
- Unit tests must not download live VieNeu models.
- Production completion requires both online Telegram voice success and Mac-offline/no-fallback acceptance tests.

---
## File Map

- `workers/qeo-voice/Dockerfile` — Linux ARM64 worker image with Python 3.12, ffmpeg, audio libs, and VieNeu dependencies.
- `workers/qeo-voice/healthcheck.py` — authenticated in-container `/health` probe using stdlib only.
- `docker/mac/compose.yml` — canonical Mac-local Compose stack.
- `docker/mac/.env.example` — safe variable names/placeholders only.
- `scripts/mac-up.sh` — validate Mac prerequisites/config, build/start Compose, wait healthy, reconcile Tailscale Serve.
- `scripts/mac-down.sh` — intentionally stop Mac Compose services without deleting private state.
- `scripts/mac-status.sh` — show Compose health plus Tailscale Serve status.
- `scripts/verify.sh` — add Docker/qeo-voice static verification while preserving native UpCloud checks.
- `docs/QEO-VOICE.md` — current Docker/Tailscale/operations guide.
- `README.md`, `docs/DEPLOYMENT.md`, `docs/TELEGRAM-COMMANDS.md` — document current runtime and command mapping.
- `tests/test_qeo_mac_docker.py` — Dockerfile/Compose/wrapper contracts.
- `tests/test_qeo_voice_repo_contract.py` — qeo-voice repository/no-UpCloud-compute contract.
- Delete/replace untracked obsolete `tests/test_voice_deploy_contract.py` because LaunchAgent deployment is superseded.

---

### Task 1: Define the Docker Packaging Contract

**Files:**
- Create: `workers/qeo-voice/Dockerfile`
- Create: `workers/qeo-voice/healthcheck.py`
- Create: `docker/mac/compose.yml`
- Create: `docker/mac/.env.example`
- Create: `tests/test_qeo_mac_docker.py`
- Delete: `tests/test_voice_deploy_contract.py` if still present as an untracked LaunchAgent-era test.

**Interfaces:**
- Compose service name: `qeo-voice-worker`.
- Container port: `8765`; host publish: `127.0.0.1:${QEO_VOICE_PORT:-8765}:8765`.
- Container asset root: `/data/voices`.
- Persistent cache root: `/cache`; `HF_HOME=/cache/huggingface`.
- Worker runtime receives `QEO_VOICE_TOKEN`, `QEO_VOICE_ASSET_ROOT=/data/voices`, `QEO_VOICE_BIND_HOST=0.0.0.0`, `QEO_VOICE_PORT=8765`.

- [ ] **Step 1: Write failing static Docker contract tests**

Create `tests/test_qeo_mac_docker.py` asserting Dockerfile uses Python 3.12, installs `ffmpeg` and `libsndfile1`, copies only worker source/dependencies, and never references Chi Chi private audio or a token value. Assert Compose contains `qeo-voice-worker`, `restart: unless-stopped`, `platform: linux/arm64`, loopback-only port publishing, read-only voice mount, persistent cache mount, and a healthcheck.

- [ ] **Step 2: Run the tests and confirm RED**

Run `python3 -m unittest tests.test_qeo_mac_docker -v`.
Expected: FAIL because Dockerfile/Compose files do not exist.

- [ ] **Step 3: Add minimal Dockerfile and in-container healthcheck**

Use `python:3.12-slim-bookworm`, install `ffmpeg` and `libsndfile1` with no recommended packages, install `workers/qeo-voice/requirements.txt`, then copy the worker Python files/registry. Do not copy `workers/qeo-voice/private`, `.env`, audio samples, or host cache paths.

`healthcheck.py` must read `QEO_VOICE_TOKEN`, call `http://127.0.0.1:8765/health` with bearer auth using `urllib.request`, require HTTP 200 plus JSON `status=ok`, and exit non-zero otherwise. It must never print the token.

- [ ] **Step 4: Add Compose and safe env example**

Compose must build from repository root using `workers/qeo-voice/Dockerfile`, map only `127.0.0.1:${QEO_VOICE_PORT:-8765}:8765`, mount `${QEO_MAC_DATA_ROOT}/voices:/data/voices:ro` and `${QEO_MAC_DATA_ROOT}/cache:/cache`, pass the four worker env vars above, set `HF_HOME=/cache/huggingface`, and run the healthcheck script. `.env.example` contains names and safe placeholders only.

- [ ] **Step 5: Validate GREEN**

Run:

```bash
python3 -m unittest tests.test_qeo_mac_docker -v
docker compose --env-file docker/mac/.env.example -f docker/mac/compose.yml config >/dev/null
```

Expected: tests PASS and Compose config parses without secrets.

- [ ] **Step 6: Commit**

```bash
git add workers/qeo-voice/Dockerfile workers/qeo-voice/healthcheck.py docker/mac tests/test_qeo_mac_docker.py
git commit -m "feat: package qeo voice worker for Mac Docker"
```

---

### Task 2: Add Mac Compose Operations and Tailscale Serve Reconciliation

**Files:**
- Create: `scripts/mac-up.sh`
- Create: `scripts/mac-down.sh`
- Create: `scripts/mac-status.sh`
- Modify: `tests/test_qeo_mac_docker.py`

**Interfaces:**
- Default private config: `$HOME/Library/Application Support/QeoSkills/config/mac.env`.
- Optional override: `QEO_MAC_ENV_FILE`.
- `mac-up.sh` delegates to `docker compose --env-file <file> -f docker/mac/compose.yml up -d --build`.
- `mac-down.sh` delegates to `docker compose ... stop` rather than deleting volumes/private state.
- `mac-status.sh` runs Compose `ps` and `tailscale serve status`.

- [ ] **Step 1: Add failing wrapper behavior tests**

Use temporary fake `docker` and `tailscale` executables placed first in `PATH`. Assert `mac-up.sh` rejects missing config/token/data root, calls Compose with the approved file/env, waits until `qeo-voice-worker` is healthy, then calls `tailscale serve --bg --http=8765 127.0.0.1:8765`. Assert `mac-down.sh` uses `stop` and never `down -v`; assert `mac-status.sh` queries both systems.

- [ ] **Step 2: Run RED**

Run `python3 -m unittest tests.test_qeo_mac_docker -v`.
Expected: FAIL because Mac wrapper scripts are absent.

- [ ] **Step 3: Implement thin wrappers**

All scripts use `set -euo pipefail`, resolve repository root relative to the script, require Darwin for Mac operations, require Docker and Tailscale binaries, validate the private config exists without echoing its contents, and delegate rather than duplicating Compose configuration.

`mac-up.sh` should poll `docker compose ps --format json` or `docker inspect` for container health with a bounded timeout, then reconcile Tailscale Serve. Do not use Funnel.

- [ ] **Step 4: Run GREEN and shell validation**

```bash
python3 -m unittest tests.test_qeo_mac_docker -v
bash -n scripts/mac-up.sh scripts/mac-down.sh scripts/mac-status.sh
```

- [ ] **Step 5: Commit**

```bash
git add scripts/mac-up.sh scripts/mac-down.sh scripts/mac-status.sh tests/test_qeo_mac_docker.py
git commit -m "feat: add Mac Docker runtime operations"
```

---

### Task 3: Extend Repository Verification and Current Documentation

**Files:**
- Modify: `scripts/verify.sh`
- Modify: `tests/test_qeo_voice_repo_contract.py`
- Modify: `README.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TELEGRAM-COMMANDS.md`
- Create: `docs/QEO-VOICE.md`

**Interfaces:**
- `verify.sh --repo-only` validates both native UpCloud source and Mac Docker source without requiring Docker daemon/model downloads.
- `docs/QEO-VOICE.md` is the canonical operator guide for Docker/Tailscale/private assets.

- [ ] **Step 1: Finish failing repo-contract tests**

Assert `verify.sh` checks `skills/qeo-voice/SKILL.md`, frontmatter `name: qeo-voice`, exact `/qeovoice` registration, Docker loopback publish, `restart: unless-stopped`, registry default `chi-chi`, and absence of VieNeu/worker deployment logic in normal UpCloud scripts. Assert docs contain Docker Desktop, Tailscale Serve, OGG/Opus, no-fallback, and `/qeovoice` mapping.

- [ ] **Step 2: Run RED**

Run `python3 -m unittest tests.test_qeo_voice_repo_contract -v`.
Expected: FAIL because verification/docs are incomplete.

- [ ] **Step 3: Extend `verify.sh` minimally**

Keep existing qeo-story checks. Add qeo-voice skill/plugin compile checks plus static Docker contract checks using shell/grep. Do not import VieNeu, build images, contact Tailscale, or require the Mac worker during `--repo-only`.

- [ ] **Step 4: Write current-state docs**

`docs/QEO-VOICE.md` must document Docker Desktop, private filesystem layout, `mac.env` variable names, Mac wrapper scripts, Tailscale Serve, OGG/Opus behavior, restart behavior, and the no-fallback policy.

README adds `qeo-voice` and the `docker/mac` runtime. Deployment guide separates native UpCloud deployment from Mac Docker operations. Telegram guide adds `qeo-voice -> /qeovoice` and native voice delivery.

- [ ] **Step 5: Run full repository verification**

```bash
python3 -m unittest discover -s tests -v
./scripts/verify.sh --repo-only
```

Expected: PASS without live model downloads.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify.sh README.md docs tests/test_qeo_voice_repo_contract.py
git commit -m "docs: document qeo voice Docker runtime"
```

---

### Task 4: Build and Smoke-Test the Real Mac Container

**Files/State:**
- Private voice asset: `~/Library/Application Support/QeoSkills/voices/chi-chi/reference.wav`.
- Private config: `~/Library/Application Support/QeoSkills/config/mac.env`.
- Persistent cache: `~/Library/Application Support/QeoSkills/cache/`.
- Runtime service: `qeo-voice-worker`.

- [ ] Prepare the private directory tree and config outside Git.
- [ ] Run `scripts/mac-up.sh` and require the container to become healthy.
- [ ] Confirm Docker publishes only on `127.0.0.1` and the voice mount is read-only.
- [ ] Call authenticated `/health` and `/v1/tts`; validate returned `.ogg` with `ffprobe` and remove the temporary file.
- [ ] Send a second synthesis and verify the container ID is unchanged.
- [ ] Recreate the service and verify model/cache data persists.
- [ ] Record startup-to-healthy and short-synthesis latency as operational evidence.

---
### Task 5: Tailnet and UpCloud Integration

Follow the approved Docker runtime spec to validate private tailnet reachability from native UpCloud Hermes, deploy only the Hermes-facing qeo-voice pieces, and preserve the hard no-fallback boundary.

### Task 6: End-to-End Acceptance and Recovery

Complete the approved Telegram online/offline acceptance tests, recovery test, Docker restart behavior check, final repository verification, complete diff review, and merge-readiness evidence.

---

## Self-Review Result

- Spec coverage is mapped across Docker packaging, Mac operations, repository docs/verification, real-container smoke, tailnet integration, and end-to-end acceptance.
- Existing qeo-voice registry, engine, API, OGG/Opus transport, and Telegram handler are reused rather than rewritten.
- LaunchAgent/host-venv deployment remains superseded.
- Service name, port 8765, private mounts, audio/ogg transport, `/qeovoice`, and no-fallback semantics remain consistent with the approved spec.
