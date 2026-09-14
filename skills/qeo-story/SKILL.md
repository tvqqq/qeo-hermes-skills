---
name: qeo-story
description: Beautify screenshots as Qeo story images.
version: 1.1.0
author: QeoQeo
metadata:
  hermes:
    tags: [image, screenshot, story, instagram, qeobench, pretty-shot]
    category: media
---

# Qeo Story

Turn one local PNG/JPEG/WebP into a deterministic **1080×1920 PNG** with the approved Qeo Story layout. Processing stays local.

## Telegram fast path

For Telegram, `qeo-shortcuts` supports both immediate and conversational flows:

```text
image + /qeostory [preset]  -> render immediately
/qeostory [preset]          -> ask for an image, valid for 60 seconds
```

In conversational mode the selected preset is preserved until the same user sends an image in the same chat/topic, or the request expires after 60 seconds. A new recognized Qeo command replaces the previous pending Qeo request for that identity.

These native gateway flows do **not** require terminal/code tools in the active agent profile and do not depend on an LLM response or `MEDIA:` directive. Supported shortcuts are `/qeostory` plus compatibility forms `/qeo_story` and `/qeo-story` when routed through the gateway plugin.

## Manual / non-gateway use

With a local input image and writable output path:

```bash
python3 scripts/render_story.py \
  --input "$INPUT" \
  --output "$OUTPUT"
```

Use `--preset qeo-green` by default. Other presets are `qeo`, `mango`, `mojito`, `stellar`, and `midnight-city`.

Keep the default footer `@QeoQeo` unless the user explicitly requests another footer. The renderer preserves source aspect ratio and does not crop or stretch by default.

List presets:

```bash
python3 scripts/render_story.py --list-presets --input ignored --output ignored
```

## Verification

A successful result must be a PNG exactly 1080×1920. Never claim a render succeeded unless the output file was actually produced and validated.

For exact visual constants, read `references/style-guide.md`.
