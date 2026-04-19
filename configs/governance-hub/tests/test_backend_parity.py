"""P3.4 — Action catalog backend parity suite.

Contract-level regression guard. For any backend type supported by the
dispatcher (fastapi_http, celery_task, n8n_webhook, and the
not-yet-implemented activepieces_trigger / mcp_tool), the dispatch
API MUST:

  * Return a DispatchResult whose shape is identical across backends
  * Populate backend_type + action_id + tenant_id + dispatched_at on
    every call (including errors) — operators rely on these fields
    to correlate audit entries
  * Substitute URL template params the same way for every HTTP-based
    backend (fastapi_http, n8n_webhook)
  * Produce a specific `error` string on failure (never None when ok=False)
  * Honour the sync/async mode contract:
      - fastapi_http, n8n_webhook → "sync"
      - celery_task               → "async"
      - unsupported               → "sync" (failure is immediate)

Adding a new backend type to ActionBackend means adding one row to
BACKEND_MATRIX here and wiring the dispatch branch in
services/action_dispatcher.py — that's it. The parity tests fan out
across every registered backend via pytest.mark.parametrize.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.schemas.actions import ActionCatalogEntry
from src.services import action_dispatcher as d


# ---------------------------------------------------------------------------
# Minimal entry factory — one per backend type, same semantics
# ---------------------------------------------------------------------------


def _entry(backend: dict) -> ActionCatalogEntry:
    return ActionCatalogEntry.model_validate({
        "schema_version": "1.0",
        "action_id": "parity_probe",
        "tenant_id": "core",
        "display_name": "Parity Probe",
        "description": "Backend-parity test fixture.",
        "category": "other",
        "backend": backend,
        "guardrail_requirements": {"minimum_guardrail_tier": "tier_general_business"},
    })


# ---------------------------------------------------------------------------
# The parity matrix — add rows here when you wire a new backend type
# ---------------------------------------------------------------------------


SUPPORTED_SYNC_HTTP = [
    # (backend_type_name, backend_dict_builder, expected_result_mode)
    (
        "fastapi_http",
        lambda url: {"type": "fastapi_http", "url": url, "method": "POST"},
        "sync",
    ),
    (
        "n8n_webhook",
        lambda url: {"type": "n8n_webhook", "webhook_url": url},
        "sync",
    ),
]

CELERY_BACKEND = (
    "celery_task",
    lambda: {
        "type": "celery_task",
        "task": "insidellm.tasks.ocr_document",
        "queue": "actions",
        "timeout_seconds": 60,
    },
    "async",
)

NOT_IMPLEMENTED_BACKENDS = [
    # These fail with a predictable error until their P3.2 / future
    # implementations land. Parity contract applies regardless.
    ("activepieces_trigger", {"type": "activepieces_trigger", "trigger_url": "http://ap/hook"}),
    ("mcp_tool",             {"type": "mcp_tool", "server": "svc", "tool_name": "probe"}),
]


# ---------------------------------------------------------------------------
# DispatchResult shape — every backend returns the same field set
# ---------------------------------------------------------------------------


REQUIRED_RESULT_FIELDS = {
    "ok", "mode", "backend_type", "action_id", "tenant_id", "dispatched_at",
    "output", "task_id", "queue", "error",
}


def _assert_contract(result, *, expected_type: str):
    """Every backend's DispatchResult must share the same top-level fields
    + the action-identity triple (id/tenant/dispatched_at) regardless of
    success or failure."""
    d_ = result.to_dict()
    assert REQUIRED_RESULT_FIELDS.issubset(d_.keys()), (
        f"result fields missing: {REQUIRED_RESULT_FIELDS - set(d_.keys())}"
    )
    assert d_["action_id"] == "parity_probe"
    assert d_["tenant_id"] == "core"
    assert d_["backend_type"] == expected_type
    # Timestamp must always be present + ISO-formatted.
    assert d_["dispatched_at"] and "T" in d_["dispatched_at"]


# ---------------------------------------------------------------------------
# Parity: sync HTTP-based backends (fastapi + n8n)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data or {"ok": True}
        self.content = b"x"
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        import httpx
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=MagicMock(), response=self)


class _FakeClient:
    def __init__(self, resp=None):
        self._resp = resp or _FakeResp()
        self.calls: list[tuple[str, str, dict]] = []
        self.last_headers: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, json=None):
        self.calls.append((method, url, json or {}))
        return self._resp

    async def get(self, url, params=None):
        self.calls.append(("GET", url, params or {}))
        return self._resp

    async def delete(self, url, params=None):
        self.calls.append(("DELETE", url, params or {}))
        return self._resp

    async def post(self, url, content=None, json=None, headers=None):
        payload = content if content is not None else (json or {})
        self.calls.append(("POST", url, payload))
        self.last_headers = dict(headers or {})
        return self._resp


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name,builder,expected_mode", SUPPORTED_SYNC_HTTP)
async def test_sync_http_success_returns_contract_result(
    backend_name, builder, expected_mode,
):
    entry = _entry(builder("http://svc:8000/actions/probe"))
    fake = _FakeClient(_FakeResp(200, {"echoed": True}))

    with patch.object(d, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        result = await d.dispatch(entry, {"x": 1})

    assert result.ok is True
    assert result.mode == expected_mode
    _assert_contract(result, expected_type=backend_name)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name,builder,_mode", SUPPORTED_SYNC_HTTP)
async def test_sync_http_url_template_substitution(backend_name, builder, _mode):
    """Both HTTP-based backends must substitute {param} identically."""
    entry = _entry(builder("http://svc:8000/api/things/{thing_id}/read"))
    fake = _FakeClient(_FakeResp(200, {"ok": True}))

    with patch.object(d, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        await d.dispatch(entry, {"thing_id": 42})

    # Both backends must resolve {thing_id} → 42 in the outbound URL.
    assert fake.calls, f"{backend_name}: no HTTP call issued"
    sent_url = fake.calls[0][1]
    assert "{thing_id}" not in sent_url, f"{backend_name} left template unsubstituted"
    assert "%7Bthing_id%7D" not in sent_url, f"{backend_name} left URL-encoded template"
    assert "/api/things/42/read" in sent_url


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name,builder,_mode", SUPPORTED_SYNC_HTTP)
async def test_sync_http_error_always_fills_error_field(
    backend_name, builder, _mode,
):
    entry = _entry(builder("http://svc:8000/broken"))
    fake = _FakeClient(_FakeResp(500, None, text="provider-kaboom"))

    with patch.object(d, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError
        result = await d.dispatch(entry, {})

    assert result.ok is False
    assert result.error is not None, f"{backend_name}: error field empty on failure"
    assert "500" in result.error
    _assert_contract(result, expected_type=backend_name)


# ---------------------------------------------------------------------------
# Parity: celery backend (async, no HTTP round-trip)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_celery_dispatch_returns_contract_async_result():
    backend_name, builder, expected_mode = CELERY_BACKEND
    entry = _entry(builder())

    fake_async = MagicMock()
    fake_async.id = "task-parity-probe"
    fake_app = MagicMock()
    fake_app.send_task = MagicMock(return_value=fake_async)

    result = await d.dispatch(
        entry, {"document_url": "s3://x"},
        celery_app_factory=lambda: fake_app,
    )

    assert result.ok is True
    assert result.mode == expected_mode
    assert result.task_id == "task-parity-probe"
    _assert_contract(result, expected_type=backend_name)


@pytest.mark.asyncio
async def test_celery_broker_down_fills_error_field():
    _, builder, _ = CELERY_BACKEND
    entry = _entry(builder())

    fake_app = MagicMock()
    fake_app.send_task = MagicMock(side_effect=RuntimeError("broker-unreachable"))

    result = await d.dispatch(entry, {}, celery_app_factory=lambda: fake_app)

    assert result.ok is False
    assert result.error and "broker-unreachable" in result.error
    _assert_contract(result, expected_type="celery_task")


# ---------------------------------------------------------------------------
# Parity: not-yet-implemented backends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name,backend_dict", NOT_IMPLEMENTED_BACKENDS)
async def test_unsupported_backend_fails_explicitly(backend_name, backend_dict):
    entry = _entry(backend_dict)
    result = await d.dispatch(entry, {})
    assert result.ok is False
    assert result.error and "not yet implemented" in result.error
    _assert_contract(result, expected_type=backend_name)


# ---------------------------------------------------------------------------
# Cross-backend invariant: all supported backends expose identical fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_registered_backend_is_covered_in_parity_matrix():
    """Regression guard: when someone adds a new backend to ActionBackend
    they MUST add it to the parity matrix above. This test introspects
    the discriminated union and fails if the matrix is out of date."""
    from src.schemas.actions import ActionBackend
    from typing import get_args, get_origin

    # ActionBackend is Annotated[Union[...], Field(...)]; walk to the Union.
    args = get_args(ActionBackend)
    union = args[0]
    backend_classes = get_args(union) or [union]

    # Collect each class's Literal `type` value.
    registered_types: set[str] = set()
    for cls in backend_classes:
        # Pydantic model — read the `type` field's default (Literal).
        if hasattr(cls, "model_fields"):
            type_field = cls.model_fields.get("type")
            if type_field is not None:
                type_args = get_args(type_field.annotation)
                if type_args:
                    registered_types.add(type_args[0])

    matrix_types = {name for name, _, _ in SUPPORTED_SYNC_HTTP}
    matrix_types.add(CELERY_BACKEND[0])
    matrix_types |= {name for name, _ in NOT_IMPLEMENTED_BACKENDS}

    missing = registered_types - matrix_types
    extra = matrix_types - registered_types
    assert not missing, (
        f"parity matrix is missing backend types: {sorted(missing)}. "
        f"Add a row in SUPPORTED_SYNC_HTTP / CELERY_BACKEND / "
        f"NOT_IMPLEMENTED_BACKENDS so contract tests run against them."
    )
    assert not extra, (
        f"parity matrix references types not in ActionBackend schema: "
        f"{sorted(extra)}"
    )
