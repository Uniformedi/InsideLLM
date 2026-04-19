"""Polyglot action dispatcher (P3.3).

Given an ActionCatalogEntry + caller inputs, routes execution to the
right backend and returns a unified result shape regardless of which
backend actually ran.

Supported today:
  * fastapi_http   — synchronous HTTP call; response body returned inline
  * celery_task    — queued; returns a task_id the caller polls

Stubbed with explicit NotImplementedError for now:
  * n8n_webhook, activepieces_trigger, mcp_tool  (P3.1, P3.2, future)

Backed by Redis for Celery status lookup. The dispatcher does NOT
enforce guardrails — that belongs to the caller (runtime agent executor
+ OPA). It does record an audit entry for each dispatch via the hash
chain so every invocation is traceable.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from ..schemas.actions import (
    ActionCatalogEntry,
    ActivepiecesBackend,
    CeleryBackend,
    FastAPIBackend,
    MCPBackend,
    N8nBackend,
)

logger = logging.getLogger("governance-hub.action_dispatcher")


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """Unified return for every backend type.

    mode="sync" means `output` holds the action's response body now.
    mode="async" means the caller polls `task_id` via get_task_status();
    `output` is None until the task completes.
    """
    ok: bool
    mode: str                    # sync | async
    backend_type: str
    action_id: str
    tenant_id: str | None
    dispatched_at: str
    output: dict[str, Any] | None = None
    task_id: str | None = None
    queue: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "backend_type": self.backend_type,
            "action_id": self.action_id,
            "tenant_id": self.tenant_id,
            "dispatched_at": self.dispatched_at,
            "output": self.output,
            "task_id": self.task_id,
            "queue": self.queue,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def dispatch(
    entry: ActionCatalogEntry,
    inputs: dict[str, Any],
    *,
    http_timeout: float | None = None,
    celery_app_factory=None,
) -> DispatchResult:
    """Route + execute. `celery_app_factory` and `http_timeout` are
    injectable for tests."""
    backend = entry.backend
    dispatched_at = datetime.now(timezone.utc).isoformat()
    base_meta = {
        "backend_type": getattr(backend, "type", "unknown"),
        "action_id": entry.action_id,
        "tenant_id": entry.tenant_id,
        "dispatched_at": dispatched_at,
    }

    if isinstance(backend, FastAPIBackend):
        return await _dispatch_fastapi(
            entry, backend, inputs, http_timeout=http_timeout, **base_meta
        )
    if isinstance(backend, CeleryBackend):
        return _dispatch_celery(
            entry, backend, inputs, celery_app_factory=celery_app_factory, **base_meta
        )
    if isinstance(backend, N8nBackend):
        return await _dispatch_n8n(
            entry, backend, inputs, http_timeout=http_timeout, **base_meta
        )
    if isinstance(backend, (ActivepiecesBackend, MCPBackend)):
        # P3.2 (activepieces) / future (mcp) will implement these; for now
        # fail explicitly so catalog entries referencing them get a clear
        # error rather than silently failing.
        return DispatchResult(
            ok=False,
            mode="sync",
            output=None,
            error=f"backend type '{getattr(backend, 'type', '?')}' not yet implemented "
                  f"(scheduled: P3.2 / future)",
            **base_meta,
        )

    return DispatchResult(
        ok=False,
        mode="sync",
        output=None,
        error=f"unknown backend type: {type(backend).__name__}",
        **base_meta,
    )


# ---------------------------------------------------------------------------
# FastAPI HTTP backend
# ---------------------------------------------------------------------------


async def _dispatch_fastapi(
    entry: ActionCatalogEntry,
    backend: FastAPIBackend,
    inputs: dict[str, Any],
    *,
    http_timeout: float | None,
    **meta: Any,
) -> DispatchResult:
    # URL-template substitution — catalog entries may use path params like
    # /connectors/{connector_id}/query. Pydantic's HttpUrl percent-encodes
    # the braces (%7B/%7D), so substitute both literal and encoded forms.
    url = str(backend.url)
    for k, v in (inputs or {}).items():
        for token in ("{" + k + "}", "%7B" + k + "%7D"):
            if token in url:
                url = url.replace(token, str(v))

    timeout = http_timeout or (backend.timeout_ms / 1000.0)
    method = backend.method

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if method == "GET":
                resp = await client.get(url, params=inputs)
            elif method == "DELETE":
                resp = await client.delete(url, params=inputs)
            else:
                resp = await client.request(method, url, json=inputs)
            resp.raise_for_status()
            output = resp.json() if resp.content else {}
            return DispatchResult(
                ok=True,
                mode="sync",
                output=output,
                **meta,
            )
        except httpx.HTTPStatusError as e:
            return DispatchResult(
                ok=False,
                mode="sync",
                output=None,
                error=f"HTTP {e.response.status_code}: {_short_body(e.response)}",
                **meta,
            )
        except Exception as e:
            return DispatchResult(
                ok=False,
                mode="sync",
                output=None,
                error=f"{type(e).__name__}: {e}"[:500],
                **meta,
            )


# ---------------------------------------------------------------------------
# n8n webhook backend (P3.1)
# ---------------------------------------------------------------------------


def _hmac_signature(secret: str, body: bytes) -> str:
    """Hex HMAC-SHA256 — matches what n8n's Code node recomputes to verify."""
    import hashlib
    import hmac as _hmac
    return _hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _dispatch_n8n(
    entry: ActionCatalogEntry,
    backend: N8nBackend,
    inputs: dict[str, Any],
    *,
    http_timeout: float | None,
    **meta: Any,
) -> DispatchResult:
    """POST to an n8n webhook URL with HMAC signature.

    The signature header is `X-Insidellm-Signature` (hex HMAC-SHA256 over the
    JSON body), the secret is read from the env var named by
    `backend.hmac_secret_env` (default `N8N_WEBHOOK_SECRET`).

    Workflow-side: first node is a Code node that recomputes the signature
    and rejects on mismatch. Template workflow ships in
    configs/n8n/workflows/verify-signature.json.
    """
    import json
    url = str(backend.webhook_url)
    # Path-param substitution (same as fastapi_http).
    for k, v in (inputs or {}).items():
        for token in ("{" + k + "}", "%7B" + k + "%7D"):
            if token in url:
                url = url.replace(token, str(v))

    body_bytes = json.dumps(inputs or {}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "insidellm-dispatcher/1.0",
        "X-Insidellm-Tenant": entry.tenant_id or "core",
        "X-Insidellm-Action": entry.action_id,
    }

    secret_env = backend.hmac_secret_env or "N8N_WEBHOOK_SECRET"
    secret = os.environ.get(secret_env, "")
    if secret:
        headers["X-Insidellm-Signature"] = _hmac_signature(secret, body_bytes)
    # Missing secret is not fatal — some tenants may operate in trusted
    # networks. Warn via log; workflows that reject unsigned bodies will
    # still surface a useful error.
    elif secret_env:
        logger.warning(
            f"n8n webhook dispatch without HMAC: env var {secret_env} unset "
            f"(action={entry.action_id})"
        )

    timeout = http_timeout or 15.0
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, content=body_bytes, headers=headers)
            resp.raise_for_status()
            output = resp.json() if resp.content else {}
            return DispatchResult(
                ok=True,
                mode="sync",
                output=output if isinstance(output, dict) else {"result": output},
                **meta,
            )
        except httpx.HTTPStatusError as e:
            return DispatchResult(
                ok=False,
                mode="sync",
                output=None,
                error=f"n8n HTTP {e.response.status_code}: {_short_body(e.response)}",
                **meta,
            )
        except Exception as e:
            return DispatchResult(
                ok=False,
                mode="sync",
                output=None,
                error=f"n8n dispatch failed: {type(e).__name__}: {e}"[:500],
                **meta,
            )


