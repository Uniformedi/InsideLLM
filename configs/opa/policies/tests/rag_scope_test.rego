# =============================================================================
# Unit tests — Humility RAG scope enforcement
# =============================================================================
package insidellm.tests.rag_scope

import rego.v1

import data.insidellm.humility
import data.insidellm.policy

# Base input — passes humility default checks, does no retrieval.
base_input := {
    "guardrail_profile": "tier_general_business",
    "agent_id": "dispute-handler",
    "tenant_id": "example-tenant",
    "messages": [{"role": "user", "content": "look up account"}],
    "requested_collections": [],
    "agent_knowledge_collections": ["organization-fdcpa-letters", "organization-account-policies"],
    "knowledge_scope": "strict",
    "request_type": "standard",
    "uncertainty_declared": true,
    "within_validated_domain": true,
    "data_classification": "internal",
}

has_scope_deny(reasons, collection) if {
    some r in reasons
    contains(r, "RAG scope")
    contains(r, collection)
}

has_obligation_type(obs, kind) if {
    some o in obs
    o.type == kind
}

# -----------------------------------------------------------------------------
# Strict scope — the default, fail-closed behaviour.
# -----------------------------------------------------------------------------

test_strict_allows_in_scope_retrieval if {
    obj := object.union(base_input, {
        "requested_collections": ["organization-fdcpa-letters"],
    })
    reasons := humility.deny_reasons with input as obj
    not has_scope_deny(reasons, "organization-fdcpa-letters")
}

test_strict_allows_all_declared_collections if {
    obj := object.union(base_input, {
        "requested_collections": ["organization-fdcpa-letters", "organization-account-policies"],
    })
    reasons := humility.deny_reasons with input as obj
    not has_scope_deny(reasons, "organization-fdcpa-letters")
    not has_scope_deny(reasons, "organization-account-policies")
}

test_strict_denies_out_of_scope_retrieval if {
    obj := object.union(base_input, {
        "requested_collections": ["hr-confidential"],
    })
    reasons := humility.deny_reasons with input as obj
    has_scope_deny(reasons, "hr-confidential")
}

test_strict_denies_mixed_in_and_out_of_scope if {
    obj := object.union(base_input, {
        "requested_collections": ["organization-fdcpa-letters", "hr-confidential"],
    })
    reasons := humility.deny_reasons with input as obj
    has_scope_deny(reasons, "hr-confidential")
    # In-scope collection does not trigger deny.
    not has_scope_deny(reasons, "organization-fdcpa-letters")
}

test_strict_empty_request_is_noop if {
    obj := object.union(base_input, {"requested_collections": []})
    reasons := humility.deny_reasons with input as obj
    not has_scope_deny(reasons, "anything")
}

test_strict_defaults_when_scope_field_missing if {
    obj := object.union(base_input, {
        "requested_collections": ["hr-confidential"],
    })
    # Remove knowledge_scope entirely — should behave as strict.
    obj_no_scope := {k: v | some k, v in obj; k != "knowledge_scope"}
    reasons := humility.deny_reasons with input as obj_no_scope
    has_scope_deny(reasons, "hr-confidential")
}

# -----------------------------------------------------------------------------
# Loose scope — audit-only, drift recorded but not blocked.
# -----------------------------------------------------------------------------

test_loose_allows_out_of_scope_but_audits if {
    obj := object.union(base_input, {
        "knowledge_scope": "loose",
        "requested_collections": ["hr-confidential"],
    })
    reasons := humility.deny_reasons with input as obj
    obs := humility.obligations with input as obj
    not has_scope_deny(reasons, "hr-confidential")
    has_obligation_type(obs, "audit.log")
}

test_loose_no_audit_when_in_scope if {
    obj := object.union(base_input, {
        "knowledge_scope": "loose",
        "requested_collections": ["organization-fdcpa-letters"],
    })
    obs := humility.obligations with input as obj
    # The rag_scope obligation adds "policy": "humility.rag_scope"; make
    # sure none of the audit-log obligations carry that policy tag.
    count([o |
        some o in obs
        o.type == "audit.log"
        o.params.policy == "humility.rag_scope"
    ]) == 0
}

# -----------------------------------------------------------------------------
# Integration — the decision entry point aggregates scope denies correctly.
# -----------------------------------------------------------------------------

test_decision_denies_on_out_of_scope_retrieval if {
    obj := object.union(base_input, {
        "requested_collections": ["hr-confidential"],
    })
    d := policy.decision with input as obj
    d.allow == false
    count(d.deny_reasons) > 0
}

test_decision_allows_valid_in_scope_retrieval if {
    obj := object.union(base_input, {
        "requested_collections": ["organization-fdcpa-letters"],
    })
    d := policy.decision with input as obj
    d.allow == true
}
