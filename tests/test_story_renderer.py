from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "qeo-story" / "scripts"


def load_module(name: str, filename: str):
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class StoryRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SCRIPTS))
        cls.presets = load_module("qeo_story_presets", "presets.py")
        cls.image_utils = load_module("qeo_story_image_utils", "image_utils.py")
        cls.renderer = load_module("qeo_story_renderer", "render_story.py")

    @classmethod
    def tearDownClass(cls):
        if sys.path and sys.path[0] == str(SCRIPTS):
            sys.path.pop(0)

    def test_renders_png_at_story_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            output = Path(tmp) / "story.png"
            Image.new("RGB", (640, 1200), "white").save(source)

            self.renderer.render_story(source, output)

            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1080, 1920))

    def test_presets_match_approved_set(self):
        self.assertEqual(
            set(self.presets.PRESETS),
            {"qeo-green", "qeo", "mango", "mojito", "stellar", "midnight-city"},
        )

    def test_unknown_preset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown preset"):
            self.presets.get_preset("not-a-preset")

    def test_fit_inside_preserves_aspect_ratio(self):
        self.assertEqual(self.image_utils.fit_inside(1000, 2000, 500, 500), (250, 500))

    def test_unsupported_input_format_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.gif"
            output = Path(tmp) / "story.png"
            Image.new("RGB", (100, 100), "white").save(source, format="GIF")

            with self.assertRaisesRegex(ValueError, "Unsupported image format"):
                self.renderer.render_story(source, output)


if __name__ == "__main__":
    unittest.main()
