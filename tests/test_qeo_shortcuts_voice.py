from __future__ import annotations

import asyncio
import importlib.util
import io
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
VOICE_PATH = ROOT / "plugins" / "qeo-shortcuts" / "handlers" / "voice.py"


def load_voice_module():
    spec = importlib.util.spec_from_file_location("qeo_shortcuts_voice", VOICE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {VOICE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

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

    def event(self, text="/qeovoice Xin chào"):
        return SimpleNamespace(
            text=text,
            source=SimpleNamespace(profile="default", chat_id="1", thread_id="2"),
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

    def test_empty_text_sends_usage_and_skips_llm(self):
        scheduled = []
        def capture(coro):
            scheduled.append(coro)
            coro.close()
        with mock.patch.object(self.voice, "_schedule", side_effect=capture):
            result = self.voice._handle_qeovoice_native(self.event("/qeovoice"), object())
        self.assertEqual(result, {"action": "skip", "reason": "qeovoice-usage"})
        self.assertEqual(len(scheduled), 1)

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
