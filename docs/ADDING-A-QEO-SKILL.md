# Adding a Qeo Hermes Skill

Use this playbook for every new Qeo-owned Hermes capability.

## 1. Choose the skill name

Every skill name must follow:

```text
qeo-<skill-name>
```

Rules:

- lowercase only;
- kebab-case for multiple words;
- concise and descriptive;
- no Qeo-owned skill without the `qeo-` prefix.

Examples:

```text
qeo-story
qeo-research
qeo-stock-chart
```

## 2. Choose the execution model

| Model | Use when |
|---|---|
| Agent skill | The task needs LLM reasoning, natural language interpretation, or Hermes tools. |
| Deterministic utility | The task is a repeatable local transform, parser, converter, or renderer. |
| Telegram native fast-path | A deterministic Telegram command should work without an LLM turn or profile tool availability. |

Prefer the smallest model that satisfies the requirement. Do not add a gateway plugin when a normal skill is enough.

## 3. Create the minimum package

Typical agent/deterministic skill:

```text
skills/qeo-<name>/
├── SKILL.md
├── scripts/          # only when executable logic is needed
├── references/       # only when supporting docs/constants are needed
└── requirements.txt  # only when Python dependencies are needed
```

`SKILL.md` must clearly describe:

- trigger/use cases;
- expected inputs;
- behavior and output;
- required tools or dependencies;
- failure behavior;
- manual fallback when useful.

Keep implementation local to the skill unless functionality is truly shared.

## 4. Add a Telegram shortcut only when needed

Canonical skill identity keeps hyphens; Telegram shortcuts remove them:

```text
qeo-story       -> /qeostory
qeo-stock-chart -> /qeostockchart
```

Telegram commands must start with `/qeo`, be lowercase, and contain no hyphens.

If a shortcut needs deterministic gateway behavior, add a focused handler under:

```text
plugins/qeo-shortcuts/handlers/<name>.py
```

Keep `plugins/qeo-shortcuts/__init__.py` limited to registration/composition.

## 5. Add targeted tests

Use tests that prove the public contract, not implementation details. For deterministic code, cover valid output, invalid input, and important invariants. For gateway handlers, cover command matching, profile path resolution, success, failure, and no-attachment behavior.

Run the relevant tests first, then the repository verification:

```bash
python3 -m unittest discover -s tests -v
./scripts/verify.sh --repo-only
```

## 6. Deploy

Deploy to default plus all discovered multiplex profiles:

```bash
sudo ./scripts/deploy.sh qeo-<name> \
  --hermes-home /opt/hermes/data \
  --profiles all
```

Or target selected profiles:

```bash
sudo ./scripts/deploy.sh qeo-<name> \
  --profiles qeo-personal,qeo-stock
```

`deploy.sh` owns backup, plugin deployment, post-deploy verification, gateway restart, health check, and rollback. Do not duplicate that logic in a skill-specific installer.

## 7. Verify runtime behavior

After deploy, run the runtime verification against the Hermes data directory and all selected profiles. For any meaningful Telegram gateway or plugin change, perform a live Telegram smoke with a fresh message after restart.

## 8. Rollback and source-of-truth rule

Deployment backups are stored below the Hermes data directory in `backups/qeo-hermes-skills/<timestamp>/`.

If post-deploy verification or gateway health fails, `deploy.sh` restores only the affected Qeo targets.

GitHub is always the source of truth. Do not fix production by editing deployed skill or plugin copies directly. Make the change in this repository, commit it, verify it, and redeploy.
