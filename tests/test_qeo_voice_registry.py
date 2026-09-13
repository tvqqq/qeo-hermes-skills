from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "workers" / "qeo-voice" / "voices.json"
SKILL = ROOT / "skills" / "qeo-voice" / "SKILL.md"
VOICES_DOC = ROOT / "skills" / "qeo-voice" / "references" / "voices.md"
GITIGNORE = ROOT / ".gitignore"


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


if __name__ == "__main__":
    unittest.main()
