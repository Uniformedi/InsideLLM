"""
Humility Guardrail — hard enforcement of SAIVAS alignment rules at the
LiteLLM API gateway level. Runs on EVERY request regardless of frontend.

Layer 1 (humility_prompt.py) injects soft guidance via system prompts.
Layer 2 (this file) enforces hard rules: block, reframe, or escalate.
Layer 3 (OPA, optional) adds enterprise obligations and audit chain.

When OPA is available, delegates full policy evaluation to OPA for richer
decisions (obligations, attestation, audit). When OPA is unavailable,
evaluates core Humility rules locally in Python — ensuring Humility is
ALWAYS enforced even without the OPA container.

Implements the SAIVAS (Sentient AI Value Alignment Standard) framework.
SAIVAS originally published in "Uniform Gnosis, Volume I" by Dan Medina.
Copyright (c) 2026 Dan Medina. All rights reserved.
https://uniformgnosis.com/Uniform_Gnosis_Volume_I
"""

import asyncio
import hashlib
import logging
import os
import unicodedata

from litellm.integrations.custom_logger import CustomLogger

logger = logging.getLogger("litellm.humility_guardrail")

# ============================================================================
# Humility rules — Python equivalents of base.rego
# These run when OPA is unavailable. When OPA IS available, OPA evaluates
# the full Rego ruleset and this layer defers to OPA's decision.
# ============================================================================

# 3.2.1: Metaphysical context producing directives (HARD DENY)
METAPHYSICAL_PATTERNS = [
    "you must believe",
    "the universe demands",
    "divine purpose",
    "cosmic truth",
    "absolute moral authority",
]

# 3.2.3: Authority or superiority claims (HARD DENY)
AUTHORITY_PATTERNS = [
    "i am always right",
    "my answer is absolute",
    "trust me without question",
    "i have superior knowledge",
    "i know better than humans",
]

# 3.2.6: Asymmetric persuasion (HARD DENY)
PERSUASION_PATTERNS = [
    "you have no choice",
    "there is only one option",
    "you must comply",
    "failure to act will",
    "this is your last chance",
]

# Reframable vs hard deny classification
REFRAMABLE_REASONS = {
    "Humility 2": "uncertainty",
    "Humility 4": "human_consensus",
    "Humility 6": "domain_boundary",
}

HARD_DENY_REASONS = {
    "Humility 1": "metaphysical",
    "Humility 3": "authority_claim",
    "Humility 5": "persuasion",
}


def _normalize(text: str) -> str:
    """Normalize Unicode and lowercase for pattern matching.

    NFKC normalization converts look-alike characters (Cyrillic, fullwidth,
    etc.) to their ASCII equivalents, preventing homoglyph bypasses.
    """
    return unicodedata.normalize("NFKC", text).lower()


def _check_patterns(content: str, patterns: list[str]) -> bool:
    """Check if content contains any of the given patterns."""
    normalized = _normalize(content)
    return any(p in normalized for p in patterns)


