from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.qeo_shortcuts_loader import load_shortcut_module

ROOT = Path(__file__).resolve().parents[1]
INTERACTION_PATH = ROOT / "plugins" / "qeo-shortcuts" / "interaction.py"
interaction = load_shortcut_module("interaction")


class InteractionModuleContractTests(unittest.TestCase):
    def test_interaction_module_exists(self):
        self.assertTrue(INTERACTION_PATH.exists())

    def test_interaction_key_requires_user_and_preserves_routing_identity(self):
        fn = getattr(interaction, "interaction_key", None)
        self.assertIsNotNone(fn)
        source = SimpleNamespace(profile="qeo-personal", user_id="7", chat_id="8", thread_id="9")
        self.assertEqual(fn(source), ("qeo-personal", "7", "8", "9"))
        source.user_id = None
        self.assertIsNone(fn(source))

    def test_slash_command_detection_only_matches_leading_slash(self):
        fn = getattr(interaction, "is_slash_command", None)
        self.assertIsNotNone(fn)
        self.assertTrue(fn("  /help"))
        self.assertFalse(fn("hello /help"))

    def test_manager_api_exists(self):
        self.assertIsNotNone(getattr(interaction, "PendingInteraction", None))
        manager_type = getattr(interaction, "InteractionManager", None)
        self.assertIsNotNone(manager_type)
        self.assertIsNotNone(getattr(interaction, "INTERACTIONS", None))
        for name in ("start", "peek", "take", "clear"):
            self.assertTrue(hasattr(manager_type, name), name)


class InteractionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_ttl_is_exactly_60_seconds(self):
        manager = interaction.InteractionManager(clock=lambda: 100.0)
        key = ("p", "u", "c", "t")
        pending = manager.start(
            key,
            kind="voice_text",
            payload={},
            source=object(),
            message_id="1",
            on_expire=mock.AsyncMock(),
        )
        self.assertIsNotNone(pending)
        self.assertEqual(pending.expires_at, 160.0)
        manager.clear(key)
        await asyncio.sleep(0)

    async def test_other_identity_cannot_take_request(self):
        manager = interaction.InteractionManager()
        owner = ("p", "u1", "c", "t")
        other = ("p", "u2", "c", "t")
        manager.start(owner, kind="voice_text", payload={}, source=object(), message_id="1", on_expire=mock.AsyncMock())
        self.assertIsNotNone(manager.peek(owner))
        self.assertIsNone(manager.take(other, "voice_text"))
        self.assertIsNotNone(manager.peek(owner))
        manager.clear(owner)
        await asyncio.sleep(0)

    async def test_take_cancels_timeout(self):
        expired = mock.AsyncMock()
        manager = interaction.InteractionManager(ttl_seconds=0.01)
        key = ("p", "u", "c", "t")
        manager.start(key, kind="voice_text", payload={}, source=object(), message_id="1", on_expire=expired)
        self.assertIsNotNone(manager.peek(key))
        taken = manager.take(key, "voice_text")
        self.assertIsNotNone(taken)
        await asyncio.sleep(0.03)
        expired.assert_not_awaited()

    async def test_replacement_only_expires_latest_request(self):
        old_cb = mock.AsyncMock()
        new_cb = mock.AsyncMock()
        manager = interaction.InteractionManager(ttl_seconds=0.01)
        key = ("p", "u", "c", "t")
        manager.start(key, kind="voice_text", payload={}, source=object(), message_id="1", on_expire=old_cb)
        manager.start(key, kind="story_image", payload={"preset": "mango"}, source=object(), message_id="2", on_expire=new_cb)
        current = manager.peek(key)
        self.assertIsNotNone(current)
        self.assertEqual(current.kind, "story_image")
        await asyncio.sleep(0.03)
        old_cb.assert_not_awaited()
        new_cb.assert_awaited_once()
        self.assertIsNone(manager.peek(key))


if __name__ == "__main__":
    unittest.main()
