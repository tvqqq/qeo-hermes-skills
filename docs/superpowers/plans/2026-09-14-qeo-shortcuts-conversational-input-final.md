# Qeo Shortcuts Conversational Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 60-second conversational follow-up flows to `/qeovoice` and `/qeostory` without breaking existing immediate forms.

**Architecture:** One shared in-memory manager owns pending state, TTL, replacement, cancellation, and stale-timeout protection. State key is `(profile, user_id, chat_id, thread_id)`. Voice/story handlers keep command parsing and action execution and consume matching follow-ups through `pre_gateway_dispatch`.

**Tech Stack:** Python 3.11 production, `asyncio`, `unittest`, Hermes plugin hooks, Telegram adapter.

**Spec:** `docs/superpowers/specs/2026-09-14-qeo-shortcuts-conversational-input-design.md`

## Global Constraints

- TTL exactly 60 seconds; invalid input never extends it.
- Conversation mode requires `source.user_id`; otherwise preserve current help/usage behavior.
- One pending Qeo interaction per key.
- Any recognized Qeo command clears old pending state before immediate execution or new pending creation.
- Non-Qeo slash commands pass through Hermes and do not consume pending state.
- State is memory-only.
- Qeo Voice keeps Mac mini as sole TTS compute host; no UpCloud fallback TTS.
- Existing `/qeovoice "text"`, `/qeovoice text`, and image + `/qeostory [preset]` remain compatible.

---

### Task 1: Shared Interaction State

**Files:**
- Create `plugins/qeo-shortcuts/interaction.py`
- Create `tests/qeo_shortcuts_loader.py`
- Create `tests/test_qeo_shortcuts_interaction.py`
- Modify existing voice/story test loaders

**Interfaces:** `interaction_key(source)`, `is_slash_command(text)`, `InteractionManager.start/peek/take/clear`, singleton `INTERACTIONS`.

- [ ] **Step 1: Make handler tests package-aware**

Create:

```python
# tests/qeo_shortcuts_loader.py
import importlib, importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugins" / "qeo-shortcuts"
PACKAGE = "qeo_shortcuts_test_plugin"


def load_shortcut_module(relative_name):
    if PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PACKAGE, PLUGIN_DIR / "__init__.py",
            submodule_search_locations=[str(PLUGIN_DIR)],
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = package
        spec.loader.exec_module(package)
    return importlib.import_module(f"{PACKAGE}.{relative_name}")
```

Use `load_shortcut_module("handlers.voice")` and `load_shortcut_module("handlers.story")` in the two existing test files.

- [ ] **Step 2: Verify loader refactor stays GREEN**

```bash
python3 -m unittest tests.test_qeo_shortcuts_voice tests.test_qeo_shortcuts_story -v
```

Expected: PASS.

- [ ] **Step 3: Write RED manager tests**

```python
class InteractionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_ttl_is_60_seconds(self):
        manager = interaction.InteractionManager(clock=lambda: 100.0)
        key = ("p", "u", "c", "t")
        pending = manager.start(key, kind="voice_text", payload={}, source=object(), message_id="1", on_expire=mock.AsyncMock())
        self.assertEqual(pending.expires_at, 160.0)
        manager.clear(key)
        await asyncio.sleep(0)

    async def test_other_identity_cannot_take_request(self):
        manager = interaction.InteractionManager()
        owner = ("p", "u1", "c", "t")
        other = ("p", "u2", "c", "t")
        manager.start(owner, kind="voice_text", payload={}, source=object(), message_id="1", on_expire=mock.AsyncMock())
        self.assertIsNone(manager.take(other, "voice_text"))
        self.assertIsNotNone(manager.peek(owner))
        manager.clear(owner)
        await asyncio.sleep(0)

    async def test_take_cancels_timeout(self):
        expired = mock.AsyncMock()
        manager = interaction.InteractionManager(ttl_seconds=0.01)
        key = ("p", "u", "c", "t")
        manager.start(key, kind="voice_text", payload={}, source=object(), message_id="1", on_expire=expired)
        manager.take(key, "voice_text")
        await asyncio.sleep(0.03)
        expired.assert_not_awaited()

    async def test_replacement_only_expires_latest_request(self):
        old_cb, new_cb = mock.AsyncMock(), mock.AsyncMock()
        manager = interaction.InteractionManager(ttl_seconds=0.01)
        key = ("p", "u", "c", "t")
        manager.start(key, kind="voice_text", payload={}, source=object(), message_id="1", on_expire=old_cb)
        manager.start(key, kind="story_image", payload={"preset": "mango"}, source=object(), message_id="2", on_expire=new_cb)
        await asyncio.sleep(0.03)
        old_cb.assert_not_awaited()
        new_cb.assert_awaited_once()
        self.assertIsNone(manager.peek(key))
```

