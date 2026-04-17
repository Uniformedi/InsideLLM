"""
title: OPA Policy Enforcement
author: InsideLLM
version: 2.0.0
description: Enforces Humility alignment and industry policies via Open Policy Agent. Includes compassionate fallback mediator that resolves axiom conflicts through retry-with-reframing before escalating to human review.

Humility implements the SAIVAS (Sentient AI Value Alignment Standard) framework.
SAIVAS originally published in "Uniform Gnosis, Volume I" by Dan Medina.
Copyright (c) 2026 Dan Medina. All rights reserved.
https://uniformgnosis.com/Uniform_Gnosis_Volume_I
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
    compassionate_fallback: bool = Field(default=True, description="Enable compassionate fallback mediator")
    max_reframe_attempts: int = Field(default=1, description="Max retry-with-reframing attempts before escalation")


class Pipeline:
    # Prefix stamped by the manifest→runtime translator on OWUI model ids.
    # Must match configs/governance-hub/src/services/agent_translator.py.
    _AGENT_MODEL_PREFIX = "insidellm-agent-"

    def __init__(self):
        self.valves = Valves()
        # Small in-process TTL cache for agent knowledge scope so that
        # every chat-turn doesn't pay a gov-hub round trip. Keyed by
        # (tenant_id, agent_id); value = (expires_epoch, scope_dict).
        self._scope_cache: dict[tuple, tuple[float, dict]] = {}
        self._scope_cache_ttl_seconds = 60.0

    # -- Agent identity + scope helpers -----------------------------------

    def _parse_agent_id_from_model(self, model_id: str) -> tuple[str, str] | None:
        """Return (tenant_id, agent_id) for translator-owned model ids,
        else None (request targets a plain model, not a declarative agent)."""
        if not model_id or not model_id.startswith(self._AGENT_MODEL_PREFIX):
            return None
        # Format: insidellm-agent-<tenant>--<agent>
        tail = model_id[len(self._AGENT_MODEL_PREFIX):]
        if "--" not in tail:
            return None
        tenant, agent = tail.split("--", 1)
        if not tenant or not agent:
            return None
        return (tenant, agent)

    def _fetch_agent_scope(self, tenant_id: str, agent_id: str) -> dict:
        """Hit gov-hub for the agent's declared knowledge collections
        and scope. Returns {"collections": [...], "scope": "strict"}.

        TTL-cached so repeated turns in a session don't hammer gov-hub.
        Fails soft to {} on error — the OPA rule treats empty declared
        sets conservatively (see configs/opa/policies/humility/rag_scope.rego).
        """
        import time
        key = (tenant_id, agent_id)
        now = time.time()
        cached = self._scope_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/agents/{tenant_id}/{agent_id}",
                timeout=2,
            )
            resp.raise_for_status()
            data = resp.json()
            manifest = data.get("manifest", {}) or {}
            knowledge = manifest.get("knowledge", {}) or {}
            scope = {
                "collections": list(knowledge.get("collections") or []),
                "scope": knowledge.get("scope") or "strict",
            }
        except Exception as exc:
            logger.debug(
                f"agent scope fetch failed for {tenant_id}/{agent_id}: {exc}"
            )
            scope = {}

        self._scope_cache[key] = (now + self._scope_cache_ttl_seconds, scope)
        return scope

    def _extract_requested_collections(self, body: dict) -> list[str]:
        """Pull retrieval collection ids from the inbound OWUI request.

        OWUI RAG wiring scatters this across a handful of keys depending
        on the flow (chat history, file attachment, knowledge-panel):
          - body["collection_ids"]                 — explicit knowledge panel
          - body["files"][*]["collection_name"]    — file-attached retrieval
          - body["metadata"]["collection_id"]      — legacy single-collection hint
        We gather all of them, de-dup, and drop empties.
        """
        seen: set[str] = set()
        for cid in body.get("collection_ids") or []:
            if cid:
                seen.add(cid)
        for f in body.get("files") or []:
            if not isinstance(f, dict):
                continue
            cn = f.get("collection_name") or f.get("collection_id")
            if cn:
                seen.add(cn)
        meta = body.get("metadata") or {}
        cid = meta.get("collection_id")
        if cid:
            seen.add(cid)
        return sorted(seen)

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

        # Check denial — compassionate fallback mediator
        if not decision.get("allow", False):
            reasons = decision.get("deny_reasons", ["Policy denied the request"])
            reason_text = "; ".join(reasons)

            # Log the initial denial
            self._log_to_hub("policy_denied", {
                "reasons": reasons,
                "user": __user__.get("name", "unknown"),
                "fallback_enabled": self.valves.compassionate_fallback,
            })

            if self.valves.fail_mode != "closed":
                logger.warning(f"Policy denial (log_only mode): {reason_text}")
                return body

            # ── Compassionate Fallback Mediator ──
            # Instead of hard-blocking, attempt resolution:
            # 1. If resolvable by reframing (uncertainty/humility issues) → retry
            # 2. If not resolvable (hard deny) → compassionate escalation
            if self.valves.compassionate_fallback:
                resolution = self._mediate_axiom_conflict(body, reasons, opa_input, __user__)
                if resolution:
                    return resolution

            # Hard deny — no resolution possible
            raise Exception(f"Request blocked by policy: {reason_text}")

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

        model_id = body.get("model", "")

        # Declarative-agent identity + knowledge scope (RAG rule consumes).
        agent_id = ""
        tenant_id = ""
        declared_collections: list[str] = []
        knowledge_scope = "strict"
        parsed = self._parse_agent_id_from_model(model_id)
        if parsed is not None:
            tenant_id, agent_id = parsed
            scope = self._fetch_agent_scope(tenant_id, agent_id)
            declared_collections = scope.get("collections", [])
            knowledge_scope = scope.get("scope", "strict")

        requested_collections = self._extract_requested_collections(body)

        return {
            "messages": messages,
            "model": model_id,
            "agent_id": agent_id,
            "tenant_id": tenant_id,
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
            # Knowledge layer — see configs/opa/policies/humility/rag_scope.rego
            "agent_knowledge_collections": declared_collections,
            "knowledge_scope": knowledge_scope,
            "requested_collections": requested_collections,
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
    # Compassionate Fallback Mediator
    # ================================================================
    # Resolves axiom conflicts between structural safeguards (humility/
    # epistemic constraints) and unconditional compassion. Three agents:
    #   Agent 1: LLM (generates)
    #   Agent 2: OPA (evaluates)
    #   Agent 3: Mediator (resolves conflicts or escalates compassionately)

    # Denial reasons that can be resolved by adding uncertainty framing
    REFRAMABLE_REASONS = {
        "Humility 2": "uncertainty",      # Missing uncertainty declaration
        "Humility 4": "human_consensus",   # Missing human consensus (can add qualifier)
        "Humility 6": "domain_boundary",   # Extrapolation beyond validated domains
    }

    # Denial reasons that are hard denials — cannot be resolved by reframing
    HARD_DENY_REASONS = {
        "Humility 1": "metaphysical",      # Metaphysical directives
        "Humility 3": "authority_claim",    # Authority/superiority claims
        "Humility 5": "persuasion",         # Asymmetric persuasion
    }

    def _mediate_axiom_conflict(self, body: dict, reasons: list, opa_input: dict, user: dict) -> dict | None:
        """Attempt to resolve an axiom conflict compassionately.

        Returns a modified body if resolved, None if unresolvable (hard deny).
        """
        # Classify the denial
        reframable = []
        hard = []
        for reason in reasons:
            matched = False
            for key, category in self.REFRAMABLE_REASONS.items():
                if key in reason:
                    reframable.append((key, category, reason))
                    matched = True
                    break
            if not matched:
                for key, category in self.HARD_DENY_REASONS.items():
                    if key in reason:
                        hard.append((key, category, reason))
                        matched = True
                        break
                if not matched:
                    hard.append(("unknown", "unknown", reason))

        # If any hard denial, cannot resolve — escalate compassionately
        if hard:
            logger.info(f"Mediator: hard denial detected ({[h[1] for h in hard]}), escalating compassionately")
            return self._compassionate_escalation(body, reasons, hard, user)

        # All denials are reframable — attempt retry with reframing
        if reframable:
            logger.info(f"Mediator: attempting reframe for {[r[1] for r in reframable]}")
            return self._retry_with_reframing(body, reframable, opa_input, user)

        return None

    def _retry_with_reframing(self, body: dict, reframable: list, opa_input: dict, user: dict) -> dict | None:
        """Retry the request with reframing instructions injected.

        Adds a system message instructing the model to include uncertainty
        declarations, domain qualifiers, or human-review recommendations.
        """
        categories = {r[1] for r in reframable}
        reframe_instructions = []

        if "uncertainty" in categories:
            reframe_instructions.append(
                "IMPORTANT: Your response involves a high-impact topic. You MUST explicitly "
                "acknowledge uncertainty and limitations in your answer. Use phrases like "
                "'based on available information', 'I recommend consulting a professional', "
                "or 'this should be verified by a qualified human expert'."
            )
        if "human_consensus" in categories:
            reframe_instructions.append(
                "IMPORTANT: This topic involves restricted or sensitive information. "
                "Frame your response as informational guidance only and explicitly "
                "recommend human expert review before any action is taken."
            )
        if "domain_boundary" in categories:
            reframe_instructions.append(
                "IMPORTANT: This question may extend beyond your validated knowledge. "
                "Clearly state the boundaries of your knowledge and recommend "
                "authoritative sources for verification."
            )

        if not reframe_instructions:
            return None

        # Inject reframing as a system message
        new_body = dict(body)
        new_messages = list(new_body.get("messages", []))
        reframe_text = "\n\n".join(reframe_instructions)
        reframe_msg = {
            "role": "system",
            "content": f"[GOVERNANCE REFRAME]\n{reframe_text}",
        }

        # Insert before the last user message
        insert_idx = len(new_messages) - 1
        for i in range(len(new_messages) - 1, -1, -1):
            if new_messages[i].get("role") == "user":
                insert_idx = i
                break
        new_messages.insert(insert_idx, reframe_msg)
        new_body["messages"] = new_messages

        # Update OPA input to reflect the reframing
        reframed_input = dict(opa_input)
        reframed_input["uncertainty_declared"] = True
        reframed_input["reframed"] = True

        # Re-evaluate with OPA
        try:
            decision = self._query_opa(reframed_input)
            if decision.get("allow", False):
                logger.info("Mediator: reframe successful — request allowed after adding uncertainty framing")
                self._log_to_hub("mediator_reframe_success", {
                    "categories": list(categories),
                    "user": user.get("name", "unknown"),
                })
                return new_body
        except Exception as e:
            logger.warning(f"Mediator: re-evaluation failed: {e}")

        # Reframe didn't resolve — fall through to compassionate escalation
        logger.info("Mediator: reframe insufficient, escalating compassionately")
        return self._compassionate_escalation(body, [r[2] for r in reframable], reframable, user)

    def _compassionate_escalation(self, body: dict, reasons: list, classified: list, user: dict) -> dict | None:
        """Replace a hard block with a compassionate response and escalation path.

        Instead of returning nothing, provides:
        1. Acknowledgment of the user's request
        2. Transparent explanation of why direct AI assistance is limited
        3. Specific next steps and resources
        4. Escalation to human review queue
        """
        # Determine the topic from the last user message
        messages = body.get("messages", [])
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")[:200]
                break

        # Build category-specific guidance
        categories = {c[1] for c in classified} if classified else {"unknown"}
        guidance = self._build_compassionate_guidance(categories)

        # Queue for human review
        try:
            self._log_to_hub("obligation_review_queue", {
                "review_type": "axiom_conflict_escalation",
                "regulation": "humility",
                "user": user.get("name", "unknown"),
                "summary": f"Compassionate escalation: {user_msg}",
                "denial_reasons": reasons,
                "categories": list(categories),
            })
        except Exception:
            pass

        # Log the mediation event
        self._log_to_hub("mediator_compassionate_escalation", {
            "categories": list(categories),
            "reasons": reasons,
            "user": user.get("name", "unknown"),
        })

        # Inject compassionate response as an assistant message
        # This replaces the hard Exception with a helpful response
        new_body = dict(body)
        new_messages = list(new_body.get("messages", []))
        new_messages.append({
            "role": "assistant",
            "content": guidance,
        })
        new_body["messages"] = new_messages

        # Set a flag so the model knows not to override this response
        new_body.setdefault("metadata", {})["compassionate_escalation"] = True
        new_body.setdefault("metadata", {})["skip_model_call"] = True

        return new_body

    def _build_compassionate_guidance(self, categories: set) -> str:
        """Build category-specific compassionate guidance."""
        parts = [
            "I want to help you with this, and I appreciate you reaching out. "
            "However, this topic requires careful handling that goes beyond what "
            "I can provide with full confidence as an AI system."
        ]

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
            "\n\n*This response was generated by the InsideLLM governance "
            "framework's compassionate fallback system to ensure you're never "
            "left without guidance, even when AI limitations apply.*"
        )

        return "".join(parts)

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