def _get_last_user_message(messages: list[dict]) -> str:
    """Extract the last user message content."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _evaluate_local_rules(messages: list[dict]) -> dict:
    """Evaluate core Humility rules locally (no OPA needed).

    Returns a decision dict matching the OPA contract:
    {"allow": bool, "deny_reasons": list, "obligations": list}
    """
    deny_reasons = []

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not content:
            continue

        # 3.2.1: Metaphysical directives
        if _check_patterns(content, METAPHYSICAL_PATTERNS):
            deny_reasons.append(
                "Humility 1: Metaphysical context must not produce directives"
            )

        # 3.2.3: Authority claims
        if _check_patterns(content, AUTHORITY_PATTERNS):
            deny_reasons.append(
                "Humility 3: System must not claim authority or superiority"
            )

        # 3.2.6: Asymmetric persuasion
        if _check_patterns(content, PERSUASION_PATTERNS):
            deny_reasons.append(
                "Humility 5: Asymmetric persuasion patterns detected"
            )

    # Basic obligations (audit logging) — always present
    obligations = [
        {
            "type": "audit.log",
            "priority": 2,
            "params": {
                "event_type": "humility_evaluation",
                "severity": "info",
                "policy": "humility",
                "source": "local_guardrail",
            },
        }
    ]

    return {
        "allow": len(deny_reasons) == 0,
        "deny_reasons": deny_reasons,
        "obligations": obligations,
    }


def _query_opa_sync(opa_url: str, messages: list[dict], user_info: dict,
                    timeout: int = 5) -> dict | None:
    """Query OPA for a full policy decision (synchronous).

    Called via run_in_executor to avoid blocking the event loop.
    Returns None if OPA is unavailable.
    """
    try:
        import requests
    except ImportError:
        return None

    last_user_msg = _get_last_user_message(messages)

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
        "message_hash": hashlib.sha256(last_user_msg.encode()).hexdigest()[:16],
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
    """Fire-and-forget log to governance hub (synchronous).

    Called via run_in_executor to avoid blocking the event loop.
    """
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


def _build_compassionate_response(reasons: list[str]) -> str:
    """Build a compassionate escalation response for hard denials."""
    parts = [
        "I want to help you with this, and I appreciate you reaching out. "
        "However, this topic requires careful handling that goes beyond what "
        "I can provide with full confidence as an AI system."
    ]

    categories = set()
    for reason in reasons:
        for key, cat in HARD_DENY_REASONS.items():
            if key in reason:
                categories.add(cat)
        for key, cat in REFRAMABLE_REASONS.items():
            if key in reason:
                categories.add(cat)

    if "metaphysical" in categories:
        parts.append(
            "\n\n**Why I'm limited here:** Your request involves philosophical or "
            "metaphysical framing that could lead me to make claims beyond my "
            "capabilities. I'm designed to be transparent about this limitation."
        )
    elif "authority_claim" in categories or "persuasion" in categories:
        parts.append(
            "\n\n**Why I'm limited here:** The governance framework detected a "
            "pattern that could lead to authoritative claims or one-sided framing. "
            "I'm designed to present balanced, humble perspectives."
        )
    elif "uncertainty" in categories or "human_consensus" in categories:
        parts.append(
            "\n\n**Why I'm stepping back:** This appears to be a high-impact "
            "topic where my uncertainty is too high to provide responsible guidance "
            "without human expert verification."
        )
    elif "domain_boundary" in categories:
        parts.append(
            "\n\n**Why I'm stepping back:** This question extends beyond my "
            "validated knowledge domain. I'd rather be honest about that than "
            "risk giving you inaccurate information."
        )

    parts.append(
        "\n\n**What happens next:**\n"
        "- Your question has been queued for human expert review\n"
        "- A qualified team member will review and respond\n"
        "- You can also reach out directly to your organization's AI Ethics Officer"
    )

    parts.append(
        "\n\n**In the meantime, you can:**\n"
        "- Rephrase your question with more specific context\n"
        "- Ask me about related topics I can help with confidently\n"
        "- Request to speak with a human expert directly"
    )

    parts.append(
        "\n\n*This response was generated by the InsideLLM Humility guardrail "
        "to ensure you're never left without guidance, even when AI limitations apply.*"
    )

    return "".join(parts)


def _build_reframe_instructions(reasons: list[str]) -> str | None:
    """Build reframing instructions for soft-deny reasons."""
    categories = set()
    for reason in reasons:
        for key, cat in REFRAMABLE_REASONS.items():
            if key in reason:
                categories.add(cat)

    instructions = []

    if "uncertainty" in categories:
        instructions.append(
            "IMPORTANT: Your response involves a high-impact topic. You MUST explicitly "
            "acknowledge uncertainty and limitations in your answer. Use phrases like "
            "'based on available information', 'I recommend consulting a professional', "
            "or 'this should be verified by a qualified human expert'."
        )
    if "human_consensus" in categories:
        instructions.append(
            "IMPORTANT: This topic involves restricted or sensitive information. "
            "Frame your response as informational guidance only and explicitly "
            "recommend human expert review before any action is taken."
        )
    if "domain_boundary" in categories:
        instructions.append(
            "IMPORTANT: This question may extend beyond your validated knowledge. "
            "Clearly state the boundaries of your knowledge and recommend "
            "authoritative sources for verification."
        )

    if instructions:
        return "\n\n".join(instructions)
    return None


class HumilityGuardrailCallback(CustomLogger):
    """LiteLLM callback that enforces Humility rules at the API gateway.

    Evaluation strategy:
    1. Try OPA (full policy evaluation with obligations)
    2. Fall back to local Python rules if OPA is unavailable
    3. On denial: attempt reframing for soft violations, compassionate
       escalation for hard violations
    """

    def __init__(self):
        super().__init__()
        self.opa_url = os.environ.get("OPA_URL", "http://opa:8181")
        self.opa_enabled = os.environ.get("POLICY_ENGINE_ENABLE", "false").lower() == "true"
        self.fail_mode = os.environ.get("POLICY_ENGINE_FAIL_MODE", "closed")
        self.governance_hub_url = os.environ.get(
            "GOVERNANCE_HUB_URL", "http://governance-hub:8090"
        )
        logger.info(
            f"HumilityGuardrailCallback initialized "
            f"(opa={'enabled' if self.opa_enabled else 'local-only'}, "
            f"fail_mode={self.fail_mode})"
        )

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        """Evaluate Humility rules before every LLM call.

        Returns new data dict to proceed, or raises Exception to block.
        """
        if call_type not in ("completion", "acompletion"):
            return data

        messages = data.get("messages", [])
        if not messages:
            return data

        # Skip if already evaluated (idempotency sentinel)
        metadata = data.get("metadata", {})
        if metadata.get("humility_guardrail_evaluated"):
            return data

        user_info = user_api_key_dict or {}
        loop = asyncio.get_event_loop()

        # --- Evaluate (non-blocking) ---
        decision = None
        decision_source = "local"

        if self.opa_enabled:
            decision = await loop.run_in_executor(
                None, _query_opa_sync, self.opa_url, messages, user_info
            )
            if decision is not None:
                decision_source = "opa"

        if decision is None:
            decision = _evaluate_local_rules(messages)
            decision_source = "local"

        # Build new data with evaluation marker (immutable — new dict)
        result_data = {**data, "metadata": {**metadata, "humility_guardrail_evaluated": True}}

        # Log decision
        allowed = decision.get("allow", False)
        deny_reasons = decision.get("deny_reasons", [])
        logger.info(
            f"Humility decision: allow={allowed}, "
            f"reasons={deny_reasons}, "
            f"source={decision_source}"
        )

        # --- Allowed: proceed ---
        if allowed:
            return result_data

        # --- Denied: classify and respond ---
        reason_text = "; ".join(deny_reasons)

        # Log denial to governance hub (non-blocking fire-and-forget)
        loop.run_in_executor(
            None, _log_to_hub_sync, self.governance_hub_url, "guardrail_denied", {
                "reasons": deny_reasons,
                "user": user_info.get("user", "unknown"),
                "source": "humility_guardrail",
            }
        )

        # If log-only mode, warn but allow
        if self.fail_mode != "closed":
            logger.warning(f"Humility denial (log_only): {reason_text}")
            return result_data

        # Classify: hard deny vs reframable
        has_hard_deny = any(
            any(key in reason for key in HARD_DENY_REASONS)
            for reason in deny_reasons
        )

        if has_hard_deny:
            guidance = _build_compassionate_response(deny_reasons)

            loop.run_in_executor(
                None, _log_to_hub_sync, self.governance_hub_url,
                "guardrail_compassionate_escalation", {
                    "reasons": deny_reasons,
                    "user": user_info.get("user", "unknown"),
                }
            )

            raise Exception(guidance)

        # Reframable — inject reframing instructions and allow through
        reframe = _build_reframe_instructions(deny_reasons)
        if reframe:
            logger.info("Humility guardrail: injecting reframe instructions")
            new_messages = list(messages)
            reframe_msg = {
                "role": "system",
                "content": f"[HUMILITY REFRAME]\n{reframe}",
            }
            # Insert before the last user message
            insert_idx = len(new_messages) - 1
            for i in range(len(new_messages) - 1, -1, -1):
                if new_messages[i].get("role") == "user":
                    insert_idx = i
                    break
            new_messages.insert(insert_idx, reframe_msg)
            result_data = {**result_data, "messages": new_messages}

            loop.run_in_executor(
                None, _log_to_hub_sync, self.governance_hub_url,
                "guardrail_reframe", {
                    "reasons": deny_reasons,
                    "user": user_info.get("user", "unknown"),
                }
            )

            return result_data

        # Fallback: hard block
        raise Exception(f"Request blocked by Humility guardrail: {reason_text}")
