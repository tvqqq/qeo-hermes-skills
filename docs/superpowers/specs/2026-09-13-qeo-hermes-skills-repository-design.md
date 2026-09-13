# Qeo Hermes Skills Repository Design

Date: 2026-09-13
Repository: `tvqqq/qeo-hermes-skills`
Status: Approved design, pending implementation plan

## Purpose

`qeo-hermes-skills` is the canonical source of truth for Qeo-owned Hermes Agent skills, gateway integrations, deployment scripts, and operational documentation.

The repository replaces ad-hoc editing on the `qeo-upcloud` Hermes server. Production copies under `/opt/hermes/data` are deployment artifacts and must not be treated as source code.

Primary flow:

`GitHub -> deploy/validate -> Hermes VPS -> Telegram/Hermes runtime`

## Goals

- Store all Qeo-owned Hermes skills using the `qeo-` prefix.
- Keep Telegram-facing commands short, predictable, and free of hyphens.
- Support Hermes multiplex profiles without copying code manually.
- Keep deterministic utilities out of the LLM/tool loop when direct gateway execution is more reliable.
- Provide one repeatable deployment, verification, and rollback workflow.
- Keep dependencies and abstractions minimal.

## Non-goals

The first implementation will not add CI/CD, release automation, a package manager, containerization, a plugin framework beyond Hermes's native plugin model, or unrelated infrastructure changes.

## Repository Structure

```text
qeo-hermes-skills/
├── README.md
├── skills/
│   └── qeo-story/
│       ├── SKILL.md
│       ├── requirements.txt
│       ├── scripts/
│       │   ├── __init__.py
│       │   ├── image_utils.py
│       │   ├── presets.py
│       │   └── render_story.py
│       └── references/
│           └── style-guide.md
├── plugins/
│   └── qeo-shortcuts/
│       ├── plugin.yaml
│       ├── __init__.py
│       └── handlers/
│           └── story.py
├── scripts/
│   ├── install.sh
│   ├── deploy-skill.sh
│   ├── deploy.sh
│   └── verify.sh
└── docs/
    ├── ADDING-A-QEO-SKILL.md
    ├── DEPLOYMENT.md
    ├── TELEGRAM-COMMANDS.md
    └── superpowers/specs/
        └── 2026-09-13-qeo-hermes-skills-repository-design.md
```

The layout is intentionally shallow. Skills own skill-specific code and references. Gateway integrations live in `plugins/`. Repository-level operational scripts live in `scripts/`.

## Naming Contract

Every Qeo-owned Hermes skill must use:

```text
qeo-<skill-name>
```

Rules:

- lowercase only
- kebab-case for multiple words
- concise descriptive names
- no Qeo-owned skill without the `qeo-` prefix

Examples:

- `qeo-story`
- `qeo-research`
- `qeo-stock-chart`

The canonical Hermes skill command remains the skill slug, for example `/qeo-story`.

When a skill exposes a Telegram shortcut, the shortcut uses the compact form:

```text
/qeo<skill-name-with-hyphens-removed>
```

Examples:

- `qeo-story` -> `/qeostory`
- `qeo-stock-chart` -> `/qeostockchart`

Telegram shortcuts must start with `/qeo`, use lowercase characters, and contain no hyphens. Aliases are avoided unless required for compatibility.

## Execution Models

A new skill must choose the smallest execution model that fits its behavior.

### Agent skill

Use a normal `skills/qeo-*` package when the task benefits from LLM reasoning, natural-language interpretation, or existing Hermes tools.

### Deterministic local utility

A skill may ship scripts for deterministic work such as rendering, conversion, or parsing. The script must have explicit inputs, outputs, validation, and failure behavior.

### Telegram native fast-path

Use `qeo-shortcuts` when a Telegram command should execute deterministic local behavior without requiring an LLM turn or session toolset. Typical examples are media transforms where the gateway already has the attachment path.

The native path should process the inbound event, call the local implementation, send the result through the platform adapter, and skip the normal agent turn after handling the request.

## qeo-shortcuts Plugin Design

`qeo-shortcuts` is the shared gateway integration plugin for Qeo Telegram shortcuts. It must not become a monolithic file.

`__init__.py` is limited to registration and composition. Command-specific behavior lives under `handlers/`.

Initial handler:

```text
handlers/story.py
```

The `/qeostory` flow is:

```text
Telegram image + /qeostory [preset]
-> pre_gateway_dispatch
-> resolve current attachment path
-> invoke qeo-story renderer locally
-> validate PNG 1080x1920
-> send_image_file to the same Telegram conversation/topic
-> skip LLM dispatch
```

This path must not require terminal/code tools in the active Hermes profile and must not rely on `MEDIA:` output from an agent response.

## qeo-story Migration

The initial migration copies the proven production implementation into the repository:

- `SKILL.md`
- `requirements.txt` with `Pillow>=10,<14`
- `scripts/render_story.py`
- `scripts/image_utils.py`
- `scripts/presets.py`
- `scripts/__init__.py`
- `references/style-guide.md`

The renderer contract remains:

- input: PNG, JPEG, or WebP
- output: PNG
- canvas: 1080x1920
- default preset: `qeo-green`
- source aspect ratio preserved
- no default crop/stretch
- footer: `@QeoQeo`

Supported presets initially remain:

- `qeo-green`
- `qeo`
- `mango`
- `mojito`
- `stellar`
- `midnight-city`

