# =============================================================================
# Tests — sessions.handoff
#
# Run with `opa test configs/opa/policies/` from the repo root.
# =============================================================================
package insidellm.sessions.handoff_test

import rego.v1

import data.insidellm.sessions.handoff

_base_input := {
    "session": {
        "session_id": "s-1",
        "tenant_id": "t-1",
        "security_tier": "T2",
        "classification": "general",
        "manifest_hash": "sha256-abc",
    },
    "source": {"owner_type": "user", "owner_ref": "u-1"},
    "target": {
        "type": "user",
        "ref": "u-2",
        "tenant_id": "t-1",
        "status": "online",
        "roles": [],
    },
    "actor": {"sub": "u-1", "roles": []},
    "agent": {"accepts_handoff": true, "handoff_chain_tags": []},
    "handoff": {"reason": "shift change eod", "hop_count": 0},
}

# ---- Happy path -------------------------------------------------------------

test_user_to_user_same_tenant_allowed if {
    result := handoff.deny_reasons with input as _base_input
    count(result) == 0
}

# ---- Invariants -------------------------------------------------------------

test_denies_non_owner_actor if {
    input_override := object.union(_base_input, {
        "actor": {"sub": "u-99", "roles": []}
    })
    some r in handoff.deny_reasons with input as input_override
    contains(r, "not the current owner")
}

test_allows_tenant_admin_override if {
    input_override := object.union(_base_input, {
        "actor": {"sub": "u-99", "roles": ["tenant-admin"]}
    })
    count(handoff.deny_reasons with input as input_override) == 0
}

test_denies_empty_reason if {
    input_override := object.union(_base_input, {
        "handoff": {"reason": "", "hop_count": 0}
    })
    some r in handoff.deny_reasons with input as input_override
    contains(r, "reason")
}

test_denies_short_reason if {
    input_override := object.union(_base_input, {
        "handoff": {"reason": "x", "hop_count": 0}
    })
    some r in handoff.deny_reasons with input as input_override
    contains(r, "too short")
}

test_denies_cross_tenant_on_handoff_endpoint if {
    input_override := object.union(_base_input, {
        "target": {
            "type": "user", "ref": "u-2",
            "tenant_id": "t-99", "status": "online", "roles": [],
        }
    })
    some r in handoff.deny_reasons with input as input_override
    contains(r, "cross-tenant")
}

# ---- Tier-specific ----------------------------------------------------------

test_t4_requires_reviewer_role_on_target if {
    input_override := object.union(_base_input, {
        "session": object.union(_base_input.session, {"security_tier": "T4"}),
    })
    some r in handoff.deny_reasons with input as input_override
    contains(r, "reviewer")
}

test_t4_with_reviewer_allowed if {
    input_override := object.union(_base_input, {
        "session": object.union(_base_input.session, {"security_tier": "T4"}),
        "target": object.union(_base_input.target, {"roles": ["reviewer"]}),
    })
    count(handoff.deny_reasons with input as input_override) == 0
}

test_t5_denies_offline_target if {
    input_override := object.union(_base_input, {
        "session": object.union(_base_input.session, {"security_tier": "T5"}),
        "target": object.union(_base_input.target, {
            "roles": ["reviewer"], "status": "offline",
        }),
    })
    some r in handoff.deny_reasons with input as input_override
    contains(r, "offline")
}

# ---- Agent handoff paths ---------------------------------------------------

test_user_to_agent_requires_accepts_handoff if {
    input_override := object.union(_base_input, {
        "target": {
            "type": "agent", "ref": "a-1",
            "tenant_id": "t-1", "status": "online", "roles": [],
        },
        "agent": {"accepts_handoff": false, "handoff_chain_tags": []},
    })
    some r in handoff.deny_reasons with input as input_override
    contains(r, "accepts_handoff")
}

test_user_to_agent_emits_dlp_rescan if {
    input_override := object.union(_base_input, {
        "target": {
            "type": "agent", "ref": "a-1",
            "tenant_id": "t-1", "status": "online", "roles": [],
        },
        "agent": {"accepts_handoff": true, "handoff_chain_tags": []},
    })
    result := handoff.obligations with input as input_override
    some o in result
    o.type == "dlp.rescan"
}

test_agent_to_agent_requires_shared_chain_tag if {
    input_override := {
        "session": _base_input.session,
        "source": {"owner_type": "agent", "owner_ref": "a-1"},
        "target": {
            "type": "agent", "ref": "a-2",
            "tenant_id": "t-1", "status": "online", "roles": [],
            "agent": {"handoff_chain_tags": ["billing"]},
        },
        "actor": {"sub": "u-1", "roles": ["tenant-admin"]},
        "agent": {"accepts_handoff": true, "handoff_chain_tags": ["collections"]},
        "handoff": {"reason": "escalation to billing agent", "hop_count": 1},
    }
    some r in handoff.deny_reasons with input as input_override
    contains(r, "handoff_chain")
}

test_agent_chain_hop_cap if {
    input_override := {
        "session": _base_input.session,
        "source": {"owner_type": "agent", "owner_ref": "a-1"},
        "target": {
            "type": "agent", "ref": "a-2",
            "tenant_id": "t-1", "status": "online", "roles": [],
            "agent": {"handoff_chain_tags": ["collections"]},
        },
        "actor": {"sub": "u-1", "roles": ["tenant-admin"]},
        "agent": {"accepts_handoff": true, "handoff_chain_tags": ["collections"]},
        "handoff": {"reason": "fourth hop should fail", "hop_count": 3},
    }
    some r in handoff.deny_reasons with input as input_override
    contains(r, "chain depth")
}

# ---- System-ownership guardrails --------------------------------------------

test_user_cannot_park_to_system if {
    input_override := object.union(_base_input, {
        "target": {
            "type": "system", "ref": "awaiting_callback",
            "tenant_id": "t-1", "status": "offline", "roles": [],
        }
    })
    some r in handoff.deny_reasons with input as input_override
    contains(r, "system")
}
