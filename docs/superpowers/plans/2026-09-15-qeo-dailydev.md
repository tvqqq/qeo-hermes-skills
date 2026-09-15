# Qeo Daily.dev Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `qeo-dailydev`, a Hermes skill that prepares a high-signal hybrid daily.dev digest for the Qeo AI Software Lab Telegram topic at 07:00 VNT and supports grounded follow-up research in that topic.

**Architecture:** A dependency-free Python client owns daily.dev HTTP/retry behavior. A deterministic utility normalizes, deduplicates, ranks, persists lightweight state, and exposes machine-friendly CLI commands; `SKILL.md` tells Hermes how to select 5-8 final articles, summarize them, resolve `bài #N`, and use keyword/semantic recommendations for Q&A. Existing Hermes topic binding, cron delivery, and generic Qeo deployment are reused rather than adding a gateway plugin or scheduler.

**Tech Stack:** Python 3.11+ standard library (`urllib`, `json`, `argparse`, `datetime`, `pathlib`), Python `unittest`, Hermes Agent skills/cron/Telegram forum-topic routing, daily.dev Public API v1.

**Spec:** `docs/superpowers/specs/2026-09-15-qeo-dailydev-design.md`

## Global Constraints

- Skill name is exactly `qeo-dailydev`; no Telegram compact slash command is added in v1.
- GitHub is source of truth; production copies under Hermes data are deployment artifacts.
- No database, n8n workflow, new bot, vector store, local embeddings, or long-running custom worker.
- No third-party Python dependency unless stdlib proves insufficient; v1 should require none.
- Read-only daily.dev API usage only.
- Canonical token variable is `DAILY_DEV_API_TOKEN`; its value must never be committed, logged, printed, embedded in URLs, or copied into cron prompts.
- Current OpenAPI contract wins over stale prose docs: personalized endpoint is `GET /feeds/foryou`; recommendation endpoints are `GET /recommend/keyword` and `GET /recommend/semantic` with `q`, `limit`, and `time`; keyword may also return a cursor.
- Recommendation endpoints are experimental and stay behind the client interface.
- State is outside the deployed skill source: `$QEO_DAILYDEV_STATE_DIR`, else `$HERMES_HOME/state/qeo-dailydev`, else `~/.hermes/state/qeo-dailydev`.
- Persistent state consists of `latest_digest.json` and `history.json`; temporary candidate bundles are disposable files and do not become durable state.
- History retention is 14 days and at most 300 delivered post IDs.
- A generation/API failure must not update `latest_digest.json` or `history.json`.
- Digest target is 5-8 useful articles; fewer is valid when quality is low.
- Morning source mix is personalized For You plus six curated Software Lab query clusters.
- Telegram delivery uses the existing Hermes bot and forum topic; no direct Telegram Bot API code is added.
- User-facing schedule is 07:00 VNT. If production Hermes runs UTC, use `0 0 * * *`; verify `next_run_at` before and after a run because of the known non-UTC recurrence risk in recent Hermes 0.21.x builds.

---

## File Map

- `skills/qeo-dailydev/SKILL.md` — Hermes behavior for morning digest, latest-digest follow-ups, and general daily.dev research.
- `skills/qeo-dailydev/references/topics.json` — six curated Software Lab clusters and query text.
- `skills/qeo-dailydev/scripts/dailydev_client.py` — authenticated HTTP client, retries, endpoint wrappers, sanitized errors.
- `skills/qeo-dailydev/scripts/dailydev.py` — normalization, dedupe/ranking, state handling, and CLI entry points.
- `tests/test_qeo_dailydev.py` — API client, ranking/state/CLI, skill contract, and secret-safety tests.
- `scripts/verify.sh` — add static `qeo-dailydev` presence/frontmatter/compile/topic checks.
- `docs/QEO-DAILYDEV.md` — production configuration, topic binding, cron creation, smoke/rollback guidance.
- `README.md` — list `qeo-dailydev` and link its operator guide.

Existing `scripts/deploy-skill.sh` and `scripts/deploy.sh` are intentionally unchanged: they already accept arbitrary valid `qeo-*` skills and deploy to default/discovered profiles.

