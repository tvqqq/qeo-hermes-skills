from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


class DeployScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "hermes"
        (self.home / "skills" / "qeo-story").mkdir(parents=True)
        (self.home / "skills" / "qeo-story" / "old.txt").write_text("default-old")
        for profile in ("qeo-personal", "qeo-stock"):
            (self.home / "profiles" / profile / "skills").mkdir(parents=True)
        (self.home / "profiles" / ".deleted").mkdir(parents=True)
        personal = self.home / "profiles" / "qeo-personal" / "skills" / "qeo-story"
        personal.mkdir()
        (personal / "old.txt").write_text("personal-old")
        self.env = os.environ.copy()
        self.env["QEO_DEPLOY_OWNER"] = ""

    def run_script(self, name: str, *args: str, env=None, check=True):
        merged = self.env.copy()
        if env:
            merged.update(env)
        return subprocess.run(
            [str(SCRIPTS / name), *args],
            cwd=ROOT,
            env=merged,
            text=True,
            capture_output=True,
            check=check,
        )

    def latest_backup(self) -> Path:
        root = self.home / "backups" / "qeo-hermes-skills"
        backups = sorted(path for path in root.iterdir() if path.is_dir())
        self.assertTrue(backups, "expected a deployment backup")
        return backups[-1]

    def test_deploy_skill_updates_default_and_all_discovered_profiles(self):
        self.run_script(
            "deploy-skill.sh", "qeo-story",
            "--hermes-home", str(self.home), "--profiles", "all",
        )
        self.assertTrue((self.home / "skills/qeo-story/SKILL.md").exists())
        self.assertTrue((self.home / "profiles/qeo-personal/skills/qeo-story/SKILL.md").exists())
        self.assertTrue((self.home / "profiles/qeo-stock/skills/qeo-story/SKILL.md").exists())
        self.assertFalse((self.home / "profiles/.deleted/skills/qeo-story").exists())
        backup = self.latest_backup()
        self.assertEqual((backup / "skills/qeo-story/old.txt").read_text(), "default-old")
        self.assertEqual(
            (backup / "profiles/qeo-personal/skills/qeo-story/old.txt").read_text(),
            "personal-old",
        )

    def test_profile_selector_updates_only_default_and_selected_profiles(self):
        self.run_script(
            "deploy-skill.sh", "qeo-story",
            "--hermes-home", str(self.home), "--profiles", "qeo-personal",
        )
        self.assertTrue((self.home / "skills/qeo-story/SKILL.md").exists())
        self.assertTrue((self.home / "profiles/qeo-personal/skills/qeo-story/SKILL.md").exists())
        self.assertFalse((self.home / "profiles/qeo-stock/skills/qeo-story").exists())

    def test_invalid_skill_name_fails_before_modifying_targets(self):
        result = self.run_script(
            "deploy-skill.sh", "story",
            "--hermes-home", str(self.home), "--profiles", "all",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / "skills/qeo-story/old.txt").read_text(), "default-old")

    def test_deploy_orchestrator_copies_shared_plugin(self):
        result = self.run_script(
            "deploy.sh", "qeo-story",
            "--hermes-home", str(self.home), "--profiles", "all", "--no-restart",
            env={"QEO_VERIFY_COMMAND": "true"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.home / "plugins/qeo-shortcuts/plugin.yaml").exists())

    def test_failed_post_deploy_verification_restores_skill_and_plugin(self):
        plugin = self.home / "plugins" / "qeo-shortcuts"
        plugin.mkdir(parents=True)
        (plugin / "old.txt").write_text("plugin-old")

        result = self.run_script(
            "deploy.sh", "qeo-story",
            "--hermes-home", str(self.home), "--profiles", "all", "--no-restart",
            env={"QEO_VERIFY_COMMAND": "false"}, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / "skills/qeo-story/old.txt").read_text(), "default-old")
        self.assertFalse((self.home / "skills/qeo-story/SKILL.md").exists())
        self.assertEqual((plugin / "old.txt").read_text(), "plugin-old")
        self.assertFalse((plugin / "plugin.yaml").exists())

    def test_install_is_thin_wrapper_over_deploy(self):
        marker = Path(self.tmp.name) / "deploy-args.txt"
        fake = Path(self.tmp.name) / "fake-deploy.sh"
        fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > "{marker}"\n')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

        self.run_script(
            "install.sh", "qeo-story",
            "--hermes-home", str(self.home), "--profiles", "all",
            env={"QEO_DEPLOY_SH": str(fake)},
        )
        args = marker.read_text()
        self.assertIn("qeo-story", args)
        self.assertIn("--profiles all", args)
        self.assertIn(f"--hermes-home {self.home}", args)


if __name__ == "__main__":
    unittest.main()
