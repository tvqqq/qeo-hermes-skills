# Qeo Shortcuts Conversational Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 60-second conversational follow-up flows to `/qeovoice` and `/qeostory` while preserving every existing one-message fast path.

**Architecture:** Add one in-memory interaction manager shared by the existing shortcut handlers. State is keyed by `(profile, user_id, chat_id, thread_id)`, each key has at most one pending Qeo interaction, and each request owns a cancellable timeout plus a `request_id` stale-timeout guard. Voice/story continue to own parsing and execution; `pre_gateway_dispatch` consumes only the matching pending follow-up.

**Tech Stack:** Python 3.11 production, `asyncio`, `unittest`, Hermes `pre_gateway_dispatch`, Telegram adapter, existing qeo-voice worker, existing qeo-story renderer.

**Spec:** `docs/superpowers/specs/2026-09-14-qeo-shortcuts-conversational-input-design.md`

## Global Constraints

- TTL is exactly 60 seconds from the original command.
- State key is exactly `(profile, user_id, chat_id, thread_id)`.
- Conversation mode requires `source.user_id`; otherwise use existing help/usage behavior.
- One key has at most one pending Qeo interaction.
- Any newly recognized Qeo command clears the old pending request before immediate execution or new pending creation.
- Non-Qeo slash commands are never consumed and never reset TTL.
- Invalid follow-up keeps pending state and never extends TTL.
- Pending state is memory-only; restart recovery is out of scope.
- Qeo Voice keeps Mac mini as sole TTS compute host; no UpCloud fallback TTS.
- Existing `/qeovoice "text"`, `/qeovoice text`, and image + `/qeostory [preset]` remain compatible.

---

## File Map

- Create `plugins/qeo-shortcuts/interaction.py` — shared state/TTL/race manager.
- Create `tests/qeo_shortcuts_loader.py` — package-aware plugin test loader.
- Create `tests/test_qeo_shortcuts_interaction.py` — manager tests.
- Modify `plugins/qeo-shortcuts/handlers/voice.py` and `tests/test_qeo_shortcuts_voice.py`.
- Modify `plugins/qeo-shortcuts/handlers/story.py` and `tests/test_qeo_shortcuts_story.py`.
- Modify `plugins/qeo-shortcuts/plugin.yaml` — version `1.1.0`.
- Modify `README.md`, `docs/TELEGRAM-COMMANDS.md`, `docs/QEO-VOICE.md`, `skills/qeo-voice/SKILL.md`, `skills/qeo-story/SKILL.md`.

---

### Task 1: Shared Interaction Manager

**Files:** create `plugins/qeo-shortcuts/interaction.py`, `tests/qeo_shortcuts_loader.py`, `tests/test_qeo_shortcuts_interaction.py`; modify both existing shortcut test loaders.

**Produces:** `InteractionKey`, `PendingInteraction`, `interaction_key`, `is_slash_command`, `InteractionManager`, `INTERACTIONS`.

- [ ] **Step 1: Replace standalone handler test loading with a package-aware loader**

Create `tests/qeo_shortcuts_loader.py`:

```python
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugins" / "qeo-shortcuts"
PACKAGE = "qeo_shortcuts_test_plugin"


def load_shortcut_module(relative_name: str):
    if PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PACKAGE,
            PLUGIN_DIR / "__init__.py",
            submodule_search_locations=[str(PLUGIN_DIR)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load qeo-shortcuts package")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = package
        spec.loader.exec_module(package)
    return importlib.import_module(f"{PACKAGE}.{relative_name}")
```

In `test_qeo_shortcuts_voice.py` and `test_qeo_shortcuts_story.py`, replace their custom `importlib.util.spec_from_file_location(...)` loaders with:

```python
from tests.qeo_shortcuts_loader import load_shortcut_module

# voice
cls.voice = load_shortcut_module("handlers.voice")

# story
cls.story = load_shortcut_module("handlers.story")
```

- [ ] **Step 2: Verify loader-only change is GREEN**

```bash
python3 -m unittest tests.test_qeo_shortcuts_voice tests.test_qeo_shortcuts_story -v
```

Expected: all pre-existing tests PASS.

- [ ] **Step 3: Write failing interaction-manager tests**

Create `tests/test_qeo_shortcuts_interaction.py`:

```python
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.qeo_shortcuts_loader import load_shortcut_module

interaction = load_shortcut_module("interaction")


class InteractionManagerTests(unittest.IsolatedAsyncioTestCase):
    def source(self, **overrides):
        data = dict(profile="qeo-personal", user_id="7", chat_id="8", thread_id="9")
        data.update(overrides)
        return SimpleNamespace(**data)

    async def test_key_requires_user_and_includes_profile_chat_topic(self):
        self.assertEqual(interaction.interaction_key(self.source()), ("qeo-personal", "7", "8", "9"))
        self.assertIsNone(interaction.interaction_key(self.source(user_id=None)))

    async def test_default_ttl_is_60_seconds(self):
        manager = interaction.InteractionManager(clock=lambda: 100.0)
        pending = manager.start(
            ("p", "u", "c", "t"), kind="voice_text", payload={},
            source=self.source(), message_id="10", on_expire=mock.AsyncMock(),
        )
        self.assertEqual(pending.expires_at, 160.0)
        manager.clear(pending.key)
        await asyncio.sleep(0)

    async def test_take_cancels_timeout(self):
        expired = mock.AsyncMock()
        manager = interaction.InteractionManager(ttl_seconds=0.01)
        key = ("p", "u", "c", "t")
        manager.start(key, kind="voice_text", payload={}, source=self.source(), message_id="10", on_expire=expired)
        self.assertIsNotNone(manager.take(key, "voice_text"))
        await asyncio.sleep(0.03)
        expired.assert_not_awaited()

    async def test_replacement_only_expires_new_request(self):
        old_expire = mock.AsyncMock()
        new_expire = mock.AsyncMock()
        manager = interaction.InteractionManager(ttl_seconds=0.01)
        key = ("p", "u", "c", "t")
        manager.start(key, kind="voice_text", payload={}, source=self.source(), message_id="10", on_expire=old_expire)
        manager.start(key, kind="story_image", payload={"preset": "mango"}, source=self.source(), message_id="11", on_expire=new_expire)
        await asyncio.sleep(0.03)
        old_expire.assert_not_awaited()
        new_expire.assert_awaited_once()
        self.assertIsNone(manager.peek(key))

    async def test_slash_detection_only_checks_message_start(self):
        self.assertTrue(interaction.is_slash_command("  /help"))
        self.assertFalse(interaction.is_slash_command("hello /help"))
```

- [ ] **Step 4: Verify RED**

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction -v
```

Expected: import failure because `qeo_shortcuts_test_plugin.interaction` does not exist.

- [ ] **Step 5: Implement the manager exactly enough to satisfy the tests**

Create `plugins/qeo-shortcuts/interaction.py`:

```python
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

DEFAULT_TTL_SECONDS = 60.0
InteractionKey = Tuple[str, str, str, str]
ExpireCallback = Callable[["PendingInteraction"], Awaitable[None]]


@dataclass(frozen=True)
class PendingInteraction:
    request_id: str
    key: InteractionKey
    kind: str
    created_at: float
    expires_at: float
    payload: Dict[str, Any]
    source: Any
    message_id: Optional[str]


def interaction_key(source) -> Optional[InteractionKey]:
    user_id = str(getattr(source, "user_id", None) or "").strip()
    if not user_id:
        return None
    return (
        str(getattr(source, "profile", None) or "default"),
        user_id,
        str(getattr(source, "chat_id", None) or ""),
        str(getattr(source, "thread_id", None) or ""),
    )


def is_slash_command(text: str) -> bool:
    return (text or "").lstrip().startswith("/")


class InteractionManager:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, clock=time.monotonic):
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._pending: Dict[InteractionKey, PendingInteraction] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def start(self, key, *, kind, payload, source, message_id, on_expire: ExpireCallback):
        self.clear(key)
        now = self._clock()
        pending = PendingInteraction(
            request_id=uuid.uuid4().hex,
            key=key,
            kind=kind,
            created_at=now,
            expires_at=now + self._ttl_seconds,
            payload=dict(payload),
            source=source,
            message_id=message_id,
        )
        self._pending[key] = pending
        task = asyncio.get_running_loop().create_task(self._expire_after(pending, on_expire))
        self._tasks[pending.request_id] = task
        return pending

    async def _expire_after(self, pending: PendingInteraction, on_expire: ExpireCallback) -> None:
        try:
            await asyncio.sleep(self._ttl_seconds)
        except asyncio.CancelledError:
            return
        current = self._pending.get(pending.key)
        if current is None or current.request_id != pending.request_id:
            return
        self._pending.pop(pending.key, None)
        self._tasks.pop(pending.request_id, None)
        await on_expire(pending)

    def peek(self, key):
        return self._pending.get(key)

    def take(self, key, kind):
        current = self._pending.get(key)
        if current is None or current.kind != kind:
            return None
        self._pending.pop(key, None)
        task = self._tasks.pop(current.request_id, None)
        if task is not None:
            task.cancel()
        return current

    def clear(self, key):
        current = self._pending.pop(key, None)
        if current is None:
            return None
        task = self._tasks.pop(current.request_id, None)
        if task is not None:
            task.cancel()
        return current