---

### Task 1: Daily.dev API Client

**Files:**
- Create: `skills/qeo-dailydev/scripts/dailydev_client.py`
- Create/extend: `tests/test_qeo_dailydev.py`

**Interfaces:**

```python
class DailyDevError(RuntimeError):
    status: int | None
    endpoint: str

class DailyDevClient:
    def __init__(self, token: str, *, base_url="https://api.daily.dev/public/v1",
                 timeout=15.0, max_retries=2, opener=None, sleeper=None): ...
    def get_for_you(self, *, limit=20, cursor=None) -> dict: ...
    def recommend_keyword(self, query: str, *, limit=10, time_range="month", cursor=None) -> dict: ...
    def recommend_semantic(self, query: str, *, limit=10, time_range="month") -> dict: ...
    def get_post(self, post_id: str) -> dict: ...
```

- [ ] **Step 1: Write RED client tests**

Use `unittest`, `unittest.mock`, `io.BytesIO`, and small fake HTTP response/error objects. Cover exact request construction:

```python
client.get_for_you(limit=20)
# path contains /feeds/foryou?limit=20
# header Authorization == "Bearer secret-token"
# header Accept == "application/json"

client.recommend_keyword("RAG vs fine-tuning", limit=8, time_range="week")
# q is URL encoded, limit=8, time=week

client.recommend_semantic("how should a small app remember conversations?", limit=10, time_range="month")
# path == /recommend/semantic with q/limit/time
```

Add tests that 401 raises once without retry; 429 honors numeric `Retry-After` and retries within `max_retries`; 503/network timeout retries then raises; malformed JSON raises sanitized `DailyDevError`; no exception string contains `secret-token`.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests.test_qeo_dailydev.DailyDevClientTests -v
```

Expected: FAIL because `dailydev_client.py` does not exist.

- [ ] **Step 3: Implement the minimal stdlib client**

Use `urllib.parse.urlencode`, `urllib.request.Request/urlopen`, and `urllib.error.HTTPError/URLError`.

Core request loop:

```python
for attempt in range(self.max_retries + 1):
    try:
        response = self._opener(request, timeout=self.timeout)
        return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 401:
            raise DailyDevError("daily.dev authentication failed", status=401, endpoint=path)
        if exc.code == 429 and attempt < self.max_retries:
            self._sleep(retry_after_seconds(exc))
            continue
        if 500 <= exc.code < 600 and attempt < self.max_retries:
            self._sleep(2 ** attempt)
            continue
        raise sanitized_error(...)
    except (URLError, TimeoutError) as exc:
        if attempt < self.max_retries:
            self._sleep(2 ** attempt)
            continue
        raise DailyDevError("daily.dev request failed", endpoint=path) from exc
```

Clamp server-provided retry delay to a safe maximum (60 seconds) and never include request headers/token in error text.

- [ ] **Step 4: Verify GREEN and compile**

```bash
python3 -m unittest tests.test_qeo_dailydev.DailyDevClientTests -v
python3 -m py_compile skills/qeo-dailydev/scripts/dailydev_client.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/qeo-dailydev/scripts/dailydev_client.py tests/test_qeo_dailydev.py
git commit -m "feat: add dailydev api client"
```

---

### Task 2: Curated Topics, Normalization, Ranking, and State

**Files:**
- Create: `skills/qeo-dailydev/references/topics.json`
- Create: `skills/qeo-dailydev/scripts/dailydev.py`
- Extend: `tests/test_qeo_dailydev.py`

**Interfaces:**

```python
def normalize_post(raw: dict, origin: str, rank: int) -> dict: ...
def merge_posts(records: list[dict]) -> list[dict]: ...
def score_post(post: dict, now: datetime) -> float: ...
def resolve_state_dir(env: Mapping[str, str] | None = None) -> Path: ...
def load_history(state_dir: Path, now: datetime) -> dict[str, str]: ...
def finalize_digest(state_dir: Path, selected: list[dict], now: datetime) -> dict: ...
def collect_candidates(client, clusters: list[dict], history: dict[str, str], now: datetime,
                       *, max_candidates=40) -> list[dict]: ...