Also assert `interaction_key()` returns `(profile,user_id,chat_id,thread_id)`, returns `None` without `user_id`, and `is_slash_command(" /help")` is true while `is_slash_command("hello /help")` is false.

- [ ] **Step 4: Verify RED**

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction -v
```

Expected: FAIL because `interaction.py` does not exist.

- [ ] **Step 5: Implement manager**

```python
# plugins/qeo-shortcuts/interaction.py
import asyncio, time, uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

DEFAULT_TTL_SECONDS = 60.0
InteractionKey = Tuple[str, str, str, str]

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


def interaction_key(source):
    user_id = str(getattr(source, "user_id", None) or "").strip()
    if not user_id:
        return None
    return (
        str(getattr(source, "profile", None) or "default"), user_id,
        str(getattr(source, "chat_id", None) or ""),
        str(getattr(source, "thread_id", None) or ""),
    )


def is_slash_command(text):
    return (text or "").lstrip().startswith("/")


class InteractionManager:
    def __init__(self, ttl_seconds=DEFAULT_TTL_SECONDS, clock=time.monotonic):
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._pending = {}
        self._tasks = {}

    def start(self, key, *, kind, payload, source, message_id, on_expire):
        self.clear(key)
        now = self._clock()
        pending = PendingInteraction(uuid.uuid4().hex, key, kind, now, now + self._ttl_seconds, dict(payload), source, message_id)
        self._pending[key] = pending
        self._tasks[pending.request_id] = asyncio.get_running_loop().create_task(self._expire_after(pending, on_expire))
        return pending

    async def _expire_after(self, pending, on_expire):
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
        if task:
            task.cancel()
        return current

    def clear(self, key):
        current = self._pending.pop(key, None)
        if current is None:
            return None
        task = self._tasks.pop(current.request_id, None)
        if task:
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

---

### Task 2: Conversational `/qeovoice`

**Files:** modify `plugins/qeo-shortcuts/handlers/voice.py`, `tests/test_qeo_shortcuts_voice.py`.

- [ ] **Step 1: Write RED voice tests**

Convert the test class to `IsolatedAsyncioTestCase` and include `user_id="7"` in its default source. Add tests that assert:

```python
# bare command -> pending
result = handler(self.event("/qeovoice"), gateway)
self.assertEqual(result["reason"], "qeovoice-awaiting-text")
self.assertEqual(INTERACTIONS.peek(key).kind, "voice_text")

# multiline follow-up -> consume + dispatch exact full text
self.assertEqual(result["reason"], "qeovoice-followup-dispatched")
process.assert_called_once_with(followup, mock.ANY, "Dòng một\nDòng hai")
self.assertIsNone(INTERACTIONS.peek(key))

# invalid empty follow-up -> keep state
self.assertEqual(result["reason"], "qeovoice-invalid-followup")
self.assertIsNotNone(INTERACTIONS.peek(key))

# /help while pending -> passthrough + keep state
self.assertIsNone(handler(self.event("/help"), gateway))
self.assertIsNotNone(INTERACTIONS.peek(key))

# immediate voice command replaces story pending
self.assertEqual(handler(self.event('/qeovoice "Xin chào"'), gateway)["reason"], "qeovoice-dispatched")
self.assertIsNone(INTERACTIONS.peek(key))
```

