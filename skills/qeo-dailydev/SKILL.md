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

# Qeo Daily.dev

Use daily.dev as the discovery layer for the Qeo AI **Software Lab** topic. This skill has two modes: the scheduled morning brief and interactive technical research.

The API credential is read only from `DAILY_DEV_API_TOKEN`. Never print, quote, log, or place that value in a URL or response.

## Runtime utility

Resolve the script from the Hermes data root instead of assuming the current working directory:

```bash
QEO_DAILYDEV_SCRIPT="${HERMES_HOME:-/opt/hermes/data}/skills/qeo-dailydev/scripts/dailydev.py"
```

Available commands:

```text
python3 "$QEO_DAILYDEV_SCRIPT" candidates [--limit 40]
python3 "$QEO_DAILYDEV_SCRIPT" recommend --mode keyword|semantic --query "..." [--limit 10] [--time month]
python3 "$QEO_DAILYDEV_SCRIPT" latest [--index N]
python3 "$QEO_DAILYDEV_SCRIPT" finalize --input FILE --ids ID1,ID2,...
```

`candidates` and `recommend` require `DAILY_DEV_API_TOKEN`. `latest` and `finalize` use local state and do not require the API token.

## Scheduled morning brief

When asked to generate the daily Software Lab brief:

1. Create a temporary JSON file outside the skill source directory.
2. Run `candidates` and save its exact JSON output into that file.
3. Review the candidates and choose **5-8** strong articles when enough quality exists. Returning fewer is better than padding with weak content.
4. Prioritize direct Software Lab relevance, practical technical depth, useful novelty, applicability to building/operating small products, and topic diversity. Normally include no more than two articles from one primary cluster.
5. Reject clickbait, generic career content, shallow promotion, and duplicate coverage even when engagement is high.
6. Draft the complete Telegram brief before mutating durable state.
7. Run `finalize --input <candidate-file> --ids <ordered-selected-ids>` only after the complete brief is ready. Pass IDs in the exact order shown in the brief.
8. If candidate generation or finalization fails, return a short sanitized operational error. Do not claim the brief succeeded.
9. Return only the finished brief as the final agent response so Hermes cron can deliver it directly to the configured Telegram topic.

Use this shape:

```text
☀️ Software Lab — Daily.dev Brief · <date>

🔎 Today's signal
<2-3 concise sentences synthesizing the strongest pattern>

1. <title>
Why it matters: <one concise sentence>
Key idea: <one concise sentence>
<link>

...

💬 Có thể hỏi tiếp: "đào sâu bài #3", "so sánh #2 với Supabase", hoặc hỏi một topic kỹ thuật bất kỳ.
```

Preserve original article links and avoid long quotations.

## Follow-up on the latest brief

For requests such as `đào sâu bài #3`, `bài 2 áp dụng được gì?`, or `so sánh #1 và #4`:

1. Resolve each requested index with `latest --index N`.
2. Never infer or guess an index when state is missing or the index is invalid.
3. Use stored daily.dev metadata as discovery context.
4. If broader evidence is useful, call `recommend` as well.
5. For a genuine deep dive, when normal Hermes web/fetch tooling is available, read a small bounded number of the original article URLs before making detailed claims.
6. If original pages cannot be read, state clearly that the answer is based on daily.dev summaries/metadata rather than full article text.

## General Software Lab research

Use daily.dev recommendations for technical questions beyond the current brief:

- Use **keyword** mode for named technologies, acronyms, libraries, protocols, or explicit comparisons.
- Use **semantic** mode for conceptual natural-language questions.
- If the first mode returns weak results, make at most one bounded fallback query using the other mode.
- Synthesize the findings instead of dumping links. Mention meaningful disagreement and include direct source links used.
- For deep evidence, fetch only the most relevant original pages when Hermes web/fetch tooling is available.

## Failure behavior

- Authentication errors: say daily.dev authentication/configuration failed; never expose credentials.
- Rate limits or transient API failures: rely on the utility's bounded retry behavior and report a sanitized failure if it still fails.
- A failed curated source may degrade the candidate pool; do not discard successful sources.
- Missing latest digest or an invalid brief index must produce an explicit message instead of a guess.
