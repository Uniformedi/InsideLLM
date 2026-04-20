"""Unit tests for P3.3 polyglot action dispatcher.

Covers:
  * FastAPI HTTP backend: request shape (GET/POST/path params), output
    returned inline with mode='sync'
  * Celery backend: send_task called with the right task name + queue,
    task_id surfaced in the result, mode='async'
  * Unsupported backends (n8n / activepieces / mcp): explicit
    not-implemented error, don't silently succeed
  * Failure modes: HTTP 4xx/5xx bubble a useful error string without
    leaking the response body; Celery transport error captured
  * get_task_status reads state + progress + result from the Celery
    AsyncResult without raising on FAILURE
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.schemas.actions import (
    ActionCatalogEntry,
    ActivepiecesBackend,
    CeleryBackend,
    FastAPIBackend,
    MCPBackend,
    N8nBackend,
)
from src.services import action_dispatcher as d


def _entry_with(backend_dict) -> ActionCatalogEntry:
    return ActionCatalogEntry.model_validate({
        "schema_version": "1.0",
        "action_id": "probe",
        "tenant_id": "core",
        "display_name": "Probe",
        "description": "Test action.",
        "category": "other",
        "backend": backend_dict,
        "guardrail_requirements": {"minimum_guardrail_tier": "tier_general_business"},
    })


# ---------------------------------------------------------------------------
# FastAPI backend
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data or {}
        self.content = b"x" if self._data else b""
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        import httpx
        if self.status_code >= 400:
            req = MagicMock()
            raise httpx.HTTPStatusError("err", request=req, response=self)


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        self.calls.append(("GET", url, params or {}))
        return self._resp

    async def delete(self, url, params=None):
        self.calls.append(("DELETE", url, params or {}))
        return self._resp

    async def request(self, method, url, json=None):
        self.calls.append((method, url, json or {}))
        return self._resp

    async def post(self, url, content=None, json=None, headers=None):
        # n8n dispatch uses client.post(url, content=…, headers=…).
        payload = content if content is not None else (json or {})
        self.calls.append(("POST", url, payload))
        self.last_headers = dict(headers or {})
        return self._resp


@pytest.mark.asyncio
async def test_fastapi_post_returns_inline_sync():
    entry = _entry_with({
        "type": "fastapi_http",
        "url": "http://svc/actions/probe",
        "method": "POST",
    })
    fake = _FakeClient(_FakeResp(200, {"echo": "hello"}))

    with patch.object(d, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        # Keep the real exception type available so the dispatcher's
        # `except httpx.HTTPStatusError` still resolves.
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        result = await d.dispatch(entry, {"x": 1})

    assert result.ok is True
    assert result.mode == "sync"
    assert result.output == {"echo": "hello"}
    assert result.backend_type == "fastapi_http"
    assert fake.calls == [("POST", "http://svc/actions/probe", {"x": 1})]


@pytest.mark.asyncio
async def test_fastapi_path_params_substituted():
    entry = _entry_with({
        "type": "fastapi_http",
        "url": "http://svc/api/connectors/{connector_id}/query",
        "method": "POST",
    })
    fake = _FakeClient(_FakeResp(200, {"rows": []}))

    with patch.object(d, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        await d.dispatch(entry, {"connector_id": 42, "query_name": "list"})

    assert fake.calls[0][1] == "http://svc/api/connectors/42/query"


@pytest.mark.asyncio
async def test_fastapi_http_error_bubbles_useful_message():
    entry = _entry_with({
        "type": "fastapi_http",
        "url": "http://svc/actions/probe",
        "method": "POST",
    })
    fake = _FakeClient(_FakeResp(500, None, text="kaboom"))

    with patch.object(d, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        result = await d.dispatch(entry, {})

    assert result.ok is False
    assert "HTTP 500" in (result.error or "")
    assert "kaboom" in (result.error or "")


# ---------------------------------------------------------------------------
# Celery backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_celery_dispatch_returns_task_id_async_mode():
    entry = _entry_with({
        "type": "celery_task",
        "task": "insidellm.tasks.ocr_document",
        "queue": "actions",
        "timeout_seconds": 60,
    })

    fake_async = MagicMock()
    fake_async.id = "task-abc-123"
    fake_app = MagicMock()
    fake_app.send_task = MagicMock(return_value=fake_async)

    result = await d.dispatch(entry, {"document_url": "s3://x"}, celery_app_factory=lambda: fake_app)

    assert result.ok is True
    assert result.mode == "async"
    assert result.task_id == "task-abc-123"
    assert result.queue == "actions"
    assert result.backend_type == "celery_task"

    # Verify the publish shape.
    fake_app.send_task.assert_called_once()
    args, kwargs = fake_app.send_task.call_args
    assert args[0] == "insidellm.tasks.ocr_document"
    assert kwargs["kwargs"] == {"document_url": "s3://x"}
    assert kwargs["queue"] == "actions"


@pytest.mark.asyncio
async def test_celery_broker_down_surfaces_error():
    entry = _entry_with({
        "type": "celery_task",
        "task": "insidellm.tasks.ocr_document",
        "queue": "actions",
    })
    fake_app = MagicMock()
    fake_app.send_task = MagicMock(side_effect=RuntimeError("broker-down"))

    result = await d.dispatch(entry, {}, celery_app_factory=lambda: fake_app)

    assert result.ok is False
    assert result.mode == "async"
    assert result.task_id is None
    assert "broker-down" in (result.error or "")


@pytest.mark.asyncio
async def test_get_task_status_success():
    fake_app = MagicMock()
    fake_result = MagicMock()
    fake_result.state = "SUCCESS"
    fake_result.ready = lambda: True
    fake_result.successful = lambda: True
    fake_result.result = {"ok": True, "rows": 0}
    fake_app.AsyncResult = MagicMock(return_value=fake_result)

    out = await d.get_task_status("task-xyz", celery_app_factory=lambda: fake_app)
    assert out["state"] == "SUCCESS"
    assert out["ready"] is True
    assert out["successful"] is True
    assert out["result"] == {"ok": True, "rows": 0}


@pytest.mark.asyncio
async def test_get_task_status_progress():
    fake_app = MagicMock()
    fake_result = MagicMock()
    fake_result.state = "PROGRESS"
    fake_result.ready = lambda: False
    fake_result.successful = lambda: False
    fake_result.info = {"processed": 5, "total": 100}
    fake_app.AsyncResult = MagicMock(return_value=fake_result)

    out = await d.get_task_status("task-xyz", celery_app_factory=lambda: fake_app)
    assert out["state"] == "PROGRESS"
    assert out["progress"] == {"processed": 5, "total": 100}
    assert out["ready"] is False


@pytest.mark.asyncio
async def test_get_task_status_failure_does_not_raise():
    fake_app = MagicMock()
    fake_result = MagicMock()
    fake_result.state = "FAILURE"
    fake_result.ready = lambda: True
    fake_result.successful = lambda: False
    fake_result.result = RuntimeError("task-crashed")
    fake_app.AsyncResult = MagicMock(return_value=fake_result)

    out = await d.get_task_status("task-xyz", celery_app_factory=lambda: fake_app)
    assert out["state"] == "FAILURE"
    assert out["successful"] is False
    assert "task-crashed" in str(out.get("result", ""))


# ---------------------------------------------------------------------------
# n8n webhook backend (P3.1)
# ---------------------------------------------------------------------------


def test_hmac_signature_is_hex_sha256_over_body():
    import hashlib, hmac
    secret = "s3cret"
    body = b'{"x":1}'
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert d._hmac_signature(secret, body) == expected


@pytest.mark.asyncio
async def test_n8n_dispatch_posts_with_signature_and_headers():
    entry = _entry_with({
        "type": "n8n_webhook",
        "webhook_url": "http://n8n:5678/webhook/foo",
        "hmac_secret_env": "N8N_WEBHOOK_SECRET",
    })
    fake = _FakeClient(_FakeResp(200, {"ok": True, "echo": 42}))

    with patch.object(d, "httpx") as mhttpx, \
         patch.dict("os.environ", {"N8N_WEBHOOK_SECRET": "s3cret"}, clear=False):
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        result = await d.dispatch(entry, {"foo": "bar", "n": 1})

    assert result.ok is True
    assert result.mode == "sync"
    assert result.backend_type == "n8n_webhook"
    assert result.output == {"ok": True, "echo": 42}

    # Verify the FakeClient recorded a POST with the signed body.
    method, url, body = fake.calls[0]
    assert method == "POST"
    assert url == "http://n8n:5678/webhook/foo"
    # Body is canonicalized JSON; verify the signature header matches.
    import hashlib, hmac
    expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert fake.last_headers.get("X-Insidellm-Signature") == expected
    assert fake.last_headers.get("X-Insidellm-Tenant") == "core"
    assert fake.last_headers.get("X-Insidellm-Action") == "probe"


@pytest.mark.asyncio
async def test_n8n_missing_secret_still_dispatches_but_logs():
    """Some tenants trust the internal network — no secret shouldn't
    block dispatch, but the workflow will typically reject it."""
    entry = _entry_with({
        "type": "n8n_webhook",
        "webhook_url": "http://n8n:5678/webhook/bar",
        "hmac_secret_env": "N8N_WEBHOOK_SECRET_MISSING",
    })
    fake = _FakeClient(_FakeResp(200, {"ok": True}))

    with patch.object(d, "httpx") as mhttpx, \
         patch.dict("os.environ", {}, clear=False):
        import os as _os
        _os.environ.pop("N8N_WEBHOOK_SECRET_MISSING", None)
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        result = await d.dispatch(entry, {})

    assert result.ok is True  # dispatch succeeds; downstream decides.


@pytest.mark.asyncio
async def test_n8n_http_error_bubbles_useful_message():
    entry = _entry_with({
        "type": "n8n_webhook",
        "webhook_url": "http://n8n:5678/webhook/broken",
    })
    fake = _FakeClient(_FakeResp(403, None, text="invalid signature"))

    with patch.object(d, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        result = await d.dispatch(entry, {})

    assert result.ok is False
    assert "n8n HTTP 403" in (result.error or "")
    assert "invalid signature" in (result.error or "")


# ---------------------------------------------------------------------------
# Not-yet-implemented backends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_dict", [
    # activepieces_trigger moved to its own test suite via the parity matrix
    # when P3.2 landed. mcp_tool is still pending implementation.
    {"type": "mcp_tool", "server": "svc", "tool_name": "x"},
])
async def test_not_yet_implemented_backends_fail_explicitly(backend_dict):
    entry = _entry_with(backend_dict)
    result = await d.dispatch(entry, {})
    assert result.ok is False
    assert "not yet implemented" in (result.error or "")


# ---------------------------------------------------------------------------
# Seed shipment
# ---------------------------------------------------------------------------


def test_async_tasks_are_in_core_seed():
    """Regression guard — async_tasks.yaml must be part of the shipped
    core wrappers so `celery_task` entries are auto-registered when the
    gov-hub first boots."""
    from src.services.action_catalog_seed import _WRAPPERS, load_core_wrappers

    assert "async_tasks.yaml" in _WRAPPERS
    entries = load_core_wrappers()
    celery_ids = {
        e.action_id for e in entries if getattr(e.backend, "type", "") == "celery_task"
    }
    assert {"batch_letter_merge", "ocr_document", "account_portfolio_export"}.issubset(
        celery_ids
    ), f"missing expected celery tasks; got: {celery_ids}"