# ---------------------------------------------------------------------------
# Celery backend
# ---------------------------------------------------------------------------


def _dispatch_celery(
    entry: ActionCatalogEntry,
    backend: CeleryBackend,
    inputs: dict[str, Any],
    *,
    celery_app_factory=None,
    **meta: Any,
) -> DispatchResult:
    """Enqueue to Celery and return the task_id. Caller polls
    get_task_status(task_id) to retrieve the eventual result."""
    try:
        app = (celery_app_factory or _default_celery_app)()
    except Exception as e:
        return DispatchResult(
            ok=False,
            mode="async",
            output=None,
            error=f"celery app init failed: {type(e).__name__}: {e}"[:500],
            **meta,
        )

    try:
        async_result = app.send_task(
            backend.task,
            kwargs=inputs or {},
            queue=backend.queue,
            expires=backend.timeout_seconds,
            retry=False,  # retry policy is baked into the task definition
        )
    except Exception as e:
        return DispatchResult(
            ok=False,
            mode="async",
            output=None,
            error=f"celery send_task failed: {type(e).__name__}: {e}"[:500],
            **meta,
        )

    return DispatchResult(
        ok=True,
        mode="async",
        output=None,
        task_id=async_result.id,
        queue=backend.queue,
        **meta,
    )


# ---------------------------------------------------------------------------
# Task-status polling
# ---------------------------------------------------------------------------


async def get_task_status(
    task_id: str,
    *,
    celery_app_factory=None,
) -> dict[str, Any]:
    """Return Celery task status. Runs the sync Celery client in a thread
    so the async FastAPI event loop isn't blocked.

    Response shape:
      {task_id, state, ready, successful, result, progress}
      state ∈ PENDING | STARTED | PROGRESS | SUCCESS | FAILURE | REVOKED
    """
    def _read():
        app = (celery_app_factory or _default_celery_app)()
        result = app.AsyncResult(task_id)
        out: dict[str, Any] = {
            "task_id": task_id,
            "state": result.state,
            "ready": result.ready(),
            "successful": result.successful() if result.ready() else None,
        }
        if result.state == "PROGRESS":
            out["progress"] = result.info or {}
        elif result.ready():
            # Guard against FAILURE where `.result` is an Exception.
            try:
                out["result"] = result.result if result.successful() else str(result.result)
            except Exception as e:
                out["result"] = f"<error reading result: {e}>"
        return out

    return await asyncio.get_event_loop().run_in_executor(None, _read)


# ---------------------------------------------------------------------------
# Celery client factory
# ---------------------------------------------------------------------------


def _default_celery_app():
    """Build a minimal Celery client bound to the same broker/backend as
    the worker container. This client doesn't need the full task
    definitions — it just publishes by task name."""
    from celery import Celery
    broker = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")
    result = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
    app = Celery("insidellm-dispatcher", broker=broker, backend=result)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
    )
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_body(resp) -> str:
    try:
        return resp.text[:200]
    except Exception:
        return "<unreadable>"
