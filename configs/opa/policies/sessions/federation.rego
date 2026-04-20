# =============================================================================
# Sessions — Cross-Tenant Federation (fork)
#
# Authorizes cross-tenant session forks (e.g. parent-organization review of a
# portfolio-company session). The fork itself carries no transcript — only a
# sanitized summary + manifest hash + content hashes. The source tenant keeps
# its obligations; the target tenant creates a NEW session with
# `forked_from_session_id` and (typically) an elevated security tier.
#
# Composes with `sessions.residency` — cross-region forks must also satisfy
# that rule. This file only decides tenant-level federation eligibility.
#
# Inputs expected:
#   input.source.tenant_id
#   input.source.session_id
#   input.source.security_tier
#   input.source.manifest.federation.allow_parent_review   — bool
#   input.source.manifest.federation.allow_peer_review     — bool
#   input.source.federated_peers[]                         — list of tenant_ids
#   input.actor.sub
#   input.actor.roles
#   input.target.tenant_id
#   input.target.max_accepted_tier                         — T0..T7
#   input.fork.reason                                      — required
# =============================================================================
package insidellm.sessions.federation

import rego.v1

_tier_order := {
    "T0": 0, "T1": 1, "T2": 2, "T3": 3,
    "T4": 4, "T5": 5, "T6": 6, "T7": 7,
}

# ---- Invariants -------------------------------------------------------------

deny_reasons contains "federation denied: fork.reason required" if {
    not input.fork.reason
}

deny_reasons contains reason if {
    input.source.tenant_id == input.target.tenant_id
    reason := "federation denied: source and target tenants are identical (use /handoff)"
}

# Source manifest must authorize federation.
deny_reasons contains reason if {
    not input.source.manifest.federation.allow_parent_review
    not input.source.manifest.federation.allow_peer_review
    reason := "federation denied: source manifest does not permit cross-tenant review"
}

# Actor must hold federation.initiator in the source tenant realm.
deny_reasons contains reason if {
    not "federation.initiator" in input.actor.roles
    reason := sprintf(
        "federation denied: actor '%s' lacks 'federation.initiator' role",
        [input.actor.sub],
    )
}

# Target tenant must be in the source tenant's configured peer list.
deny_reasons contains reason if {
    not input.target.tenant_id in input.source.federated_peers
    reason := sprintf(
        "federation denied: target tenant '%s' is not in source federated_peers",
        [input.target.tenant_id],
    )
}

# Target tenant must accept the source's tier (no downgrade).
deny_reasons contains reason if {
    _tier_order[input.source.security_tier] > _tier_order[input.target.max_accepted_tier]
    reason := sprintf(
        "federation denied: source tier %s exceeds target max_accepted_tier %s",
        [input.source.security_tier, input.target.max_accepted_tier],
    )
}

# ---- Obligations ------------------------------------------------------------

# Always emit a matched pair — source chain gets forked_out, target chain
# gets forked_in. Enforcement layer is responsible for posting both.
obligations contains obligation if {
    count(deny_reasons) == 0
    obligation := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "session.forked_out",
            "severity": "info",
            "policy": "sessions.federation",
            "source_session_id": input.source.session_id,
            "target_tenant_id": input.target.tenant_id,
            "reason": input.fork.reason,
        },
    }
}

obligations contains obligation if {
    count(deny_reasons) == 0
    obligation := {
        "type": "token.exchange",
        "priority": 1,
        "params": {
            "audience": sprintf("insidellm.%s.session", [input.target.tenant_id]),
            "fork_intent": {
                "source_session_id": input.source.session_id,
                "retention_floor_days": input.source.retention_floor_days,
            },
            "ttl_seconds": 60,
        },
    }
}

# Require a federated identity mapping for the actor (deterministic hash of
# source_sub + target_realm) — enforcement layer computes + injects.
obligations contains obligation if {
    count(deny_reasons) == 0
    obligation := {
        "type": "identity.federated_sub",
        "priority": 1,
        "params": {
            "source_sub": input.actor.sub,
            "source_tenant": input.source.tenant_id,
            "target_tenant": input.target.tenant_id,
        },
    }
}