```

`normalize_post()` returns:

```json
{
  "id": "post-id",
  "title": "...",
  "url": "https://...",
  "source": "Publisher",
  "published_at": "2026-09-15T00:00:00Z",
  "summary": "...",
  "tags": ["..."],
  "read_time": 7,
  "upvotes": 10,
  "comments": 2,
  "origins": ["for_you"],
  "source_ranks": [1]
}
```

- [ ] **Step 1: Add the six approved query clusters**

`topics.json` contains stable IDs and one compact query per cluster:

```json
{
  "clusters": [
    {"id":"ai-coding-agents","query":"AI coding agents agentic software engineering RAG MCP tool calling LLM application engineering"},
    {"id":"web-app-engineering","query":"Next.js React TypeScript frontend architecture web performance"},
    {"id":"backend-data","query":"backend APIs Postgres Supabase database architecture queues background jobs"},
    {"id":"infra-self-hosting","query":"Docker containers self-hosting Cloudflare edge serverless low-cost infrastructure"},
    {"id":"automation-devtools","query":"n8n developer tooling CI/CD automation open source tooling"},
    {"id":"solo-product-engineering","query":"solo developer product engineering indie bootstrapped software maintainable architecture"}
  ]
}
```

- [ ] **Step 2: Write RED normalization/dedupe/ranking/state tests**

Assert missing optional fields become safe defaults; duplicate IDs merge origins/ranks; different IDs with the same canonical URL merge; history IDs from the last 14 days are filtered; history older than 14 days is ignored.

Use the fixed scoring contract:

```text
+3.0 if origin contains for_you
+max(0, 2.5 - 0.15 * (best_rank - 1))
+min(2.0, 0.5 * max(0, unique_origins - 1))
+freshness: 2.0 <=1d, 1.5 <=3d, 1.0 <=7d, 0.25 <=30d, else 0
+engagement: min(2.0, log1p(upvotes)/4 + log1p(comments)/6)
```

Tests must prove a For You result beats an otherwise-equal non-personal result; a rank-1 result beats rank-8; and score tolerates missing dates/engagement.

State tests use `tempfile.TemporaryDirectory()` and assert `finalize_digest()` writes only `latest_digest.json` and `history.json`, preserves final order, prunes to 14 days/300 IDs, and uses `Path.replace()` semantics so readers never see partial JSON.

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest tests.test_qeo_dailydev.DailyDevCoreTests -v
```

Expected: FAIL because core functions do not exist.

- [ ] **Step 4: Implement collection behavior**

`collect_candidates()`:

```text
1. Try client.get_for_you(limit=20); normalize with origin=for_you.
2. For each cluster, call recommend_keyword(query, limit=8, time_range=week).
3. If that cluster yields fewer than 3 records, call the same query once with time_range=month and merge.
4. A failing cluster is recorded in diagnostics but does not discard other results.
5. A failed personalized request still permits curated-only output.
6. Merge/dedupe, filter recent history, score, sort by (-score, title.lower()), return first max_candidates.
```

Return diagnostics alongside candidates only if needed by CLI; do not expose token/request headers.

- [ ] **Step 5: Verify GREEN**

```bash
python3 -m unittest tests.test_qeo_dailydev.DailyDevCoreTests -v
python3 -m py_compile skills/qeo-dailydev/scripts/dailydev.py
```

- [ ] **Step 6: Commit**

```bash
git add skills/qeo-dailydev/references/topics.json skills/qeo-dailydev/scripts/dailydev.py tests/test_qeo_dailydev.py
git commit -m "feat: add dailydev candidate ranking and state"
```

---

### Task 3: Machine-Friendly CLI and Safe Finalization

**Files:**
- Modify: `skills/qeo-dailydev/scripts/dailydev.py`
- Extend: `tests/test_qeo_dailydev.py`

**Interfaces:**

```text
python3 scripts/dailydev.py candidates [--limit 40]
python3 scripts/dailydev.py recommend --mode keyword|semantic --query TEXT [--limit 10] [--time month]
python3 scripts/dailydev.py latest [--index N]
python3 scripts/dailydev.py finalize --input FILE --ids ID1,ID2,...
```

