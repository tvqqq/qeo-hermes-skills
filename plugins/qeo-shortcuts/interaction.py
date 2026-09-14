"""Shared pending interaction state for Qeo Telegram shortcuts."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

DEFAULT_TTL_SECONDS = 60.0
InteractionKey = Tuple[str, str, str, str]


@dataclass(frozen=True)
class PendingInteraction:
    request_id: str
    key: InteractionKey
    kind: str
    created_at: float
    expires_at: float
    payload: Dict[str, Any]
    source: Any
    message_id: Optional[str]


ExpireCallback = Callable[[PendingInteraction], Awaitable[None]]


def interaction_key(source) -> Optional[InteractionKey]:
    user_id = str(getattr(source, "user_id", None) or "").strip()
    if not user_id:
        return None
    profile = str(getattr(source, "profile", None) or "default")
    chat_id = str(getattr(source, "chat_id", None) or "")
    thread_id = str(getattr(source, "thread_id", None) or "")
    return (profile, user_id, chat_id, thread_id)


def is_slash_command(text: str) -> bool:
    return (text or "").lstrip().startswith("/")


class InteractionManager:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, clock=time.monotonic):
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._pending: Dict[InteractionKey, PendingInteraction] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def start(
        self, key: InteractionKey, *, kind: str, payload: Dict[str, Any],
        source: Any, message_id: Optional[str], on_expire: ExpireCallback,
    ) -> PendingInteraction:
        self.clear(key)
        now = self._clock()
        pending = PendingInteraction(
            request_id=uuid.uuid4().hex,
            key=key,
            kind=kind,
            created_at=now,
            expires_at=now + self._ttl_seconds,
            payload=dict(payload),
            source=source,
            message_id=message_id,
        )
        self._pending[key] = pending
        task = asyncio.get_running_loop().create_task(
            self._expire_after(pending, on_expire)
        )
        self._tasks[pending.request_id] = task
        return pending

    async def _expire_after(
        self, pending: PendingInteraction, on_expire: ExpireCallback,
    ) -> None:
        try:
            await asyncio.sleep(self._ttl_seconds)
        except asyncio.CancelledError:
            return

        current = self._pending.get(pending.key)
        if current is None or current.request_id != pending.request_id:
            return
        self._pending.pop(pending.key, None)
        self._tasks.pop(pending.request_id, None)
        await on_expire(pending)

    def peek(self, key: InteractionKey) -> Optional[PendingInteraction]:
        return self._pending.get(key)

    def take(self, key: InteractionKey, kind: str) -> Optional[PendingInteraction]:
        current = self._pending.get(key)
        if current is None or current.kind != kind:
            return None
        return self.clear(key)

    def clear(self, key: InteractionKey) -> Optional[PendingInteraction]:
        current = self._pending.pop(key, None)
        if current is None:
            return None
        task = self._tasks.pop(current.request_id, None)
        if task is not None:
            task.cancel()
        return current


INTERACTIONS = InteractionManager()
