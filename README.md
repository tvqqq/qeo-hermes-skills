# Qeo Hermes Skills

Canonical source repository for Qeo-owned Hermes Agent skills and Telegram gateway integrations.

Production copies under the Hermes data directory are deployment artifacts. Make source changes here first, commit them, then deploy them to Hermes.

## Purpose

This repository keeps custom Hermes capabilities simple and repeatable:

- reusable `qeo-*` skills;
- deterministic local utilities bundled with skills;
- Telegram-native shortcuts through shared plugins;
- profile-aware deployment, verification, backup, and rollback;
- documentation for adding future skills without server-side drift.

## Repository layout

```text
skills/        Qeo-owned Hermes skills
plugins/       Shared Hermes gateway integrations
scripts/       Install, deploy, verify, and rollback tooling
tests/         Targeted Python and deployment tests
docs/          Operational guides and design/implementation records
```

## Naming convention

Every custom skill uses `qeo-<name>` in lowercase kebab-case.
Examples:

```text
qeo-story
qeo-stock-chart
qeo-research
```

When a skill exposes a Telegram shortcut, remove hyphens from the skill name:

```text
qeo-story       -> /qeostory
qeo-stock-chart -> /qeostockchart
```

Telegram commands always start with `/qeo`, use lowercase characters, and contain no hyphens.

## Quick start

Validate the repository without touching a Hermes runtime:

```bash
./scripts/verify.sh --repo-only
```

Deploy `qeo-story` to the default profile and every discovered multiplex profile:

```bash
sudo ./scripts/deploy.sh qeo-story --profiles all
```

To target selected multiplex profiles instead:
```bash
sudo ./scripts/deploy.sh qeo-story \
  --profiles qeo-personal,qeo-stock
```

Override the Hermes data root when required:

```bash
sudo ./scripts/deploy.sh qeo-story \
  --hermes-home /opt/hermes/data \
  --profiles all
```

Use `--no-restart` only when you intentionally want to defer the gateway restart.

## Current skills

### `qeo-story`

Turns a local PNG/JPEG/WebP screenshot into a deterministic 1080×1920 story PNG with the approved Qeo layout and `@QeoQeo` footer.

Telegram supports both immediate and conversational forms:

```text
image + /qeostory [preset]   -> render immediately
/qeostory [preset]           -> ask for an image, valid for 60 seconds
```

`qeo-shortcuts` handles both flows directly in the gateway, so they do not depend on an LLM turn or terminal/code tools in the routed Hermes profile.

### `qeo-voice`

Uses the Mac mini Docker worker as the sole VieNeu compute host. `/qeovoice "text"` and `/qeovoice text` synthesize immediately; bare `/qeovoice` asks for text and accepts the same user's follow-up for 60 seconds. Multiline text is preserved. Successful synthesis is returned as OGG/Opus and sent as a native Telegram voice bubble. UpCloud only routes requests and never falls back to another TTS engine.

### `qeo-dailydev`

Builds a 07:00 VNT Software Lab briefing from the daily.dev `For You` feed plus curated engineering queries, then keeps the latest article ordering as lightweight state so follow-up questions such as `đào sâu bài #3` are deterministic. The Software Lab Telegram forum topic can auto-load the skill for keyword/semantic daily.dev research. v1 intentionally has no compact Telegram slash command.

## Deployment summary

A normal deploy validates source, creates a timestamped backup, stages replacements, updates the default and selected multiplex profiles, deploys shared plugin code, verifies runtime state, restarts the gateway once, and rolls back affected Qeo targets if validation fails.
Backups live under:

```text
$HERMES_HOME/backups/qeo-hermes-skills/<timestamp>/
```

The deployment scripts never intentionally modify unrelated Hermes skills, plugins, or configuration.

## Documentation

- [`docs/ADDING-A-QEO-SKILL.md`](docs/ADDING-A-QEO-SKILL.md) — create a new Qeo skill.
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — deployment, profiles, verification, and rollback.
- [`docs/TELEGRAM-COMMANDS.md`](docs/TELEGRAM-COMMANDS.md) — canonical Hermes commands and compact Telegram shortcuts.
- [`docs/QEO-DAILYDEV.md`](docs/QEO-DAILYDEV.md) — configure daily.dev, Software Lab topic binding, cron delivery, and Q&A smoke tests.
- [`docs/superpowers/specs/2026-09-13-qeo-hermes-skills-repository-design.md`](docs/superpowers/specs/2026-09-13-qeo-hermes-skills-repository-design.md) — approved repository design.