`candidates` JSON output shape:

```json
{"generated_at":"...","candidates":[...],"diagnostics":{"failed_sources":[]}}
```

`finalize --input` reads a candidate bundle file produced by the same run, validates all requested IDs exist, preserves ID order, writes durable state, and returns the selected ordered records. The caller may use a temporary file under `/tmp`; temporary candidate bundles are not durable skill state.

- [ ] **Step 1: Write RED CLI tests**

Test `build_parser()` and `main(argv, env)` directly rather than spawning network calls. Inject/mock `DailyDevClient` for candidate/recommend tests.

Required cases:

```python
with self.assertRaisesRegex(SystemExit, "DAILY_DEV_API_TOKEN"):
    main(["candidates"], env={})
```

Also assert `recommend --mode keyword` calls `recommend_keyword`; semantic calls `recommend_semantic`; `latest --index 3` returns article 3 and invalid/missing digest exits clearly; `finalize` rejects an ID not present in the input bundle and leaves history unchanged.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests.test_qeo_dailydev.DailyDevCliTests -v
```

- [ ] **Step 3: Implement CLI**

Use `argparse`. Token lookup must happen only for commands that need the API (`candidates`, `recommend`), not for `latest` or `finalize`.

For API commands:

```python
token = (env or os.environ).get("DAILY_DEV_API_TOKEN", "").strip()
if not token:
    parser.error("DAILY_DEV_API_TOKEN is required")
```

JSON goes to stdout; sanitized failures go to stderr with non-zero exit. No logging framework is required.

- [ ] **Step 4: Verify GREEN plus no-token smoke**

```bash
python3 -m unittest tests.test_qeo_dailydev.DailyDevCliTests -v
python3 skills/qeo-dailydev/scripts/dailydev.py latest --state-dir /tmp/qeo-dailydev-empty || true
```

Expected: tests pass; empty latest command fails clearly without asking for an API token.

- [ ] **Step 5: Commit**

```bash
git add skills/qeo-dailydev/scripts/dailydev.py tests/test_qeo_dailydev.py
git commit -m "feat: add qeo dailydev cli"
```

---

### Task 4: Hermes Skill Behavior

**Files:**
- Create: `skills/qeo-dailydev/SKILL.md`
- Extend: `tests/test_qeo_dailydev.py`

**Interfaces:** Hermes uses the CLI above. No gateway hook and no `/qeodailydev` registration.

- [ ] **Step 1: Write RED repository-contract tests**

Assert `SKILL.md` contains frontmatter `name: qeo-dailydev`, `DAILY_DEV_API_TOKEN`, commands `candidates`, `finalize`, `latest`, `recommend`, the 5-8 quality target, exact digest title `☀️ Software Lab — Daily.dev Brief`, and Q&A routing guidance. Assert it does **not** contain a real-looking bearer token, `TELEGRAM_BOT_TOKEN`, or `/qeodailydev` registration language.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests.test_qeo_dailydev.QeoDailyDevSkillContractTests -v
```

- [ ] **Step 3: Write `SKILL.md` morning workflow**

Frontmatter:

```yaml
---
name: qeo-dailydev
description: Curate daily.dev Software Lab briefings and grounded technical research.
version: 1.0.0
author: QeoQeo
metadata:
  hermes:
    tags: [dailydev, research, software-engineering, ai, telegram]
    category: research
---
```

Morning instructions must be explicit:

```text
1. Create a temporary candidate JSON path.
2. Run `dailydev.py candidates`, saving the exact JSON to that file.
3. Select up to 5-8 articles by relevance, depth, novelty, builder applicability, diversity; do not pad weak content; normally max two per primary cluster.
4. Draft the complete Telegram digest using the approved format.
5. Only after the complete digest is ready, run `dailydev.py finalize --input ... --ids ...` in the exact displayed order.
6. Return only the digest as the final response so Hermes cron delivers it.
```

If candidate generation or finalization fails, return a short sanitized operational error; do not pretend a digest succeeded.

- [ ] **Step 4: Write Q&A workflow**

