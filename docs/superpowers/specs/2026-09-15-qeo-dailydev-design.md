# qeo-dailydev Design

Date: 2026-09-15
Status: Approved design, pending implementation-plan review
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
- General technical questions can use daily.dev keyword or semantic recommendation endpoints and return grounded article links.
- API failures expose useful, sanitized errors without leaking credentials.
- Repository tests and `./scripts/verify.sh --repo-only` pass.

## 3. Constraints and non-goals

### Constraints

- Follow repository naming rules: skill name is `qeo-dailydev`.
- No Telegram compact shortcut is required in v1. Topic binding and natural-language Q&A are the primary interaction model.
- Keep dependencies minimal. Prefer Python standard library HTTP/JSON/date utilities unless a repository-standard dependency is clearly better.
- GitHub remains the source of truth. Production copies are deployment artifacts.
- State must be stored outside the deployed skill source directory.
- The daily.dev recommendation endpoints are currently experimental and must be isolated behind a small client interface so changes do not leak through the whole skill.

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

The client must support the following read-only operations used by this feature:

- personalized feed retrieval (`/feeds`);
- keyword recommendations (`/recommend/keyword`);
- semantic recommendations (`/recommend/semantic`);
- post detail retrieval only when required to fill missing metadata.

The recommendation endpoints accept up to 20 results and support time filters such as `day`, `week`, `month`, `year`, and `all`. They are marked experimental, so response normalization belongs in one client module.

Current documented API limits are 300 requests/minute per IP and 60 requests/minute per user. This workflow stays far below those limits.

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

Vietnam is UTC+7 year-round, so the canonical wall-clock instant is 00:00 UTC.

A recent Hermes 0.21.x upstream issue reports that recurring non-UTC cron jobs can persist the next occurrence with the wrong timezone after a run. To avoid making the workflow depend on that behavior, production setup should prefer a UTC-based schedule when the Hermes runtime is UTC:

```text
0 0 * * *
```

which is 07:00 VNT.

Deployment must inspect the effective Hermes timezone before creating the job rather than blindly assuming it. If the runtime is not UTC, configuration must either:

1. use a Hermes version where the recurrence bug is verified fixed, then schedule the equivalent 07:00 VNT local expression; or
2. run this profile/runtime in UTC and use `0 0 * * *`.

Changing a shared Hermes timezone solely for this skill is not allowed if that would change unrelated jobs.

Acceptance verification must inspect `next_run_at` both before and after one test execution and confirm that the following scheduled occurrence still corresponds to 07:00 VNT. A single successful manual run is not sufficient proof because Hermes also has a recent upstream report where off-tick manual runs may affect the next recurrence.

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

Required secrets/configuration:

```text
DAILY_DEV_API_TOKEN
QEO_AI_TELEGRAM_CHAT_ID
QEO_AI_SOFTWARE_LAB_THREAD_ID
```

Optional configuration:

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
- Telegram IDs may be runtime configuration because they are deployment-specific and should not be hardcoded into the reusable skill.

## 9. Curated topic model

`references/topics.json` is source-controlled configuration for Software Lab interests. v1 uses six query clusters rather than one API request per individual technology.

### Cluster 1: AI coding and agents

Terms include:

- AI coding agents
- coding assistants
- agentic software engineering
- RAG
- LLM application engineering
- MCP / tool calling

### Cluster 2: Web application engineering

Terms include:

- Next.js
- React
- TypeScript
- frontend architecture
- web performance

### Cluster 3: Backend and data

Terms include:

- backend APIs
- Postgres
- Supabase
- database architecture
- queues and background jobs

### Cluster 4: Infrastructure and self-hosting

Terms include:

- Docker
- containers
- self-hosting
- Cloudflare
- edge/serverless
- low-cost infrastructure

### Cluster 5: Automation and developer tools

Terms include:

- n8n
- developer tooling
- CI/CD
- automation
- open source tooling

### Cluster 6: Solo builder and product engineering

Terms include:

- solo developer
- product engineering
- indie/bootstrapped software
- shipping small products
- maintainable architecture

Keeping clusters in data rather than Python makes tuning straightforward without changing collection logic.

## 10. Morning candidate collection

A scheduled run performs this deterministic collection sequence:

1. Fetch approximately 20 items from the personalized `For You` feed.
2. Query each curated cluster through keyword recommendation, requesting a small recent result set.
3. Prefer `time=week` for normal morning discovery. If a cluster returns too few useful candidates, the collector may widen that cluster to `month` once; it must not recursively broaden without a bound.
4. Normalize every response into one internal post shape.
5. Deduplicate first by post ID and then by canonical article URL when available.
6. Remove post IDs already sent within the configured recent-history window.
7. Compute deterministic ranking signals.
8. Return a bounded candidate set to Hermes for final editorial selection.

Target raw volume is roughly 50-80 records before deduplication and no more than 40 candidates passed to the model.

The collector should make requests sequentially or with very low concurrency. The workload is tiny and does not justify an async HTTP framework.

## 11. Normalized post shape

Internal normalized records should contain only fields useful to ranking or presentation, for example:

