"""In-process pub/sub for canonical session events.

Subscribes to Postgres NOTIFY channel `session_events` (signaled by the
per-row trigger in sessions_schema.sql) and fans out to per-session
asyncio.Queue subscribers. Consumed by:

  * `GET /api/v1/sessions/{id}/events/stream` (SSE for adapters + PWA)
  * Mattermost/Teams/Slack adapters (future, same subscribe API)

Cross-tenant isolation: each subscribe call declares tenant_id; the bus
ignores notifications whose payload tenant_id doesn't match. Session_id
alone is not trusted — uuid collisions across tenants would otherwise
leak events.

Backpressure: per-subscriber queue is bounded (default 1000). Overflow
drops the oldest payload AND emits a `__overflow__` sentinel so the
subscriber can signal the client it may have missed events (client
reconnects with after_seq to backfill from the DB).

Singleton lifecycle:
    at app startup  -> await session_events_bus.start()
    at shutdown     -> await session_events_bus.stop()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("governance-hub.sessions.events_bus")

_PG_CHANNEL = "session_events"
_DEFAULT_QUEUE_SIZE = 1000
_OVERFLOW_SENTINEL: dict[str, Any] = {"__overflow__": True}


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------


@dataclass
class _Subscriber:
    tenant_id: str
    session_id: str
    queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_DEFAULT_QUEUE_SIZE)
    )


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


class SessionEventsBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[_Subscriber]] = {}
        self._lock = asyncio.Lock()
        self._conn = None
        self._listener_task: asyncio.Task | None = None
        self._running = False

    # ---- Lifecycle --------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        dsn = _asyncpg_dsn_from_env()
        if not dsn:
            logger.warning(
                "session_events_bus: no DSN derivable from env; LISTEN disabled. "
                "SSE subscribers will only receive backlog replays."
            )
            return

        try:
            import asyncpg  # local import to keep startup fast when unused
        except ImportError:
            logger.error(
                "session_events_bus: asyncpg not installed; LISTEN disabled"
            )
            return

        self._conn = await asyncpg.connect(dsn=dsn)
        await self._conn.add_listener(_PG_CHANNEL, self._handle_notify)
        self._running = True
        logger.info("session_events_bus: LISTEN %s", _PG_CHANNEL)

    async def stop(self) -> None:
        self._running = False
        if self._conn is not None:
            try:
                await self._conn.remove_listener(_PG_CHANNEL, self._handle_notify)
                await self._conn.close()
            except Exception as e:  # noqa: BLE001
                logger.debug("session_events_bus stop: %s", e)
            self._conn = None

    # ---- Subscribe / Unsubscribe ------------------------------------------

    async def subscribe(self, *, tenant_id: str, session_id: str) -> _Subscriber:
        sub = _Subscriber(tenant_id=tenant_id, session_id=session_id)
        async with self._lock:
            self._subscribers.setdefault(session_id, set()).add(sub)
        return sub

    async def unsubscribe(self, sub: _Subscriber) -> None:
        async with self._lock:
            group = self._subscribers.get(sub.session_id)
            if group is not None:
                group.discard(sub)
                if not group:
                    self._subscribers.pop(sub.session_id, None)

    # ---- Notify handler (called by asyncpg) --------------------------------

    def _handle_notify(self, _conn, _pid, _channel, payload: str) -> None:
        # Called in asyncpg's loop — must not block. Fan out asynchronously.
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("session_events_bus: bad notify payload: %r", payload[:200])
            return
        session_id = event.get("session_id")
        if not session_id:
            return
        asyncio.create_task(self._fanout(session_id, event))

    async def _fanout(self, session_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            group = list(self._subscribers.get(session_id, ()))
        for sub in group:
            if sub.tenant_id != event.get("tenant_id"):
                continue  # tenant isolation
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop one oldest, push overflow marker + new event
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    sub.queue.put_nowait(_OVERFLOW_SENTINEL)
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Give up; client will reconnect with after_seq to catch up
                    logger.warning(
                        "session_events_bus: queue overflow for %s (dropping)", session_id
                    )


# Module-level singleton.
bus = SessionEventsBus()


# ---------------------------------------------------------------------------
# SSE formatting helpers
# ---------------------------------------------------------------------------


def format_sse(event: dict[str, Any]) -> bytes:
    """Single SSE `data:` frame for an event dict, UTF-8 encoded."""
    body = json.dumps(event, separators=(",", ":"), default=str)
    return f"data: {body}\n\n".encode("utf-8")


def format_comment(text: str) -> bytes:
    """SSE comment frame — used as a heartbeat to keep proxies from idling out."""
    return f": {text}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asyncpg_dsn_from_env() -> str | None:
    """Derive a raw asyncpg DSN from the same env the app uses.

    Prefers GOVERNANCE_HUB_DATABASE_URL (the SQLAlchemy URL), stripping the
    `+asyncpg` dialect suffix. Falls back to DATABASE_URL.
    """
    for key in ("GOVERNANCE_HUB_DATABASE_URL", "DATABASE_URL"):
        raw = os.environ.get(key)
        if not raw:
            continue
        dsn = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
        return dsn
    return None
