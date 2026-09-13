from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STORY_PATH = ROOT / "plugins" / "qeo-shortcuts" / "handlers" / "story.py"


def load_story_module():
    spec = importlib.util.spec_from_file_location("qeo_shortcuts_story", STORY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {STORY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StoryShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.story = load_story_module()

    def test_extracts_known_preset_and_ignores_unknown(self):
        self.assertEqual(self.story._extract_preset("mango"), "mango")
        self.assertIsNone(self.story._extract_preset("unknown"))

    def test_resolves_profile_skill_dir_from_hermes_home(self):
        source = SimpleNamespace(profile="qeo-personal")
        with mock.patch.dict(os.environ, {"HERMES_HOME": "/tmp/hermes"}, clear=False):
            path = self.story._skill_dir_for_source(source)
        self.assertEqual(path, Path("/tmp/hermes/profiles/qeo-personal/skills/qeo-story"))

    def test_resolves_default_profile_skill_dir(self):
        source = SimpleNamespace(profile=None)
        with mock.patch.dict(os.environ, {"HERMES_HOME": "/tmp/hermes"}, clear=False):
            path = self.story._skill_dir_for_source(source)
        self.assertEqual(path, Path("/tmp/hermes/skills/qeo-story"))

    def test_accepts_compact_and_compatibility_command_forms(self):
        for command in ("/qeostory", "/qeo_story", "/qeo-story"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.story.CMD_RE.match(command))

    def test_success_schedules_image_and_skips_agent_turn(self):
        event = SimpleNamespace(
            text="/qeostory mango",
            media_urls=["/tmp/input.jpg"],
            source=SimpleNamespace(profile="qeo-personal", chat_id="1", thread_id="2"),
            message_id="10",
        )
        scheduled = []

        def capture(coro):
            scheduled.append(coro)
            coro.close()

        with mock.patch.object(self.story.os.path, "exists", return_value=True), \
             mock.patch.object(self.story, "_render_story", return_value="/tmp/output.png"), \
             mock.patch.object(self.story, "_schedule", side_effect=capture):
            result = self.story._handle_qeostory_native(event, object())

        self.assertEqual(result, {"action": "skip", "reason": "qeostory-rendered"})
        self.assertEqual(len(scheduled), 1)

    def test_render_failure_schedules_error_and_skips_agent_turn(self):
        event = SimpleNamespace(
            text="/qeostory",
            media_urls=["/tmp/input.jpg"],
            source=SimpleNamespace(profile="default", chat_id="1", thread_id=None),
            message_id="10",
        )
        scheduled = []

        def capture(coro):
            scheduled.append(coro)
            coro.close()

        with mock.patch.object(self.story.os.path, "exists", return_value=True), \
             mock.patch.object(self.story, "_render_story", side_effect=RuntimeError("boom")), \
             mock.patch.object(self.story, "_schedule", side_effect=capture):
            result = self.story._handle_qeostory_native(event, object())

        self.assertEqual(result, {"action": "skip", "reason": "qeostory-render-failed"})
        self.assertEqual(len(scheduled), 1)

    def test_no_image_falls_through_to_registered_help_command(self):
        event = SimpleNamespace(
            text="/qeostory",
            media_urls=[],
            source=SimpleNamespace(profile="default"),
        )
        self.assertIsNone(self.story._handle_qeostory_native(event, object()))


if __name__ == "__main__":
    unittest.main()
