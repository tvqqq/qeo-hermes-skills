from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "workers" / "qeo-voice" / "voices.json"
SKILL = ROOT / "skills" / "qeo-voice" / "SKILL.md"
VOICES_DOC = ROOT / "skills" / "qeo-voice" / "references" / "voices.md"
GITIGNORE = ROOT / ".gitignore"
WORKER = ROOT / "workers" / "qeo-voice"


def load_worker_module(name: str, filename: str):
    path = WORKER / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class QeoVoiceRegistryStaticTests(unittest.TestCase):
    def test_chi_chi_is_default_tight_denoised_voice(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(registry["default"], "chi-chi")
        chi = registry["voices"]["chi-chi"]
        self.assertEqual(chi["display_name"], "Chi Chi")
        self.assertEqual(chi["engine"], "v3turbo")
        self.assertEqual(chi["profile"], "tight-denoised")
        self.assertEqual(chi["temperature"], 0.55)
        self.assertEqual(chi["top_k"], 20)
        self.assertEqual(chi["top_p"], 0.90)
        self.assertEqual(chi["repetition_penalty"], 1.20)
        self.assertTrue(chi["denoise"])
        self.assertTrue(chi["use_ref_codes"])
        self.assertEqual(chi["max_chars"], 140)
        self.assertEqual(chi["silence_p"], 0.10)
        self.assertEqual(chi["crossfade_p"], 0.0)
        self.assertEqual(chi["reference"], "chi-chi/reference.wav")

    def test_skill_and_voice_docs_define_public_contract(self):
        skill = SKILL.read_text(encoding="utf-8")
        voices_doc = VOICES_DOC.read_text(encoding="utf-8")
        self.assertIn("name: qeo-voice", skill)
        self.assertIn("/qeovoice", skill)
        self.assertIn("Mac mini", skill)
        self.assertIn("no fallback", skill.lower())
        self.assertIn("Chi Chi", voices_doc)
        self.assertIn("tight-denoised", voices_doc)

    def test_gitignore_blocks_private_voice_audio_only_in_worker_scope(self):
        rules = GITIGNORE.read_text(encoding="utf-8")
        self.assertIn("workers/qeo-voice/**/*.wav", rules)
        self.assertIn("workers/qeo-voice/**/*.mp3", rules)
        self.assertIn("workers/qeo-voice/**/*.ogg", rules)
        self.assertIn("workers/qeo-voice/.env", rules)
        self.assertIn("workers/qeo-voice/.venv/", rules)
        self.assertNotIn("\n*.wav\n", f"\n{rules}\n")


class QeoVoiceRegistryRuntimeTests(unittest.TestCase):
    def _asset_root(self, tmp: str) -> Path:
        root = Path(tmp) / "assets"
        ref = root / "chi-chi" / "reference.wav"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"RIFFfake")
        return root

    def test_load_registry_resolves_default_and_named_voice(self):
        registry_mod = load_worker_module("qeo_voice_registry", "registry.py")
        with tempfile.TemporaryDirectory() as tmp:
            registry = registry_mod.load_registry(REGISTRY, self._asset_root(tmp))
            self.assertEqual(registry.default_slug, "chi-chi")
            self.assertEqual(registry.resolve(None).slug, "chi-chi")
            self.assertEqual(registry.resolve("chi-chi").display_name, "Chi Chi")

    def test_unknown_voice_is_rejected(self):
        registry_mod = load_worker_module("qeo_voice_registry_unknown", "registry.py")
        with tempfile.TemporaryDirectory() as tmp:
            registry = registry_mod.load_registry(REGISTRY, self._asset_root(tmp))
            with self.assertRaises(registry_mod.UnknownVoiceError):
                registry.resolve("missing")

    def test_missing_reference_asset_is_rejected(self):
        registry_mod = load_worker_module("qeo_voice_registry_missing", "registry.py")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(registry_mod.VoiceAssetError):
                registry_mod.load_registry(REGISTRY, Path(tmp) / "empty")

    def test_reference_must_stay_under_asset_root(self):
        registry_mod = load_worker_module("qeo_voice_registry_traversal", "registry.py")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            asset_root = tmp_path / "assets"
            asset_root.mkdir()
            escape = tmp_path / "escape.wav"
            escape.write_bytes(b"RIFFfake")
            payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
            payload["voices"]["chi-chi"]["reference"] = "../escape.wav"
            registry_path = tmp_path / "voices.json"
            registry_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(registry_mod.VoiceAssetError):
                registry_mod.load_registry(registry_path, asset_root)


