# Qeo Voice

`qeo-voice` provides the Telegram command `/qeovoice "text"` using a Mac mini as the only voice-compute host. The quoted form is preferred; unquoted text remains backward-compatible.

## Runtime boundary

```text
Telegram
  -> Hermes on UpCloud (native)
  -> qeo-shortcuts voice handler
  -> Tailscale private path
  -> Mac mini Docker Desktop
  -> qeo-voice-worker
  -> VieNeu v3 Turbo + Chi Chi
  -> OGG/Opus
  -> Telegram native voice bubble
```

UpCloud never runs VieNeu or another TTS provider. There is **no fallback TTS** on UpCloud.

If the Mac worker is unavailable, `/qeovoice` returns an availability error instead of synthesizing elsewhere.

## Mac Docker runtime

All Qeo components that execute locally on the Mac are packaged as Docker services. `qeo-voice-worker` is the first service in the shared Mac Compose stack.

```text
docker/mac/compose.yml
workers/qeo-voice/Dockerfile
scripts/mac-up.sh
scripts/mac-down.sh
scripts/mac-status.sh
```

The voice service uses `restart: unless-stopped`. After a reboot, once Docker Desktop starts, Docker can restart the previously-created container automatically.
## Private Mac data

Private assets and caches live under the canonical local checkout but are excluded from Git by `.local/`:

```text
<repo>/.local/qeo-mac/
├── config/mac.env
├── voices/chi-chi/reference.wav
└── cache/huggingface/
```

`reference.wav` must never be committed. The Compose stack mounts the voice directory read-only and keeps Hugging Face/model cache persistent across container recreation.

Required Mac environment values:

```text
QEO_MAC_DATA_ROOT
QEO_VOICE_TOKEN
QEO_VOICE_PORT=8765
```

The token is shared only with the authorized UpCloud caller. Do not put its real value in Git or documentation.

Start or refresh the stack:

```bash
./scripts/mac-up.sh
```
Stop containers without deleting persistent state:

```bash
./scripts/mac-down.sh
```

Inspect the local stack:

```bash
./scripts/mac-status.sh
```

## Private ingress

Tailscale stays native on macOS; it is infrastructure, not a skill container. The Docker service publishes only to loopback:

```text
127.0.0.1:8765 -> container:8765
```

Configure Tailscale Serve once on the Mac host to expose that loopback endpoint only inside the tailnet. Do not use Funnel and do not publish the container directly on `0.0.0.0`.

The approved mapping is:

```text
Tailnet :8765 -> 127.0.0.1:8765
```

Bearer authentication remains mandatory even though transport is inside Tailscale.
## Worker API

`GET /health` requires the bearer token. A healthy worker returns:

```json
{"status":"ok","engine":"v3turbo","default_voice":"chi-chi"}
```

`POST /v1/tts` requires the same token and accepts:

```json
{"text":"Xin chào","voice":"chi-chi"}
```

Success is `audio/ogg` containing OGG/Opus. VieNeu may use WAV/PCM internally on the Mac, but the network and Telegram transport is OGG/Opus.

The worker loads VieNeu and enrolls Chi Chi once at startup. Inference is single-flight: one generation runs at a time; concurrent requests return HTTP 503 `busy` rather than starting another model.

Hermes calls `/v1/tts` directly for each Telegram request. It does not perform a separate `/health` request per message.

## UpCloud configuration

Hermes remains native on UpCloud. Configure only connector values there:

```text
QEO_VOICE_WORKER_URL
QEO_VOICE_TOKEN
QEO_VOICE_TIMEOUT_SECONDS=90
```
Normal UpCloud deployment copies `skills/qeo-voice` and the shared `qeo-shortcuts` plugin. It never copies `workers/qeo-voice`, installs VieNeu, or performs local TTS computation.

## Telegram behavior

Preferred usage, especially for multiline text:

```text
/qeovoice "Dòng một
Dòng hai"
```

The handler removes only the outer quote pair and preserves embedded newlines. The legacy unquoted form remains supported:

```text
/qeovoice Xin chào anh Qeo
```

Empty input:

```text
Usage: /qeovoice "text"
```

Worker offline/network timeout:

```text
⚠️ Qeo Voice unavailable — Mac mini voice worker is offline.
```

Busy worker:

```text
⚠️ Qeo Voice is busy. Please try again in a moment.
```

Worker synthesis failure:

```text
⚠️ Qeo Voice failed to generate audio. Please try again.
```

No error path may invoke another TTS implementation. Telegram receives the successful `.ogg` as a native voice bubble; the temporary UpCloud file is deleted after send.
