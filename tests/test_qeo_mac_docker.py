from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "workers" / "qeo-voice" / "Dockerfile"
HEALTHCHECK = ROOT / "workers" / "qeo-voice" / "healthcheck.py"
COMPOSE = ROOT / "docker" / "mac" / "compose.yml"
ENV_EXAMPLE = ROOT / "docker" / "mac" / ".env.example"


class QeoMacDockerStaticTests(unittest.TestCase):
    def read_required(self, path: Path) -> str:
        self.assertTrue(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")
        return path.read_text(encoding="utf-8")

    def test_voice_dockerfile_has_minimal_runtime_contract(self):
        text = self.read_required(DOCKERFILE)
        self.assertIn("FROM python:3.12-slim-bookworm", text)
        self.assertIn("ffmpeg", text)
        self.assertIn("libsndfile1", text)
        self.assertIn("--no-install-recommends", text)
        self.assertIn("requirements.txt", text)
        self.assertIn("healthcheck.py", text)
        self.assertNotIn("reference.wav", text)
        self.assertNotIn("COPY .", text)

    def test_healthcheck_uses_authenticated_local_probe(self):
        text = self.read_required(HEALTHCHECK)
        self.assertIn("QEO_VOICE_TOKEN", text)
        self.assertIn("http://127.0.0.1:8765/health", text)
        self.assertIn("Authorization", text)
        self.assertIn("Bearer", text)
        self.assertIn('"status"', text)
        self.assertNotIn("print(token", text)

    def test_compose_is_loopback_only_and_persistent(self):
        text = self.read_required(COMPOSE)
        self.assertIn("qeo-voice-worker:", text)
        self.assertIn("platform: linux/arm64", text)
        self.assertIn("restart: unless-stopped", text)
        self.assertIn('127.0.0.1:${QEO_VOICE_PORT:-8765}:8765', text)
        self.assertIn('${QEO_MAC_DATA_ROOT}/voices:/data/voices:ro', text)
        self.assertIn('${QEO_MAC_DATA_ROOT}/cache:/cache', text)
        self.assertIn("HF_HOME=/cache/huggingface", text)
        self.assertIn("healthcheck:", text)
        self.assertNotIn('0.0.0.0:${QEO_VOICE_PORT', text)

    def test_env_example_contains_only_safe_runtime_placeholders(self):
        text = self.read_required(ENV_EXAMPLE)
        self.assertIn("QEO_MAC_DATA_ROOT=", text)
        self.assertIn("QEO_VOICE_TOKEN=replace-me", text)
        self.assertIn("QEO_VOICE_PORT=8765", text)
        self.assertNotIn("tskey-", text)
        self.assertNotIn("213.163.", text)


if __name__ == "__main__":
    unittest.main()
