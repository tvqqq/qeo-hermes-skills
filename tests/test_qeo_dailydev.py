from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

        client = self.client_mod.DailyDevClient(
            "secret-token", opener=opener, sleeper=lambda _: None
        )
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

        client = self.client_mod.DailyDevClient(
            "secret-token", opener=opener, sleeper=lambda _: None
        )
        client.recommend_keyword("RAG vs fine-tuning", limit=8, time_range="week")
        client.recommend_semantic(
            "how should a small app remember conversations?",
            limit=10,
            time_range="month",
        )
        self.assertIn("/recommend/keyword?", urls[0])
        self.assertIn("q=RAG+vs+fine-tuning", urls[0])
        self.assertIn("limit=8", urls[0])
        self.assertIn("time=week", urls[0])
        self.assertIn("/recommend/semantic?", urls[1])
        self.assertIn(
            "q=how+should+a+small+app+remember+conversations%3F", urls[1]
        )
        self.assertIn("limit=10", urls[1])
        self.assertIn("time=month", urls[1])

    def test_401_is_not_retried_and_error_is_sanitized(self):
        attempts = 0

        def opener(request, timeout):
            nonlocal attempts
            attempts += 1
            raise HTTPError(
                request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad")
            )

        client = self.client_mod.DailyDevClient(
            "secret-token", opener=opener, sleeper=lambda _: None
        )
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
                raise HTTPError(
                    request.full_url,
                    429,
                    "Too Many",
                    {"Retry-After": "7"},
                    io.BytesIO(b""),
                )
            return FakeResponse({"data": [{"id": "ok"}]})

        client = self.client_mod.DailyDevClient(
            "secret-token", opener=opener, sleeper=sleeps.append
        )
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

        client = self.client_mod.DailyDevClient(
            "secret-token", max_retries=2, opener=opener, sleeper=sleeps.append
        )
        with self.assertRaises(self.client_mod.DailyDevError) as caught:
            client.get_for_you()
        self.assertEqual(attempts, 3)
        self.assertEqual(sleeps, [1, 2])
        self.assertNotIn("secret-token", str(caught.exception))

    def test_malformed_json_is_sanitized(self):
        client = self.client_mod.DailyDevClient(
            "secret-token",
            opener=lambda request, timeout: FakeResponse(b"not-json"),
            sleeper=lambda _: None,
        )
        with self.assertRaises(self.client_mod.DailyDevError) as caught:
            client.get_for_you()
        self.assertIn("invalid JSON", str(caught.exception))
        self.assertNotIn("secret-token", str(caught.exception))


class DailyDevCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        cls.core = load_module("qeo_dailydev_core", "dailydev.py")

    def test_normalize_post_uses_safe_defaults_and_source_name(self):
        result = self.core.normalize_post(
            {
                "id": "p1",
                "title": "Useful article",
                "url": "https://example.com/a",
                "source": {"name": "Example"},
                "publishedAt": "2026-09-15T00:00:00Z",
                "tags": [{"name": "python"}, "agents"],
                "numUpvotes": 5,
            },
            "for_you",
            1,
        )
        self.assertEqual(result["source"], "Example")
        self.assertEqual(result["summary"], "")
        self.assertEqual(result["read_time"], 0)
        self.assertEqual(result["comments"], 0)
        self.assertEqual(result["tags"], ["python", "agents"])
        self.assertEqual(result["origins"], ["for_you"])
        self.assertEqual(result["source_ranks"], [1])

    def test_merge_posts_deduplicates_id_and_canonical_url(self):
        one = self.core.normalize_post(
            {
                "id": "p1",
                "title": "A",
                "url": "https://EXAMPLE.com/a/",
                "numUpvotes": 1,
            },
            "for_you",
            3,
        )
        same_id = self.core.normalize_post(
            {
                "id": "p1",
                "title": "A",
                "url": "https://example.com/a",
                "numComments": 2,
            },
            "ai-coding-agents",
            1,
        )
        same_url = self.core.normalize_post(
            {
                "id": "p2",
                "title": "A mirror",
                "url": "https://example.com/a#top",
            },
            "web-app-engineering",
            4,
        )
        merged = self.core.merge_posts([one, same_id, same_url])
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            set(merged[0]["origins"]),
            {"for_you", "ai-coding-agents", "web-app-engineering"},
        )
        self.assertEqual(merged[0]["upvotes"], 1)
        self.assertEqual(merged[0]["comments"], 2)

    def test_score_prefers_personal_and_better_rank(self):
        now = datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc)
        base = {
            "published_at": "2026-09-15T00:00:00Z",
            "upvotes": 0,
            "comments": 0,
            "origins": ["backend-data"],
            "source_ranks": [8],
        }
        personal = dict(base, origins=["for_you"], source_ranks=[8])
        rank_one = dict(base, source_ranks=[1])
        self.assertGreater(
            self.core.score_post(personal, now), self.core.score_post(base, now)
        )
        self.assertGreater(
            self.core.score_post(rank_one, now), self.core.score_post(base, now)
        )
        missing = {
            "published_at": "",
            "upvotes": 0,
            "comments": 0,
            "origins": [],
            "source_ranks": [],
        }
        self.assertIsInstance(self.core.score_post(missing, now), float)

    def test_load_history_keeps_only_last_14_days(self):
        now = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "history.json").write_text(
                json.dumps(
                    {
                        "delivered": {
                            "fresh": (now - timedelta(days=2)).isoformat(),
                            "old": (now - timedelta(days=20)).isoformat(),
                        }
                    }
                )
            )
            self.assertEqual(
                self.core.load_history(state, now),
                {"fresh": (now - timedelta(days=2)).isoformat()},
            )

    def test_finalize_digest_preserves_order_and_caps_history(self):
        now = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            delivered = {
                f"old-{i}": (now - timedelta(minutes=i + 1)).isoformat()
                for i in range(305)
            }
            state.mkdir(parents=True, exist_ok=True)
            (state / "history.json").write_text(
                json.dumps({"delivered": delivered})
            )
            selected = [
                {
                    "id": "b",
                    "title": "B",
                    "url": "https://b",
                    "origins": ["backend-data"],
                },
                {
                    "id": "a",
                    "title": "A",
                    "url": "https://a",
                    "origins": ["for_you"],
                },
            ]
            result = self.core.finalize_digest(state, selected, now)
            self.assertEqual([item["id"] for item in result["articles"]], ["b", "a"])
            latest = json.loads((state / "latest_digest.json").read_text())
            history = json.loads((state / "history.json").read_text())["delivered"]
            self.assertEqual([item["id"] for item in latest["articles"]], ["b", "a"])
            self.assertLessEqual(len(history), 300)
            self.assertIn("a", history)
            self.assertIn("b", history)
            self.assertFalse(
                any(path.name.endswith(".tmp") for path in state.iterdir())
            )

    def test_collect_candidates_propagates_auth_failure(self):
        now = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
        error_type = self.core.DailyDevError

        class Client:
            def get_for_you(self, limit=20):
                raise error_type(
                    "auth failed", status=401, endpoint="/feeds/foryou"
                )

        with self.assertRaises(error_type):
            self.core.collect_candidates(Client(), [], {}, now)

    def test_collect_candidates_propagates_access_denied(self):
        now = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
        error_type = self.core.DailyDevError

        class Client:
            def get_for_you(self, limit=20):
                raise error_type(
                    "access denied", status=403, endpoint="/feeds/foryou"
                )

        with self.assertRaises(error_type):
            self.core.collect_candidates(Client(), [], {}, now)

    def test_collect_candidates_fails_when_every_source_errors(self):
        now = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)

        class Client:
            def get_for_you(self, limit=20):
                raise RuntimeError("offline")

            def recommend_keyword(self, query, limit=8, time_range="week"):
                raise RuntimeError("offline")

        with self.assertRaises(self.core.DailyDevError):
            self.core.collect_candidates(
                Client(), [{"id": "one", "query": "one"}], {}, now
            )

    def test_collect_candidates_uses_hybrid_sources_and_degrades_per_cluster(self):
        now = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)

        class Client:
            def __init__(self):
                self.calls = []

            def get_for_you(self, limit=20):
                self.calls.append(("for_you", limit))
                return {
                    "data": [
                        {
                            "id": "personal",
                            "title": "Personal",
                            "url": "https://x/p",
                            "publishedAt": "2026-09-15T00:00:00Z",
                        }
                    ]
                }

            def recommend_keyword(self, query, limit=8, time_range="week"):
                self.calls.append((query, time_range))
                if query == "broken":
                    raise RuntimeError("boom")
                if time_range == "week":
                    return {
                        "data": [
                            {
                                "id": f"{query}-1",
                                "title": query,
                                "url": f"https://x/{query}-1",
                                "publishedAt": "2026-09-14T00:00:00Z",
                            }
                        ]
                    }
                return {
                    "data": [
                        {
                            "id": f"{query}-2",
                            "title": query + " 2",
                            "url": f"https://x/{query}-2",
                            "publishedAt": "2026-09-13T00:00:00Z",
                        },
                        {
                            "id": f"{query}-3",
                            "title": query + " 3",
                            "url": f"https://x/{query}-3",
                            "publishedAt": "2026-09-12T00:00:00Z",
                        },
                    ]
                }

        client = Client()
        diagnostics = {}
        candidates = self.core.collect_candidates(
            client,
            [{"id": "good", "query": "good"}, {"id": "bad", "query": "broken"}],
            {"already": now.isoformat()},
            now,
            diagnostics=diagnostics,
        )
        self.assertIn("personal", [item["id"] for item in candidates])
        self.assertIn(("good", "week"), client.calls)
        self.assertIn(("good", "month"), client.calls)
        self.assertIn("bad", diagnostics["failed_sources"])
        self.assertLessEqual(len(candidates), 40)


class DailyDevCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        cls.core = load_module("qeo_dailydev_cli", "dailydev.py")

    def test_candidates_requires_token(self):
        with self.assertRaises(SystemExit):
            self.core.main(["candidates"], env={})

    def test_recommend_routes_keyword_and_semantic(self):
        class Client:
            instances = []

            def __init__(self, token):
                self.calls = []
                self.__class__.instances.append(self)

            def recommend_keyword(self, query, limit=10, time_range="month"):
                self.calls.append(("keyword", query, limit, time_range))
                return {"data": []}

            def recommend_semantic(self, query, limit=10, time_range="month"):
                self.calls.append(("semantic", query, limit, time_range))
                return {"data": []}

        with contextlib.redirect_stdout(io.StringIO()):
            self.core.main(
                ["recommend", "--mode", "keyword", "--query", "Next.js"],
                env={"DAILY_DEV_API_TOKEN": "x"},
                client_factory=Client,
            )
            self.core.main(
                ["recommend", "--mode", "semantic", "--query", "small app memory"],
                env={"DAILY_DEV_API_TOKEN": "x"},
                client_factory=Client,
            )
        self.assertEqual(Client.instances[0].calls[0][0], "keyword")
        self.assertEqual(Client.instances[1].calls[0][0], "semantic")

    def test_latest_resolves_index_without_api_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "latest_digest.json").write_text(
                json.dumps({"articles": [{"id": "a"}, {"id": "b"}, {"id": "c"}]})
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.core.main(
                    ["latest", "--index", "3", "--state-dir", tmp], env={}
                )
            self.assertEqual(json.loads(output.getvalue())["id"], "c")

    def test_finalize_rejects_unknown_id_without_mutating_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            bundle = root / "bundle.json"
            bundle.write_text(
                json.dumps(
                    {"candidates": [{"id": "a", "title": "A", "url": "https://a"}]}
                )
            )
            with self.assertRaises(SystemExit):
                self.core.main(
                    [
                        "finalize",
                        "--input",
                        str(bundle),
                        "--ids",
                        "missing",
                        "--state-dir",
                        str(state),
                    ],
                    env={},
                )
            self.assertFalse((state / "history.json").exists())


class QeoDailyDevSkillContractTests(unittest.TestCase):
    def test_skill_defines_digest_and_research_workflows(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: qeo-dailydev", text)
        self.assertIn("DAILY_DEV_API_TOKEN", text)
        for command in ("candidates", "finalize", "latest", "recommend"):
            self.assertIn(command, text)
        self.assertIn("5-8", text)
        self.assertIn("☀️ Software Lab — Daily.dev Brief", text)
        self.assertIn("keyword", text.lower())
        self.assertIn("semantic", text.lower())
        self.assertNotIn("/qeodailydev", text)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", text)


class QeoDailyDevRepositoryContractTests(unittest.TestCase):
    def test_verify_script_and_docs_cover_dailydev(self):
        verify = (ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        doc = (ROOT / "docs/QEO-DAILYDEV.md").read_text(encoding="utf-8")
        for expected in (
            "qeo-dailydev",
            "dailydev_client.py",
            "dailydev.py",
            "topics.json",
        ):
            self.assertIn(expected, verify)
        self.assertIn("qeo-dailydev", readme)
        self.assertIn("docs/QEO-DAILYDEV.md", readme)
        for expected in (
            "DAILY_DEV_API_TOKEN",
            "group_topics",
            "skill: qeo-dailydev",
            "telegram:<QEO_AI_CHAT_ID>:<SOFTWARE_LAB_THREAD_ID>",
            "0 0 * * *",
            "07:00 VNT",
            "cron.wrap_response",
            "next_run_at",
        ):
            self.assertIn(expected, doc)


if __name__ == "__main__":
    unittest.main()