INTERACTIONS = InteractionManager()
```

- [ ] **Step 6: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction tests.test_qeo_shortcuts_voice tests.test_qeo_shortcuts_story -v
git add plugins/qeo-shortcuts/interaction.py tests/qeo_shortcuts_loader.py tests/test_qeo_shortcuts_interaction.py tests/test_qeo_shortcuts_voice.py tests/test_qeo_shortcuts_story.py
git commit -m "feat: add qeo shortcut interaction state"
```

Expected: PASS, no pending-task or unawaited-coroutine warnings.

---

### Task 2: Qeo Voice Conversational Flow

**Files:** modify `plugins/qeo-shortcuts/handlers/voice.py`, `tests/test_qeo_shortcuts_voice.py`.

**Consumes:** `INTERACTIONS`, `interaction_key`, `is_slash_command`. Pending kind is `voice_text`.

- [ ] **Step 1: Add failing async voice-flow tests**

Change the test event helper so normal events include `user_id="7"`. Keep the legacy usage assertion by explicitly using `user_id=None` in that test. Add these tests to `QeoVoiceShortcutTests` and make the class `unittest.IsolatedAsyncioTestCase` so the real timeout task has a running loop:

```python
async def test_bare_command_starts_pending(self):
    event = self.event("/qeovoice")
    key = self.voice.interaction_key(event.source)
    scheduled = []
    with mock.patch.object(self.voice, "_schedule", side_effect=lambda coro: (scheduled.append(coro), coro.close())):
        result = self.voice._handle_qeovoice_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeovoice-awaiting-text"})
    self.assertEqual(self.voice.INTERACTIONS.peek(key).kind, "voice_text")
    self.assertEqual(len(scheduled), 1)
    self.voice.INTERACTIONS.clear(key)
    await asyncio.sleep(0)

async def test_followup_multiline_text_is_consumed(self):
    command = self.event("/qeovoice")
    key = self.voice.interaction_key(command.source)
    self.voice.INTERACTIONS.start(key, kind="voice_text", payload={}, source=command.source, message_id="10", on_expire=mock.AsyncMock())
    followup = self.event("Dòng một\nDòng hai")
    process = mock.Mock()
    with mock.patch.object(self.voice, "_schedule"), mock.patch.object(self.voice, "_process_qeovoice", new=process):
        result = self.voice._handle_qeovoice_native(followup, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeovoice-followup-dispatched"})
    process.assert_called_once_with(followup, mock.ANY, "Dòng một\nDòng hai")
    self.assertIsNone(self.voice.INTERACTIONS.peek(key))

async def test_invalid_followup_keeps_pending(self):
    event = self.event("")
    key = self.voice.interaction_key(event.source)
    self.voice.INTERACTIONS.start(key, kind="voice_text", payload={}, source=event.source, message_id="10", on_expire=mock.AsyncMock())
    scheduled = []
    with mock.patch.object(self.voice, "_schedule", side_effect=lambda coro: (scheduled.append(coro), coro.close())):
        result = self.voice._handle_qeovoice_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeovoice-invalid-followup"})
    self.assertIsNotNone(self.voice.INTERACTIONS.peek(key))
    self.voice.INTERACTIONS.clear(key)
    await asyncio.sleep(0)

async def test_other_slash_command_passes_through_and_keeps_pending(self):
    event = self.event("/help")
    key = self.voice.interaction_key(event.source)
    self.voice.INTERACTIONS.start(key, kind="voice_text", payload={}, source=event.source, message_id="10", on_expire=mock.AsyncMock())
    self.assertIsNone(self.voice._handle_qeovoice_native(event, object()))
    self.assertIsNotNone(self.voice.INTERACTIONS.peek(key))
    self.voice.INTERACTIONS.clear(key)
    await asyncio.sleep(0)

async def test_immediate_voice_command_clears_old_pending(self):
    event = self.event('/qeovoice "Xin chào"')
    key = self.voice.interaction_key(event.source)
    self.voice.INTERACTIONS.start(key, kind="story_image", payload={"preset": "mango"}, source=event.source, message_id="9", on_expire=mock.AsyncMock())
    with mock.patch.object(self.voice, "_schedule"):
        result = self.voice._handle_qeovoice_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeovoice-dispatched"})
    self.assertIsNone(self.voice.INTERACTIONS.peek(key))
```