For `bài #N`, run `latest --index N`; never guess indexes. For specific technologies/acronyms/comparisons, use keyword recommendation; for conceptual natural-language questions, semantic; allow one fallback query if results are weak. daily.dev results are discovery/metadata: when deep evidence is requested and Hermes web/fetch is available, fetch only a small relevant set of original article URLs. If full pages cannot be read, say the answer is based on daily.dev summaries/metadata.

- [ ] **Step 5: Verify GREEN**

```bash
python3 -m unittest tests.test_qeo_dailydev.QeoDailyDevSkillContractTests -v
```

- [ ] **Step 6: Commit**

```bash
git add skills/qeo-dailydev/SKILL.md tests/test_qeo_dailydev.py
git commit -m "feat: add qeo dailydev hermes skill"
```

---

### Task 5: Repository Verification and Operator Documentation

**Files:**
- Modify: `scripts/verify.sh`
- Create: `docs/QEO-DAILYDEV.md`
- Modify: `README.md`
- Extend: `tests/test_qeo_dailydev.py`

**Interfaces:** `./scripts/verify.sh --repo-only` validates the new skill without needing a live API token or network.

- [ ] **Step 1: Write RED verification/docs contract tests**

Assert `verify.sh` checks:

```text
skills/qeo-dailydev/SKILL.md exists
frontmatter name is qeo-dailydev
dailydev_client.py and dailydev.py compile
references/topics.json parses and contains exactly six unique cluster IDs
```

