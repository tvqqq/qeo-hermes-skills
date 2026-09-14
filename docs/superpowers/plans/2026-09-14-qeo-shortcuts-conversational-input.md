# Qeo Shortcuts Conversational Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 60-second conversational follow-up flows to `/qeovoice` and `/qeostory` while preserving every existing one-message fast path.

**Architecture:** Add one in-memory interaction manager shared by the existing shortcut handlers. State is keyed by `(profile, user_id, chat_id, thread_id)`, each key has at most one pending Qeo interaction, and each request owns a cancellable timeout plus `request_id` stale-timeout guard. The existing voice/story handlers remain responsible for command parsing and action execution; `pre_gateway_dispatch` continues to skip consumed follow-ups before the LLM.

**Tech Stack:** Python 3.11 production, Python `asyncio`, `unittest`, existing Hermes `pre_gateway_dispatch` plugin API, Telegram adapter, existing qeo-voice worker and qeo-story renderer.

**Spec:** `docs/superpowers/specs/2026-09-14-qeo-shortcuts-conversational-input-design.md`

## Global Constraints

- Pending TTL is exactly 60 seconds from the original command.
- State key is exactly `(profile, user_id, chat_id, thread_id)`.
- Conversation mode requires `source.user_id`; missing identity falls back to existing help/usage behavior.
- Only one pending Qeo interaction may exist per key.
- A newly recognized Qeo command clears the previous pending request before immediate execution or creation of new pending state.
- Non-Qeo slash commands are never consumed as pending input and do not reset TTL.
- Invalid follow-up input keeps state and does not extend TTL.
- Pending state is in-memory only; gateway restart recovery is out of scope.
- Qeo Voice keeps Mac mini as sole TTS compute host; no server-side TTS fallback may be introduced.
- Existing `/qeovoice "text"`, `/qeovoice text`, and image + `/qeostory [preset]` fast paths remain compatible.

---

## File Structure

- Create `plugins/qeo-shortcuts/interaction.py`: pending-state model, key normalization, slash-command detection, timeout lifecycle, replacement, take/clear operations.
- Create `tests/qeo_shortcuts_loader.py`: package-aware test loader so handler relative imports work under unit tests.
- Create `tests/test_qeo_shortcuts_interaction.py`: isolated manager/TTL/race tests.
- Modify `plugins/qeo-shortcuts/handlers/voice.py`: bare-command prompt, pending text consumption, timeout/reminder copy, replacement clearing.
- Modify `tests/test_qeo_shortcuts_voice.py`: conversational voice behavior and regression coverage.
- Modify `plugins/qeo-shortcuts/handlers/story.py`: bare-command prompt, preset-preserving pending image flow, timeout/reminder copy, shared render dispatch helper.
- Modify `tests/test_qeo_shortcuts_story.py`: conversational story behavior and regression coverage.
- Modify `plugins/qeo-shortcuts/plugin.yaml`: bump plugin version for the new gateway behavior.
- Modify `README.md`, `docs/TELEGRAM-COMMANDS.md`, `docs/QEO-VOICE.md`, `skills/qeo-voice/SKILL.md`, `skills/qeo-story/SKILL.md`: document both immediate and conversational modes.

---

### Task 1: Shared Interaction Manager

**Files:**
- Create: `plugins/qeo-shortcuts/interaction.py`
- Create: `tests/qeo_shortcuts_loader.py`
- Create: `tests/test_qeo_shortcuts_interaction.py`
- Modify: `tests/test_qeo_shortcuts_voice.py`
- Modify: `tests/test_qeo_shortcuts_story.py`

**Interfaces:**
- Produces: `interaction_key(source) -> Optional[InteractionKey]`
- Produces: `is_slash_command(text: str) -> bool`
- Produces: `PendingInteraction`
- Produces: `InteractionManager.start(...)`, `.peek(key)`, `.take(key, kind)`, `.clear(key)`
- Produces singleton: `INTERACTIONS = InteractionManager()`

- [ ] **Step 1: Add package-aware test loader before production imports change**

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
        module = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = module
        spec.loader.exec_module(module)
    return importlib.import_module(f"{PACKAGE}.{relative_name}")
