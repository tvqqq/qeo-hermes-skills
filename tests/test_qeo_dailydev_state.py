from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "qeo-dailydev" / "scripts"
sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("qeo_dailydev_state_test", SCRIPTS / "dailydev.py")
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load qeo-dailydev dailydev.py")
dailydev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dailydev
spec.loader.exec_module(dailydev)


class DailyDevStateEnvironmentTests(unittest.TestCase):
    def test_explicit_empty_env_does_not_leak_process_environment(self):
        with mock.patch.dict(os.environ, {"HERMES_HOME": "/should-not-leak"}, clear=False):
            expected = Path.home() / ".hermes" / "state" / "qeo-dailydev"
            self.assertEqual(dailydev.resolve_state_dir({}), expected)


if __name__ == "__main__":
    unittest.main()
