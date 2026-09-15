# qeo-dailydev Design

Date: 2026-09-15
Status: In-chat design approved; pending written-spec user review
Repository: `tvqqq/qeo-hermes-skills`

## 1. Purpose

Add a Qeo-owned Hermes skill named `qeo-dailydev` that turns the daily.dev Public API into a focused Software Lab research workflow for the Qeo AI Telegram group.

The workflow has two responsibilities:

1. Every morning at 07:00 Vietnam time, publish a short, high-signal digest of 5-8 daily.dev articles into the existing `Software Lab` Telegram forum topic.
2. When users ask technical follow-up questions in that same topic, automatically load `qeo-dailydev`, search daily.dev's article corpus, and answer with grounded links to relevant articles.

The design favors simple deterministic collection/state code plus Hermes reasoning. It does not introduce n8n, a separate database, a long-running custom worker, or a new Telegram bot.

## 2. Success criteria

The implementation is successful when all of the following are true:

- `qeo-dailydev` is discoverable as a valid Hermes skill.
- The daily.dev token is read only from runtime configuration and is never committed to Git.
- A scheduled run can collect candidates from both the personalized feed and curated Software Lab queries.
- Candidate posts are deduplicated and recent repeats are suppressed.
- Hermes produces a Telegram-friendly digest containing 5-8 useful articles when enough quality candidates exist; it may return fewer rather than pad with low-value content.
- The digest reaches the configured Qeo AI `Software Lab` Telegram topic at 07:00 VNT.
- Messages in the Software Lab topic auto-load `qeo-dailydev`.
- Follow-up prompts such as `đào sâu bài #3` can resolve article #3 from the latest digest even though cron deliveries are not assumed to be mirrored into the topic session.
- General technical questions can use daily.dev keyword or semantic recommendations and return grounded article links.
- Deep-dive answers can fetch relevant original article pages when a web/fetch tool is enabled for the Telegram profile, rather than pretending the daily.dev summary is the full article.
- API failures expose useful, sanitized errors without leaking credentials.
- Repository tests and `./scripts/verify.sh --repo-only` pass.

## 3. Constraints and non-goals

### Constraints

- Follow repository naming rules: skill name is `qeo-dailydev`.
- No Telegram compact shortcut is required in v1. Topic binding and natural-language Q&A are the primary interaction model.
- Keep dependencies minimal. Prefer Python standard library HTTP/JSON/date utilities unless an existing repository dependency is clearly better.
- GitHub remains the source of truth. Production copies are deployment artifacts.
- State must be stored outside the deployed skill source directory.
- The daily.dev recommendation endpoints are currently experimental and must be isolated behind a small client interface so changes do not leak through the whole skill.
- Treat the current OpenAPI specification as the endpoint/schema contract when it conflicts with older prose examples in the docs.

### Non-goals for v1

- No web dashboard.
- No vector database or local embeddings.
- No automatic daily.dev bookmark/upvote mutations.
- No custom Telegram command such as `/qeodailydev` unless later usage proves it useful.
- No cross-user personalization beyond the daily.dev account represented by the configured token.
- No multi-source news aggregation outside daily.dev.

## 4. External interfaces

### daily.dev

Base URL:

```text
https://api.daily.dev/public/v1
```

Authentication:

```text
Authorization: Bearer <token>
```

The client supports these read-only operations:

- personalized `For You` feed: `GET /feeds/foryou`;
- keyword recommendations: `GET /recommend/keyword`;
- semantic recommendations: `GET /recommend/semantic`;
- post details when needed: `GET /posts/{id}`.

The recommendation endpoints accept up to 20 results and support `day`, `week`, `month`, `year`, and `all` time filters. They are marked experimental, so all request/response normalization belongs in one client module.

Current documented API limits are 300 requests/minute per IP and 60 requests/minute per user. This workflow stays far below those limits.

The current `FeedPost` schema guarantees fields including `id`, `title`, `url`, optional `summary`, `publishedAt`, `source`, `tags`, `readTime`, `numUpvotes`, and `numComments`. The collector must not assume undocumented engagement fields such as view count exist.

### Hermes Telegram routing

The existing Hermes bot is reused. The Software Lab forum topic is configured under:

