from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.qeo_shortcuts_loader import load_shortcut_module

ROOT = Path(__file__).resolve().parents[1]
VOICE_PATH = ROOT / "plugins" / "qeo-shortcuts" / "handlers" / "voice.py"


def load_voice_module():
    return load_shortcut_module("handlers.voice")

class FakeAdapter:
    def __init__(self):
        self.texts = []
        self.voices = []

    async def send(self, chat_id, text, reply_to=None, metadata=None):
        self.texts.append((chat_id, text, reply_to, metadata))

    async def send_voice(self, chat_id, audio_path, caption=None, reply_to=None, metadata=None, **kwargs):
        path = Path(audio_path)
        self.voices.append({
            "chat_id": chat_id,
            "path": path,
            "exists_during_send": path.exists(),
            "bytes": path.read_bytes(),
            "caption": caption,
            "reply_to": reply_to,
            "metadata": metadata,
        })


class FakeGateway:
    def __init__(self, adapter):
        self.adapter = adapter

    def _adapter_for_source(self, source):
        return self.adapter

class QeoVoiceShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voice = load_voice_module()
        cls.interaction = load_shortcut_module("interaction")

    def event(self, text="/qeovoice Xin chào", media_urls=None, user_id="7"):
        return SimpleNamespace(
            text=text,
            media_urls=list(media_urls or []),
            source=SimpleNamespace(
                profile="default", user_id=user_id, chat_id="1", thread_id="2"
            ),
            message_id="10",
        )

    def test_recognizes_only_compact_qeovoice_command(self):
        self.assertIsNotNone(self.voice.CMD_RE.match("/qeovoice Xin chào"))
        self.assertIsNotNone(self.voice.CMD_RE.match("/qeovoice@mybot Xin chào"))
        self.assertIsNone(self.voice.CMD_RE.match("/qeo-voice Xin chào"))
        self.assertIsNone(self.voice.CMD_RE.match("/qeo_voice Xin chào"))

    def test_nonempty_command_schedules_worker_path_and_skips_llm(self):
        scheduled = []
        def capture(coro):
            scheduled.append(coro)
            coro.close()
        with mock.patch.object(self.voice, "_schedule", side_effect=capture):
            result = self.voice._handle_qeovoice_native(self.event(), object())
        self.assertEqual(result, {"action": "skip", "reason": "qeovoice-dispatched"})
        self.assertEqual(len(scheduled), 1)

    def test_quoted_multiline_text_strips_outer_quotes_and_preserves_newlines(self):
        event = self.event('/qeovoice "Dòng một\nDòng hai"')
        process = mock.Mock()
        with mock.patch.object(self.voice, "_schedule"), \
             mock.patch.object(self.voice, "_process_qeovoice", new=process):
            result = self.voice._handle_qeovoice_native(event, object())
        self.assertEqual(result, {"action": "skip", "reason": "qeovoice-dispatched"})
        process.assert_called_once_with(event, mock.ANY, "Dòng một\nDòng hai")

    def test_unquoted_multiline_text_remains_backward_compatible(self):
        event = self.event('/qeovoice Dòng một\nDòng hai')
        process = mock.Mock()
        with mock.patch.object(self.voice, "_schedule"), \
             mock.patch.object(self.voice, "_process_qeovoice", new=process):
            result = self.voice._handle_qeovoice_native(event, object())
        self.assertEqual(result, {"action": "skip", "reason": "qeovoice-dispatched"})
        process.assert_called_once_with(event, mock.ANY, "Dòng một\nDòng hai")

    def test_bare_command_starts_voice_pending_and_prompts(self):
        async def scenario():
            adapter = FakeAdapter()
            gateway = FakeGateway(adapter)
            event = self.event("/qeovoice")
            key = self.interaction.interaction_key(event.source)
            manager = self.interaction.InteractionManager()
            with mock.patch.object(self.voice, "INTERACTIONS", manager, create=True):
                result = self.voice._handle_qeovoice_native(event, gateway)
                await asyncio.sleep(0)
            self.assertEqual(result, {"action": "skip", "reason": "qeovoice-awaiting-text"})
            pending = manager.peek(key)
            self.assertIsNotNone(pending)
            self.assertEqual(pending.kind, "voice_text")
            self.assertEqual(
                adapter.texts[-1][1],
                "🎙️ Bạn muốn Chi Chi đọc nội dung gì? Hãy gửi text trong vòng 1 phút.",
            )
            manager.clear(key)
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_pending_voice_consumes_multiline_followup(self):
        async def scenario():
            command = self.event("/qeovoice")
            followup = self.event("Dòng một\nDòng hai")
            key = self.interaction.interaction_key(command.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="voice_text", payload={}, source=command.source,
                message_id=command.message_id, on_expire=mock.AsyncMock(),
            )
            process = mock.Mock()
            with mock.patch.object(self.voice, "INTERACTIONS", manager, create=True), \
                 mock.patch.object(self.voice, "_schedule"), \
                 mock.patch.object(self.voice, "_process_qeovoice", new=process):
                result = self.voice._handle_qeovoice_native(followup, object())
            self.assertEqual(result, {"action": "skip", "reason": "qeovoice-followup-dispatched"})
            process.assert_called_once_with(followup, mock.ANY, "Dòng một\nDòng hai")
            self.assertIsNone(manager.peek(key))
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_invalid_voice_followup_keeps_pending_and_reminds(self):
        async def scenario():
            adapter = FakeAdapter()
            gateway = FakeGateway(adapter)
            command = self.event("/qeovoice")
            followup = self.event("", media_urls=["/tmp/input.jpg"])
            key = self.interaction.interaction_key(command.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="voice_text", payload={}, source=command.source,
                message_id=command.message_id, on_expire=mock.AsyncMock(),
            )
            with mock.patch.object(self.voice, "INTERACTIONS", manager, create=True):
                result = self.voice._handle_qeovoice_native(followup, gateway)
                await asyncio.sleep(0)
            self.assertEqual(result, {"action": "skip", "reason": "qeovoice-invalid-followup"})
            self.assertIsNotNone(manager.peek(key))
            self.assertEqual(
                adapter.texts[-1][1],
                "⚠️ Hãy gửi nội dung text. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu.",
            )
            manager.clear(key)
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_usage_recommends_quoted_text_form(self):
        self.assertEqual(self.voice.USAGE_TEXT, 'Usage: /qeovoice "text"')

    def test_bare_command_without_user_identity_sends_usage_and_skips_llm(self):
        scheduled = []
        def capture(coro):
            scheduled.append(coro)
            coro.close()
        event = self.event("/qeovoice", user_id=None)
        with mock.patch.object(self.voice, "_schedule", side_effect=capture):
            result = self.voice._handle_qeovoice_native(event, object())
        self.assertEqual(result, {"action": "skip", "reason": "qeovoice-usage"})
        self.assertEqual(len(scheduled), 1)

    def test_immediate_voice_command_replaces_existing_pending(self):
        async def scenario():
            event = self.event('/qeovoice "Xin chào"')
            key = self.interaction.interaction_key(event.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="story_image", payload={"preset": "mango"},
                source=event.source, message_id="9", on_expire=mock.AsyncMock(),
            )
            process = mock.Mock()
            with mock.patch.object(self.voice, "INTERACTIONS", manager, create=True), \
                 mock.patch.object(self.voice, "_schedule"), \
                 mock.patch.object(self.voice, "_process_qeovoice", new=process):
                result = self.voice._handle_qeovoice_native(event, object())
            self.assertEqual(result, {"action": "skip", "reason": "qeovoice-dispatched"})
            self.assertIsNone(manager.peek(key))
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_non_qeo_slash_command_does_not_consume_voice_pending(self):
        async def scenario():
            event = self.event("/help")
            key = self.interaction.interaction_key(event.source)
            manager = self.interaction.InteractionManager()
            manager.start(
                key, kind="voice_text", payload={}, source=event.source,
                message_id="9", on_expire=mock.AsyncMock(),
            )
            with mock.patch.object(self.voice, "INTERACTIONS", manager, create=True):
                result = self.voice._handle_qeovoice_native(event, object())
            self.assertIsNone(result)
            self.assertIsNotNone(manager.peek(key))
            manager.clear(key)
            await asyncio.sleep(0)
        asyncio.run(scenario())

    def test_voice_pending_expiry_sends_exact_alert_once(self):
        async def scenario():
            adapter = FakeAdapter()
            gateway = FakeGateway(adapter)
            event = self.event("/qeovoice")
            manager = self.interaction.InteractionManager(ttl_seconds=0.01)
            with mock.patch.object(self.voice, "INTERACTIONS", manager, create=True):
                self.voice._handle_qeovoice_native(event, gateway)
                await asyncio.sleep(0.03)
            alerts = [text for _, text, _, _ in adapter.texts if text.startswith("⏱️")]
            self.assertEqual(
                alerts,
                ["⏱️ Yêu cầu Qeo Voice đã hết hạn. Hãy gửi lại /qeovoice để tạo voice mới."],
            )
        asyncio.run(scenario())

    def test_success_sends_native_ogg_voice_then_deletes_temp_file(self):
        adapter = FakeAdapter()
        gateway = FakeGateway(adapter)
        event = self.event()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"HERMES_HOME": tmp}, clear=False), \
             mock.patch.object(self.voice, "_request_worker", return_value=b"OggSfake-opus"):
            asyncio.run(self.voice._process_qeovoice(event, gateway, "Xin chào"))

        self.assertEqual(len(adapter.voices), 1)
        sent = adapter.voices[0]
        self.assertEqual(sent["bytes"], b"OggSfake-opus")
        self.assertEqual(sent["path"].suffix, ".ogg")
        self.assertTrue(sent["exists_during_send"])
        self.assertFalse(sent["path"].exists())
        self.assertEqual(sent["reply_to"], "10")
        self.assertEqual(sent["metadata"], {"thread_id": "2", "message_thread_id": "2"})

    def test_offline_busy_and_failure_messages_are_exact(self):
        cases = [
            ("WorkerOfflineError", "⚠️ Qeo Voice unavailable — Mac mini voice worker is offline."),
            ("WorkerBusyError", "⚠️ Qeo Voice is busy. Please try again in a moment."),
            ("WorkerGenerationError", "⚠️ Qeo Voice failed to generate audio. Please try again."),
        ]
        for error_name, expected in cases:
            with self.subTest(error_name=error_name):
                adapter = FakeAdapter()
                gateway = FakeGateway(adapter)
                error_type = getattr(self.voice, error_name)
                with mock.patch.object(self.voice, "_request_worker", side_effect=error_type()):
                    asyncio.run(self.voice._process_qeovoice(self.event(), gateway, "Xin chào"))
                self.assertEqual(adapter.texts[0][1], expected)
                self.assertEqual(adapter.voices, [])

    def test_missing_worker_configuration_is_offline(self):
        env = {k: v for k, v in os.environ.items() if k not in {
            "QEO_VOICE_WORKER_URL", "QEO_VOICE_TOKEN", "QEO_VOICE_TIMEOUT_SECONDS"
        }}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(self.voice.WorkerOfflineError):
                self.voice._request_worker("Xin chào")

    def test_network_failure_is_classified_offline(self):
        with mock.patch.dict(os.environ, {
            "QEO_VOICE_WORKER_URL": "http://100.64.0.1:8765",
            "QEO_VOICE_TOKEN": "secret",
        }, clear=False), mock.patch.object(
            self.voice.urllib.request, "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            with self.assertRaises(self.voice.WorkerOfflineError):
                self.voice._request_worker("Xin chào")

    def test_worker_503_busy_and_500_failure_are_classified(self):
        env = {"QEO_VOICE_WORKER_URL": "http://100.64.0.1:8765", "QEO_VOICE_TOKEN": "secret"}
        busy = urllib.error.HTTPError("http://x", 503, "busy", {}, io.BytesIO(b'{"error":"busy"}'))
        failed = urllib.error.HTTPError("http://x", 500, "failed", {}, io.BytesIO(b'{"error":"synthesis_failed"}'))
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(self.voice.urllib.request, "urlopen", side_effect=busy):
                with self.assertRaises(self.voice.WorkerBusyError):
                    self.voice._request_worker("x")
            with mock.patch.object(self.voice.urllib.request, "urlopen", side_effect=failed):
                with self.assertRaises(self.voice.WorkerGenerationError):
                    self.voice._request_worker("x")

    def test_handler_source_has_no_local_tts_fallback(self):
        source = VOICE_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("tts_tool", source)
        self.assertNotIn("vieneu", source)
        self.assertNotIn("edge-tts", source)
        self.assertNotIn("subprocess", source)

    def test_register_voice_exposes_qeovoice_and_hook(self):
        calls = []
        ctx = SimpleNamespace(
            register_command=lambda *args, **kwargs: calls.append(("command", args, kwargs)),
            register_hook=lambda *args, **kwargs: calls.append(("hook", args, kwargs)),
        )
        self.voice.register_voice(ctx)
        command = next(item for item in calls if item[0] == "command")
        hook = next(item for item in calls if item[0] == "hook")
        self.assertEqual(command[1][0], "qeovoice")
        self.assertEqual(hook[1][0], "pre_gateway_dispatch")


if __name__ == "__main__":
    unittest.main()