Add one async expiry test with `mock.patch.object(self.voice.INTERACTIONS, "_ttl_seconds", 0.01)` and a `FakeGateway/FakeAdapter`; assert the exact text is `⏱️ Yêu cầu Qeo Voice đã hết hạn. Hãy gửi lại /qeovoice để tạo voice mới.`. Add one bare-command test with `source.user_id=None`; assert no pending state and existing `USAGE_TEXT` is scheduled.

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest tests.test_qeo_shortcuts_voice -v
```

Expected: bare command/follow-up/expiry tests FAIL because current handler is stateless.

- [ ] **Step 3: Implement voice behavior**

Add imports:

```python
from ..interaction import INTERACTIONS, interaction_key, is_slash_command
```

Add exact copy:

```python
PROMPT_TEXT = "🎙️ Bạn muốn Chi Chi đọc nội dung gì? Hãy gửi text trong vòng 1 phút."
INVALID_TEXT = "⚠️ Hãy gửi nội dung text. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu."
EXPIRED_TEXT = "⏱️ Yêu cầu Qeo Voice đã hết hạn. Hãy gửi lại /qeovoice để tạo voice mới."
```

Implement `_handle_qeovoice_native` in this order:

```python
source = getattr(event, "source", None)
if source is None:
    return None
text = getattr(event, "text", None) or ""
match = CMD_RE.match(text)

if match:
    key = interaction_key(source)
    if key is not None:
        INTERACTIONS.clear(key)
    speech = (match.group("args") or "").strip()
    if len(speech) >= 2 and speech.startswith('"') and speech.endswith('"'):
        speech = speech[1:-1]
    if speech.strip():
        _schedule(_process_qeovoice(event, gateway, speech))
        return {"action": "skip", "reason": "qeovoice-dispatched"}
    if key is None:
        _schedule(_send_text_reply(gateway, source, event, USAGE_TEXT))
        return {"action": "skip", "reason": "qeovoice-usage"}

    async def expire(_pending):
        await _send_text_reply(gateway, source, event, EXPIRED_TEXT)

    INTERACTIONS.start(key, kind="voice_text", payload={}, source=source,
                       message_id=getattr(event, "message_id", None), on_expire=expire)
    _schedule(_send_text_reply(gateway, source, event, PROMPT_TEXT))
    return {"action": "skip", "reason": "qeovoice-awaiting-text"}

key = interaction_key(source)
if key is None:
    return None
pending = INTERACTIONS.peek(key)
if pending is None or pending.kind != "voice_text":
    return None
if is_slash_command(text):
    return None
if not text.strip():
    _schedule(_send_text_reply(gateway, source, event, INVALID_TEXT))
    return {"action": "skip", "reason": "qeovoice-invalid-followup"}
INTERACTIONS.take(key, "voice_text")
_schedule(_process_qeovoice(event, gateway, text))
return {"action": "skip", "reason": "qeovoice-followup-dispatched"}
```

Do not change worker HTTP, OGG/Opus, offline/busy/failure strings, or fallback behavior.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction tests.test_qeo_shortcuts_voice -v
git add plugins/qeo-shortcuts/handlers/voice.py tests/test_qeo_shortcuts_voice.py
git commit -m "feat: add conversational qeovoice input"
```

Expected: PASS without coroutine warnings.

---

### Task 3: Qeo Story Conversational Flow

**Files:** modify `plugins/qeo-shortcuts/handlers/story.py`, `tests/test_qeo_shortcuts_story.py`.

**Consumes:** shared interaction API. Pending kind is `story_image`; payload is `{"preset": Optional[str]}`.

- [ ] **Step 1: Add failing async story-flow tests**

Make `StoryShortcutTests` an `IsolatedAsyncioTestCase` and include `user_id="7"` in normal event sources. Add:

