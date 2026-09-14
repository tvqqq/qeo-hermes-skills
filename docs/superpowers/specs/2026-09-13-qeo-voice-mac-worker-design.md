# Qeo Voice Mac Worker Design

Date: 2026-09-13
Repository: `tvqqq/qeo-hermes-skills`
Status: Approved functional design; Mac runtime/deployment superseded by `2026-09-14-qeo-mac-docker-runtime-design.md`

> **Supersession note:** For Mac packaging, networking, boot/recovery, and worker audio transport, the 2026-09-14 Docker runtime design takes precedence. The qeo-voice API, registry, Telegram handler, error behavior, and hard no-fallback policy in this document remain authoritative where they do not conflict.

## Purpose

Add `qeo-voice` with Telegram shortcut `/qeovoice` while keeping all VieNeu voice synthesis off the UpCloud Hermes server.

The Mac mini is the sole voice-compute authority. UpCloud owns Telegram/Hermes routing only. If the Mac worker is unavailable, `/qeovoice` returns an explicit offline message and does not fall back to any TTS engine on UpCloud.

Primary flow:

`Telegram -> UpCloud Hermes -> qeo-shortcuts -> Tailscale -> Mac mini Docker qeo-voice worker -> VieNeu v3 Turbo -> OGG/Opus -> Telegram voice bubble`

## Goals

- Expose Telegram command `/qeovoice` with no hyphen.
- Keep canonical Hermes skill name `qeo-voice`.
- Use the approved `Chi Chi` voice profile by default.
- Run VieNeu v3 Turbo only on the Mac mini.
- Keep UpCloud lightweight and free of VieNeu model/runtime dependencies.
- Use private Tailscale connectivity between UpCloud and the Mac mini.
- Return Telegram native voice messages.
- Make future voices additive through a registry rather than new skill code.
- Keep private reference audio out of the public GitHub repository.

## Non-goals

This feature will not:

- run VieNeu Nano, Turbo, Edge TTS, Hermes default TTS, or any fallback TTS on UpCloud;
- expose the Mac worker publicly to the Internet;
- add a general-purpose job queue, broker, container platform, or distributed scheduler;
- commit `reference.wav` or other private voice samples to GitHub;
- add automatic voice selection based on LLM reasoning in the first version.

## Repository Structure

The qeo-voice functional boundaries remain split between Hermes-facing skill/plugin code and the Mac-local worker:

```text
qeo-hermes-skills/
├── skills/qeo-voice/
├── plugins/qeo-shortcuts/handlers/voice.py
├── workers/qeo-voice/
│   ├── Dockerfile
│   ├── app.py
│   ├── engine.py
│   ├── registry.py
│   ├── requirements.txt
│   └── voices.json
├── docker/mac/compose.yml
└── scripts/
    ├── mac-up.sh
    ├── mac-down.sh
    └── mac-status.sh
```

`workers/qeo-voice` is intentionally separate from `skills/qeo-voice`. The skill is deployed natively to Hermes on UpCloud; the worker is packaged into the Mac Docker runtime defined by the 2026-09-14 design.

## Naming Contract

Canonical Hermes skill:

```text
qeo-voice
```

Telegram shortcut:

```text
/qeovoice
```

The Telegram shortcut contains no hyphen and follows the repository rule `qeo-<name> -> /qeo<name-without-hyphens>`.

The first registered voice is:

```text
slug: chi-chi
display_name: Chi Chi
```

`Chi Chi` is the default voice until an explicit voice argument is added in a future-compatible way.

## Voice Profile

The approved `Chi Chi` profile is the tight-denoised VieNeu v3 Turbo configuration:

```text
engine: v3turbo
denoise: true
use_ref_codes: true
temperature: 0.55
top_k: 20
top_p: 0.90
repetition_penalty: 1.20
max_chars: 140
silence_p: 0.10
crossfade_p: 0.0
```

The profile is public configuration. The source voice sample is private data and is not stored in GitHub.

## Private Voice Asset Contract

The public repository must ignore voice reference files and generated audio artifacts.

The Mac worker resolves private voice assets from a configurable data directory, for example:

```text
~/Library/Application Support/QeoVoice/
└── voices/
    └── chi-chi/
        └── reference.wav
```

The actual location is supplied through configuration, not hardcoded into public runtime code.

Minimum requirements for the Chi Chi asset:

- file exists before worker startup;
- WAV format readable by VieNeu;
- not committed to Git;
- deploy scripts never upload it to UpCloud;
- missing asset causes the Mac worker health state to be unhealthy rather than silently substituting another voice.

## Runtime Ownership Rule

The following rule is mandatory:

