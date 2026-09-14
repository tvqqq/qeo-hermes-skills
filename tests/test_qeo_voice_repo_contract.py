from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify.sh"
README = ROOT / "README.md"
DEPLOYMENT = ROOT / "docs" / "DEPLOYMENT.md"
COMMANDS = ROOT / "docs" / "TELEGRAM-COMMANDS.md"
VOICE_DOC = ROOT / "docs" / "QEO-VOICE.md"


class QeoVoiceRepositoryContractTests(unittest.TestCase):
    def test_verify_script_validates_qeo_voice_contract(self):
        text = VERIFY.read_text(encoding="utf-8")
        self.assertIn("qeo-voice", text)
        self.assertIn("qeovoice", text)
        self.assertIn("voices.json", text)
        self.assertIn("handlers/voice.py", text)

    def test_normal_upcloud_deploy_scripts_contain_no_voice_compute(self):
        text = "\n".join((ROOT / "scripts" / name).read_text(encoding="utf-8").lower()
                         for name in ("deploy.sh", "deploy-skill.sh", "install.sh"))
        self.assertNotIn("vieneu", text)
        self.assertNotIn("workers/qeo-voice", text)

    def test_docs_define_qeovoice_mac_only_ogg_transport(self):
        readme = README.read_text(encoding="utf-8")
        deployment = DEPLOYMENT.read_text(encoding="utf-8")
        commands = COMMANDS.read_text(encoding="utf-8")
        voice_doc = VOICE_DOC.read_text(encoding="utf-8")

        self.assertIn("qeo-voice", readme)
        self.assertIn("/qeovoice", readme)
        self.assertIn("qeo-voice", deployment)
        self.assertIn("/qeovoice", deployment)
        self.assertIn("qeo-voice", commands)
        self.assertIn("/qeovoice", commands)
        self.assertIn("Mac mini", voice_doc)
        self.assertIn("no fallback", voice_doc.lower())
        self.assertIn("OGG/Opus", voice_doc)
        self.assertIn("QEO_VOICE_WORKER_URL", voice_doc)
        self.assertIn("QEO_VOICE_TOKEN", voice_doc)

    def test_repo_only_verification_passes(self):
        result = subprocess.run(
            [str(VERIFY), "--repo-only"], cwd=ROOT,
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