```yaml
platforms:
  telegram:
    extra:
      group_topics:
      - chat_id: <QEO_AI_CHAT_ID>
        topics:
        - name: Software Lab
          thread_id: <SOFTWARE_LAB_THREAD_ID>
          skill: qeo-dailydev
```

This provides topic-level session isolation and automatically loads the skill for ordinary Q&A messages in that topic.

### Hermes scheduled delivery

The scheduled digest attaches `qeo-dailydev` to a Hermes cron run and explicitly delivers to:

```text
telegram:<QEO_AI_CHAT_ID>:<SOFTWARE_LAB_THREAD_ID>
```

The cron response wrapper should be disabled so the topic receives only the digest text.

The implementation must not rely on an explicit-target cron delivery being present in the topic's conversational history. The latest digest is persisted as lightweight state so references such as `bài #3` remain resolvable.

## 5. Scheduling strategy

The user-facing requirement is 07:00 Asia/Ho_Chi_Minh every day.

Vietnam is UTC+7 year-round, so the same instant is 00:00 UTC.

A recent Hermes 0.21.x upstream issue reports that recurring non-UTC cron jobs can persist the next occurrence with the wrong timezone after a run. Production setup therefore must inspect the effective Hermes timezone before creating the job.

Preferred configuration when the target Hermes runtime is UTC:

```text
0 0 * * *
```

which corresponds to 07:00 VNT without relying on a non-UTC recurrence conversion.

If the target runtime is not UTC, setup must not blindly change a shared Hermes timezone. It must first verify whether the deployed Hermes version has corrected the recurrence bug. If not, production setup is blocked until the target profile/runtime can safely use UTC or another scheduler-safe solution is chosen.

Acceptance verification must inspect `next_run_at` before and after a completed scheduled execution and confirm that the following occurrence still corresponds to 07:00 VNT. A single successful manual run is not sufficient proof because Hermes also has a recent upstream report where off-tick manual runs may affect the next recurrence.

## 6. Architecture

```text
                    +-------------------------+
                    | daily.dev Public API    |
                    +------------+------------+
                                 |
                     Bearer token, read-only
                                 |
                  +--------------v---------------+
                  | qeo-dailydev deterministic   |
                  | client + collector + state   |
                  +--------------+---------------+
                                 |
                       normalized candidates
                                 |
                  +--------------v---------------+
                  | Hermes + qeo-dailydev skill  |
                  | select, explain, summarize   |
                  +--------------+---------------+
                                 |
               +-----------------+------------------+
               |                                    |
      07:00 scheduled digest                 interactive Q&A
               |                                    |
               +-----------------+------------------+
                                 |
                  +--------------v---------------+
                  | Qeo AI / Software Lab topic  |
                  +------------------------------+
```

Responsibilities are deliberately separated:

- Python code owns API calls, normalization, deduplication, simple ranking signals, local state, and deterministic error behavior.
- Hermes owns qualitative selection, concise explanation, synthesis, and natural-language routing between keyword and semantic research.
- For deep dives, daily.dev discovers and ranks relevant sources; Hermes may fetch a small number of original article URLs through its normal web/fetch capability when that tool is available.
- Telegram/Hermes configuration owns delivery and topic skill binding.

## 7. Proposed skill package

```text
skills/qeo-dailydev/
├── SKILL.md
├── scripts/
│   ├── dailydev_client.py
│   └── dailydev.py
└── references/
    └── topics.json
```

Repository-level additions:

```text
tests/
└── test_qeo_dailydev.py

docs/
└── QEO-DAILYDEV.md
```

No gateway plugin is needed because the workflow requires agent reasoning and Hermes already provides topic binding and scheduled delivery.

## 8. Runtime configuration

Required runtime values:

```text
DAILY_DEV_API_TOKEN
QEO_AI_TELEGRAM_CHAT_ID
QEO_AI_SOFTWARE_LAB_THREAD_ID
```

Optional:

```text
QEO_DAILYDEV_STATE_DIR
```

Default state directory:

```text
$HERMES_HOME/state/qeo-dailydev
```

If `HERMES_HOME` is absent, fall back to `~/.hermes/state/qeo-dailydev`.