```python
async def test_command_without_image_starts_pending_with_preset(self):
    event = self.event(text="/qeostory mango", media_urls=[])
    key = self.story.interaction_key(event.source)
    with mock.patch.object(self.story, "_schedule", side_effect=lambda coro: coro.close()):
        result = self.story._handle_qeostory_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeostory-awaiting-image"})
    self.assertEqual(self.story.INTERACTIONS.peek(key).payload, {"preset": "mango"})
    self.story.INTERACTIONS.clear(key)
    await asyncio.sleep(0)

async def test_pending_story_consumes_image_with_saved_preset(self):
    event = self.event(text="caption", media_urls=["/tmp/input.jpg"])
    key = self.story.interaction_key(event.source)
    self.story.INTERACTIONS.start(key, kind="story_image", payload={"preset": "mango"}, source=event.source, message_id="10", on_expire=mock.AsyncMock())
    with mock.patch.object(self.story.os.path, "exists", return_value=True), \
         mock.patch.object(self.story, "_render_story", return_value="/tmp/out.png") as render, \
         mock.patch.object(self.story, "_schedule"):
        result = self.story._handle_qeostory_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeostory-rendered"})
    render.assert_called_once_with(event.source, "/tmp/input.jpg", "mango")
    self.assertIsNone(self.story.INTERACTIONS.peek(key))

async def test_text_only_followup_reminds_and_keeps_pending(self):
    event = self.event(text="hello", media_urls=[])
    key = self.story.interaction_key(event.source)
    self.story.INTERACTIONS.start(key, kind="story_image", payload={"preset": None}, source=event.source, message_id="10", on_expire=mock.AsyncMock())
    with mock.patch.object(self.story, "_schedule", side_effect=lambda coro: coro.close()):
        result = self.story._handle_qeostory_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeostory-invalid-followup"})
    self.assertIsNotNone(self.story.INTERACTIONS.peek(key))
    self.story.INTERACTIONS.clear(key)
    await asyncio.sleep(0)

async def test_help_slash_passes_through_while_story_stays_pending(self):
    event = self.event(text="/help", media_urls=[])
    key = self.story.interaction_key(event.source)
    self.story.INTERACTIONS.start(key, kind="story_image", payload={"preset": None}, source=event.source, message_id="10", on_expire=mock.AsyncMock())
    self.assertIsNone(self.story._handle_qeostory_native(event, object()))
    self.assertIsNotNone(self.story.INTERACTIONS.peek(key))
    self.story.INTERACTIONS.clear(key)
    await asyncio.sleep(0)

async def test_story_command_replaces_voice_pending(self):
    event = self.event(text="/qeostory mango", media_urls=[])
    key = self.story.interaction_key(event.source)
    self.story.INTERACTIONS.start(key, kind="voice_text", payload={}, source=event.source, message_id="9", on_expire=mock.AsyncMock())
    with mock.patch.object(self.story, "_schedule", side_effect=lambda coro: coro.close()):
        self.story._handle_qeostory_native(event, object())
    self.assertEqual(self.story.INTERACTIONS.peek(key).kind, "story_image")
    self.story.INTERACTIONS.clear(key)
    await asyncio.sleep(0)
```

Add an expiry test asserting exact text `⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới.`. Add a missing-user test asserting a no-image command returns `None` and creates no state. Keep the current image + command immediate regression test.

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest tests.test_qeo_shortcuts_story -v
```

Expected: new pending-flow tests FAIL against the current stateless handler.

- [ ] **Step 3: Extract shared story dispatch helper and implement pending flow**

Add imports and exact copy:

```python
from ..interaction import INTERACTIONS, interaction_key, is_slash_command

PROMPT_TEXT = "🖼️ Hãy gửi ảnh screenshot trong vòng 1 phút."
INVALID_TEXT = "⚠️ Hãy gửi ảnh screenshot. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu."
EXPIRED_TEXT = "⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới."
```

Extract:

```python
def _dispatch_story(event, gateway, source, image_path: str, preset: Optional[str]):
    try:
        output_path = _render_story(source, image_path, preset)
    except Exception as exc:
        _schedule(_send_text_reply(gateway, source, event, f"❌ Render thất bại: {str(exc)[:1500]}"))
        return {"action": "skip", "reason": "qeostory-render-failed"}
    _schedule(_send_image_reply(gateway, source, event, output_path))
    return {"action": "skip", "reason": "qeostory-rendered"}
```

Implement handler order:

```python
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

    async def expire(_pending):
        await _send_text_reply(gateway, source, event, EXPIRED_TEXT)

    INTERACTIONS.start(key, kind="story_image", payload={"preset": preset}, source=source,
                       message_id=getattr(event, "message_id", None), on_expire=expire)
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
preset = pending.payload.get("preset") if pending else None
return _dispatch_story(event, gateway, source, image_path, preset)
```

- [ ] **Step 4: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction tests.test_qeo_shortcuts_story tests.test_qeo_shortcuts_voice -v
git add plugins/qeo-shortcuts/handlers/story.py tests/test_qeo_shortcuts_story.py
git commit -m "feat: add conversational qeostory input"
```