For missing identity set `event.source.user_id = None`; assert reason `qeovoice-usage` and no key. For expiry, patch `INTERACTIONS._ttl_seconds = 0.01`, use existing `FakeGateway/FakeAdapter`, await `0.03`, and assert the last sent text equals `⏱️ Yêu cầu Qeo Voice đã hết hạn. Hãy gửi lại /qeovoice để tạo voice mới.`. Clear pending state at the end of tests that leave it active and `await asyncio.sleep(0)` after cancellation.

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest tests.test_qeo_shortcuts_voice -v
```

- [ ] **Step 3: Implement voice flow**

Add:

```python
from ..interaction import INTERACTIONS, interaction_key, is_slash_command
PROMPT_TEXT = "🎙️ Bạn muốn Chi Chi đọc nội dung gì? Hãy gửi text trong vòng 1 phút."
INVALID_TEXT = "⚠️ Hãy gửi nội dung text. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu."
EXPIRED_TEXT = "⏱️ Yêu cầu Qeo Voice đã hết hạn. Hãy gửi lại /qeovoice để tạo voice mới."
```

Command branch: clear existing key first; keep current immediate synthesis for non-empty args; if bare and no key send existing usage; otherwise `INTERACTIONS.start(... kind="voice_text" ...)`, schedule prompt, return `qeovoice-awaiting-text`.

Follow-up branch:

```python
key = interaction_key(source)
pending = INTERACTIONS.peek(key) if key else None
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

Expiry callback sends `EXPIRED_TEXT` using the original source/event. Do not touch worker HTTP, OGG/Opus, existing offline/busy/failure strings, or fallback behavior.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction tests.test_qeo_shortcuts_voice -v
git add plugins/qeo-shortcuts/handlers/voice.py tests/test_qeo_shortcuts_voice.py
git commit -m "feat: add conversational qeovoice input"
```

---

### Task 3: Conversational `/qeostory`

**Files:** modify `plugins/qeo-shortcuts/handlers/story.py`, `tests/test_qeo_shortcuts_story.py`.

- [ ] **Step 1: Write RED story tests**

Add an event helper returning source fields `profile="qeo-personal"`, `user_id`, `chat_id="1"`, `thread_id="2"`, plus `text`, `media_urls`, `message_id`. Convert the class to `IsolatedAsyncioTestCase`.

Assert these exact behaviors:

```python
# /qeostory mango without image -> pending preset
self.assertEqual(result["reason"], "qeostory-awaiting-image")
self.assertEqual(INTERACTIONS.peek(key).payload, {"preset": "mango"})

# follow-up image -> stored preset used
render.assert_called_once_with(event.source, "/tmp/input.jpg", "mango")
self.assertEqual(result["reason"], "qeostory-rendered")
self.assertIsNone(INTERACTIONS.peek(key))

# text-only follow-up -> reminder + keep state
self.assertEqual(result["reason"], "qeostory-invalid-followup")
self.assertIsNotNone(INTERACTIONS.peek(key))

# /help while pending -> passthrough
self.assertIsNone(handler(help_event, gateway))
self.assertIsNotNone(INTERACTIONS.peek(key))

# /qeostory mango replaces voice pending
self.assertEqual(INTERACTIONS.peek(key).kind, "story_image")

# image + /qeostory mango clears voice pending and renders immediately
self.assertEqual(result["reason"], "qeostory-rendered")
self.assertIsNone(INTERACTIONS.peek(key))
```

Also assert missing `user_id` + no image returns `None`, and expiry exact text is `⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới.` using a 0.01-second patched TTL and a minimal fake adapter.

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest tests.test_qeo_shortcuts_story -v
```

- [ ] **Step 3: Implement story flow**

Add:

```python
from ..interaction import INTERACTIONS, interaction_key, is_slash_command
PROMPT_TEXT = "🖼️ Hãy gửi ảnh screenshot trong vòng 1 phút."
INVALID_TEXT = "⚠️ Hãy gửi ảnh screenshot. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu."
EXPIRED_TEXT = "⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới."
```

Extract existing render/error/send behavior into:

```python
def _dispatch_story(event, gateway, source, image_path, preset):
    try:
        output_path = _render_story(source, image_path, preset)
    except Exception as exc:
        _schedule(_send_text_reply(gateway, source, event, f"❌ Render thất bại: {str(exc)[:1500]}"))
        return {"action": "skip", "reason": "qeostory-render-failed"}
    _schedule(_send_image_reply(gateway, source, event, output_path))
    return {"action": "skip", "reason": "qeostory-rendered"}
```