```

Update the two existing handler tests to use `load_shortcut_module("handlers.voice")` and `load_shortcut_module("handlers.story")` instead of loading each handler as a standalone module.

- [ ] **Step 2: Run existing shortcut tests and verify the loader refactor is green**

Run:

```bash
python3 -m unittest tests.test_qeo_shortcuts_voice tests.test_qeo_shortcuts_story -v
```

Expected: all existing voice/story tests PASS before interaction production code exists.

- [ ] **Step 3: Write failing manager tests**

Create `tests/test_qeo_shortcuts_interaction.py` with tests equivalent to:

```python
import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.qeo_shortcuts_loader import load_shortcut_module

interaction = load_shortcut_module("interaction")


class InteractionManagerTests(unittest.IsolatedAsyncioTestCase):
    def source(self, **overrides):
        values = dict(profile="qeo-personal", user_id="7", chat_id="8", thread_id="9")
        values.update(overrides)
        return SimpleNamespace(**values)

    async def test_key_requires_user_and_isolates_profile_chat_and_topic(self):
        self.assertEqual(
            interaction.interaction_key(self.source()),
            ("qeo-personal", "7", "8", "9"),
        )
        self.assertIsNone(interaction.interaction_key(self.source(user_id=None)))

    async def test_default_ttl_is_exactly_60_seconds(self):
        manager = interaction.InteractionManager(clock=lambda: 100.0)
        pending = manager.start(
            ("p", "u", "c", "t"), kind="voice_text", payload={},
            source=self.source(), message_id="10", on_expire=mock.AsyncMock(),
        )
        self.assertEqual(pending.expires_at, 160.0)
        manager.clear(pending.key)

    async def test_completion_cancels_expiry(self):
        expired = mock.AsyncMock()
        manager = interaction.InteractionManager(ttl_seconds=0.01)
        key = ("p", "u", "c", "t")
        manager.start(key, kind="voice_text", payload={}, source=self.source(), message_id="10", on_expire=expired)
        taken = manager.take(key, "voice_text")
        self.assertIsNotNone(taken)
        await asyncio.sleep(0.03)
        expired.assert_not_awaited()

    async def test_replacement_suppresses_stale_timeout(self):
        first = mock.AsyncMock()
        second = mock.AsyncMock()
        manager = interaction.InteractionManager(ttl_seconds=0.01)
        key = ("p", "u", "c", "t")
        manager.start(key, kind="voice_text", payload={}, source=self.source(), message_id="10", on_expire=first)
        manager.start(key, kind="story_image", payload={"preset": "mango"}, source=self.source(), message_id="11", on_expire=second)
        await asyncio.sleep(0.03)
        first.assert_not_awaited()
        second.assert_awaited_once()

    async def test_slash_command_detection(self):
        self.assertTrue(interaction.is_slash_command("  /help"))
        self.assertFalse(interaction.is_slash_command("hello /help"))
```

- [ ] **Step 4: Run manager tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction -v
```

Expected: FAIL because `qeo_shortcuts_test_plugin.interaction` does not exist yet.

- [ ] **Step 5: Implement the minimal interaction manager**

Create `plugins/qeo-shortcuts/interaction.py` with this public shape:

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
    profile = str(getattr(source, "profile", None) or "default")
    chat_id = str(getattr(source, "chat_id", None) or "")
    thread_id = str(getattr(source, "thread_id", None) or "")
    return (profile, user_id, chat_id, thread_id)


def is_slash_command(text: str) -> bool:
    return (text or "").lstrip().startswith("/")
```

Implement `InteractionManager` so `start()` first clears the old key, records a new `PendingInteraction`, creates an `asyncio` timeout task, and the timeout checks the same `request_id` before popping state and awaiting `on_expire`. `take(key, kind)` only removes matching kinds and cancels their task; `clear(key)` removes any kind and cancels its task; `peek(key)` is read-only. Export `INTERACTIONS = InteractionManager()`.

- [ ] **Step 6: Run manager + existing shortcut tests and verify GREEN**

Run:

```bash
python3 -m unittest \
  tests.test_qeo_shortcuts_interaction \
  tests.test_qeo_shortcuts_voice \
  tests.test_qeo_shortcuts_story -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add plugins/qeo-shortcuts/interaction.py tests/qeo_shortcuts_loader.py \
  tests/test_qeo_shortcuts_interaction.py tests/test_qeo_shortcuts_voice.py \
  tests/test_qeo_shortcuts_story.py