The migrated `SKILL.md` must be updated to describe the actual runtime behavior. It must not claim that `/qeostory` requires an agent terminal tool or that Telegram output depends on `MEDIA:`. Manual script execution can remain documented as a fallback for non-gateway use.

## Deployment Contract

GitHub is authoritative. Production files are deployed from a checked-out or downloaded repository state.

Default Hermes root:

```text
/opt/hermes/data
```

Deployment targets:

```text
/opt/hermes/data/skills/qeo-<name>
/opt/hermes/data/profiles/<profile>/skills/qeo-<name>
/opt/hermes/data/plugins/qeo-*
```

The default profile receives the skill. Multiplex profiles are selected with a deployment option.

Supported profile selectors:

```text
--profiles all
--profiles qeo-personal,qeo-stock
```

`--profiles all` discovers profile directories under `/opt/hermes/data/profiles/`; profile names are not hardcoded in the public repository.

A normal deployment lifecycle is:

```text
validate source
-> create timestamped backup of affected production targets
-> stage new files in a temporary location
-> validate staged files
-> atomically replace production targets
-> set hermes:hermes ownership
-> install required runtime dependencies when needed
-> validate Hermes discovery/plugin registration
-> restart gateway once
-> verify gateway health
```

Production source must not be edited manually after deployment. If production differs from GitHub, redeploy the repository version or make the intended change in GitHub first.

## Verification Gates

Every deployment must pass four gates.

### 1. Static validation

- `SKILL.md` exists for every deployed skill.
- Frontmatter `name` matches the directory and starts with `qeo-`.
- Telegram shortcut names, when present, start with `qeo`, are lowercase, and contain no hyphens.
- Required files declared by the implementation exist.

### 2. Runtime validation

- Python source compiles.
- Required Python imports work in the Hermes virtual environment.
- `hermes plugins doctor <plugin> --ci` passes for changed plugins.
- Skill-specific smoke validation runs when a deterministic script exposes one.

### 3. Hermes discovery validation

- The default profile discovers the canonical skill command.
- Every selected multiplex profile discovers the skill after deployment.
- Telegram shortcut registration resolves to the intended behavior.
- Menu priority is configured only where needed; the full `/commands` listing remains the fallback when the Telegram command menu cap is reached.

### 4. Gateway health

- Gateway restart occurs once after successful deployment validation.
- The gateway reports active/running.
- The new process remains alive after a short post-restart health interval.

A Telegram-facing media skill is not considered fully verified until its command is exercised through Telegram at least once after a meaningful gateway/plugin change.

## Backup and Rollback

Before replacing any existing production target, deployment creates a timestamped backup under:

```text
/opt/hermes/data/backups/qeo-hermes-skills/<timestamp>/
```

The backup preserves affected skills and plugins only.

If post-deployment validation fails:

- restore changed targets from the backup;
- remove newly introduced targets that did not exist before deployment;
- restore ownership;
- restart the gateway once more;
- report rollback status clearly.

Rollback must not overwrite unrelated Hermes configuration or unrelated skills/plugins.

## Secrets and Configuration

The repository is public and must never contain:

- Telegram bot tokens
- API keys
- passwords
- SSH credentials
- private access tokens
- user/chat-specific secrets

Environment-specific values use environment variables or existing Hermes configuration. Public deployment scripts may contain stable filesystem conventions such as `/opt/hermes/data` when they are intentional defaults, but must allow an explicit override where practical.

## Documentation Contract

### README.md

Provides repository purpose, structure, quick start, naming examples, and links to the detailed guides.

### docs/ADDING-A-QEO-SKILL.md

Acts as the primary playbook for future skills:

1. choose `qeo-<name>`;
2. choose agent, deterministic, or Telegram native execution model;
3. create the minimum package structure;
4. add Telegram shortcut only when needed;
5. validate locally;
6. deploy with `scripts/deploy.sh`;
7. verify Hermes/Telegram behavior;
8. rollback if necessary.

### docs/DEPLOYMENT.md

Documents server paths, default and multiplex profile behavior, backup lifecycle, deployment commands, verification, and rollback.

### docs/TELEGRAM-COMMANDS.md

Documents the distinction between canonical Hermes names and Telegram shortcuts, including:

```text
qeo-story -> /qeostory
qeo-stock-chart -> /qeostockchart
```

It also explains when a native fast-path belongs in `qeo-shortcuts` instead of an LLM-mediated skill invocation.

## Initial Implementation Scope

The first implementation contains only:

- `qeo-story` source migrated from the working VPS implementation;
- `qeo-shortcuts` with the working `/qeostory` native flow, refactored into a handler module;
- repository deployment and verification scripts;
- repository and operational documentation.

No additional skills are introduced in this migration.

## Acceptance Criteria

Implementation is complete when all of the following are true:

- The repository contains the approved structure and documentation.
- `qeo-story` source in GitHub reproduces the working renderer behavior.
- `/qeostory` works without enabling terminal/code tools for the routed Hermes profile.
- The deploy script installs `qeo-story` into the default profile and selected multiplex profiles.
- `qeo-shortcuts` can be installed/enabled from repository source.
- Static, runtime, discovery, and gateway-health checks are automated by repository scripts where practical.
- Failed deployment validation can restore the previous affected skill/plugin copies without touching unrelated Hermes state.
- No secrets or chat-specific identifiers are committed.
- GitHub is documented as the only canonical source for Qeo-owned Hermes skill code.