```text
Mac mini = sole voice compute authority
UpCloud = Telegram/Hermes router only
```

UpCloud must not install or execute VieNeu for `/qeovoice`.

If the Mac worker is unavailable, UpCloud must not use:

- VieNeu Nano;
- VieNeu Turbo;
- Edge TTS;
- Hermes default TTS;
- any other provider.

This is a hard no-fallback policy.

## Mac Worker Design

The Mac mini runs one long-lived `qeo-voice-worker` process.

At startup it:

1. loads `voices.json`;
2. validates all required private reference assets;
3. loads VieNeu v3 Turbo once;
4. enrolls `Chi Chi` once;
5. starts a private HTTP server;
6. reports healthy only after the model and default voice are ready.

The worker keeps the model resident to avoid per-request model initialization cost.

Inference is serialized in v1. A process-wide non-blocking synthesis lock allows exactly one active generation. A second concurrent synthesis request receives `503 busy` immediately; the worker never starts a second model instance and does not maintain an unbounded request queue.

## Worker API Contract

The worker exposes only the minimum API. Both endpoints require the same bearer token.

### Health

```http
GET /health
Authorization: Bearer <QEO_VOICE_TOKEN>
```

Healthy response:

```json
{
  "status": "ok",
  "engine": "v3turbo",
  "default_voice": "chi-chi"
}
```

Health returns non-2xx while the model or default voice is unavailable. It is used by deployment/operations checks, not as a mandatory extra round trip before every Telegram synthesis.

### Synthesize

```http
POST /v1/tts
Authorization: Bearer <QEO_VOICE_TOKEN>
Content-Type: application/json
```

Request:

```json
{
  "text": "Hôm nay thị trường có một điểm khá đáng chú ý.",
  "voice": "chi-chi"
}
```

Success:

```http
200 OK
Content-Type: audio/ogg
```

The body is generated OGG/Opus bytes suitable for Telegram native voice delivery.

Validation errors use 4xx. A concurrent generation returns `503` with a machine-readable `busy` error. Worker/model failures use 5xx. Error responses are JSON and never contain secrets or internal stack traces.

## Connectivity and Security

UpCloud reaches qeo-voice only through Tailscale/private Tailnet routing. The Docker service publishes its worker port only to macOS loopback (`127.0.0.1`), and host-native Tailscale Serve proxies that loopback endpoint to the tailnet. Funnel/public exposure is not used.

The public repository does not hardcode the Mac Tailscale IP, MagicDNS hostname, bearer token, Telegram IDs, or bot tokens. UpCloud receives `QEO_VOICE_WORKER_URL`, `QEO_VOICE_TOKEN`, and `QEO_VOICE_TIMEOUT_SECONDS` from private runtime configuration; timeout defaults to 90 seconds.

The matching token and private voice asset path are supplied to the Docker service through the private Mac config described by the 2026-09-14 Docker runtime design. Deployment must verify authenticated reachability from UpCloud before enabling the production command.

## Telegram Native Fast Path

`plugins/qeo-shortcuts/handlers/voice.py` owns `/qeovoice`.

Flow:

```text
Telegram /qeovoice <text>
-> pre_gateway_dispatch
-> validate non-empty text
-> POST directly to Mac worker /v1/tts through configured private URL
-> receive OGG/Opus bytes
-> write a bounded temporary `.ogg` file under HERMES_HOME/audio_cache/qeovoice
-> await Telegram adapter send_voice for the same conversation/topic
-> delete the temporary file after send completes
-> skip normal LLM dispatch
```

This path is deterministic and does not require an LLM turn. Runtime requests do not perform a separate `/health` request; connection failures and request timeouts are classified directly by the synthesis call.

The handler must register only the public Telegram shortcut `qeovoice` for the first version. The canonical Hermes skill remains available separately as `qeo-voice` through Hermes skill discovery.

## Error Behavior

User-facing failure behavior is intentionally simple.

When the Mac cannot be reached, the connection is refused, Tailscale routing fails, or synthesis exceeds the configured timeout, return:

```text
⚠️ Qeo Voice unavailable — Mac mini voice worker is offline.
```

When the worker returns `503 busy`, return:

```text
⚠️ Qeo Voice is busy. Please try again in a moment.
```

When the Mac worker responds but synthesis fails internally, return:

```text
⚠️ Qeo Voice failed to generate audio. Please try again.
```

No failure path invokes any UpCloud TTS provider.

Empty text returns concise usage help:

```text
Usage: /qeovoice <text>
```

## qeo-voice Skill Responsibilities

`skills/qeo-voice/SKILL.md` documents:

