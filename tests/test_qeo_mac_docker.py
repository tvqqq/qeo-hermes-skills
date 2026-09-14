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


import os
import stat
import subprocess
import tempfile

SCRIPTS = ROOT / "scripts"


class QeoMacDockerWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fakebin = self.root / "bin"
        self.fakebin.mkdir()
        self.log = self.root / "calls.log"
        self.data = self.root / "data"
        (self.data / "voices" / "chi-chi").mkdir(parents=True)
        (self.data / "cache").mkdir()
        (self.data / "voices" / "chi-chi" / "reference.wav").write_bytes(b"RIFF-test")
        self.env_file = self.root / "mac.env"
        self.env_file.write_text(
            f'QEO_MAC_DATA_ROOT="{self.data}"\n'
            'QEO_VOICE_TOKEN=test-only\n'
            'QEO_VOICE_PORT=8765\n',
            encoding="utf-8",
        )
        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.fakebin}:{self.env['PATH']}"
        self.env["QEO_MAC_ENV_FILE"] = str(self.env_file)

    def write_executable(self, name: str, body: str) -> None:
        path = self.fakebin / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_script(self, name: str, *, env=None, check=False):
        script = SCRIPTS / name
        self.assertTrue(script.is_file(), f"missing required script: {name}")
        values = self.env.copy()
        if env:
            values.update(env)
        return subprocess.run(
            [str(script)], cwd=ROOT, env=values,
            text=True, capture_output=True, check=check,
        )

    def test_mac_up_rejects_missing_private_config(self):
        env = {"QEO_MAC_ENV_FILE": str(self.root / "missing.env")}
        result = self.run_script("mac-up.sh", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mac.env", result.stderr + result.stdout)


    def test_mac_up_rejects_missing_reference(self):
        (self.data / "voices" / "chi-chi" / "reference.wav").unlink()
        self.write_executable("docker", "exit 0\n")
        result = self.run_script("mac-up.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reference.wav", result.stderr + result.stdout)

    def test_mac_up_builds_and_waits_for_health(self):
        self.write_executable(
            "docker",
            f'echo "docker $*" >> "{self.log}"\n'
            'case "$*" in *"ps --format json"*) echo "{\\"Health\\":\\"healthy\\"}" ;; esac\n',
        )
        result = self.run_script("mac-up.sh")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = self.log.read_text(encoding="utf-8")
        self.assertIn("up -d --build", calls)
        self.assertIn("ps --format json qeo-voice-worker", calls)

    def test_mac_down_stops_without_deleting_state(self):
        self.write_executable("docker", f'echo "docker $*" >> "{self.log}"\n')
        result = self.run_script("mac-down.sh")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = self.log.read_text(encoding="utf-8")
        self.assertIn(" stop", calls)
        self.assertNotIn("down -v", calls)

    def test_mac_status_queries_compose(self):
        self.write_executable("docker", f'echo "docker $*" >> "{self.log}"\n')
        result = self.run_script("mac-status.sh")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = self.log.read_text(encoding="utf-8")
        self.assertIn(" ps", calls)


class QeoMacRuntimePathTests(unittest.TestCase):
    def test_repo_ignores_local_runtime_state(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".local/", text)

    def test_mac_scripts_default_to_canonical_repo_local_runtime(self):
        for name in ("mac-up.sh", "mac-down.sh", "mac-status.sh"):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("rev-parse --path-format=absolute --git-common-dir", text, name)
            self.assertIn(".local/qeo-mac/config/mac.env", text, name)
            self.assertNotIn("Library/Application Support/QeoSkills", text, name)

    def test_env_example_uses_repo_local_data_root(self):
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("/_www/qeo-hermes-skills/.local/qeo-mac", text)
        self.assertNotIn("Library/Application Support/QeoSkills", text)

    def test_docs_use_repo_local_runtime_path(self):
        docs = (
            ROOT / "docs" / "QEO-VOICE.md",
            ROOT / "docs" / "superpowers" / "specs" / "2026-09-14-qeo-mac-docker-runtime-design.md",
            ROOT / "docs" / "superpowers" / "plans" / "2026-09-14-qeo-mac-docker-runtime.md",
        )
        for path in docs:
            text = path.read_text(encoding="utf-8")
            self.assertIn(".local/qeo-mac", text, path.name)
            self.assertNotIn("Library/Application Support/QeoSkills", text, path.name)
