from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "qeo-dailydev"
SCRIPTS = SKILL / "scripts"


def load_module(name: str, filename: str):
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        return None


class DailyDevClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SCRIPTS))
        cls.client_mod = load_module("qeo_dailydev_client", "dailydev_client.py")

    @classmethod
    def tearDownClass(cls):
        if sys.path and sys.path[0] == str(SCRIPTS):
            sys.path.pop(0)

    def test_for_you_request_uses_bearer_auth_and_limit(self):
        seen = []

        def opener(request, timeout):
            seen.append((request, timeout))
            return FakeResponse({"data": []})

        client = self.client_mod.DailyDevClient("secret-token", opener=opener, sleeper=lambda _: None)
        self.assertEqual(client.get_for_you(limit=20), {"data": []})
        request, timeout = seen[0]
        self.assertIn("/feeds/foryou?limit=20", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(timeout, 15.0)

    def test_keyword_and_semantic_requests_encode_query_and_time(self):
        urls = []

        def opener(request, timeout):
            urls.append(request.full_url)
            return FakeResponse({"data": []})

        client = self.client_mod.DailyDevClient("secret-token", opener=opener, sleeper=lambda _: None)
        client.recommend_keyword("RAG vs fine-tuning", limit=8, time_range="week")
        client.recommend_semantic("how should a small app remember conversations?", limit=10, time_range="month")
        self.assertIn("/recommend/keyword?", urls[0])
        self.assertIn("q=RAG+vs+fine-tuning", urls[0])
        self.assertIn("limit=8", urls[0])
        self.assertIn("time=week", urls[0])
        self.assertIn("/recommend/semantic?", urls[1])
        self.assertIn("q=how+should+a+small+app+remember+conversations%3F", urls[1])
        self.assertIn("limit=10", urls[1])
        self.assertIn("time=month", urls[1])

    def test_401_is_not_retried_and_error_is_sanitized(self):
        attempts = 0

        def opener(request, timeout):
            nonlocal attempts
            attempts += 1
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad"))

        client = self.client_mod.DailyDevClient("secret-token", opener=opener, sleeper=lambda _: None)
        with self.assertRaises(self.client_mod.DailyDevError) as caught:
            client.get_for_you()
        self.assertEqual(attempts, 1)
        self.assertEqual(caught.exception.status, 401)
        self.assertNotIn("secret-token", str(caught.exception))

    def test_429_honors_retry_after_and_retries(self):
        attempts = 0
        sleeps = []

        def opener(request, timeout):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise HTTPError(request.full_url, 429, "Too Many", {"Retry-After": "7"}, io.BytesIO(b""))
            return FakeResponse({"data": [{"id": "ok"}]})

        client = self.client_mod.DailyDevClient("secret-token", opener=opener, sleeper=sleeps.append)
        result = client.get_for_you()
        self.assertEqual(result["data"][0]["id"], "ok")
        self.assertEqual(attempts, 2)
        self.assertEqual(sleeps, [7.0])

    def test_transient_failure_retries_then_raises(self):
        attempts = 0
        sleeps = []

        def opener(request, timeout):
            nonlocal attempts
            attempts += 1
            raise URLError("offline")

        client = self.client_mod.DailyDevClient("secret-token", max_retries=2, opener=opener, sleeper=sleeps.append)
        with self.assertRaises(self.client_mod.DailyDevError) as caught:
            client.get_for_you()
        self.assertEqual(attempts, 3)
        self.assertEqual(sleeps, [1, 2])
        self.assertNotIn("secret-token", str(caught.exception))

    def test_malformed_json_is_sanitized(self):
        client = self.client_mod.DailyDevClient(
            "secret-token", opener=lambda request, timeout: FakeResponse(b"not-json"), sleeper=lambda _: None
        )
        with self.assertRaises(self.client_mod.DailyDevError) as caught:
            client.get_for_you()
        self.assertIn("invalid JSON", str(caught.exception))
        self.assertNotIn("secret-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
