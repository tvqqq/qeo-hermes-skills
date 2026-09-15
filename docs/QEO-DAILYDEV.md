# Qeo Daily.dev

`qeo-dailydev` curates a hybrid daily.dev feed for the Qeo AI **Software Lab** Telegram topic and gives Hermes a repeatable research workflow for follow-up questions in that topic.

## Runtime flow

```text
daily.dev Public API
  -> qeo-dailydev deterministic collector/ranker
  -> Hermes editorial selection and synthesis
  -> Telegram Qeo AI / Software Lab
```

The morning brief combines the authenticated daily.dev `For You` feed with six curated Software Lab query clusters. The same skill can later use daily.dev keyword or semantic recommendations to answer research questions.

No gateway plugin, extra bot, database, n8n workflow, or long-running worker is required.

## Required runtime configuration

The skill itself requires:

```text
DAILY_DEV_API_TOKEN
```

Keep the token in the Hermes runtime secret environment. Never put the real value in Git, `SKILL.md`, cron prompts, shell history examples, or logs.

For production setup, keep the Telegram destination values outside Git as operator variables/placeholders:

```text
QEO_AI_CHAT_ID
SOFTWARE_LAB_THREAD_ID
```

The utility stores lightweight state at `$QEO_DAILYDEV_STATE_DIR` when set, otherwise `$HERMES_HOME/state/qeo-dailydev`, and finally `~/.hermes/state/qeo-dailydev` when `HERMES_HOME` is absent.

## Deploy the skill

Use the existing repository deployment path:

```bash
sudo ./scripts/deploy.sh qeo-dailydev \
  --hermes-home /opt/hermes/data \
  --profiles all

./scripts/verify.sh \
  --hermes-home /opt/hermes/data \
  --profiles all \
  --skill qeo-dailydev
```

The deploy remains profile-aware and uses the existing backup/restart/rollback workflow.

## Bind Software Lab to the skill

Merge the Software Lab topic into the existing Telegram configuration. Do not replace unrelated topics.

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

`chat_id` is the Telegram supergroup ID and `thread_id` is the Software Lab forum topic ID. Topic binding makes `qeo-dailydev` auto-load for normal messages in that topic.

After changing Telegram config, restart the Hermes gateway using the normal production procedure and send a fresh message in Software Lab to confirm the skill is loaded.

## Deliver raw cron output

The brief is already formatted for Telegram, so disable the default cron header/footer in the existing Hermes config:

```yaml
cron:
  wrap_response: false
```

This is the `cron.wrap_response` setting. Review any other cron users before changing a shared config because this affects cron response wrapping globally.

## 07:00 VNT schedule

Vietnam is UTC+7 year-round. When the Hermes scheduler runtime is UTC, use:

```text
0 0 * * *
```

which is **07:00 VNT**.

Create the job with an explicit Software Lab destination:

```bash
hermes cron create "0 0 * * *" \
  "Generate today's Software Lab Daily.dev Brief. Follow qeo-dailydev exactly and return only the final brief." \
  --skill qeo-dailydev \
  --deliver "telegram:<QEO_AI_CHAT_ID>:<SOFTWARE_LAB_THREAD_ID>" \
  --name "Software Lab daily.dev brief"
```

Do not blindly change a shared Hermes timezone just for this job. If the target scheduler is not UTC, verify the deployed Hermes recurrence behavior before choosing the equivalent local-time schedule.

## API and CLI smoke

Do not echo the token. With it already present in the runtime environment:

```bash
QEO_DAILYDEV_SCRIPT="${HERMES_HOME:-/opt/hermes/data}/skills/qeo-dailydev/scripts/dailydev.py"
python3 "$QEO_DAILYDEV_SCRIPT" candidates --limit 10 >/tmp/qeo-dailydev-candidates.json
python3 "$QEO_DAILYDEV_SCRIPT" recommend \
  --mode keyword \
  --query "AI coding agents" \
  --limit 5
```

Inspect the candidate JSON for real article IDs/titles/links. Remove temporary smoke files after validation.

## Cron acceptance

Before declaring production ready:

```bash
hermes cron list
hermes cron status
hermes cron doctor
```

Record the job's `next_run_at`, then trigger one run:

```bash
hermes cron run "Software Lab daily.dev brief"
```

Confirm:

- a real brief arrives in `telegram:<QEO_AI_CHAT_ID>:<SOFTWARE_LAB_THREAD_ID>`;
- the message is not wrapped in the default cron header/footer;
- the brief contains up to 5-8 high-signal articles and direct links;
- `latest_digest.json` contains the same final article ordering;
- Hermes does not report `delivery_failed` for the run.

After that execution, inspect the job again and confirm the new `next_run_at` still maps to **07:00 VNT**. This before/after check is required because scheduler timezone/recurrence behavior can differ across Hermes versions.

## Q&A acceptance

In the Software Lab topic, send:

```text
đào sâu bài #1
```

Hermes must resolve article #1 from `latest_digest.json` rather than guessing from chat history.

Then ask one general question, for example:

```text
RAG hay fine-tuning phù hợp hơn cho một app nhỏ cần knowledge riêng?
```

The skill should use keyword or semantic daily.dev recommendations, synthesize the useful findings, and include direct source links. For deeper claims, Hermes should read a small number of original article pages when web/fetch tooling is available.

## Failure and recovery

- `401`: fix `DAILY_DEV_API_TOKEN`; never paste the token into logs or Git.
- `429`/transient failures: the client retries within a bounded budget; repeated failure should surface as a sanitized error.
- One curated query can fail without discarding other successful sources.
- If cron reports `delivery_failed`, treat delivery as failed even when agent generation succeeded.
- `finalize` writes duplicate-suppression state before Hermes performs platform delivery. If generation succeeded but Telegram delivery failed and you need to resend the same articles, inspect/repair `latest_digest.json` and `history.json` deliberately before rerunning; do not blindly delete unrelated Hermes state.
- For a bad skill deployment, use the repository deployment backup/rollback path. Do not edit the deployed skill as the long-term fix; change GitHub source and redeploy.