Expected: PASS, including replacement and immediate-mode regressions.

---

### Task 4: Documentation, Full Verification, Deployment, Acceptance

**Files:** modify `plugins/qeo-shortcuts/plugin.yaml`, `README.md`, `docs/TELEGRAM-COMMANDS.md`, `docs/QEO-VOICE.md`, `skills/qeo-voice/SKILL.md`, `skills/qeo-story/SKILL.md`.

- [ ] **Step 1: Update runtime metadata and docs**

Set:

```yaml
name: qeo-shortcuts
version: 1.1.0
description: Telegram shortcuts for Qeo custom skills
provides_hooks:
  - pre_gateway_dispatch
```

Document exactly:

```text
/qeovoice "text" -> immediate voice
/qeovoice          -> prompt -> text within 60 seconds -> voice

image + /qeostory [preset] -> immediate render
/qeostory [preset]         -> prompt -> image within 60 seconds -> render
```

Also document: same profile/user/chat/topic isolation, one pending request per key, command replacement, proactive 60-second expiry, non-Qeo slash passthrough, memory-only state, and unchanged qeo-voice no-fallback.

- [ ] **Step 2: Run repository verification**

```bash
./scripts/verify.sh --repo-only
```

Expected: `verify: repository checks passed`.

- [ ] **Step 3: Run macOS-only tests**

```bash
python3 -m unittest tests.test_qeo_mac_docker -v
```

Expected: PASS.

- [ ] **Step 4: Run the complete non-macOS suite in Python 3.12**

```bash
docker run --rm -v "$PWD:/repo" -w /repo qeo-mac-qeo-voice-worker:latest \
  sh -lc 'python -m pip install --quiet Pillow && python -m unittest \
    tests.test_deploy_scripts \
    tests.test_qeo_shortcuts_interaction \
    tests.test_qeo_shortcuts_story \
    tests.test_qeo_shortcuts_voice \
    tests.test_qeo_voice_registry \
    tests.test_qeo_voice_repo_contract \
    tests.test_qeo_voice_worker \
    tests.test_story_renderer -v'
```

Expected: PASS. Third-party deprecation warnings are acceptable; failures and unawaited-coroutine warnings are not.

- [ ] **Step 5: Review diff and commit docs/versioning**

```bash
git diff --check
git status --short
git diff HEAD~3..HEAD -- plugins/qeo-shortcuts tests README.md docs skills/qeo-voice skills/qeo-story
git add plugins/qeo-shortcuts/plugin.yaml README.md docs/TELEGRAM-COMMANDS.md docs/QEO-VOICE.md skills/qeo-voice/SKILL.md skills/qeo-story/SKILL.md
git commit -m "docs: document conversational qeo shortcuts"
```

Confirm no worker API changes, no UpCloud TTS imports/fallback, no private audio/token files, and no unrelated refactor.

- [ ] **Step 6: Push and deploy exact branch tip**

```bash
git push origin feat/qeo-voice
sudo ./scripts/deploy.sh qeo-voice --hermes-home /opt/hermes/data --profiles all
```

Run plugin doctor and gateway status after restart. Do not deploy `workers/qeo-voice` or install VieNeu on UpCloud.

- [ ] **Step 7: Telegram production acceptance**

Run all scenarios:

```text
1. /qeovoice
   -> prompt
   -> multiline text within 60 seconds
   -> one native voice bubble

2. /qeostory mango
   -> prompt
   -> screenshot within 60 seconds
   -> rendered mango story

3. /qeovoice
   -> no reply for >60 seconds
   -> exactly one voice expiry alert

4. /qeovoice
   -> then /qeostory mango before replying
   -> story prompt replaces voice pending
   -> no stale voice expiry alert
   -> screenshot produces story

5. Start a pending flow, then send /help
   -> /help goes through Hermes
   -> pending request still expires at its original deadline
```

Acceptance requires all five scenarios to pass without an LLM turn consuming a valid pending input and without any qeo-voice fallback TTS.

- [ ] **Step 8: Final branch status**

```bash
git status --short
git log --oneline -6
```

Expected: clean worktree with the interaction, voice, story, and docs commits at branch tip.