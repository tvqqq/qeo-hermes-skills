# Qeo Shortcuts Conversational Input Design

Date: 2026-09-14
Status: Approved design pending implementation plan

## Goal

Add a conversational two-message mode to the existing Telegram shortcuts without breaking their current one-message fast paths.

Required behavior:

- `/qeovoice "text"` and `/qeovoice text` still synthesize immediately.
- Bare `/qeovoice` asks for text, then consumes the same user's next valid text message.
- Image + `/qeostory [preset]` still renders immediately.
- `/qeostory [preset]` without an image asks for an image, then consumes the same user's next valid image.
- Pending requests expire after 60 seconds and proactively notify the user.
- Pending follow-up messages are handled deterministically in `qeo-shortcuts` and do not require an LLM turn.

## Architecture

Add one shared in-memory interaction-state module:

```text
plugins/qeo-shortcuts/
├── interaction.py
└── handlers/
    ├── story.py
    └── voice.py
```

`interaction.py` owns pending state, timeout scheduling, replacement, expiry, and race protection. It does not know how to synthesize voice or render stories.

Each handler continues to own command parsing, input validation, execution, and user-facing success/failure behavior. Both handlers use the shared interaction manager so timeout and isolation logic is implemented once.

No database or external service is added. Pending state is intentionally memory-only because the lifetime is one minute. A gateway restart may discard pending requests.

## Pending State Identity

A pending interaction is isolated by:

```text
(profile, user_id, chat_id, thread_id)
```

Conversation mode requires `source.user_id`. If no user identity is available, the handler must not create pending state.

Only one pending interaction may exist for a key. Starting another Qeo conversational command replaces the previous pending request for that key.

Each pending interaction records at minimum:

- a unique `request_id`;
- interaction kind: `voice_text` or `story_image`;
- creation and expiry timestamps;
- command-specific payload such as the selected story preset;
- original source/message information needed to send timeout feedback in the same chat/topic.

The timeout is always 60 seconds from the original command. Invalid follow-up input does not reset or extend the deadline.

## Gateway Hook Semantics

Hermes runs `pre_gateway_dispatch` once per inbound non-internal message before normal agent dispatch. The first returned `skip`, `rewrite`, or `allow` action wins.

The shortcut handlers continue to use this hook as the deterministic interception point. A valid pending follow-up is consumed and returns `skip`, preventing it from reaching the LLM.

Recognized Qeo shortcut commands take precedence over pending-input consumption. For example, if a user waiting on voice text sends `/qeostory`, the voice flow must not consume that command as speech; the story flow replaces the pending request instead. The inverse applies to `/qeovoice` while story input is pending.

Other slash commands are not consumed as pending content. They continue through Hermes normally while the pending request keeps its original expiry time.

## Qeo Voice Flow

Immediate modes remain unchanged:

```text
/qeovoice "text"
/qeovoice text
```

Both synthesize immediately through the existing Mac mini worker path.

Bare `/qeovoice` starts `voice_text` pending state and replies:

```text
🎙️ Bạn muốn Chi Chi đọc nội dung gì? Hãy gửi text trong vòng 1 phút.
```

The next valid plain-text message from the same `(profile, user_id, chat_id, thread_id)` is the speech payload. It may contain multiple lines and does not need outer quotes.

When valid text arrives:

1. remove the pending state before starting synthesis;
2. cancel or invalidate its timeout task;
3. call the existing `_process_qeovoice` path;
4. return `skip` so the message does not reach the LLM.

If the user sends an image, sticker, empty message, or other non-text payload while voice input is pending, keep the pending request and reply:

```text
⚠️ Hãy gửi nội dung text. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu.
```

The original 60-second deadline is unchanged.

If the deadline expires first, clear the pending state and send:

```text
⏱️ Yêu cầu Qeo Voice đã hết hạn. Hãy gửi lại /qeovoice để tạo voice mới.
```

Existing worker offline, busy, synthesis-failure, OGG/Opus, and no-fallback behavior remain unchanged.