```json
{
  "id": "...",
  "title": "...",
  "url": "...",
  "source": "...",
  "published_at": "...",
  "summary": "...",
  "tags": ["..."],
  "upvotes": 0,
  "comments": 0,
  "views": 0,
  "origins": ["for_you", "ai-coding-agents"],
  "source_ranks": [1, 4]
}
```

The client must tolerate missing engagement fields and schema additions.

## 12. Ranking and diversity

The deterministic layer should not try to replace Hermes with a complicated scoring model. It only needs to provide a good shortlist.

Use simple signals:

- personalized-feed presence;
- reciprocal rank within daily.dev results;
- number of distinct query clusters that surfaced the post;
- freshness;
- available engagement signals such as upvotes/comments/views.

Exact weights belong in one small function with tests. No ML model is introduced.

Hermes then chooses 5-8 final articles using the following editorial priorities in order:

1. direct relevance to Software Lab;
2. practical technical depth;
3. useful novelty compared with recently sent articles;
4. applicability to building and operating small software products;
5. diversity across topic clusters.

Diversity rule: normally include no more than two final articles from the same primary cluster unless the day's strongest signal clearly warrants it.

Clickbait, generic career content, shallow promotional content, and duplicate coverage should be rejected even if engagement is high.

## 13. Digest format

Output must be compact enough for Telegram and easy to continue discussing.

Template:

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

- Do not manufacture a fixed number of articles; 5-8 is the target, fewer is acceptable when quality is low.
- Keep each item concise.
- Preserve original article links.
- Do not quote large passages from source articles.
- Separate factual article metadata from Hermes interpretation when ambiguity matters.

## 14. State and duplicate suppression

No database is needed.

Persist two small JSON files under the state directory:

```text
latest_digest.json
history.json
```

### `latest_digest.json`

Stores:

- digest generation timestamp;
- final article ordering;
- article IDs, titles, URLs, and compact metadata necessary for follow-up resolution.

This is what allows `bài #3` to work even when the cron delivery itself is not conversation history.

### `history.json`

Stores recently delivered post IDs and timestamps.

Retention policy for v1:

- keep up to 14 days;
- cap stored IDs at 300;
- prune on each successful digest write.

State writes must be atomic: write a temporary file in the same directory and replace the target.

A failed scheduled run must not mark unsent candidates as delivered.

## 15. Interactive Q&A behavior

When `qeo-dailydev` is loaded in the Software Lab topic, it handles two broad intents.

### Follow-up on the latest digest

Examples:

```text
đào sâu bài #3
bài 2 áp dụng được gì cho finqeo?
so sánh #1 và #4
```

Behavior:

1. Read `latest_digest.json`.
2. Resolve article numbers deterministically.
3. If the answer requires broader evidence, run a daily.dev recommendation query as well.
4. Answer with direct links to the relevant article(s).
5. If there is no latest digest or the index is invalid, say so clearly rather than guessing.

### General technical research

Examples:

```text
RAG vs fine-tuning cho app nhỏ?
Làm auth trong Next.js hiện nay nên theo hướng nào?
Có pattern nào tốt cho self-hosted background jobs?
```

Routing guidance:

- use keyword recommendation when the prompt contains specific technologies, acronyms, libraries, protocols, or comparison terms;
- use semantic recommendation for natural-language conceptual questions;
- when one mode produces weak results, the skill may make one bounded fallback query using the other mode.

The final answer should synthesize, not merely list links. It should identify where sources agree or differ and include the source links used.

## 16. API client behavior

`dailydev_client.py` owns all HTTP behavior.

Requirements:

- standard Bearer authentication;
- configurable request timeout with a conservative default;
- JSON decoding and normalized error objects;
- cursor support where used;
- bounded retry for transient failures;
- respect `Retry-After` for HTTP 429;
- never retry 401 automatically;
- never log authorization headers;
- include endpoint and status in sanitized diagnostics.

Failure handling:

- `401`: configuration/authentication error; stop the affected operation.
- `429`: wait according to `Retry-After` within a bounded retry budget.
- `5xx` or network timeout: retry a small number of times with backoff, then degrade gracefully.
- one curated cluster failing must not discard successful results from the personalized feed or other clusters.
- personalized feed failure may still produce a curated-only digest; the digest should note internally that personalization was unavailable, but the Telegram output should only mention degraded mode if it materially affects quality.

## 17. Command-line utility contract

`scripts/dailydev.py` provides deterministic entry points that are useful both to Hermes and tests/operators.

Proposed commands:

```text
python3 scripts/dailydev.py candidates
python3 scripts/dailydev.py recommend --query "RAG vs fine-tuning" --mode keyword
python3 scripts/dailydev.py recommend --query "how should a small app remember chats?" --mode semantic
python3 scripts/dailydev.py latest
```

Output is JSON on stdout for successful machine-oriented commands. Errors go to stderr with non-zero exit status.

The exact internal Python module layout may change during implementation if repository patterns make a smaller structure clearer, but the responsibilities above must remain separated and testable.

## 18. Skill instructions

`SKILL.md` should tell Hermes:

- when to use the collector versus recommendation queries;
- how to build the morning digest from candidates;
- how to resolve `#N` references through latest digest state;
- when to choose keyword versus semantic recommendations;
- to ground research answers with article links;
- to avoid padding the morning brief with low-signal content;
- to keep Telegram output concise;
- what configuration is required;
- how to surface failures without exposing secrets.

It should not duplicate the full API schema or embed the daily.dev token.

## 19. Production configuration and deployment

Deployment follows repository conventions:

```bash
./scripts/verify.sh --repo-only
python3 -m unittest discover -s tests -v
sudo ./scripts/deploy.sh qeo-dailydev --hermes-home /opt/hermes/data --profiles <target-profile>
```

After the skill is deployed, production setup must:

1. provide `DAILY_DEV_API_TOKEN` to the Hermes runtime environment;
2. provide or otherwise resolve the Qeo AI chat ID and Software Lab thread ID;
3. add the `group_topics` binding for `qeo-dailydev` without overwriting unrelated Telegram configuration;
4. ensure cron raw delivery (`cron.wrap_response: false`) if not already configured intentionally otherwise;
5. create or update exactly one named daily digest job rather than creating duplicates;
6. restart/reload Hermes only through the established deployment/runtime mechanism;
7. verify gateway health;
8. run live Telegram smoke tests.

The implementation should prefer an idempotent setup helper if existing Hermes CLI/config APIs make that safe. It must not hand-edit production state in a way that bypasses GitHub as the source of truth for skill code.

## 20. Tests

Targeted unit tests should cover public behavior rather than implementation details.

Minimum cases:

- Authorization header is constructed from environment configuration but never appears in sanitized errors.
- Missing token fails explicitly.
- Personalized and curated records normalize into the same shape.
- Duplicate IDs collapse.
- Duplicate canonical URLs collapse.
- Recently delivered IDs are filtered.
- Ranking is deterministic for the same input.
- Cluster failure still returns candidates from successful sources.
- 401 is not retried.
- 429 honors bounded retry behavior.
- latest digest state resolves valid `#N` references and rejects invalid ones.
- history pruning enforces age/count bounds.
- state writes are atomic from the caller's perspective.
- `topics.json` is valid and contains the approved Software Lab clusters.

Repository verification should also validate the `qeo-dailydev` name and package structure through existing generic checks.

## 21. Production smoke checklist

A deployment is not accepted until all of these pass:

- daily.dev authenticated request succeeds from the Hermes runtime.
- `candidates` produces a non-empty normalized result without exposing the token.
- a keyword recommendation works.
- a semantic recommendation works.
- the Software Lab topic auto-loads `qeo-dailydev` for a fresh message.
- a test digest lands in the correct Qeo AI topic and not in the group root or another topic.
- `đào sâu bài #1` resolves against the test/latest digest.
- the scheduled job has exactly one active instance.
- the next scheduled occurrence corresponds to 07:00 VNT before and after a completed test run.
- unrelated existing Qeo Telegram commands such as `/qeostory` and `/qeovoice` still work.

## 22. Observability

Keep observability lightweight.

The deterministic utility should emit concise structured diagnostics to stderr for:

- request endpoint category, never the token;
- response status on failures;
- candidate counts before/after deduplication and repeat filtering;
- state-write success/failure.

Hermes cron execution history remains the primary scheduler audit trail. No external logging service is added.

## 23. Security

- Treat `DAILY_DEV_API_TOKEN` as a secret.
- Never include the token in repository files, Telegram messages, exception reprs, test fixtures, or command-line examples with real values.
- Tests use dummy tokens only.
- API requests are HTTPS only.
- The skill is read-only against daily.dev in v1.
- Do not expose internal stack traces to Telegram users.
- Do not widen Telegram authorization as part of this feature; existing Hermes group/user access policy remains authoritative.

## 24. Future extensions

Explicitly deferred until v1 usage justifies them:

- `/qeodailydev` shortcut for on-demand digest generation;
- per-user topic preferences;
- automatic feedback learning from Telegram reactions;
- daily.dev bookmark/upvote actions;
- additional content providers;
- persistent database or vector search;
- weekly Software Lab trend report.

## 25. Reference documentation

- daily.dev Public API: https://docs.daily.dev/public-api/
- daily.dev OpenAPI JSON: https://api.daily.dev/public/v1/docs/json
- daily.dev API announcement supplied for this work: https://daily.dev/posts/public-api-access-is-now-open-for-everyone-ljj8kh9sa
- Hermes scheduled tasks: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/cron.md
- Hermes Telegram topic binding: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/telegram.md
- Hermes cron timezone issue reviewed during design: https://github.com/NousResearch/hermes-agent/issues/103904

## 26. Design decision summary

Use one self-contained `qeo-dailydev` agent skill with a small deterministic Python client/collector and local JSON state. Pull both personalized and curated daily.dev candidates, let Hermes perform the final editorial synthesis, deliver one 07:00 VNT digest into the Software Lab Telegram topic, and bind that topic to the same skill for grounded follow-up research. Avoid extra infrastructure and explicitly verify scheduling semantics because current Hermes releases have recent cron timezone regressions.