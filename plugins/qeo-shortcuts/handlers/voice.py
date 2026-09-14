"""Native Telegram fast-path for qeo-voice."""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path

USAGE_TEXT = 'Usage: /qeovoice "text"'
OFFLINE_TEXT = "⚠️ Qeo Voice unavailable — Mac mini voice worker is offline."
BUSY_TEXT = "⚠️ Qeo Voice is busy. Please try again in a moment."
FAILED_TEXT = "⚠️ Qeo Voice failed to generate audio. Please try again."
MAX_AUDIO_BYTES = 20 * 1024 * 1024

CMD_RE = re.compile(
    r"^\s*/qeovoice(?:@\w+)?(?:\s+(?P<args>.*))?\s*$",
    re.IGNORECASE | re.DOTALL,
)


class WorkerOfflineError(RuntimeError):
    pass


class WorkerBusyError(RuntimeError):
    pass


class WorkerGenerationError(RuntimeError):
    pass


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or "/opt/hermes/data")


def _reply_metadata(source):
    thread_id = getattr(source, "thread_id", None)
    if not thread_id:
        return None
    return {"thread_id": thread_id, "message_thread_id": thread_id}


def _schedule(coro) -> None:
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        asyncio.run(coro)


async def _send_text_reply(gateway, source, event, text: str) -> None:
    adapter = gateway._adapter_for_source(source)
    if adapter is None:
        return
    await adapter.send(
        source.chat_id,
        text,
        reply_to=getattr(event, "message_id", None),
        metadata=_reply_metadata(source),
    )


async def _send_voice_reply(gateway, source, event, audio_path: Path) -> None:
    adapter = gateway._adapter_for_source(source)
    if adapter is None:
        return
    await adapter.send_voice(
        chat_id=source.chat_id,
        audio_path=str(audio_path),
        caption=None,
        reply_to=getattr(event, "message_id", None),
        metadata=_reply_metadata(source),
    )


def _worker_timeout() -> float:
    raw = os.environ.get("QEO_VOICE_TIMEOUT_SECONDS", "90")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 90.0
    return value if value > 0 else 90.0


def _worker_config() -> tuple[str, str, float]:
    url = (os.environ.get("QEO_VOICE_WORKER_URL") or "").strip().rstrip("/")
    token = (os.environ.get("QEO_VOICE_TOKEN") or "").strip()
    if not url or not token:
        raise WorkerOfflineError()
    return url, token, _worker_timeout()


def _read_worker_audio(response) -> bytes:
    data = response.read(MAX_AUDIO_BYTES + 1)
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise WorkerGenerationError()
    return data


def _request_worker(text: str) -> bytes:
    url, token, timeout = _worker_config()
    payload = json.dumps({"text": text, "voice": "chi-chi"}).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/v1/tts",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "audio/ogg",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _read_worker_audio(response)
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_AUDIO_BYTES + 1)
        if exc.code == 503:
            try:
                if json.loads(body.decode("utf-8")).get("error") == "busy":
                    raise WorkerBusyError() from exc
            except (ValueError, UnicodeDecodeError):
                pass
        raise WorkerGenerationError() from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
        raise WorkerOfflineError() from exc


async def _process_qeovoice(event, gateway, text: str) -> None:
    source = getattr(event, "source", None)
    if source is None:
        return
    try:
        audio = await asyncio.to_thread(_request_worker, text)
    except WorkerOfflineError:
        await _send_text_reply(gateway, source, event, OFFLINE_TEXT)
        return
    except WorkerBusyError:
        await _send_text_reply(gateway, source, event, BUSY_TEXT)
        return
    except WorkerGenerationError:
        await _send_text_reply(gateway, source, event, FAILED_TEXT)
        return

    out_dir = _hermes_home() / "audio_cache" / "qeovoice"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"qeovoice-{uuid.uuid4().hex}.ogg"
    try:
        out_path.write_bytes(audio)
        await _send_voice_reply(gateway, source, event, out_path)
    finally:
        try:
            out_path.unlink()
        except FileNotFoundError:
            pass


def _handle_qeovoice_help(raw_args: str) -> str:
    return USAGE_TEXT


def _handle_qeovoice_native(event, gateway, **kwargs):
    text = getattr(event, "text", None) or ""
    match = CMD_RE.match(text)
    if not match:
        return None
    source = getattr(event, "source", None)
    if source is None:
        return None

    speech = (match.group("args") or "").strip()
    if len(speech) >= 2 and speech.startswith('"') and speech.endswith('"'):
        speech = speech[1:-1]
    if not speech.strip():
        _schedule(_send_text_reply(gateway, source, event, USAGE_TEXT))
        return {"action": "skip", "reason": "qeovoice-usage"}

    _schedule(_process_qeovoice(event, gateway, speech))
    return {"action": "skip", "reason": "qeovoice-dispatched"}


def register_voice(ctx) -> None:
    ctx.register_command(
        "qeovoice",
        handler=_handle_qeovoice_help,
        description="Generate a Chi Chi Telegram voice message via the Mac mini worker",
    )
    ctx.register_hook("pre_gateway_dispatch", _handle_qeovoice_native)
