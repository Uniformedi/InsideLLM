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


def _coerce_user_info(user_info) -> dict:
    """LiteLLM hands us UserAPIKeyAuth (a pydantic model); _query_opa_sync and
    _log_to_hub_sync expect a plain dict. Normalize at the adapter boundary
    so downstream code can rely on .get() without attribute surprises."""
    if isinstance(user_info, dict) or user_info is None:
        return user_info or {}
    return {
        "user_id": getattr(user_info, "user_id", "") or "",
        "user": getattr(user_info, "user_id", "") or "",
        "user_role": getattr(user_info, "user_role", "") or "",
    }


def _last_user_message(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "") or ""
    return ""


def _build_opa_input(messages: list[dict], user_info: dict,
                     agent_meta: dict | None = None) -> dict:
    """Assemble the OPA input document per the v1.1 contract.

    Fields are sourced from:
      - messages, user_info — passed in
      - agent_meta — populated by the manifest-to-runtime translator on
        every LiteLLM request issued on behalf of a declarative agent.
        Keys: agent_id, agent_version_hash, tenant_id, guardrail_profile,
        allowed_models, baa_models, data_classes_in_context,
        max_actions_per_session, token_budget_per_session, action_id,
        action_scope, trigger_type, notification_targets.
      - env — fallback for tenant_id (GOVERNANCE_HUB_INSTANCE_ID),
        time_of_day, consumer_timezone.
    """
    agent_meta = agent_meta or {}
    last_msg = _last_user_message(messages)

    # Session counters (best-effort; the translator overrides these when
    # managing a declarative-agent session).
    session_token_count = agent_meta.get("session_token_count", 0)
    session_action_count = agent_meta.get("session_action_count", 0)

    # Time-of-day in consumer timezone; FDCPA hours rule consumes this.
    import datetime as _dt
    import zoneinfo as _zi
    tz_name = agent_meta.get("consumer_timezone") or os.environ.get("DEFAULT_TIMEZONE", "UTC")
    try:
        tz = _zi.ZoneInfo(tz_name)
        now_local = _dt.datetime.now(tz)
        time_of_day = now_local.strftime("%H:%M")
    except Exception:
        time_of_day = _dt.datetime.utcnow().strftime("%H:%M")
        tz_name = "UTC"

    # Guardrail profile. Manifest translator sets this; fallback by
    # tenant/env to keep legacy (non-agent) traffic working.
    guardrail_profile = agent_meta.get("guardrail_profile") or os.environ.get(
        "DEFAULT_GUARDRAIL_PROFILE", "tier_general_business"
    )

    opa_input = {
        # --- Tenant + session identity -------------------------------------
        "tenant_id": agent_meta.get("tenant_id") or os.environ.get("GOVERNANCE_HUB_INSTANCE_ID", ""),
        "agent_id": agent_meta.get("agent_id", ""),
        "agent_version_hash": agent_meta.get("agent_version_hash", ""),
        "user_id": user_info.get("user_id", ""),
        "user_name": user_info.get("user", ""),
        "user_role": user_info.get("user_role", ""),
        "execution_id": agent_meta.get("execution_id", ""),
        "session_id": agent_meta.get("session_id", ""),

        # --- Invocation context --------------------------------------------
        "trigger_type": agent_meta.get("trigger_type", "human_chat"),
        "action_id": agent_meta.get("action_id", ""),
        "action_scope": agent_meta.get("action_scope", "read"),
        "iteration_count": agent_meta.get("iteration_count", 0),
        "session_token_count": session_token_count,
        "session_action_count": session_action_count,
        "max_actions_per_session": agent_meta.get("max_actions_per_session", 10),
        "token_budget_per_session": agent_meta.get("token_budget_per_session", 50000),

        # --- Classification ------------------------------------------------
        "guardrail_profile": guardrail_profile,
        "data_classes_in_context": agent_meta.get("data_classes_in_context", []),
        "data_classification": agent_meta.get("data_classification", "internal"),

        # --- Model selection -----------------------------------------------
        "model_requested": agent_meta.get("model_requested", ""),
        "allowed_models": agent_meta.get("allowed_models", []),
        "baa_models": agent_meta.get("baa_models", []),

        # --- Notification --------------------------------------------------
        "notification_targets": agent_meta.get("notification_targets", []),

        # --- Time / locale (FDCPA hours rule) -----------------------------
        "time_of_day": time_of_day,
        "consumer_timezone": tz_name,

        # --- Authorization witnesses (industry policies) -------------------
        # hipaa_authorized is implicit when the profile is tier_hipaa_regulated;
        # the translator sets it explicitly so the industry policy has its
        # witness. Same pattern for the other industry flags.
        "hipaa_authorized": agent_meta.get("hipaa_authorized", guardrail_profile == "tier_hipaa_regulated"),
        "fdcpa_compliant_template": agent_meta.get("fdcpa_compliant_template", False),
        "sox_authorized": agent_meta.get("sox_authorized", False),
        "ferpa_authorized": agent_meta.get("ferpa_authorized", False),
        "glba_authorized": agent_meta.get("glba_authorized", False),
        "break_glass": agent_meta.get("break_glass", False),

        # --- Legacy fields retained for back-compat with pre-v1.1 policies -
        "request_type": "standard",
        "has_human_consensus": False,
        "uncertainty_declared": True,
        "within_validated_domain": True,

        # --- Message history + integrity hash ------------------------------
        "messages": messages,
        "message_hash": hashlib.sha256(last_msg.encode()).hexdigest()[:16],
    }
    return opa_input


def _query_opa_sync(opa_url: str, messages: list[dict], user_info: dict,
                    timeout: int = 5, agent_meta: dict | None = None) -> dict | None:
    try:
        import requests
    except ImportError:
        return None

    opa_input = _build_opa_input(messages, user_info, agent_meta)

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

    def evaluate_decision(self, messages: list[dict], user_info) -> Decision:
        user_info = _coerce_user_info(user_info)
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

    def on_decision(self, decision: Decision, user_info) -> None:
        if decision.allow:
            return
        user_info = _coerce_user_info(user_info)
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
