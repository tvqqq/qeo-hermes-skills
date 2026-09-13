---
name: qeo-voice
description: Generate Vietnamese voice notes through the private Qeo Voice worker.
version: 1.0.0
author: QeoQeo
metadata:
  hermes:
    tags: [voice, tts, vietnamese, telegram]
    category: media
---

# Qeo Voice

Generate Vietnamese speech with the Qeo Voice worker.

## Telegram

The Telegram shortcut is:

```text
/qeovoice <text>
```

The default registered voice is **Chi Chi** using the `tight-denoised` profile.

## Runtime ownership

Mac mini is the sole voice-compute authority. UpCloud/Hermes routes requests only.

There is **no fallback** TTS on UpCloud. If the Mac mini worker is offline, busy, or fails, the command returns an explicit status message and must not invoke VieNeu Nano/Turbo, Edge TTS, Hermes default TTS, or another provider on UpCloud.

## Worker dependency

The Telegram fast path is implemented by `qeo-shortcuts` and calls the private Mac worker over Tailscale. This skill package contains no VieNeu model, TTS runtime, or private voice reference audio.

## Voice registry

Public voice behavior lives in `workers/qeo-voice/voices.json`. Private samples are provisioned outside Git. Future voices are added to that registry plus the private asset store; they do not require a new Hermes skill.

See `references/voices.md` for the current voice contract.