Rules:

- Do not put the daily.dev token in `SKILL.md`, tracked `.env` files, cron prompts, logs, URLs, or error messages.
- Missing required configuration must fail explicitly with the variable name but never its value.
- Telegram IDs are deployment-specific configuration and must not be hardcoded into the reusable skill.

## 9. Curated topic model

`references/topics.json` is source-controlled configuration for Software Lab interests. v1 uses six query clusters rather than one request per individual technology.

1. **AI coding and agents** — AI coding agents, coding assistants, agentic software engineering, RAG, LLM app engineering, MCP/tool calling.
2. **Web application engineering** — Next.js, React, TypeScript, frontend architecture, web performance.
3. **Backend and data** — backend APIs, Postgres, Supabase, database architecture, queues/background jobs.
4. **Infrastructure and self-hosting** — Docker, containers, self-hosting, Cloudflare, edge/serverless, low-cost infrastructure.
5. **Automation and developer tools** — n8n, developer tooling, CI/CD, automation, open source tooling.
6. **Solo builder and product engineering** — solo developer, product engineering, indie/bootstrapped software, shipping small products, maintainable architecture.

Keeping clusters in data rather than Python makes tuning straightforward without changing collection logic.

## 10. Morning candidate collection

A scheduled run performs this deterministic sequence:

1. Fetch 20 items from `GET /feeds/foryou`.
2. Query each curated cluster through `GET /recommend/keyword`, requesting a small recent result set.
3. Prefer `time=week`. If one cluster yields too little useful content, widen that cluster once to `month`; never broaden recursively.
4. Normalize responses into one internal post shape.
5. Deduplicate first by post ID and then by canonical article URL when available.
6. Remove post IDs already sent within the recent-history window.
7. Compute deterministic ranking signals.
8. Return a bounded candidate set to Hermes for final editorial selection.

Target raw volume is approximately 50-80 records before deduplication and no more than 40 candidates passed to the model.

The collector should issue requests sequentially or with very low concurrency. This workload does not justify an async HTTP framework.

## 11. Normalized post shape

Internal records contain only useful fields, for example:

```json
{
  "id": "...",
  "title": "...",
  "url": "...",
  "source": "...",
  "published_at": "...",
  "summary": "...",
  "tags": ["..."],
  "read_time": 0,
  "upvotes": 0,
  "comments": 0,
  "origins": ["for_you", "ai-coding-agents"],
  "source_ranks": [1, 4]
}
```

The client must tolerate optional fields being absent, schema additions, and minor pagination-shape changes. It should accept the current OpenAPI pagination field and may defensively accept the older documented cursor naming when harmless.

## 12. Ranking and diversity

The deterministic layer only produces a good shortlist; it does not replace Hermes with a complex scoring model.

Signals:

- personalized-feed presence;
- reciprocal rank within daily.dev results;
- number of distinct query clusters that surfaced the post;
- freshness;
- available engagement such as upvotes/comments.

Exact weights live in one small tested function. No ML model is introduced.

Hermes chooses 5-8 final articles using these priorities:

1. direct relevance to Software Lab;
2. practical technical depth;
3. useful novelty compared with recently sent articles;
4. applicability to building and operating small software products;
5. diversity across topic clusters.

Normally no more than two final articles should come from the same primary cluster unless the day's strongest signal clearly warrants it.

Reject clickbait, generic career content, shallow promotional content, and duplicate coverage even when engagement is high.

## 13. Digest format

```text
☀️ Software Lab — Daily.dev Brief · <date>

🔎 Today's signal
<2-3 sentence synthesis of the strongest pattern across today's articles>

1. <title>
Why it matters: <one concise sentence>
Key idea: <one concise sentence>
<link>

...

💬 Có thể hỏi tiếp: "đào sâu bài #3", "so sánh #2 với Supabase", hoặc hỏi một topic kỹ thuật bất kỳ.
```

Rules:

- 5-8 is a quality target, not a quota; fewer is acceptable.
- Keep each item concise.
- Preserve original links.
- Do not quote large passages.
- Keep factual article metadata distinct from Hermes interpretation when ambiguity matters.

## 14. State and duplicate suppression

No database is needed.

