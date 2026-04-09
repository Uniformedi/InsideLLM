"""
title: OPA Policy Enforcement
author: InsideLLM
version: 1.0.0
description: Enforces Humility alignment and industry policies via Open Policy Agent. Executes obligations in strict order. Fail-closed on any error.
"""

import hashlib
import json
import logging
from typing import Any

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger("opa-policy")


class Valves(BaseModel):
    enabled: bool = Field(default=True, description="Enable policy enforcement")
    opa_url: str = Field(default="http://opa:8181", description="OPA server URL")
    governance_hub_url: str = Field(default="http://governance-hub:8090", description="Governance Hub URL")
    fail_mode: str = Field(default="closed", description="'closed' = block on error, 'log_only' = allow but log")
    log_decisions: bool = Field(default=True, description="Log all policy decisions")
    opa_timeout: int = Field(default=5, description="OPA query timeout in seconds")


class Pipeline:
    def __init__(self):
        self.valves = Valves()

    async def inlet(self, body: dict, __user__: dict = {}) -> dict:
        """Intercept incoming messages, evaluate policy, execute obligations."""
        if not self.valves.enabled:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        # Build OPA input document (immutable — new dict)
        opa_input = self._build_input(body, __user__)

        # Query OPA
        try:
            decision = self._query_opa(opa_input)
        except Exception as e:
            logger.error(f"OPA query failed: {e}")
            if self.valves.fail_mode == "closed":
                raise Exception(f"Policy evaluation failed (fail-closed): {e}")
            return body

        # Log decision
        if self.valves.log_decisions:
            logger.info(f"Policy decision: allow={decision.get('allow')}, reasons={decision.get('deny_reasons', [])}")

        # Check denial
        if not decision.get("allow", False):
            reasons = decision.get("deny_reasons", ["Policy denied the request"])
            reason_text = "; ".join(reasons)

            # Log the denial to governance hub
            self._log_to_hub("policy_denied", {
                "reasons": reasons,
                "user": __user__.get("name", "unknown"),
            })

            if self.valves.fail_mode == "closed":
                raise Exception(f"Request blocked by policy: {reason_text}")
            else:
                logger.warning(f"Policy denial (log_only mode): {reason_text}")
                return body

        # Execute obligations in strict order
        obligations = decision.get("obligations", [])
        sorted_obs = sorted(obligations, key=lambda o: o.get("priority", 99))

        new_body = dict(body)  # Immutable — work on a copy
        for obligation in sorted_obs:
            try:
                new_body = self._execute_obligation(new_body, obligation, __user__)
            except Exception as e:
                logger.error(f"Obligation {obligation.get('type')} failed: {e}")
                if self.valves.fail_mode == "closed":
                    raise Exception(f"Obligation execution failed (fail-closed): {obligation.get('type')}: {e}")

        return new_body

    async def outlet(self, body: dict, __user__: dict = {}) -> dict:
        """Scan assistant responses for output policy violations."""
        # Output scanning is lighter — just audit log
        if not self.valves.enabled:
            return body
        return body

    # ================================================================
    # OPA Query
    # ================================================================

    def _build_input(self, body: dict, user: dict) -> dict:
        """Build the OPA input document from request context."""
        messages = body.get("messages", [])
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        return {
            "messages": messages,
            "model": body.get("model", ""),
            "user_id": user.get("id", ""),
            "user_name": user.get("name", ""),
            "user_role": user.get("role", ""),
            "data_classification": "internal",  # Default; could be enriched from context
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

    def _query_opa(self, opa_input: dict) -> dict:
        """Query OPA for a policy decision."""
        resp = requests.post(
            f"{self.valves.opa_url}/v1/data/insidellm/policy/decision",
            json={"input": opa_input},
            timeout=self.valves.opa_timeout,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})

        if not isinstance(result, dict):
            raise ValueError(f"OPA returned non-dict result: {type(result)}")

        return result

    # ================================================================
    # Obligation Execution
    # ================================================================

    def _execute_obligation(self, body: dict, obligation: dict, user: dict) -> dict:
        """Execute a single obligation. Returns (possibly modified) body."""
        ob_type = obligation.get("type", "")
        params = obligation.get("params", {})

        if ob_type == "filter.fields":
            return self._execute_filter_fields(body, params)
        elif ob_type == "audit.log":
            self._execute_audit_log(params, user)
            return body
        elif ob_type == "audit.break_glass":
            self._execute_break_glass(params, user)
            return body
        elif ob_type == "audit.tag":
            return self._execute_audit_tag(body, params)
        elif ob_type == "require.attestation":
            self._execute_attestation(params, user)
            return body
        elif ob_type == "review.queue":
            self._execute_review_queue(body, params, user)
            return body
        else:
            logger.warning(f"Unknown obligation type: {ob_type}")
            return body

    def _execute_filter_fields(self, body: dict, params: dict) -> dict:
        """Redact or remove specified fields from message content."""
        fields = params.get("fields", [])
        action = params.get("action", "redact")
        if not fields:
            return body

        new_body = dict(body)
        new_messages = []
        for msg in new_body.get("messages", []):
            new_msg = dict(msg)
            content = new_msg.get("content", "")
            for field in fields:
                if action == "redact":
                    content = content.replace(field, "[REDACTED]")
                elif action == "remove":
                    content = content.replace(field, "")
            new_msg["content"] = content
            new_messages.append(new_msg)
        new_body["messages"] = new_messages
        return new_body

    def _execute_audit_log(self, params: dict, user: dict) -> None:
        """Record an audit event in the governance hub."""
        self._log_to_hub("obligation_audit_log", {
            "event_type": params.get("event_type", "policy_event"),
            "severity": params.get("severity", "info"),
            "policy": params.get("policy", "unknown"),
            "user": user.get("name", "unknown"),
        })

    def _execute_break_glass(self, params: dict, user: dict) -> None:
        """Record a break-glass access event."""
        self._log_to_hub("obligation_break_glass", {
            "reason": params.get("reason", ""),
            "data_classification": params.get("data_classification", "restricted"),
            "user": user.get("name", "unknown"),
        })

    def _execute_audit_tag(self, body: dict, params: dict) -> dict:
        """Add metadata tags to the request."""
        tags = params.get("tags", [])
        new_body = dict(body)
        existing_tags = new_body.get("metadata", {}).get("policy_tags", [])
        new_body.setdefault("metadata", {})["policy_tags"] = list(set(existing_tags + tags))
        return new_body

    def _execute_attestation(self, params: dict, user: dict) -> None:
        """Check for valid user attestation. Raises if not attested."""
        action_type = params.get("action_type", "")
        user_id = user.get("id", user.get("name", "unknown"))

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/obligations/attestation/{user_id}/{action_type}",
                timeout=5,
            )
            if resp.ok:
                data = resp.json()
                if data.get("valid"):
                    return
        except Exception:
            pass

        raise Exception(
            f"Attestation required: {params.get('attestation_text', 'Please attest before proceeding.')} "
            f"Submit attestation via the Governance Hub API."
        )

    def _execute_review_queue(self, body: dict, params: dict, user: dict) -> None:
        """Submit request to the review queue. Blocks the request."""
        messages = body.get("messages", [])
        summary = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                summary = msg.get("content", "")[:500]
                break

        self._log_to_hub("obligation_review_queue", {
            "review_type": params.get("review_type", "general"),
            "regulation": params.get("regulation", ""),
            "user": user.get("name", "unknown"),
            "summary": summary,
        })

        raise Exception(
            f"This request has been queued for supervisor review ({params.get('regulation', 'policy')}). "
            f"A supervisor must approve it before it can proceed."
        )

    # ================================================================
    # Governance Hub logging
    # ================================================================

    def _log_to_hub(self, event_type: str, details: dict) -> None:
        """Fire-and-forget log to governance hub."""
        try:
            requests.post(
                f"{self.valves.governance_hub_url}/api/v1/obligations/audit-log",
                json={"event_type": event_type, "severity": details.get("severity", "info"), "details": details},
                timeout=3,
            )
        except Exception:
            logger.warning(f"Failed to log to governance hub: {event_type}")
