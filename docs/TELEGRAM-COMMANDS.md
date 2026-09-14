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
qeo-voice       -> /qeovoice
qeo-stock-chart -> /qeostockchart
```

Rules:

- commands start with `/qeo`;
- lowercase only;
- no hyphens;
- keep names short and predictable;
- avoid aliases unless compatibility requires one.

Telegram's visible command menu is capped by Hermes. Production command-menu priority must keep both `qeostory` and `qeovoice` ahead of lower-priority dynamic commands so both shortcuts are suggested while typing `/`.

## Not every skill needs a Telegram shortcut

Normal agent skills can rely on Hermes skill discovery and natural-language invocation. Add a compact Telegram shortcut only when it materially improves a chat workflow.

## When to use `qeo-shortcuts`

`qeo-shortcuts` is shared gateway infrastructure for deterministic Telegram-native behavior. Use it when the gateway already has all required input and the command should not depend on an LLM turn or on tools enabled in the routed Hermes profile.

Examples include media transforms, format conversions, or other bounded local actions.

Keep each command handler in its own module:

```text
plugins/qeo-shortcuts/
├── __init__.py
├── interaction.py
└── handlers/
    ├── story.py
    ├── voice.py
    └── <future-command>.py
```

The root plugin file should only compose registrations. `interaction.py` provides the shared 60-second in-memory pending state used by conversational shortcuts. State is isolated by profile, user, chat, and topic; one new Qeo command replaces the previous pending Qeo request for that identity. Non-Qeo slash commands pass through normally and do not reset the deadline.

## `qeo-story` example

`/qeostory` supports both native fast paths:

```text
image + /qeostory [preset]
-> render immediately

/qeostory [preset]
-> ask for screenshot
-> same user sends image within 60 seconds
-> render with the stored preset
```

Both flows run through `pre_gateway_dispatch`, send the result through the Telegram adapter, and skip the normal agent turn. The skill identity remains `qeo-story`; the shortcut does not rename the skill.

## `qeo-voice` example

`qeo-voice` maps to `/qeovoice`. `/qeovoice "text"` and `/qeovoice text` synthesize immediately. Bare `/qeovoice` asks for text, then consumes the same user's text in the same chat/topic within 60 seconds. Multiline text is preserved. The gateway sends text to the authenticated Mac mini worker and returns OGG/Opus as a native Telegram voice bubble. The shortcut has no hyphen and has no server-side TTS fallback.
