# Qeo Shortcuts Conversational Input Design

Date: 2026-09-14
Status: Approved design pending implementation plan

## Goal

Add a two-message conversational mode while preserving all existing one-message fast paths.

- `/qeovoice "text"` and `/qeovoice text` synthesize immediately.
- Bare `/qeovoice` asks for text, then consumes the same user's next valid text message.
- image + `/qeostory [preset]` renders immediately.
- `/qeostory [preset]` without an image asks for an image, then consumes the same user's next valid image.
- Pending requests expire after 60 seconds and proactively notify the user.
- Pending replies are handled inside `qeo-shortcuts`; they do not require an LLM turn.

## Architecture

Add `plugins/qeo-shortcuts/interaction.py` as a shared in-memory pending-state manager. It owns state identity, TTL, replacement, cancellation, expiry, and stale-timeout protection. Voice and story handlers keep ownership of parsing, validation, execution, and user-facing result/error messages.

No database or external service is added. State is intentionally memory-only; a gateway restart may discard pending requests.

## State Identity

Pending state is keyed by:

```text
(profile, user_id, chat_id, thread_id)
```

Conversation mode requires `source.user_id`. If it is missing, a bare command does not create state and falls back to that command's existing help/usage response.

One key can have only one pending Qeo interaction. Any newly recognized Qeo shortcut from the same key clears the previous pending request first, then either executes immediately or creates a new pending request.

A pending record contains a unique `request_id`, kind (`voice_text` or `story_image`), created/expiry timestamps, command payload such as story preset, and original routing/message metadata for timeout feedback.

TTL is exactly 60 seconds from the original command. Invalid input never extends it.

## Gateway Semantics

Hermes `pre_gateway_dispatch` is the deterministic interception point. Consumed conversational messages return `skip`, so they do not reach the LLM.

Recognized Qeo commands take precedence over pending-input consumption. Example: while waiting for voice text, `/qeostory mango` is not spoken; it clears voice pending and starts story pending. The inverse applies to `/qeovoice` while story is pending.

Other slash commands are not consumed as pending content. They continue through Hermes while the pending Qeo request keeps its original deadline.

## Qeo Voice

Bare `/qeovoice` creates `voice_text` pending state and replies:

```text
🎙️ Bạn muốn Chi Chi đọc nội dung gì? Hãy gửi text trong vòng 1 phút.
```

A valid follow-up has non-whitespace `event.text` and is not a slash command. The full text, including newlines, is the speech payload; quotes are not required. Attachments do not matter when valid text is present.

On valid text: clear pending first, invalidate/cancel timeout, call the existing `_process_qeovoice` path, and return `skip`.

Without valid text, keep pending and reply:

```text
⚠️ Hãy gửi nội dung text. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu.
```

On expiry:

```text
⏱️ Yêu cầu Qeo Voice đã hết hạn. Hãy gửi lại /qeovoice để tạo voice mới.
```

Existing worker offline/busy/failure messages, OGG/Opus delivery, and the no-fallback invariant remain unchanged.

## Qeo Story

If `/qeostory [preset]` arrives without an image, create `story_image` pending state, preserve the selected preset, and reply:

```text
🖼️ Hãy gửi ảnh screenshot trong vòng 1 phút.
```

A valid follow-up is any event for which the existing story image extractor resolves a local image path. Caption text is ignored for rendering input.

On valid image: clear pending first, invalidate/cancel timeout, render with the stored preset, send the image, and return `skip`.

Without a resolvable image, keep pending and reply:

```text
⚠️ Hãy gửi ảnh screenshot. Yêu cầu hiện tại sẽ hết hạn sau 1 phút kể từ lúc bắt đầu.
```

On expiry:

```text
⏱️ Yêu cầu Qeo Story đã hết hạn. Hãy gửi lại /qeostory để tạo story mới.
```

Existing preset validation and render-failure behavior remain unchanged.

## Replacement, Isolation, and Race Safety

A new recognized Qeo command always clears the old pending request before processing the new one, including immediate commands. For example, pending story + `/qeovoice "Xin chào"` cancels story and synthesizes immediately.

Messages from another profile, user, chat, or topic never consume or mutate the pending request.

Each pending request has a unique `request_id`. A timeout callback must confirm the current record still has that `request_id` before clearing state or sending an alert. Completing or replacing a request should also cancel its timeout task when possible. This prevents stale alerts when response and timeout race.

Timeout alerts stay in the original chat/topic and should reply to the original command when supported.

## Error Handling

- Invalid follow-up: remind, keep state, do not reset TTL.
- Voice failure after valid input: use existing qeo-voice error behavior; do not recreate pending state.
- Story failure after valid image: use existing render-failure behavior; do not recreate pending state.
- Missing `user_id`: no pending state; use current help/usage.
- Gateway restart: pending may be lost; no persistence/recovery required.
- No server-side TTS fallback may be introduced.

## Testing and Acceptance

Implementation uses TDD. Cover: key isolation; exact 60-second expiry; one timeout alert; completion suppressing timeout; replacement suppressing stale timeout; immediate replacement commands; unrelated identities; non-Qeo slash commands; missing user identity; bare voice prompt; plain/multiline voice follow-up; invalid voice follow-up; bare story prompt; preset preservation; image follow-up; invalid story follow-up; existing immediate forms; and qeo-voice no-fallback.

Production acceptance must verify both conversational Telegram flows, timeout alerts, and replacing one pending Qeo command with the other.

## Out of Scope

Persistent state across restart, a generic conversation framework, multiple simultaneous pending Qeo interactions per key, TTL extension after invalid input, new command aliases, and changes to the Mac voice worker, Tailscale path, audio format, or story renderer.