git commit -m "feat: add qeo shortcut interaction state"
```

---

### Task 2: Qeo Voice Conversational Text Flow

**Files:**
- Modify: `plugins/qeo-shortcuts/handlers/voice.py`
- Modify: `tests/test_qeo_shortcuts_voice.py`

**Interfaces:**
- Consumes: `interaction_key`, `is_slash_command`, `INTERACTIONS`
- Pending kind: `voice_text`
- Existing execution path remains: `_process_qeovoice(event, gateway, text)`

- [ ] **Step 1: Write failing conversational voice tests**

Add tests covering these concrete behaviors:

```python
def test_bare_command_starts_voice_pending_and_prompts(self):
    event = self.event("/qeovoice")
    scheduled = []
    with mock.patch.object(self.voice, "_schedule", side_effect=lambda coro: (scheduled.append(coro), coro.close())):
        result = self.voice._handle_qeovoice_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeovoice-awaiting-text"})
    self.assertEqual(self.voice.INTERACTIONS.peek(self.voice.interaction_key(event.source)).kind, "voice_text")
    self.assertEqual(len(scheduled), 1)


def test_pending_voice_consumes_multiline_followup(self):
    command = self.event("/qeovoice")
    followup = self.event("Dòng một\nDòng hai")
    process = mock.Mock()
    self.voice.INTERACTIONS.start(
        self.voice.interaction_key(command.source), kind="voice_text", payload={},
        source=command.source, message_id=command.message_id, on_expire=mock.AsyncMock(),
    )
    with mock.patch.object(self.voice, "_schedule"), mock.patch.object(self.voice, "_process_qeovoice", new=process):
        result = self.voice._handle_qeovoice_native(followup, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeovoice-followup-dispatched"})
    process.assert_called_once_with(followup, mock.ANY, "Dòng một\nDòng hai")
    self.assertIsNone(self.voice.INTERACTIONS.peek(self.voice.interaction_key(command.source)))


def test_pending_voice_does_not_consume_other_slash_command(self):
    event = self.event("/help")
    key = self.voice.interaction_key(event.source)
    self.voice.INTERACTIONS.start(key, kind="voice_text", payload={}, source=event.source, message_id="1", on_expire=mock.AsyncMock())
    self.assertIsNone(self.voice._handle_qeovoice_native(event, object()))
    self.assertIsNotNone(self.voice.INTERACTIONS.peek(key))
```

Also add: invalid image/no-text reminder keeps pending; missing `user_id` bare command uses usage instead of state; immediate `/qeovoice "text"` clears an older pending interaction before dispatch; expiry callback uses the exact approved timeout message.

- [ ] **Step 2: Run voice tests and verify RED**

```bash
python3 -m unittest tests.test_qeo_shortcuts_voice -v
```

Expected: new conversational tests FAIL because bare `/qeovoice` still returns usage and follow-ups are not consumed.

- [ ] **Step 3: Implement voice command and follow-up behavior**

In `voice.py` import the shared interaction API and define exact copy:

```python
PROMPT_TEXT = "🎙️ Bạn muốn Chi Chi đọc nội dung gì? Hãy gửi text trong vòng 1 phút."
INVALID_TEXT = "⚠️ Hãy gửi nội dung text. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu."
EXPIRED_TEXT = "⏱️ Yêu cầu Qeo Voice đã hết hạn. Hãy gửi lại /qeovoice để tạo voice mới."
```

Handler order must be:

1. If the event matches `/qeovoice`, derive the key and clear any existing pending state first.
2. If command text is non-empty, execute the existing immediate path unchanged.
3. If bare command has no key because `user_id` is missing, send `USAGE_TEXT` and skip.
4. Otherwise start `voice_text` pending with an expiry callback that sends `EXPIRED_TEXT` to the original source/message, send `PROMPT_TEXT`, and skip.
5. For non-command events, look up the same key. If no `voice_text` pending exists, return `None`.
6. If `is_slash_command(event.text)` is true, return `None` without mutating state.
7. If `event.text` is missing/whitespace, send `INVALID_TEXT`, keep state, and skip.
8. Otherwise `take()` the pending state before scheduling `_process_qeovoice`; pass the full follow-up text, preserving embedded newlines; return `qeovoice-followup-dispatched`.

Do not change `_request_worker`, OGG/Opus handling, exact offline/busy/failure messages, or fallback behavior.

- [ ] **Step 4: Run voice + interaction tests and verify GREEN**

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction tests.test_qeo_shortcuts_voice -v
```

Expected: PASS with no coroutine warnings.

- [ ] **Step 5: Commit Task 2**

```bash
git add plugins/qeo-shortcuts/handlers/voice.py tests/test_qeo_shortcuts_voice.py
git commit -m "feat: add conversational qeovoice input"
```

---

### Task 3: Qeo Story Conversational Image Flow

**Files:**
- Modify: `plugins/qeo-shortcuts/handlers/story.py`
- Modify: `tests/test_qeo_shortcuts_story.py`

**Interfaces:**
- Consumes: `interaction_key`, `is_slash_command`, `INTERACTIONS`
- Pending kind: `story_image`
- Pending payload: `{"preset": Optional[str]}`
- Existing renderer remains: `_render_story(source, input_path, preset)`

- [ ] **Step 1: Write failing conversational story tests**

Add tests equivalent to:

```python
def test_bare_story_command_without_image_starts_pending(self):
    event = self.event(text="/qeostory mango", media_urls=[])
    scheduled = []
    with mock.patch.object(self.story, "_schedule", side_effect=lambda coro: (scheduled.append(coro), coro.close())):
        result = self.story._handle_qeostory_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeostory-awaiting-image"})
    pending = self.story.INTERACTIONS.peek(self.story.interaction_key(event.source))
    self.assertEqual(pending.payload["preset"], "mango")


def test_pending_story_consumes_image_with_stored_preset(self):
    event = self.event(text="caption", media_urls=["/tmp/input.jpg"])
    key = self.story.interaction_key(event.source)
    self.story.INTERACTIONS.start(key, kind="story_image", payload={"preset": "mango"}, source=event.source, message_id="1", on_expire=mock.AsyncMock())
    with mock.patch.object(self.story.os.path, "exists", return_value=True), \
         mock.patch.object(self.story, "_render_story", return_value="/tmp/out.png") as render, \
         mock.patch.object(self.story, "_schedule"):
        result = self.story._handle_qeostory_native(event, object())
    self.assertEqual(result, {"action": "skip", "reason": "qeostory-rendered"})
    render.assert_called_once_with(event.source, "/tmp/input.jpg", "mango")
    self.assertIsNone(self.story.INTERACTIONS.peek(key))
```

Also add: invalid text-only follow-up reminds and keeps state; non-Qeo slash command is not consumed; missing `user_id` without image falls through to existing help command; image + `/qeostory` immediate mode clears older pending first; `/qeostory` replaces pending voice state; expiry callback sends the exact approved story timeout copy.

- [ ] **Step 2: Run story tests and verify RED**

```bash
python3 -m unittest tests.test_qeo_shortcuts_story -v
```

Expected: conversational tests FAIL because no-image commands still fall through and follow-up images are not stateful.

- [ ] **Step 3: Extract one shared story dispatch helper**

Add a focused helper so immediate and follow-up paths do not duplicate render/error/send logic:

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

Keep existing render semantics unchanged.

- [ ] **Step 4: Implement story pending behavior**

Define exact copy:

```python
PROMPT_TEXT = "🖼️ Hãy gửi ảnh screenshot trong vòng 1 phút."
INVALID_TEXT = "⚠️ Hãy gửi ảnh screenshot. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu."
EXPIRED_TEXT = "⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới."
```

Handler order must be:

1. Recognized `/qeostory` command clears any old pending state for the same key before processing.
2. If the same event already has a resolvable image, call `_dispatch_story` immediately with the parsed preset.
3. If there is no image and no key because `user_id` is missing, return `None` so the registered help command handles it.
4. Otherwise start `story_image` pending with `{"preset": preset}`, expiry callback, send `PROMPT_TEXT`, and skip.
5. For non-command events, only inspect pending state whose kind is `story_image`.
6. If event text is another slash command, return `None` and preserve pending state.
7. If no local image resolves, send `INVALID_TEXT`, keep state, and skip.
8. If image resolves, `take()` pending before render, read stored preset, call `_dispatch_story`, and return its action.

- [ ] **Step 5: Run story + voice + interaction tests and verify GREEN**

```bash
python3 -m unittest \
  tests.test_qeo_shortcuts_interaction \
  tests.test_qeo_shortcuts_story \
  tests.test_qeo_shortcuts_voice -v
```

Expected: PASS, including cross-command replacement behavior.

- [ ] **Step 6: Commit Task 3**

```bash
git add plugins/qeo-shortcuts/handlers/story.py tests/test_qeo_shortcuts_story.py
git commit -m "feat: add conversational qeostory input"
```

---

### Task 4: Documentation, Versioning, Full Verification, and Production Acceptance

**Files:**
- Modify: `plugins/qeo-shortcuts/plugin.yaml`
- Modify: `README.md`
- Modify: `docs/TELEGRAM-COMMANDS.md`
- Modify: `docs/QEO-VOICE.md`
- Modify: `skills/qeo-voice/SKILL.md`
- Modify: `skills/qeo-story/SKILL.md`

**Interfaces:**
- No new runtime interface; documents and packages describe Tasks 1-3 exactly.

- [ ] **Step 1: Update documentation and plugin version**

Set `plugins/qeo-shortcuts/plugin.yaml` version to `1.1.0`.

Document both forms explicitly:

```text
/qeovoice "text" -> immediate voice
/qeovoice          -> prompt -> text within 60 seconds -> voice

image + /qeostory [preset] -> immediate render
/qeostory [preset]         -> prompt -> image within 60 seconds -> render
```

Document identity isolation, 60-second proactive expiry, command replacement, non-Qeo slash-command passthrough, memory-only state, and unchanged qeo-voice no-fallback behavior.

- [ ] **Step 2: Run repository verification**

```bash
./scripts/verify.sh --repo-only
```

Expected: `verify: repository checks passed`.

- [ ] **Step 3: Run macOS-only Docker wrapper tests**

```bash
python3 -m unittest tests.test_qeo_mac_docker -v
```

Expected: all macOS Docker tests PASS.

- [ ] **Step 4: Run the complete non-macOS suite under Python 3.12**

Use the existing qeo-voice ARM64 image so FastAPI/VieNeu requirements match the established verification environment:

```bash
docker run --rm \
  -v "$PWD:/repo" -w /repo \
  qeo-mac-qeo-voice-worker:latest \
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

Expected: PASS. Warnings from third-party FastAPI/TestClient deprecations are acceptable; test failures or unawaited-coroutine warnings are not.

- [ ] **Step 5: Review complete diff and verify no scope leaks**

```bash
git diff --check
git status --short
git diff HEAD~3..HEAD -- \
  plugins/qeo-shortcuts tests README.md docs skills/qeo-voice skills/qeo-story
```

Confirm: no worker API changes, no server-side TTS imports/fallback, no private audio/token files, no unrelated refactor.

- [ ] **Step 6: Commit docs/versioning**

```bash
git add plugins/qeo-shortcuts/plugin.yaml README.md docs/TELEGRAM-COMMANDS.md \
  docs/QEO-VOICE.md skills/qeo-voice/SKILL.md skills/qeo-story/SKILL.md
git commit -m "docs: document conversational qeo shortcuts"
```

- [ ] **Step 7: Push and deploy the verified branch**

```bash
git push origin feat/qeo-voice
```

On UpCloud, deploy the exact pushed commit with the existing validated deploy flow:

```bash
sudo ./scripts/deploy.sh qeo-voice --hermes-home /opt/hermes/data --profiles all
```

Then verify gateway status and plugin doctor pass. Do not deploy `workers/qeo-voice` or install VieNeu on UpCloud.

- [ ] **Step 8: Telegram production acceptance**

Run these exact scenarios:

```text
1. /qeovoice
   -> prompt appears
   -> send multiline text within 60 seconds
   -> one native voice bubble arrives

2. /qeostory mango
   -> prompt appears
   -> send screenshot within 60 seconds
   -> rendered story arrives using mango preset

3. /qeovoice
   -> do not reply for >60 seconds
   -> exactly one Qeo Voice expiry alert arrives

4. /qeovoice
   -> before replying, send /qeostory mango
   -> story prompt replaces voice pending
   -> no stale Qeo Voice timeout alert arrives
   -> send screenshot and receive story

5. Start either pending flow, send /help
   -> /help continues through Hermes
   -> pending flow remains active until its original deadline
```

Acceptance requires all five scenarios to pass without an LLM turn consuming valid pending input and without any qeo-voice fallback TTS.

- [ ] **Step 9: Final branch status**

```bash
git status --short
git log --oneline -5
```

Expected: clean worktree and the conversational-input commits at branch tip.