## Qeo Story Flow

Immediate mode remains unchanged:

```text
image + /qeostory [preset]
```

If `/qeostory` or `/qeostory [preset]` arrives without an image, start `story_image` pending state. Store the selected preset, if any, in the pending payload and reply:

```text
🖼️ Hãy gửi ảnh screenshot trong vòng 1 phút.
```

Examples:

```text
/qeostory
→ pending story_image {preset: null}

/qeostory mango
→ pending story_image {preset: "mango"}
```

The next valid image from the same `(profile, user_id, chat_id, thread_id)` completes the request.

When a valid image arrives:

1. remove the pending state before rendering;
2. cancel or invalidate its timeout task;
3. call the existing qeo-story render path with the stored preset;
4. send the resulting image through the Telegram adapter;
5. return `skip` so the message does not reach the LLM.

If the user sends ordinary text instead of an image while story input is pending, keep the pending request and reply:

```text
⚠️ Hãy gửi ảnh screenshot. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu.
```

The original 60-second deadline is unchanged.

If the deadline expires first, clear the pending state and send:

```text
⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới.
```

Existing preset validation and render-failure behavior remain unchanged.

## Replacement and Isolation Rules

A new recognized Qeo shortcut from the same interaction key replaces the previous pending request.

Example:

```text
/qeovoice
→ waiting for voice text
/qeostory mango
→ voice pending is cancelled
→ waiting for story image with preset mango
```

The replaced request must never emit a stale timeout alert.

Messages from another user, chat, topic, or profile do not consume or mutate the pending request. They continue through the normal Hermes flow.

## Timeout and Race Safety

Each pending request has a unique `request_id`. The timeout callback must confirm that the current state for the key still has the same `request_id` before clearing state or sending an expiry message.

This protects the race where a timeout wakes up at the same moment the user responds or starts a replacement command.

Completing, replacing, or otherwise clearing a pending interaction should cancel its timeout task when possible. `request_id` validation remains the final protection against stale timeout delivery.

Timeout alerts must be sent to the same chat/topic as the original command and should reply to the original command message when the adapter supports it.

## Error Handling

- Invalid follow-up type: send a reminder, keep pending state, do not reset TTL.
- Voice worker failure after valid input: use existing exact qeo-voice error behavior; do not recreate pending state.
- Story render failure after valid image: use existing render-failure behavior; do not recreate pending state.
- Missing `user_id`: do not create conversational pending state.
- Gateway restart: pending state may be lost; no persistence or recovery is required.
- No failure path may introduce server-side TTS fallback.

## Testing

Implementation follows TDD. Automated coverage must include at least:

- interaction key isolation by profile, user, chat, and topic;
- exact 60-second TTL behavior;
- one timeout alert on expiry;
- completion before expiry suppresses timeout alert;
- replacement invalidates the old timeout;
- unrelated user/chat/topic/profile cannot consume state;
- non-Qeo slash commands are not consumed as pending input;
- bare `/qeovoice` prompts for text;
- plain and multiline follow-up text generates voice;
- invalid voice follow-up reminds without resetting TTL;
- bare `/qeostory` prompts for an image;
- `/qeostory mango` preserves `mango` in pending state;
- follow-up image renders with the stored preset;
- invalid story follow-up reminds without resetting TTL;
- immediate `/qeovoice "text"`, `/qeovoice text`, and image + `/qeostory` continue to work;
- qeo-voice no-fallback invariant remains enforced.

Production acceptance must verify both conversational flows in Telegram, including timeout behavior and replacement of one pending Qeo command by the other.

## Out of Scope

- Persistent conversational state across gateway restarts.
- A generic conversation framework for unrelated plugins.
- More than one simultaneous pending Qeo interaction for the same interaction key.
- Extending the 60-second deadline after invalid input.
- Adding aliases or changing existing Telegram command names.
- Changing the Mac voice worker, Tailscale path, audio format, or qeo-story renderer implementation.