Persist two JSON files:

```text
latest_digest.json
history.json
```

`latest_digest.json` stores generation time and the final ordered articles with enough metadata to resolve follow-up references such as `#3`.

`history.json` stores recently delivered post IDs and timestamps.

Retention policy:

- up to 14 days;
- maximum 300 IDs;
- prune on each successful digest write.

State writes must be atomic: write a temporary file in the same directory and replace the target. A failed scheduled run must not mark unsent candidates as delivered.

## 15. Interactive Q&A behavior

### Follow-up on latest digest

Examples:

```text
đào sâu bài #3
bài 2 áp dụng được gì cho finqeo?
so sánh #1 và #4
```

Behavior:

1. Read `latest_digest.json`.
2. Resolve article numbers deterministically.
3. Use stored daily.dev summaries/metadata as discovery context.
4. For a genuine deep dive, fetch up to a small bounded number of relevant original article pages when Hermes web/fetch tooling is available.
5. If broader evidence is useful, run a daily.dev recommendation query too.
6. Answer with direct links to the relevant article(s).
7. If the digest is missing or an index is invalid, say so instead of guessing.

### General technical research

Examples:

```text
RAG vs fine-tuning cho app nhỏ?
Làm auth trong Next.js hiện nay nên theo hướng nào?
Có pattern nào tốt cho self-hosted background jobs?
```

Routing:

- use keyword recommendation for specific technologies, acronyms, libraries, protocols, or comparison terms;
- use semantic recommendation for natural-language conceptual questions;
- if one mode is weak, permit one bounded fallback query using the other mode;
- fetch a small number of original sources when deeper evidence is needed and web/fetch tooling is available.

The final answer synthesizes rather than merely listing links, notes meaningful disagreement between sources, and cites/links the sources used. If original pages cannot be fetched, the answer must be clear that it is based on daily.dev-provided summaries/metadata rather than full article text.

## 16. API client behavior

`dailydev_client.py` owns all HTTP behavior.

Requirements:

- Bearer authentication;
- configurable request timeout with a conservative default;
- JSON decoding and normalized errors;
- cursor support where used;
- bounded retry for transient failures;
- respect `Retry-After` for HTTP 429;
- never retry 401 automatically;
- never log authorization headers;
- include endpoint category and status in sanitized diagnostics.

Failure behavior:

- `401`: configuration/authentication error; stop the affected operation.
- `429`: wait according to `Retry-After` within a bounded retry budget.
- `5xx` or network timeout: retry a small number of times with backoff, then degrade gracefully.
- one curated cluster failing must not discard successful results from other sources.
- personalized-feed failure may still produce a curated-only digest.

## 17. Command-line utility contract

`scripts/dailydev.py` exposes deterministic machine-friendly entry points:

```text
python3 scripts/dailydev.py candidates
python3 scripts/dailydev.py recommend --query "RAG vs fine-tuning" --mode keyword
python3 scripts/dailydev.py recommend --query "how should a small app remember chats?" --mode semantic
python3 scripts/dailydev.py latest
```

Successful output is JSON on stdout. Errors go to stderr with a non-zero exit status.

The internal file split may be simplified during implementation if repository patterns make a smaller structure clearer, but HTTP, state, and orchestration responsibilities must remain independently testable.

## 18. Skill instructions

`SKILL.md` tells Hermes:

- when to collect morning candidates;
- how to select and format the digest;
- how to resolve `#N` references through latest digest state;
- when to choose keyword versus semantic recommendations;
- when to fetch original article pages for deeper analysis;
- to ground research answers with article links;
- not to imply it read a full article when only daily.dev summary metadata was available;
- not to pad the digest with low-signal content;
- to keep Telegram output concise;
- required configuration and sanitized failure behavior.

It must not duplicate the whole OpenAPI schema or embed credentials.

## 19. Production configuration and deployment

Deployment follows repository conventions:

```bash
./scripts/verify.sh --repo-only
python3 -m unittest discover -s tests -v
sudo ./scripts/deploy.sh qeo-dailydev --hermes-home /opt/hermes/data --profiles <target-profile>
```

After deployment, production setup must:

1. provide `DAILY_DEV_API_TOKEN` to the Hermes runtime environment;
2. resolve the Qeo AI chat ID and Software Lab thread ID;
3. add the `group_topics` binding for `qeo-dailydev` without overwriting unrelated Telegram configuration;
4. ensure the Telegram profile has the web/fetch tool needed for optional deep article reading, or document the summary-only fallback;
5. ensure cron raw delivery (`cron.wrap_response: false`) if that change is compatible with existing jobs; if not, preserve global behavior and accept the wrapper rather than breaking unrelated jobs;
6. create or update exactly one named daily digest job rather than creating duplicates;
7. verify the effective timezone and scheduler behavior described in section 5;
8. restart/reload Hermes only through the established runtime mechanism;
9. verify gateway health and run live Telegram smoke tests.

Prefer an idempotent setup helper if existing Hermes CLI/config APIs make it safe. Do not overwrite unrelated server configuration.

## 20. Tests

Minimum targeted cases:

- missing token fails explicitly;
- auth header uses the token but sanitized errors never expose it;
- `/feeds/foryou` and recommendation results normalize to the same shape;
- duplicate IDs collapse;
- duplicate canonical URLs collapse;
- recently delivered IDs are filtered;
- ranking is deterministic for identical input;
- one cluster failure still returns successful candidates;
- 401 is not retried;
- 429 follows bounded retry behavior;
- latest digest state resolves valid `#N` references and rejects invalid ones;
- history pruning enforces age/count bounds;
- state writes are atomic from the caller's perspective;
- `topics.json` is valid and contains the approved six clusters.

Then run:

```bash
python3 -m unittest discover -s tests -v
./scripts/verify.sh --repo-only
```

## 21. Production smoke checklist

A deployment is accepted only after:

- an authenticated daily.dev request succeeds from the Hermes runtime;
- `candidates` returns non-empty normalized data without exposing the token;
- keyword recommendation works;
- semantic recommendation works;
- a fresh Software Lab message auto-loads `qeo-dailydev`;
- a test digest lands in the correct topic and nowhere else;
- `đào sâu bài #1` resolves against the latest digest;
- if web/fetch is enabled, a deep-dive test can open at least one original source page;
- exactly one active digest schedule exists;
- the next scheduled occurrence still maps to 07:00 VNT after a completed scheduled execution;
- existing `/qeostory` and `/qeovoice` behavior still works.

## 22. Observability and security

Keep observability lightweight. Emit concise diagnostics to stderr for endpoint category, failure status, candidate counts, deduplication counts, and state-write result. Never log the token.

Security rules:

- HTTPS only for daily.dev.
- Read-only daily.dev behavior in v1.
- No real secrets in tests or docs.
- No internal stack traces in Telegram output.
- Do not widen existing Telegram authorization as part of this feature.
- Hermes cron execution history remains the scheduler audit trail; no external logging service is added.

## 23. Future extensions

Deferred until v1 usage justifies them:

- `/qeodailydev` on-demand shortcut;
- per-user topic preferences;
- learning from Telegram reactions;
- bookmark/upvote mutations;
- additional content providers;
- vector search/database;
- weekly Software Lab trend report.

## 24. Reference documentation

- daily.dev Public API: https://docs.daily.dev/public-api/
- daily.dev OpenAPI JSON: https://api.daily.dev/public/v1/docs/json
- daily.dev API announcement supplied for this work: https://daily.dev/posts/public-api-access-is-now-open-for-everyone-ljj8kh9sa
- Hermes scheduled tasks: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/cron.md
- Hermes Telegram topic binding: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/telegram.md
- Hermes cron timezone issue reviewed during design: https://github.com/NousResearch/hermes-agent/issues/103904

## 25. Design decision summary

Use one self-contained `qeo-dailydev` agent skill with a small deterministic Python client/collector and local JSON state. Pull both personalized and curated daily.dev candidates, let Hermes perform final editorial synthesis, deliver one 07:00 VNT digest into the Software Lab Telegram topic, and bind that topic to the same skill for grounded follow-up research. Avoid extra infrastructure, use the current OpenAPI contract, fetch original sources only when a deep answer needs them, and explicitly verify scheduling semantics because current Hermes releases have recent cron regressions.