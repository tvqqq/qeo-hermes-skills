# Qeo Mac Docker Runtime Design

Date: 2026-09-14
Repository: `tvqqq/qeo-hermes-skills`
Status: Approved architecture, pending implementation plan

## Purpose

Standardize every Qeo application component that runs locally on the Mac mini as a Docker-managed service.

UpCloud remains native. Hermes skills, plugins, and Telegram routing continue to run directly on the UpCloud host. Docker is only the execution boundary for Mac-local workers.

`qeo-voice-worker` is the first service migrated to this runtime model.

## Core Runtime Rule

```text
UpCloud = native Hermes runtime
Mac mini = Docker application runtime
Tailscale = host-native private network infrastructure
```

No Mac-local Qeo worker should require a Python virtualenv, LaunchAgent, Homebrew service, or manually managed long-lived process after migration.

## Goals

- Make Mac-local workers reproducible from the repository.
- Make reboot recovery simple: when Docker Desktop starts, previously enabled Qeo services start again automatically.
- Isolate Python/system dependencies per worker image.
- Keep private assets and secrets outside Git.
- Keep model caches persistent across container replacement.
- Keep Mac services private to the tailnet rather than exposing them to LAN or public Internet.
- Preserve the existing native UpCloud deployment workflow.
- Make future Mac-local workers additive through the same Compose stack.

## Non-goals

This design does not:

- containerize Hermes on UpCloud;
- move Tailscale into containers;
- expose Mac worker ports on `0.0.0.0` at the macOS host layer;
- add Kubernetes, Nomad, Swarm, or another orchestrator;
- create one monolithic container for all workers;
- promise GPU acceleration inside Docker Desktop on macOS;
- add automatic image publishing or a container registry in v1.

## Architecture Decision

Chosen approach: Docker Compose for Mac-local workers plus host-native Tailscale Serve.

Rejected alternatives:

- Tailscale sidecar per worker: more container auth/state complexity without a current benefit.
- Direct host publish on `0.0.0.0`: simpler but unnecessarily exposes worker ports to the LAN.
- Native per-worker LaunchAgent/venv: loses the standard packaging and reboot workflow this design is intended to provide.

## Repository Structure

```text
qeo-hermes-skills/
├── docker/
│   └── mac/
│       ├── compose.yml
│       └── .env.example
├── workers/
│   └── qeo-voice/
│       ├── Dockerfile
│       ├── app.py
│       ├── engine.py
│       ├── registry.py
│       ├── requirements.txt
│       └── voices.json
├── scripts/
│   ├── mac-up.sh
│   ├── mac-down.sh
│   ├── mac-status.sh
│   ├── deploy.sh
│   └── verify.sh
└── docs/
    └── QEO-VOICE.md
```

`workers/<name>` owns one Mac-local service. `docker/mac/compose.yml` composes those services without moving worker-specific logic into the Compose layer.

## Compose Ownership Model

Each Mac-local worker is one Compose service with its own image and dependency boundary.

The first service is:

```text
qeo-voice-worker
```

It uses:

```text
restart: unless-stopped
```

After the service has been created once with `docker compose up -d`, Docker Desktop remembers the container. On a later Mac reboot, once Docker Desktop starts, Docker restarts the worker automatically unless it was intentionally stopped.

Adding a future local worker should mean adding one worker directory, one Dockerfile, and one Compose service. Existing workers should not need to be rebuilt into a shared application image.

## Mac Filesystem Contract

Private runtime state stays outside the Git checkout:

```text
~/Library/Application Support/QeoSkills/
├── voices/
│   └── chi-chi/
│       └── reference.wav
├── cache/
│   └── huggingface/
└── config/
    └── mac.env
```

The Compose stack bind-mounts private voice assets read-only and mounts persistent model/cache storage separately. Secrets are loaded from the private config file at runtime; they are never copied into an image layer or committed to Git.

The public repository contains `.env.example` with variable names and safe placeholders only.

## Qeo Voice Container Contract

`workers/qeo-voice/Dockerfile` builds a Linux ARM64-compatible image for Docker Desktop on Apple Silicon.

The image contains only worker runtime dependencies such as Python 3.12, VieNeu, ffmpeg, and required audio libraries. It does not contain Chi Chi reference audio, tokens, Tailscale state, Telegram credentials, or Hermes runtime files.

Inside the container, the worker binds to `0.0.0.0:8765`. This is acceptable because Docker publishes that port only to macOS loopback:

```text
127.0.0.1:8765 -> container:8765
```

The host must not publish this service as `0.0.0.0:8765`.

VieNeu v3 Turbo currently resolves `device=auto` to CUDA when available and CPU otherwise. The installed Mac implementation does not select MPS for v3 Turbo, so running it in Docker Desktop is not expected to remove an acceleration path currently in use. CPU performance remains a production smoke-test requirement.

## Private Networking Contract

Tailscale remains installed and authenticated on macOS. It is infrastructure, not part of the application runtime.

The worker container is reachable only through this chain:

```text
UpCloud Hermes
  -> tailnet
  -> Tailscale Serve on the Mac mini
  -> 127.0.0.1:8765 on macOS
  -> Docker published port
  -> qeo-voice-worker:8765
```

Tailscale Serve is configured once in background HTTP mode on tailnet port `8765` to proxy `127.0.0.1:8765` (equivalent to `tailscale serve --bg --http=8765 127.0.0.1:8765`). Traffic remains encrypted by Tailscale, bearer authentication remains mandatory, and Tailscale Funnel is not used.

This avoids exposing the Docker worker to the LAN while also avoiding a Tailscale sidecar and its extra auth/state lifecycle.

