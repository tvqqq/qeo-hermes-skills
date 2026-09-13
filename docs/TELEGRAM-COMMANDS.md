# Telegram Command Conventions

Qeo skills and Telegram shortcuts use related but intentionally different names.

## Canonical skill identity

Hermes skill names always keep the `qeo-` prefix and kebab-case:

```text
qeo-story
qeo-stock-chart
```

Their canonical Hermes slash forms are:

```text
/qeo-story
/qeo-stock-chart
```

## Telegram compact shortcuts

Telegram-facing shortcuts remove hyphens after the `qeo` prefix:

```text
qeo-story       -> /qeostory
qeo-stock-chart -> /qeostockchart
```

Rules:

- commands start with `/qeo`;
- lowercase only;
- no hyphens;
- keep names short and predictable;
- avoid aliases unless compatibility requires one.

## Not every skill needs a Telegram shortcut

Normal agent skills can rely on Hermes skill discovery and natural-language invocation. Add a compact Telegram shortcut only when it materially improves a chat workflow.

## When to use `qeo-shortcuts`

`qeo-shortcuts` is shared gateway infrastructure for deterministic Telegram-native behavior. Use it when the gateway already has all required input and the command should not depend on an LLM turn or on tools enabled in the routed Hermes profile.

Examples include media transforms, format conversions, or other bounded local actions.

Keep each command handler in its own module:

```text
plugins/qeo-shortcuts/
├── __init__.py
└── handlers/
    ├── story.py
    └── <future-command>.py
```

The root plugin file should only compose registrations.

## `qeo-story` example

`/qeostory` is implemented as a native fast-path:

```text
Telegram image + /qeostory [preset]
-> pre_gateway_dispatch
-> local qeo-story renderer
-> validate output
-> send image through the Telegram adapter
-> skip the normal agent turn
```

The skill identity remains `qeo-story`; the shortcut does not rename the skill.
