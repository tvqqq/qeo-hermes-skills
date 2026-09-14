from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.qeo_shortcuts_loader import load_shortcut_module

ROOT = Path(__file__).resolve().parents[1]
STORY_PATH = ROOT / "plugins" / "qeo-shortcuts" / "handlers" / "story.py"


def load_story_module():
    return load_shortcut_module("handlers.story")


class FakeAdapter:
    def __init__(self):
        self.texts = []

    async def send(self, chat_id, text, reply_to=None, metadata=None):
        self.texts.append((chat_id, text, reply_to, metadata))


class FakeGateway:
    def __init__(self, adapter):
        self.adapter = adapter

    def _adapter_for_source(self, source):
        return self.adapter


class StoryShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.story = load_story_module()
        cls.interaction = load_shortcut_module("interaction")

    def event(
        self, text="/qeostory", media_urls=None, user_id="7",
        profile="qeo-personal", chat_id="1", thread_id="2",
    ):
        return SimpleNamespace(
            text=text,
            media_urls=list(media_urls or []),
            source=SimpleNamespace(
                profile=profile, user_id=user_id, chat_id=chat_id, thread_id=thread_id,
            ),
            message_id="10",
        )

    def test_extracts_known_preset_and_ignores_unknown(self):
        self.assertEqual(self.story._extract_preset("mango"), "mango")
        self.assertIsNone(self.story._extract_preset("unknown"))

    def test_resolves_profile_skill_dir_from_hermes_home(self):
        source = SimpleNamespace(profile="qeo-personal")
        with mock.patch.dict(os.environ, {"HERMES_HOME": "/tmp/hermes"}, clear=False):
            path = self.story._skill_dir_for_source(source)
        self.assertEqual(path, Path("/tmp/hermes/profiles/qeo-personal/skills/qeo-story"))

    def test_resolves_default_profile_skill_dir(self):
        source = SimpleNamespace(profile=None)
        with mock.patch.dict(os.environ, {"HERMES_HOME": "/tmp/hermes"}, clear=False):
            path = self.story._skill_dir_for_source(source)
        self.assertEqual(path, Path("/tmp/hermes/skills/qeo-story"))

    def test_accepts_compact_and_compatibility_command_forms(self):
        for command in ("/qeostory", "/qeo_story", "/qeo-story"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.story.CMD_RE.match(command))

    def test_success_schedules_image_and_skips_agent_turn(self):
        event = SimpleNamespace(
            text="/qeostory mango",
            media_urls=["/tmp/input.jpg"],
            source=SimpleNamespace(profile="qeo-personal", chat_id="1", thread_id="2"),
            message_id="10",
        )
        scheduled = []

        def capture(coro):
            scheduled.append(coro)
            coro.close()

        with mock.patch.object(self.story.os.path, "exists", return_value=True), \
             mock.patch.object(self.story, "_render_story", return_value="/tmp/output.png"), \
             mock.patch.object(self.story, "_schedule", side_effect=capture):
            result = self.story._handle_qeostory_native(event, object())

        self.assertEqual(result, {"action": "skip", "reason": "qeostory-rendered"})
        self.assertEqual(len(scheduled), 1)

    def test_render_failure_schedules_error_and_skips_agent_turn(self):
        event = SimpleNamespace(
            text="/qeostory",
            media_urls=["/tmp/input.jpg"],
            source=SimpleNamespace(profile="default", chat_id="1", thread_id=None),
            message_id="10",
        )
        scheduled = []

        def capture(coro):
            scheduled.append(coro)
            coro.close()

        with mock.patch.object(self.story.os.path, "exists", return_value=True), \
             mock.patch.object(self.story, "_render_story", side_effect=RuntimeError("boom")), \
             mock.patch.object(self.story, "_schedule", side_effect=capture):
            result = self.story._handle_qeostory_native(event, object())

        self.assertEqual(result, {"action": "skip", "reason": "qeostory-render-failed"})
        self.assertEqual(len(scheduled), 1)

    def test_command_without_image_starts_story_pending_with_preset_and_prompts(self):
        async def scenario():
            adapter = FakeAdapter()
            gateway = FakeGateway(adapter)
            event = self.event("/qeostory mango")
            key = self.interaction.interaction_key(event.source)
            manager = self.interaction.InteractionManager()
            with mock.patch.object(self.story, "INTERACTIONS", manager, create=True):
                result = self.story._handle_qeostory_native(event, gateway)
                await asyncio.sleep(0)
            self.assertEqual(result, {"action": "skip", "reason": "qeostory-awaiting-image"})
            pending = manager.peek(key)
            self.assertIsNotNone(pending)
            self.assertEqual(pending.kind, "story_image")
            self.assertEqual(pending.payload, {"preset": "mango"})
            self.assertEqual(adapter.texts[-1][1], "🖼️ Hãy gửi ảnh screenshot trong vòng 1 phút.")
            manager.clear(key)
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_pending_story_consumes_followup_image_with_stored_preset(self):
        async def scenario():
            command = self.event("/qeostory mango")
            followup = self.event("caption", media_urls=["/tmp/input.jpg"])
            key = self.interaction.interaction_key(command.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="story_image", payload={"preset": "mango"},
                source=command.source, message_id=command.message_id,
                on_expire=mock.AsyncMock(),
            )
            scheduled = []
            def capture(coro):
                scheduled.append(coro)
                coro.close()
            with mock.patch.object(self.story, "INTERACTIONS", manager, create=True), \
                 mock.patch.object(self.story.os.path, "exists", return_value=True), \
                 mock.patch.object(self.story, "_render_story", return_value="/tmp/output.png") as render, \
                 mock.patch.object(self.story, "_schedule", side_effect=capture):
                result = self.story._handle_qeostory_native(followup, object())
            self.assertEqual(result, {"action": "skip", "reason": "qeostory-rendered"})
            render.assert_called_once_with(followup.source, "/tmp/input.jpg", "mango")
            self.assertIsNone(manager.peek(key))
            self.assertEqual(len(scheduled), 1)
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_invalid_story_followup_keeps_pending_and_reminds(self):
        async def scenario():
            adapter = FakeAdapter()
            gateway = FakeGateway(adapter)
            command = self.event("/qeostory")
            followup = self.event("not an image")
            key = self.interaction.interaction_key(command.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="story_image", payload={"preset": None},
                source=command.source, message_id=command.message_id,
                on_expire=mock.AsyncMock(),
            )
            with mock.patch.object(self.story, "INTERACTIONS", manager, create=True):
                result = self.story._handle_qeostory_native(followup, gateway)
                await asyncio.sleep(0)
            self.assertEqual(result, {"action": "skip", "reason": "qeostory-invalid-followup"})
            self.assertIsNotNone(manager.peek(key))
            self.assertEqual(
                adapter.texts[-1][1],
                "⚠️ Hãy gửi ảnh screenshot. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu.",
            )
            manager.clear(key)
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_story_command_replaces_voice_pending(self):
        async def scenario():
            adapter = FakeAdapter()
            gateway = FakeGateway(adapter)
            event = self.event("/qeostory mango")
            key = self.interaction.interaction_key(event.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="voice_text", payload={}, source=event.source,
                message_id="9", on_expire=mock.AsyncMock(),
            )
            with mock.patch.object(self.story, "INTERACTIONS", manager, create=True):
                result = self.story._handle_qeostory_native(event, gateway)
                await asyncio.sleep(0)
            self.assertEqual(result, {"action": "skip", "reason": "qeostory-awaiting-image"})
            pending = manager.peek(key)
            self.assertIsNotNone(pending)
            self.assertEqual(pending.kind, "story_image")
            self.assertEqual(pending.payload, {"preset": "mango"})
            manager.clear(key)
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_immediate_story_command_clears_voice_pending(self):
        async def scenario():
            event = self.event("/qeostory mango", media_urls=["/tmp/input.jpg"])
            key = self.interaction.interaction_key(event.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="voice_text", payload={}, source=event.source,
                message_id="9", on_expire=mock.AsyncMock(),
            )
            scheduled = []
            def capture(coro):
                scheduled.append(coro)
                coro.close()
            with mock.patch.object(self.story, "INTERACTIONS", manager, create=True), \
                 mock.patch.object(self.story.os.path, "exists", return_value=True), \
                 mock.patch.object(self.story, "_render_story", return_value="/tmp/output.png"), \
                 mock.patch.object(self.story, "_schedule", side_effect=capture):
                result = self.story._handle_qeostory_native(event, object())
            self.assertEqual(result, {"action": "skip", "reason": "qeostory-rendered"})
            self.assertIsNone(manager.peek(key))
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_story_pending_expiry_sends_exact_alert_once(self):
        async def scenario():
            adapter = FakeAdapter()
            gateway = FakeGateway(adapter)
            event = self.event("/qeostory")
            manager = self.interaction.InteractionManager(ttl_seconds=0.01)
            with mock.patch.object(self.story, "INTERACTIONS", manager, create=True):
                self.story._handle_qeostory_native(event, gateway)
                await asyncio.sleep(0.03)
            alerts = [text for _, text, _, _ in adapter.texts if text.startswith("⏱️")]
            self.assertEqual(
                alerts,
                ["⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới."],
            )
        asyncio.run(scenario())

    def test_non_qeo_slash_command_does_not_consume_story_pending(self):
        async def scenario():
            event = self.event("/help")
            key = self.interaction.interaction_key(event.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="story_image", payload={"preset": None}, source=event.source,
                message_id="9", on_expire=mock.AsyncMock(),
            )
            with mock.patch.object(self.story, "INTERACTIONS", manager, create=True):
                result = self.story._handle_qeostory_native(event, object())
            self.assertIsNone(result)
            self.assertIsNotNone(manager.peek(key))
            manager.clear(key)
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_no_image_falls_through_to_registered_help_command(self):
        event = SimpleNamespace(
            text="/qeostory",
            media_urls=[],
            source=SimpleNamespace(profile="default"),
        )
        self.assertIsNone(self.story._handle_qeostory_native(event, object()))


if __name__ == "__main__":
    unittest.main()