Command branch: clear existing key first; if image exists call `_dispatch_story`; if no key return `None`; otherwise start `story_image` with payload `{"preset": preset}`, schedule prompt, return `qeostory-awaiting-image`.

Follow-up branch:

```python
key = interaction_key(source)
pending = INTERACTIONS.peek(key) if key else None
if pending is None or pending.kind != "story_image":
    return None
if is_slash_command(text):
    return None
image_path = _extract_local_image_path(event)
if not image_path:
    _schedule(_send_text_reply(gateway, source, event, INVALID_TEXT))
    return {"action": "skip", "reason": "qeostory-invalid-followup"}
pending = INTERACTIONS.take(key, "story_image")
return _dispatch_story(event, gateway, source, image_path, pending.payload.get("preset"))
```

Expiry callback sends `EXPIRED_TEXT` to the original source/event.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_qeo_shortcuts_interaction tests.test_qeo_shortcuts_story tests.test_qeo_shortcuts_voice -v
git add plugins/qeo-shortcuts/handlers/story.py tests/test_qeo_shortcuts_story.py
git commit -m "feat: add conversational qeostory input"
```

---

### Task 4: Docs, Verification, Deployment, Acceptance

**Files:** modify `plugins/qeo-shortcuts/plugin.yaml`, `README.md`, `docs/TELEGRAM-COMMANDS.md`, `docs/QEO-VOICE.md`, `skills/qeo-voice/SKILL.md`, `skills/qeo-story/SKILL.md`.

- [ ] **Step 1: Update metadata/docs**

Set plugin version `1.1.0`. Document both immediate and conversational forms, identity isolation, one pending per key, replacement, 60-second proactive expiry, `/help` passthrough, memory-only state, and unchanged no-fallback behavior.

- [ ] **Step 2: Run repository verification**

```bash
./scripts/verify.sh --repo-only
```

- [ ] **Step 3: Run macOS-only suite**

```bash
python3 -m unittest tests.test_qeo_mac_docker -v
```

- [ ] **Step 4: Run complete non-macOS suite under Python 3.12**

```bash
docker run --rm -v "$PWD:/repo" -w /repo qeo-mac-qeo-voice-worker:latest \
  sh -lc 'python -m pip install --quiet Pillow && python -m unittest \
    tests.test_deploy_scripts tests.test_qeo_shortcuts_interaction \
    tests.test_qeo_shortcuts_story tests.test_qeo_shortcuts_voice \
    tests.test_qeo_voice_registry tests.test_qeo_voice_repo_contract \
    tests.test_qeo_voice_worker tests.test_story_renderer -v'
```

Expected: PASS; no unawaited-coroutine warnings.

- [ ] **Step 5: Review diff and commit docs**

```bash
git diff --check
git status --short
git diff HEAD~3..HEAD -- plugins/qeo-shortcuts tests README.md docs skills/qeo-voice skills/qeo-story
git add plugins/qeo-shortcuts/plugin.yaml README.md docs/TELEGRAM-COMMANDS.md docs/QEO-VOICE.md skills/qeo-voice/SKILL.md skills/qeo-story/SKILL.md
git commit -m "docs: document conversational qeo shortcuts"
```

Confirm no worker API changes, no UpCloud TTS imports/fallback, no private audio/token files, no unrelated refactor.

- [ ] **Step 6: Push and deploy exact tip**

```bash
git push origin feat/qeo-voice
sudo ./scripts/deploy.sh qeo-voice --hermes-home /opt/hermes/data --profiles all
```

Run plugin doctor and gateway status after restart. Never deploy `workers/qeo-voice` to UpCloud.

- [ ] **Step 7: Telegram production acceptance**

```text
1. /qeovoice -> prompt -> multiline text within 60s -> native voice bubble.
2. /qeostory mango -> prompt -> screenshot within 60s -> mango story.
3. /qeovoice -> wait >60s -> exactly one voice expiry alert.
4. /qeovoice -> /qeostory mango -> no stale voice timeout -> screenshot produces story.
5. Start pending -> /help -> /help reaches Hermes; pending keeps original deadline.
```

Acceptance requires all five scenarios and no qeo-voice fallback TTS.

- [ ] **Step 8: Final status**

```bash
git status --short
git log --oneline -6
```

Expected: clean worktree with interaction, voice, story, and docs commits at branch tip.