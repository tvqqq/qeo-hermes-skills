"""Native Telegram fast-path for the qeo-story skill."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from ..interaction import INTERACTIONS, interaction_key, is_slash_command

PROMPT_TEXT = "🖼️ Hãy gửi ảnh screenshot trong vòng 1 phút."
INVALID_TEXT = "⚠️ Hãy gửi ảnh screenshot. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu."
EXPIRED_TEXT = "⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới."

HELP_TEXT = (
    "Tạo Qeo Story theo 2 cách:\n\n"
    "- Gửi ảnh screenshot kèm caption `/qeostory [preset]` để render ngay.\n"
    "- Gửi `/qeostory [preset]`, rồi gửi ảnh trong vòng 1 phút.\n\n"
    "Ví dụ: `/qeostory`, `/qeostory mango`, `/qeostory qeo-green`."
)

CMD_RE = re.compile(
    r"^\s*/(?:qeostory|qeo_story|qeo-story)(?:@\w+)?(?:\s+(?P<args>.*))?\s*$",
    re.IGNORECASE,
)

ALLOWED_PRESETS = {
    "qeo",
    "qeo-green",
    "mango",
    "mojito",
    "stellar",
    "midnight-city",
}


def _handle_qeostory_help(raw_args: str) -> str:
    return HELP_TEXT


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or "/opt/hermes/data")


def _profile_name(source) -> str:
    profile = str(getattr(source, "profile", None) or "").strip()
    return profile or "default"


def _skill_dir_for_source(source) -> Path:
    profile = _profile_name(source)
    base = _hermes_home()
    if profile == "default":
        return base / "skills" / "qeo-story"
    return base / "profiles" / profile / "skills" / "qeo-story"


def _extract_preset(raw_args: str) -> Optional[str]:
    if not raw_args:
        return None
    try:
        tokens = shlex.split(raw_args)
    except Exception:
        tokens = raw_args.split()
    for token in tokens:
        preset = token.strip().lower()
        if preset in ALLOWED_PRESETS:
            return preset
    return None


def _extract_local_image_path(event) -> Optional[str]:
    for item in getattr(event, "media_urls", None) or []:
        if isinstance(item, str) and os.path.exists(item):
            return item
    return None


def _schedule(coro) -> None:
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        asyncio.run(coro)


def _reply_metadata(source):
    thread_id = getattr(source, "thread_id", None)
    if not thread_id:
        return None
    return {"thread_id": thread_id, "message_thread_id": thread_id}


async def _send_text_to_source(gateway, source, message_id, text: str) -> None:
    adapter = gateway._adapter_for_source(source)
    if adapter is None:
        return
    await adapter.send(
        source.chat_id,
        text,
        reply_to=message_id,
        metadata=_reply_metadata(source),
    )


async def _send_text_reply(gateway, source, event, text: str) -> None:
    await _send_text_to_source(
        gateway, source, getattr(event, "message_id", None), text
    )


async def _send_image_reply(gateway, source, event, image_path: str) -> None:
    adapter = gateway._adapter_for_source(source)
    if adapter is None:
        return
    await adapter.send_image_file(
        chat_id=source.chat_id,
        image_path=image_path,
        caption=None,
        reply_to=getattr(event, "message_id", None),
        metadata=_reply_metadata(source),
    )


def _render_story(source, input_path: str, preset: Optional[str]) -> str:
    skill_dir = _skill_dir_for_source(source)
    script_path = skill_dir / "scripts" / "render_story.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing renderer script: {script_path}")

    out_dir = _hermes_home() / "cache" / "qeo-story"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"story-{int(time.time())}-{uuid.uuid4().hex[:8]}.png"

    cmd = [sys.executable, str(script_path), "--input", input_path, "--output", str(out_path)]
    if preset:
        cmd += ["--preset", preset]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or "render_story.py failed")
    if not out_path.exists():
        raise RuntimeError(f"Renderer finished but output not found: {out_path}")

    from PIL import Image
    with Image.open(out_path) as image:
        if image.format != "PNG" or image.size != (1080, 1920):
            raise RuntimeError(f"Invalid output: format={image.format}, size={image.size}")
    return str(out_path)


def _dispatch_story(event, gateway, source, image_path: str, preset: Optional[str]):
    try:
        output_path = _render_story(source, image_path, preset)
    except Exception as exc:
        _schedule(
            _send_text_reply(
                gateway, source, event, f"❌ Render thất bại: {str(exc)[:1500]}"
            )
        )
        return {"action": "skip", "reason": "qeostory-render-failed"}

    _schedule(_send_image_reply(gateway, source, event, output_path))
    return {"action": "skip", "reason": "qeostory-rendered"}


def _handle_qeostory_native(event, gateway, **kwargs):
    text = getattr(event, "text", None) or ""
    source = getattr(event, "source", None)
    if source is None:
        return None

    match = CMD_RE.match(text)
    if match:
        key = interaction_key(source)
        if key is not None:
            INTERACTIONS.clear(key)

        preset = _extract_preset(match.group("args") or "")
        image_path = _extract_local_image_path(event)
        if image_path:
            return _dispatch_story(event, gateway, source, image_path, preset)

        if key is None:
            return None

        async def on_expire(pending):
            await _send_text_to_source(
                gateway, pending.source, pending.message_id, EXPIRED_TEXT
            )

        INTERACTIONS.start(
            key,
            kind="story_image",
            payload={"preset": preset},
            source=source,
            message_id=getattr(event, "message_id", None),
            on_expire=on_expire,
        )
        _schedule(_send_text_reply(gateway, source, event, PROMPT_TEXT))
        return {"action": "skip", "reason": "qeostory-awaiting-image"}

    key = interaction_key(source)
    if key is None:
        return None
    pending = INTERACTIONS.peek(key)
    if pending is None or pending.kind != "story_image":
        return None
    if is_slash_command(text):
        return None

    image_path = _extract_local_image_path(event)
    if not image_path:
        _schedule(_send_text_reply(gateway, source, event, INVALID_TEXT))
        return {"action": "skip", "reason": "qeostory-invalid-followup"}

    pending = INTERACTIONS.take(key, "story_image")
    if pending is None:
        return None
    return _dispatch_story(
        event, gateway, source, image_path, pending.payload.get("preset")
    )


def register_story(ctx) -> None:
    ctx.register_command(
        "qeostory",
        handler=_handle_qeostory_help,
        description="Create a Qeo Story image from an attached screenshot",
    )
    ctx.register_hook("pre_gateway_dispatch", _handle_qeostory_native)