- purpose and command mapping;
- default voice `Chi Chi`;
- no-fallback ownership rule;
- worker dependency;
- manual/non-Telegram usage where appropriate;
- how future voice entries are added to the registry.

The skill package does not contain VieNeu model files, Python TTS dependencies, or private reference audio.

## Voice Registry

`workers/qeo-voice/voices.json` is the public registry for voice behavior.

Initial shape:

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

Future voices are added by registry entry plus private asset provisioning. They do not require a new Hermes skill.

## Mac Deployment Contract

The Mac worker is deployed as the `qeo-voice-worker` Docker Compose service. It is not installed into a host Python virtual environment and does not use LaunchAgent.

The service image contains Python/VieNeu/ffmpeg runtime dependencies. Private Chi Chi reference audio is bind-mounted read-only from outside Git, and model cache persists outside the replaceable container layer. The service uses `restart: unless-stopped`, publishes only to macOS loopback, and is exposed to UpCloud through host-native Tailscale Serve.

Operational commands and exact Compose contracts are owned by `2026-09-14-qeo-mac-docker-runtime-design.md`.

## UpCloud Deployment Contract

Normal repository deployment installs:

- `skills/qeo-voice`;
- updated `plugins/qeo-shortcuts` with `handlers/voice.py`;
- required environment configuration references.

It does not install:

- `vieneu`;
- model files;
- voice reference audio;
- a Qeo Voice Python virtual environment;
- any local fallback synthesizer.

Any experimental VieNeu/Nano artifacts previously placed on UpCloud are removed as part of the migration only after the Mac worker passes authenticated health and synthesis verification from UpCloud.

## Verification Gates

### Repository validation

- `qeo-voice` directory and frontmatter name match.
- Telegram shortcut is exactly `qeovoice`.
- `.gitignore` blocks private voice reference/audio files in worker asset paths.
- registry default is `chi-chi`.
- no public source contains tokens, Tailscale addresses, chat IDs, or private audio.

### Worker unit validation

Tests cover:

- registry loading;
- missing reference asset failure;
- unknown voice rejection;
- auth rejection on both endpoints;
- health state before and after readiness;
- synthesis success with the engine mocked;
- concurrent inference returns `503 busy` without loading another engine;
- error responses without stack traces.

Tests must not download live VieNeu models.

### Telegram handler validation

Tests cover:

- `/qeovoice <text>` recognition;
- empty text usage response;
- successful OGG/Opus response sent through `send_voice`;
- worker connection failure/timeout returns the exact offline alert;
- worker `503 busy` returns the busy alert;
- worker 5xx returns the generation-failed alert;
- no code path invokes Hermes TTS or a local UpCloud TTS engine.

### Mac production smoke

- Docker `qeo-voice-worker` container is running and healthy;
- authenticated `/health` returns `status=ok`;
- Chi Chi synthesis produces valid OGG/Opus audio;
- repeated requests reuse the resident worker process.

### End-to-end Telegram smoke

After gateway/plugin deployment:

```text
/qeovoice Xin chào anh Qeo. Đây là Chi Chi.
```

must return a Telegram native voice message generated by the Mac mini.

A second smoke test temporarily stops or makes the Mac worker unreachable and verifies the response is exactly the offline alert with no fallback audio.

## Operational Limits

- v1 processes one synthesis at a time and rejects overlap with `503 busy`.
- Worker availability depends on the Mac mini being online, Docker Desktop running, Tailscale connected, Tailscale Serve configured, and the container healthy.
- UpCloud intentionally cannot synthesize voice when the Mac is offline.
- Reference quality currently limits clone fidelity; replacing the private Chi Chi sample with a better 5–8 second sample is allowed without code changes.

## Acceptance Criteria

Implementation is complete when all of the following are true:

- `qeo-voice` exists under `skills/` and follows naming rules.
- Telegram exposes `/qeovoice` through `qeo-shortcuts`.
- Chi Chi is the default registered voice using the approved tight-denoised profile.
- Private `reference.wav` is absent from Git history and ignored by repository rules.
- Mac mini runs a long-lived VieNeu v3 Turbo worker and passes health/synthesis smoke tests.
- UpCloud reaches the worker only through configured Tailscale/private routing.
- UpCloud contains no active VieNeu runtime, model, Nano fallback, or voice reference asset for this feature.
- `/qeovoice` returns a Telegram native voice message while the Mac worker is online.
- `/qeovoice` returns the explicit Mac-offline alert while the Mac worker is unavailable.
- No offline/error path falls back to any UpCloud TTS provider.
- Worker and handler unit tests pass without live model downloads.
- Deployment documentation explains worker deployment, UpCloud deployment, verification, and recovery.