Assert README names `qeo-dailydev` and docs link. Assert `docs/QEO-DAILYDEV.md` contains `DAILY_DEV_API_TOKEN`, `group_topics`, `skill: qeo-dailydev`, `telegram:<QEO_AI_CHAT_ID>:<SOFTWARE_LAB_THREAD_ID>`, `0 0 * * *`, `07:00 VNT`, `cron.wrap_response`, and `next_run_at` verification.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests.test_qeo_dailydev.QeoDailyDevRepositoryContractTests -v
```

- [ ] **Step 3: Extend `verify.sh` minimally**

Add `DAILYDEV_SKILL="$REPO_ROOT/skills/qeo-dailydev"`; require its `SKILL.md`, check frontmatter, add its two Python scripts to `py_compile`, and use a small inline Python JSON check:

```python
data = json.loads(path.read_text(encoding="utf-8"))
clusters = data.get("clusters", [])
assert len(clusters) == 6
ids = [item.get("id") for item in clusters]
assert len(set(ids)) == 6 and all(ids)
assert all(item.get("query") for item in clusters)
```

Do not contact daily.dev in repository verification.

- [ ] **Step 4: Write `docs/QEO-DAILYDEV.md`**

Document:

```text
Purpose / runtime flow
Required env values (names only)
Deploy qeo-dailydev using existing deploy.sh
Telegram group_topics binding snippet
Cron wrapper config: cron.wrap_response: false
UTC-safe schedule: 0 0 * * * == 07:00 VNT
Cron create command with --skill qeo-dailydev and explicit Telegram chat:thread target
Manual API/CLI smoke without printing token
Hermes cron list/status/doctor checks
Manual cron run and next_run_at before/after acceptance
Q&A smoke: “đào sâu bài #1” and one general research question
Failure/rollback guidance
```

Do not hardcode actual chat ID, thread ID, or token.

- [ ] **Step 5: Update README**

Add a short `qeo-dailydev` section describing the morning digest + topic Q&A, and link `docs/QEO-DAILYDEV.md` under Documentation.

- [ ] **Step 6: Run GREEN**

```bash
python3 -m unittest tests.test_qeo_dailydev.QeoDailyDevRepositoryContractTests -v
./scripts/verify.sh --repo-only
```

- [ ] **Step 7: Commit**

```bash
git add scripts/verify.sh docs/QEO-DAILYDEV.md README.md tests/test_qeo_dailydev.py
git commit -m "docs: add qeo dailydev operations"
```

---

### Task 6: Full Validation and Diff Review

**Files:** no new files unless a directly related failure requires a fix.

- [ ] **Step 1: Run targeted tests**

```bash
python3 -m unittest tests.test_qeo_dailydev -v
```

Expected: PASS.

- [ ] **Step 2: Run the complete repository suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: PASS with existing story/voice/deployment coverage unchanged.

- [ ] **Step 3: Run repository verification**

```bash
./scripts/verify.sh --repo-only
```

Expected: `verify: repository checks passed`.

- [ ] **Step 4: Secret scan**

```bash
git grep -nE 'Authorization: Bearer [A-Za-z0-9._-]{16,}|DAILY_DEV_API_TOKEN=' -- ':!docs/superpowers/*'
```

Expected: no committed secret value. Variable names/documentation are allowed; actual values are not.

- [ ] **Step 5: Review branch diff**

```bash
git diff --check main...HEAD
git diff --stat main...HEAD
git diff main...HEAD -- skills/qeo-dailydev tests/test_qeo_dailydev.py scripts/verify.sh docs/QEO-DAILYDEV.md README.md
```

Confirm no `plugins/qeo-shortcuts` or unrelated worker/deploy behavior changed.

- [ ] **Step 6: Commit directly related fixes, then repeat Steps 1-5 until clean**

Use focused commit messages matching the actual fix.

---

### Task 7: Production Integration Acceptance

**Repository code is complete before this task. Production requires authorized access plus deployment-specific values and the daily.dev token; none are committed.**

- [ ] Set `DAILY_DEV_API_TOKEN` in the Hermes runtime secret environment.
- [ ] Identify the existing Qeo AI group `chat_id` and Software Lab `thread_id`; keep them runtime-only.
- [ ] Deploy with existing repository tooling:

```bash
sudo ./scripts/deploy.sh qeo-dailydev --hermes-home /opt/hermes/data --profiles all
./scripts/verify.sh --hermes-home /opt/hermes/data --profiles all --skill qeo-dailydev
```

- [ ] Merge `skill: qeo-dailydev` into the existing Telegram `group_topics` entry without overwriting unrelated topics/config.
- [ ] Set `cron.wrap_response: false` without changing unrelated cron settings.
- [ ] Inspect the effective Hermes scheduler timezone. If UTC, create the recurring job at `0 0 * * *`; otherwise verify the deployed Hermes recurrence fix before choosing a non-UTC schedule.
- [ ] Create one cron job named `Software Lab daily.dev brief`, attach `qeo-dailydev`, and deliver explicitly to `telegram:<chat_id>:<thread_id>`.
- [ ] Run a live candidate/API smoke and a manual cron execution; confirm a real digest arrives in Software Lab with 5-8 or fewer high-quality articles and no wrapper.
- [ ] Confirm `latest --index 1` resolves the first delivered article and a Telegram reply `đào sâu bài #1` uses that same article.
- [ ] Ask one general Software Lab question and confirm keyword/semantic research returns direct source links.
- [ ] Inspect cron status/doctor and `next_run_at` before and after a completed execution; next occurrence must still represent 07:00 VNT.
- [ ] If Telegram delivery is recorded as `delivery_failed`, treat the run as production-failed and investigate delivery separately from agent execution before declaring acceptance.

---

## Self-Review Result

- **Spec coverage:** API auth/endpoints, hybrid ingestion, curated clusters, dedupe/ranking, 14-day history, latest-digest index resolution, keyword/semantic Q&A, original-source deep dives, topic binding, explicit Telegram delivery, schedule safety, docs, tests, and production acceptance all map to tasks above.
- **Isolation:** No gateway plugin is added. Existing generic deploy scripts are reused. daily.dev experimental APIs are isolated in `dailydev_client.py`.
- **Type/interface consistency:** CLI verbs and function names are defined once and reused by `SKILL.md`, docs, and tests.
- **Secret safety:** token is environment-only; repository tests and final validation explicitly scan for accidental committed values.
- **State safety:** durable state changes only via `finalize`; candidate collection/research cannot mark posts delivered. Hermes delivery itself happens after the agent final response, so production acceptance separately checks Hermes `delivery_failed` status; the repository does not duplicate Telegram delivery to fake transactional delivery state.
- **YAGNI:** no DB, async HTTP stack, extra service, custom Telegram handler, ML ranker, or new deployment abstraction.
