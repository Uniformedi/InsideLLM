"""InsideLLM Humility guardrail adapter — thin wrapper around humility-guardrail.

Adds InsideLLM-specific behavior:
  - Delegates policy evaluation to OPA when available (richer decisions,
    industry overlays, attestation obligations).
  - Falls back to humility's pure-Python evaluator if OPA is down.
  - Fire-and-forget audit logging to the Governance Hub.

The canonical Humility framework lives in the standalone repo:
    https://github.com/uniformedi/humility-guardrail

SAIVAS framework originally published in "Uniform Gnosis, Volume I" by Dan Medina.
See NOTICE for attribution.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os

from humility.adapters.litellm import HumilityGuardrailCallback as _BaseGuardrail
from humility.rules import Decision, evaluate

logger = logging.getLogger("insidellm.humility_guardrail")


def _last_user_message(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "") or ""
    return ""


def _query_opa_sync(opa_url: str, messages: list[dict], user_info: dict,
                    timeout: int = 5) -> dict | None:
    try:
        import requests
    except ImportError:
        return None

    last_msg = _last_user_message(messages)
    opa_input = {
        "messages": messages,
        "user_id": user_info.get("user_id", ""),
        "user_name": user_info.get("user", ""),
        "user_role": user_info.get("user_role", ""),
        "data_classification": "internal",
        "request_type": "standard",
        "has_human_consensus": False,
        "uncertainty_declared": True,
        "within_validated_domain": True,
        "hipaa_authorized": False,
        "fdcpa_compliant_template": False,
        "sox_authorized": False,
        "ferpa_authorized": False,
        "glba_authorized": False,
        "break_glass": False,
        "message_hash": hashlib.sha256(last_msg.encode()).hexdigest()[:16],
    }

    try:
        resp = requests.post(
            f"{opa_url}/v1/data/insidellm/policy/decision",
            json={"input": opa_input},
            timeout=timeout,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        if isinstance(result, dict):
            return result
    except Exception as exc:
        logger.debug(f"OPA unavailable, using local rules: {exc}")
    return None


def _log_to_hub_sync(hub_url: str, event_type: str, details: dict) -> None:
    try:
        import requests
        requests.post(
            f"{hub_url}/api/v1/obligations/audit-log",
            json={
                "event_type": event_type,
                "severity": details.get("severity", "info"),
                "details": details,
            },
            timeout=2,
        )
    except Exception as exc:
        logger.debug(f"Could not log to governance hub ({event_type}): {exc}")


class HumilityGuardrailCallback(_BaseGuardrail):
    """OPA-delegating Humility guardrail with governance-hub audit logging."""

    def __init__(self) -> None:
        super().__init__(fail_mode=os.environ.get("POLICY_ENGINE_FAIL_MODE", "closed"))
        self.opa_url = os.environ.get("OPA_URL", "http://opa:8181")
        self.opa_enabled = os.environ.get("POLICY_ENGINE_ENABLE", "false").lower() == "true"
        self.hub_url = os.environ.get("GOVERNANCE_HUB_URL", "http://governance-hub:8090")
        self._loop = None
        logger.info(
            f"HumilityGuardrailCallback initialized "
            f"(opa={'enabled' if self.opa_enabled else 'local-only'}, "
            f"fail_mode={self.fail_mode})"
        )

    def evaluate_decision(self, messages: list[dict], user_info: dict) -> Decision:
        if self.opa_enabled:
            try:
                loop = asyncio.get_event_loop()
                future = loop.run_in_executor(
                    None, _query_opa_sync, self.opa_url, messages, user_info
                )
                opa_result = asyncio.run_coroutine_threadsafe(
                    asyncio.wrap_future(future), loop
                ).result(timeout=6)
            except Exception:
                opa_result = None

            if opa_result is not None:
                return Decision(
                    allow=opa_result.get("allow", False),
                    deny_reasons=tuple(opa_result.get("deny_reasons", [])),
                    obligations=tuple(opa_result.get("obligations", [])),
                )

        return evaluate(messages)

    def on_decision(self, decision: Decision, user_info: dict) -> None:
        if decision.allow:
            return
        try:
            loop = asyncio.get_event_loop()
            loop.run_in_executor(
                None, _log_to_hub_sync, self.hub_url, "guardrail_denied",
                {
                    "reasons": list(decision.deny_reasons),
                    "user": user_info.get("user", "unknown"),
                    "source": "humility_guardrail",
                },
            )
        except Exception:
            pass


# Module-level instance for LiteLLM's custom_callback_path loader.
proxy_handler_instance = HumilityGuardrailCallback()