## Boot and Recovery Behavior

The desired operator flow is:

```text
reboot Mac mini
-> Tailscale returns online
-> user starts Docker Desktop
-> Docker daemon starts
-> qeo-voice-worker restarts because of `restart: unless-stopped`
-> container healthcheck becomes healthy
-> Tailscale Serve can reach 127.0.0.1:8765 again
-> /qeovoice works without starting a Python process manually
```

No LaunchAgent is required for Qeo application workers.

If Docker Desktop is not running, Tailscale Serve may still be present but its local backend is unavailable. UpCloud treats that exactly as Mac worker offline and never falls back to another TTS engine.

## Qeo Voice Data Flow

The voice path becomes:

```text
Telegram /qeovoice <text>
-> UpCloud Hermes qeo-shortcuts
-> authenticated request over Tailscale Serve
-> qeo-voice-worker container
-> VieNeu v3 Turbo / Chi Chi
-> OGG/Opus encoding inside the container
-> UpCloud temporary .ogg
-> Telegram adapter send_voice
-> native Telegram voice bubble
```

The Mac performs both synthesis and voice-format encoding. UpCloud does not transcode or synthesize audio.

The worker API returns `Content-Type: audio/ogg` on successful synthesis. WAV remains only an internal intermediate representation used before ffmpeg/libopus encoding.

## Security Model

The worker still requires bearer authentication even though traffic stays on the tailnet.

Secrets remain private configuration:

```text
QEO_VOICE_TOKEN
QEO_VOICE_ASSET_ROOT
QEO_VOICE_TIMEOUT_SECONDS
```

UpCloud keeps the matching worker URL/token in its private runtime environment. The repository contains no token, Tailscale IP, MagicDNS hostname, Telegram identifier, or private voice sample.

Container logs must not print bearer tokens or full authorization headers. Docker image history must contain no secrets.

The voice asset mount is read-only. Generated audio is returned in-memory and is not persisted in the image filesystem except for bounded temporary files when required by runtime libraries.

## Health and Operations

Docker healthcheck verifies the worker from inside the container using the same authenticated `/health` contract. Healthcheck command text references the token through environment expansion rather than embedding its value in Compose source.

Operator commands are standardized through thin repository wrappers:

```text
scripts/mac-up.sh      build/start the Mac Compose stack
scripts/mac-down.sh    stop the stack intentionally
scripts/mac-status.sh  show Compose status and health
```

The wrappers do not duplicate Compose configuration. They validate prerequisites, locate the private config file, and delegate to `docker compose`.

Normal upgrades rebuild only changed images and preserve private assets/model cache.

## UpCloud Contract

Nothing about this design containerizes production Hermes.

UpCloud continues to deploy through the existing repository scripts:

```text
scripts/deploy-skill.sh
scripts/deploy.sh
scripts/verify.sh
```

`qeo-voice` on UpCloud contains the Hermes skill plus `qeo-shortcuts` handler only. It must not install VieNeu, ffmpeg for qeo-voice synthesis, worker model files, private reference audio, or a Mac-worker container image.

If the Mac Docker worker is down, `/qeovoice` returns the existing offline alert and produces no fallback audio.

## Migration from the Previous Mac Worker Design

This design supersedes the Mac deployment portions of `2026-09-13-qeo-voice-mac-worker-design.md`.

Specifically, replace:

```text
Python venv + LaunchAgent + direct Tailscale bind
```

with:

```text
Docker image + Docker Compose + loopback publish + host-native Tailscale Serve
```

It also corrects the worker transport from WAV to OGG/Opus for Telegram native voice delivery.

The existing qeo-voice registry, engine boundary, HTTP API, `/qeovoice` fast path, error messages, single-flight behavior, and hard no-fallback policy remain valid.

## Verification Gates

Repository validation must verify:

- Compose config contains only Mac-local workers;
- qeo-voice publishes only to `127.0.0.1` on the host;
- `restart: unless-stopped` is present;
- private asset mounts are read-only;
- no secrets or private samples are tracked;
- worker image contains ffmpeg and required runtime dependencies;
- UpCloud deploy scripts contain no VieNeu/container-worker installation path.

Container validation must verify build success on the Mac mini, container health, authenticated synthesis, valid OGG/Opus output, and repeated sequential requests without recreating the container.

Networking validation must verify Tailscale Serve can reach the loopback-published worker and UpCloud can call the worker through the tailnet while a LAN client cannot use the Docker host port directly.

## Failure Behavior

Failure ownership remains deterministic:

```text
Docker Desktop stopped -> Mac worker offline
container unhealthy -> Mac worker offline
Tailscale unavailable -> Mac worker offline
Tailscale Serve unavailable -> Mac worker offline
worker busy -> busy response
worker synthesis error -> generation-failed response
```

None of these states trigger an UpCloud voice provider.

A failed Mac container rebuild must leave the previous image/container available for operator rollback rather than deleting caches or private assets.

## Acceptance Criteria

Implementation is complete when:

- Mac-local Qeo workers are represented by a Compose stack under `docker/mac`;
- qeo-voice runs from its Docker image, not a host Python venv or LaunchAgent;
- opening Docker Desktop after reboot automatically resumes qeo-voice once the service was previously enabled;
- the qeo-voice host port is bound only to `127.0.0.1`;
- Tailscale Serve exposes that loopback service only to the tailnet;
- Chi Chi private reference audio stays outside Git and is mounted read-only;
- model cache survives container replacement;
- qeo-voice returns valid OGG/Opus audio;
- UpCloud remains native and contains no qeo-voice compute runtime;
- Telegram online and Mac-offline acceptance tests both pass with no fallback.