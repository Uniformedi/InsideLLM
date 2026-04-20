"""Canonical session cost attribution — LiteLLM success callback.

Ties every successful LLM call to the canonical session the OWUI sessions
bridge stamped into request metadata. On success, POSTs token / cost usage
to governance-hub's /api/v1/sessions/{id}/cost endpoint. Fails silently —
cost tracking must never block a user's completion.

Pairs with configs/open-webui/sessions-bridge-pipeline.py (stamps the
insidellm_session_id into metadata) and the sessions_service.record_cost
endpoint that persists the attribution.

Why async_log_success_event vs. async_post_call_success_hook:
  * We want observational, out-of-band attribution — never rewrite the
    response. log_success_event is LiteLLM's canonical hook for that.
  * It gets full kwargs including model + usage + response_cost even when
    the provider didn't bill a first-party cost (LiteLLM computes it).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from litellm.integrations.custom_logger import CustomLogger

logger = logging.getLogger("insidellm.session_cost")

_GOVHUB_URL = os.environ.get("INSIDELLM_GOVHUB_URL", "http://governance-hub:8090")
_SERVICE_TOKEN = os.environ.get("LITELLM_MASTER_KEY", "")
_HTTP_TIMEOUT = httpx.Timeout(3.0, connect=1.5)


def _extract_session_id(kwargs: dict[str, Any]) -> str | None:
    """Pull insidellm_session_id out of the metadata the OWUI bridge stamped.

    LiteLLM nests metadata under litellm_params.metadata; older versions use
    kwargs.metadata directly. Check both.
    """
    metadata = (kwargs.get("litellm_params") or {}).get("metadata") or {}
    sid = metadata.get("insidellm_session_id")
    if sid:
        return sid
    return (kwargs.get("metadata") or {}).get("insidellm_session_id")


def _extract_usage(
    kwargs: dict[str, Any], response_obj: Any
) -> tuple[int, int, int, float]:
    """Return (prompt_tokens, completion_tokens, total_tokens, cost_usd)."""
    usage = None
    try:
        usage = getattr(response_obj, "usage", None)
        if usage is None and isinstance(response_obj, dict):
            usage = response_obj.get("usage")
    except Exception:
        usage = None

    def _g(obj: Any, key: str) -> int:
        if obj is None:
            return 0
        v = getattr(obj, key, None) if not isinstance(obj, dict) else obj.get(key)
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    prompt = _g(usage, "prompt_tokens")
    completion = _g(usage, "completion_tokens")
    total = _g(usage, "total_tokens") or (prompt + completion)

    cost = kwargs.get("response_cost")
    if cost is None:
        cost = (kwargs.get("standard_logging_object") or {}).get("response_cost")
    try:
        cost_f = float(cost or 0.0)
    except (TypeError, ValueError):
        cost_f = 0.0

    return prompt, completion, total, cost_f


class SessionCostCallback(CustomLogger):
    """LiteLLM success/failure hook that attributes usage to canonical sessions."""

    def __init__(self) -> None:
        super().__init__()
        self._client = httpx.AsyncClient(
            base_url=_GOVHUB_URL,
            timeout=_HTTP_TIMEOUT,
            headers=(
                {"Authorization": f"Bearer {_SERVICE_TOKEN}"} if _SERVICE_TOKEN else {}
            ),
        )

    async def async_log_success_event(
        self, kwargs, response_obj, start_time, end_time
    ):  # noqa: D401
        session_id = _extract_session_id(kwargs)
        if not session_id:
            return  # chat not bound to a canonical session — nothing to attribute

        prompt, completion, total, cost_usd = _extract_usage(kwargs, response_obj)
        model = kwargs.get("model") or "unknown"

        payload = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "cost_usd": cost_usd,
            "model": model,
            "latency_ms": int((end_time - start_time).total_seconds() * 1000)
            if end_time and start_time
            else 0,
        }

        try:
            resp = await self._client.post(
                f"/api/v1/sessions/{session_id}/cost", json=payload
            )
            if resp.status_code >= 400:
                logger.warning(
                    "session_cost: govhub returned %s for %s: %s",
                    resp.status_code,
                    session_id,
                    resp.text[:200],
                )
        except Exception as e:  # noqa: BLE001
            # Never block on cost-tracking failure. Governance-hub can
            # reconcile from LiteLLM's own spend log if needed.
            logger.debug("session_cost post failed: %s", e)

    async def async_log_failure_event(
        self, kwargs, response_obj, start_time, end_time
    ):
        """Record a zero-cost error entry so the session keeps correct call counts."""
        session_id = _extract_session_id(kwargs)
        if not session_id:
            return

        payload = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "model": kwargs.get("model") or "unknown",
            "latency_ms": int((end_time - start_time).total_seconds() * 1000)
            if end_time and start_time
            else 0,
            "error": True,
        }

        try:
            await self._client.post(
                f"/api/v1/sessions/{session_id}/cost", json=payload
            )
        except Exception:
            pass


# Module-level instance for LiteLLM's custom_callback_path loader.
proxy_handler_instance = SessionCostCallback()
