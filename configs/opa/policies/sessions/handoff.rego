# =============================================================================
# Sessions — Handoff Eligibility (InsideLLM canonical session policy)
#
# Decides whether a handoff of a canonical session is permitted. Handoffs are
# the only way a session's owner (user | group | agent | system) changes, so
# this rule is the load-bearing authorization check for all ownership
# transitions.
#
# Inputs expected:
#   input.session.tenant_id             — source tenant id
#   input.session.security_tier         — T0..T7
#   input.session.classification        — general|confidential|regulated
#   input.session.manifest_hash         — sha256 hex, pinned at session start
#   input.source.owner_type             — user|group|agent|system
#   input.source.owner_ref              — the current owner id / reason
#   input.target.type                   — user|group|agent|system
#   input.target.ref                    — target id / reason
#   input.target.tenant_id              — same as source for in-tenant handoff
#   input.target.status                 — online|away|busy|offline (from presence)
#   input.actor.sub                     — Keycloak sub of the requester
#   input.actor.roles                   — list of Keycloak realm roles
#   input.agent.accepts_handoff         — bool (from agent manifest)
#   input.agent.handoff_chain_tags      — list (from agent manifest)
#   input.target.agent.handoff_chain_tags — list (for agent->agent)
#   input.handoff.reason                — free-text, required
#   input.handoff.hop_count             — current chain depth (agent-to-agent)
#
# Emissions:
#   deny_reasons      — non-empty ⇒ request denied
#   obligations       — side effects the enforcement layer must apply
#     • dlp.rescan     — required when user -> agent
#     • audit.log      — always emitted with policy_decision_id reference
# =============================================================================
package insidellm.sessions.handoff

import rego.v1

# ---- Constants ---------------------------------------------------------------

_max_agent_chain_hops := 3

_reviewer_required_tiers := {"T4", "T5", "T6"}

# Tiers where synchronous handoff requires the target to be reachable.
_synchronous_presence_required_tiers := {"T4", "T5", "T6"}

# ---- Invariants (applied to ALL handoffs) -----------------------------------

# Separation of duties: an actor cannot hand off a session they don't own
# (unless they hold `tenant-admin` or `compliance`, which are explicit exceptions).
deny_reasons contains reason if {
    input.source.owner_type == "user"
    input.source.owner_ref != input.actor.sub
    not _actor_has_any(["tenant-admin", "compliance"])
    reason := sprintf(
        "handoff rejected: actor '%s' is not the current owner and lacks override role",
        [input.actor.sub],
    )
}

# Reason is mandatory and must be non-trivial.
deny_reasons contains "handoff rejected: reason required" if {
    not input.handoff.reason
}
deny_reasons contains "handoff rejected: reason too short" if {
    input.handoff.reason
    count(input.handoff.reason) < 8
}

# Cross-tenant is forbidden on this endpoint. Use the fork endpoint instead.
deny_reasons contains reason if {
    input.target.tenant_id
    input.target.tenant_id != input.session.tenant_id
    reason := "handoff rejected: cross-tenant transfer requires /fork-cross-tenant"
}

# System ownership can only be ENTERED from agent or scheduler, never from user.
deny_reasons contains reason if {
    input.target.type == "system"
    input.source.owner_type == "user"
    reason := "handoff rejected: user cannot transition a session to system ownership"
}

# Agent-to-agent chain depth cap.
deny_reasons contains reason if {
    input.source.owner_type == "agent"
    input.target.type == "agent"
    input.handoff.hop_count >= _max_agent_chain_hops
    reason := sprintf(
        "handoff rejected: agent chain depth %d reached max %d",
        [input.handoff.hop_count, _max_agent_chain_hops],
    )
}

# Agents are never eligible approvers (prompt-injection defense).
deny_reasons contains reason if {
    input.target.type == "user"
    input.source.owner_type == "agent"
    not input.target.ref
    reason := "handoff rejected: agent must name an explicit target user or group"
}

# ---- Type-specific eligibility ----------------------------------------------

# user -> user
deny_reasons contains reason if {
    input.source.owner_type == "user"
    input.target.type == "user"
    not _same_tenant(input.target)
    reason := "handoff rejected: target user is not in the session tenant"
}

# For regulated tiers, the receiving user must hold the reviewer role.
deny_reasons contains reason if {
    input.source.owner_type == "user"
    input.target.type == "user"
    input.session.security_tier in _reviewer_required_tiers
    not _target_has_role("reviewer")
    reason := sprintf(
        "handoff rejected: tier %s requires target to hold 'reviewer' role",
        [input.session.security_tier],
    )
}

# user/agent -> group: target group must be tenant-scoped.
deny_reasons contains reason if {
    input.target.type == "group"
    not _same_tenant(input.target)
    reason := "handoff rejected: target group is not in the session tenant"
}

# Synchronous high-tier handoffs require reachable target.
deny_reasons contains reason if {
    input.target.type == "user"
    input.session.security_tier in _synchronous_presence_required_tiers
    input.target.status == "offline"
    reason := sprintf(
        "handoff rejected: tier %s requires reachable target (status=offline)",
        [input.session.security_tier],
    )
}

# user -> agent: target agent must declare accepts_handoff.
deny_reasons contains reason if {
    input.source.owner_type == "user"
    input.target.type == "agent"
    not input.agent.accepts_handoff
    reason := "handoff rejected: target agent manifest does not declare accepts_handoff=true"
}

# agent -> agent: both must share a handoff_chain tag.
deny_reasons contains reason if {
    input.source.owner_type == "agent"
    input.target.type == "agent"
    not _shared_chain_tag
    reason := "handoff rejected: agents do not share a handoff_chain tag"
}

# System → * must specify the session's prior owner provenance (reconstitution).
deny_reasons contains reason if {
    input.source.owner_type == "system"
    not input.source.prior_owner_type
    reason := "handoff rejected: system exit requires prior_owner_type for reconstitution"
}

# ---- Obligations ------------------------------------------------------------

# DLP must re-scan the next inbound when a user hands to an agent
# (the content shifts from a human eye to an autonomous policy loop).
obligations contains obligation if {
    input.source.owner_type == "user"
    input.target.type == "agent"
    obligation := {
        "type": "dlp.rescan",
        "priority": 1,
        "params": {
            "scope": "next_inbound_message",
            "session_id": input.session.session_id,
            "trigger": "user_to_agent_handoff",
        },
    }
}

# Always emit an audit obligation — the enforcement layer writes the chain.
obligations contains obligation if {
    count(deny_reasons) == 0
    obligation := {
        "type": "audit.log",
        "priority": 2,
        "params": {
            "event_type": "session.handoff.authorized",
            "severity": "info",
            "policy": "sessions.handoff",
            "session_id": input.session.session_id,
            "source_owner_type": input.source.owner_type,
            "target_type": input.target.type,
            "reason": input.handoff.reason,
        },
    }
}

# ---- Helpers ----------------------------------------------------------------

_same_tenant(target) if {
    not target.tenant_id
}
_same_tenant(target) if {
    target.tenant_id == input.session.tenant_id
}

_actor_has_any(roles) if {
    some r in roles
    r in input.actor.roles
}

_target_has_role(r) if {
    r in input.target.roles
}

_shared_chain_tag if {
    some t in input.agent.handoff_chain_tags
    t in input.target.agent.handoff_chain_tags
}
