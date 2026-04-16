# =============================================================================
# Unit tests — tier_general_business profile
# =============================================================================
package insidellm.tests.tier_general_business

import rego.v1

import data.insidellm.policy
import data.insidellm.profile.tier_general_business as p

valid_input := {
    "guardrail_profile": "tier_general_business",
    "action_scope": "read",
    "model_requested": "claude-sonnet-4-6",
    "allowed_models": ["claude-sonnet-4-6", "claude-haiku-4-5"],
    "max_actions_per_session": 10,
    "session_action_count": 2,
    "token_budget_per_session": 50000,
    "session_token_count": 12000,
    "iteration_count": 1,
    "data_classes_in_context": [],
    "messages": [{"role": "user", "content": "what is our holiday schedule?"}],
}

has_reason_contains(reasons, needle) if {
    some r in reasons
    contains(r, needle)
}

has_obligation_type(obs, kind) if {
    some o in obs
    o.type == kind
}

has_obligation_tag(obs, tag) if {
    some o in obs
    o.type == "audit.tag"
    tag in o.params.tags
}

has_redact_class(obs, cls) if {
    some o in obs
    o.type == "filter.fields"
    cls in o.params.redact_classes
}

test_active_industries_empty if {
    p.active_industries == set()
}

test_allow_valid_request if {
    reasons := p.deny_reasons with input as valid_input
    count(reasons) == 0
}

test_deny_model_outside_allowlist if {
    obj := object.union(valid_input, {"model_requested": "claude-opus-4-6"})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "allowed_models")
}

test_deny_session_action_count_exceeded if {
    obj := object.union(valid_input, {"session_action_count": 11})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "max_actions_per_session")
}

test_deny_session_token_budget_exceeded if {
    obj := object.union(valid_input, {"session_token_count": 50001})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "token budget")
}

test_pii_triggers_redact_obligation if {
    obj := object.union(valid_input, {"data_classes_in_context": ["pii"]})
    obs := p.obligations with input as obj
    has_redact_class(obs, "pii")
}

test_no_pii_no_redact_obligation if {
    obs := p.obligations with input as valid_input
    not has_obligation_type(obs, "filter.fields")
}

test_elevated_iteration_count_warns if {
    obj := object.union(valid_input, {"iteration_count": 6})
    obs := p.obligations with input as obj
    has_obligation_tag(obs, "elevated_iteration_count")
}

test_decision_allows_valid_request if {
    d := policy.decision with input as valid_input
    d.allow == true
    d.profile == "tier_general_business"
}
