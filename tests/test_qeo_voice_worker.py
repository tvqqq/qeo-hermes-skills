from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "workers" / "qeo-voice"
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))


def load_app_module():
    path = WORKER / "app.py"
    spec = importlib.util.spec_from_file_location("qeo_voice_app", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeEngine:
    def __init__(self):
        self.ready = True
        self.registry = SimpleNamespace(default_slug="chi-chi")
        self.action = lambda text, voice: b"OggSfake-opus"

    def synthesize(self, text, voice=None):
        return self.action(text, voice)


class QeoVoiceWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_mod = load_app_module()
        cls.token = "test-secret-token"

    def client(self, engine=None):
        app = self.app_mod.create_app(engine or FakeEngine(), self.token)
        return TestClient(app)

    @property
    def auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_both_endpoints_require_bearer_auth(self):
        client = self.client()
        self.assertEqual(client.get("/health").status_code, 401)
        self.assertEqual(client.post("/v1/tts", json={"text": "xin chao"}).status_code, 401)
        wrong = {"Authorization": "Bearer wrong"}
        self.assertEqual(client.get("/health", headers=wrong).status_code, 401)

    def test_health_reports_ready_and_not_ready_states(self):
        engine = FakeEngine()
        client = self.client(engine)
        response = client.get("/health", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ok", "engine": "v3turbo", "default_voice": "chi-chi"
        })
        engine.ready = False
        self.assertEqual(client.get("/health", headers=self.auth).status_code, 503)

    def test_empty_text_is_rejected(self):
        response = self.client().post(
            "/v1/tts", headers=self.auth, json={"text": "   ", "voice": "chi-chi"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_text"})

    def test_success_returns_ogg_opus_bytes(self):
        response = self.client().post(
            "/v1/tts", headers=self.auth, json={"text": "Xin chào", "voice": "chi-chi"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/ogg")
        self.assertEqual(response.content, b"OggSfake-opus")

    def test_unknown_busy_and_synthesis_errors_are_mapped(self):
        engine = FakeEngine()
        client = self.client(engine)

        engine.action = lambda text, voice: (_ for _ in ()).throw(
            self.app_mod.UnknownVoiceError("missing")
        )
        self.assertEqual(
            client.post("/v1/tts", headers=self.auth, json={"text": "x"}).json(),
            {"error": "unknown_voice"},
        )

        engine.action = lambda text, voice: (_ for _ in ()).throw(
            self.app_mod.VoiceBusyError("busy")
        )
        busy = client.post("/v1/tts", headers=self.auth, json={"text": "x"})
        self.assertEqual(busy.status_code, 503)
        self.assertEqual(busy.json(), {"error": "busy"})

        engine.action = lambda text, voice: (_ for _ in ()).throw(
            self.app_mod.VoiceSynthesisError("secret traceback details")
        )
        failed = client.post("/v1/tts", headers=self.auth, json={"text": "x"})
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json(), {"error": "synthesis_failed"})
        self.assertNotIn("secret", failed.text)
        self.assertNotIn(self.token, failed.text)


if __name__ == "__main__":
    unittest.main()

class QeoVoiceRuntimeSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_mod = load_app_module()

    def test_runtime_settings_require_private_env_and_default_port(self):
        base = {
            "QEO_VOICE_TOKEN": "secret",
            "QEO_VOICE_ASSET_ROOT": "/private/voices",
            "QEO_VOICE_BIND_HOST": "100.64.0.10",
        }
        settings = self.app_mod.load_runtime_settings(base)
        self.assertEqual(settings["port"], 8765)
        self.assertEqual(settings["bind_host"], "100.64.0.10")
        self.assertEqual(settings["token"], "secret")
        self.assertEqual(settings["asset_root"], Path("/private/voices"))
        with self.assertRaisesRegex(RuntimeError, "QEO_VOICE_TOKEN"):
            self.app_mod.load_runtime_settings({})
