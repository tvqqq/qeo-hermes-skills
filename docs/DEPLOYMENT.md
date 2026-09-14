# Deployment Guide

This repository is the canonical source of truth. Files under the Hermes data directory are deployment artifacts.

## Hermes data root

Runtime code and scripts use this precedence:

1. explicit `--hermes-home PATH` argument;
2. `HERMES_HOME` environment variable;
3. default `/opt/hermes/data`.

The default production layout is:

```text
/opt/hermes/data/
├── skills/qeo-<name>
├── profiles/<profile>/skills/qeo-<name>
├── plugins/qeo-shortcuts
└── backups/qeo-hermes-skills/<timestamp>/
```

No profile names are hardcoded in repository source.

## Script responsibilities

### `scripts/verify.sh`

Read-only verification. `--repo-only` checks repository source. With a Hermes home it also checks deployed skill copies and runs Hermes plugin doctor when the CLI is available.

### `scripts/deploy-skill.sh`

Deploys one `qeo-*` skill into the default profile and selected multiplex profiles. It stages and replaces skill directories but never restarts the gateway.

### `scripts/deploy.sh`

Production orchestrator. It validates source, creates one backup root, deploys the shared plugin and requested skill, installs skill requirements in the Hermes Python environment when available, runs post-deploy verification, restarts the gateway once, and checks gateway health.

If post-deploy verification or gateway health fails, it restores the affected Qeo targets. Unrelated Hermes state is not intentionally modified.

### `scripts/install.sh`

Thin first-time wrapper over `deploy.sh`. It exists for discoverability and must not duplicate backup, copy, verification, restart, or rollback logic.

## Profile selection

The default profile is always included.

Deploy to every discovered multiplex profile:

```bash
sudo ./scripts/deploy.sh qeo-story \
  --hermes-home /opt/hermes/data \
  --profiles all
```

Deploy to selected multiplex profiles only:

```bash
sudo ./scripts/deploy.sh qeo-story \
  --hermes-home /opt/hermes/data \
  --profiles qeo-personal,qeo-stock
```

`--profiles all` scans direct profile directories under the configured Hermes data root.

## Validation before production

Run repository-only checks first:

```bash
./scripts/verify.sh --repo-only
python3 -m unittest discover -s tests -v
```

Only deploy after both succeed.

For `qeo-voice`, production deployment installs only the Hermes skill and shared `qeo-shortcuts` connector on UpCloud. VieNeu remains on the Mac mini Docker worker. Configure `QEO_VOICE_WORKER_URL`, `QEO_VOICE_TOKEN`, and `QEO_VOICE_TIMEOUT_SECONDS` in the Hermes runtime environment before restarting the gateway. Smoke `/qeovoice` after deploy; no failure path may invoke server-side TTS.

## Backup and rollback

Each deployment creates one timestamped backup directory below:

```text
<hermes-home>/backups/qeo-hermes-skills/
```

The backup contains only affected skill/plugin targets plus internal manifests describing which paths existed before the deploy.

Rollback behavior:

- previously existing targets are restored from backup;
- targets newly introduced by the failed deploy are removed;
- unrelated skills, plugins, profiles, and config are left alone;
- gateway is restarted again only when rollback follows a restart/health failure.

## Gateway restart

Normal production deployment restarts the gateway once after post-deploy verification passes. Use `--no-restart` only when intentionally deferring the restart, such as isolated filesystem tests.

## Runtime ownership and overrides

Production defaults assume deployed files are owned by `hermes:hermes` and Hermes runtime commands run as the `hermes` user. Test environments can set `QEO_DEPLOY_OWNER` to an empty value to skip ownership changes.

Supported operator overrides include `HERMES_BIN`, `HERMES_PYTHON`, `HERMES_RUNTIME_HOME`, and `QEO_RUNTIME_USER` when the server layout differs from defaults.

## Post-deploy verification

After deployment, run:

```bash
./scripts/verify.sh \
  --hermes-home /opt/hermes/data \
  --profiles all
```

For a Telegram-facing handler or gateway/plugin change, filesystem/runtime checks are not the final acceptance test. Send a fresh Telegram message that exercises the command after restart.

For `qeo-story`, smoke with a new image plus `/qeostory`, then another new image plus `/qeostory mango`. Both should return story PNGs without asking to enable terminal/code tools.

## Production discipline

Do not edit deployed copies to create a permanent fix. Make the change in GitHub, validate it in the repository, commit it, and redeploy. If production differs from the repository, treat that as drift.