class FakeVieNeuBackend:
    def __init__(self):
        self.add_voice_calls = []
        self.infer_calls = []

    def add_voice(self, **kwargs):
        self.add_voice_calls.append(kwargs)

    def infer(self, **kwargs):
        self.infer_calls.append(kwargs)
        return [0.0, 0.1, -0.1]


class QeoVoiceEngineTests(unittest.TestCase):
    def _load(self, tmp: str):
        if str(WORKER) not in sys.path:
            sys.path.insert(0, str(WORKER))
        registry_mod = load_worker_module("registry", "registry.py")
        engine_mod = load_worker_module("qeo_voice_engine", "engine.py")
        root = Path(tmp) / "assets"
        ref = root / "chi-chi" / "reference.wav"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"RIFFfake")
        registry = registry_mod.load_registry(REGISTRY, root)
        return engine_mod, registry

    def test_start_creates_one_backend_and_enrolls_chi_chi_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine_mod, registry = self._load(tmp)
            backend = FakeVieNeuBackend()
            factory_calls = []
            engine = engine_mod.VieNeuVoiceEngine(
                registry,
                backend_factory=lambda: factory_calls.append(True) or backend,
                wav_encoder=lambda audio: b"RIFFencoded",
            )
            engine.start()
            engine.start()
            self.assertEqual(len(factory_calls), 1)
            self.assertEqual(len(backend.add_voice_calls), 1)
            call = backend.add_voice_calls[0]
            self.assertEqual(call["name"], "chi-chi")
            self.assertTrue(call["denoise"])
            self.assertTrue(call["use_ref_codes"])

    def test_synthesize_forwards_tight_profile_and_returns_wav_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine_mod, registry = self._load(tmp)
            backend = FakeVieNeuBackend()
            engine = engine_mod.VieNeuVoiceEngine(
                registry,
                backend_factory=lambda: backend,
                wav_encoder=lambda audio: b"RIFFencoded",
            )
            engine.start()
            result = engine.synthesize("Xin chào")
            self.assertEqual(result, b"RIFFencoded")
            call = backend.infer_calls[0]
            self.assertEqual(call["text"], "Xin chào")
            self.assertEqual(call["voice"], "chi-chi")
            self.assertEqual(call["temperature"], 0.55)
            self.assertEqual(call["top_k"], 20)
            self.assertEqual(call["top_p"], 0.90)
            self.assertEqual(call["repetition_penalty"], 1.20)
            self.assertEqual(call["max_chars"], 140)
            self.assertEqual(call["silence_p"], 0.10)
            self.assertEqual(call["crossfade_p"], 0.0)
            self.assertTrue(call["use_ref_codes"])

    def test_overlapping_synthesis_is_rejected_as_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine_mod, registry = self._load(tmp)
            engine = engine_mod.VieNeuVoiceEngine(
                registry,
                backend_factory=FakeVieNeuBackend,
                wav_encoder=lambda audio: b"RIFFencoded",
            )
            engine.start()
            self.assertTrue(engine._lock.acquire(blocking=False))
            try:
                with self.assertRaises(engine_mod.VoiceBusyError):
                    engine.synthesize("second")
            finally:
                engine._lock.release()


if __name__ == "__main__":
    unittest.main()


class QeoVoiceOpusEncoderTests(unittest.TestCase):
    def test_encoder_uses_ffmpeg_libopus_and_returns_ogg_bytes(self):
        if str(WORKER) not in sys.path:
            sys.path.insert(0, str(WORKER))
        load_worker_module("registry", "registry.py")
        engine_mod = load_worker_module("qeo_voice_engine_opus", "engine.py")
        calls = []

        class Result:
            returncode = 0
            stdout = b"OggSopus"
            stderr = b""

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Result()

        output = engine_mod._encode_ogg_opus(
            [0.0],
            wav_encoder=lambda audio: b"RIFFpcm",
            runner=runner,
        )
        self.assertEqual(output, b"OggSopus")
        command, kwargs = calls[0]
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("libopus", command)
        self.assertEqual(kwargs["input"], b"RIFFpcm")
