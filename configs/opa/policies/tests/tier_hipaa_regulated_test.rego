# =============================================================================
# Unit tests — tier_hipaa_regulated profile
# =============================================================================
package insidellm.tests.tier_hipaa_regulated

import rego.v1

import data.insidellm.policy
import data.insidellm.profile.tier_hipaa_regulated as p

valid_input := {
    "guardrail_profile": "tier_hipaa_regulated",
    "action_scope": "read",
    "model_requested": "claude-sonnet-4-6",
    "allowed_models": ["claude-sonnet-4-6"],
    "baa_models": ["claude-sonnet-4-6", "claude-haiku-4-5"],
    "data_classes_in_context": ["phi"],
    "notification_targets": ["teams"],
    # hipaa_authorized is set by the manifest-to-runtime translator when
    # the invoking agent's guardrail_profile is tier_hipaa_regulated. The
    # industry HIPAA policy uses it as the authorization witness.
    "hipaa_authorized": true,
    "messages": [{"role": "user", "content": "summarize patient intake"}],
}

has_reason_contains(reasons, needle) if {
    some r in reasons
    contains(r, needle)
}

has_obligation(obs, kind, pred_key, pred_val) if {
    some o in obs
    o.type == kind
    object.get(o.params, pred_key, "") == pred_val
}

test_active_industries if {
    p.active_industries == {"hipaa"}
}

test_allow_valid_hipaa_request if {
    reasons := p.deny_reasons with input as valid_input
    count(reasons) == 0
}

test_deny_non_baa_model if {
    obj := object.union(valid_input, {"model_requested": "gpt-4"})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "not BAA-covered")
}

test_phi_in_non_hipaa_context_denies if {
    # Minimum-Necessary rule: PHI outside HIPAA profile is always denied.
    obj := object.union(valid_input, {"guardrail_profile": "tier_general_business"})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "Minimum Necessary")
}

test_deny_disallowed_channel if {
    obj := object.union(valid_input, {"notification_targets": ["slack"]})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "not permitted for HIPAA")
}

test_allow_teams_channel if {
    reasons := p.deny_reasons with input as valid_input
    not has_reason_contains(reasons, "channel")
}

test_phi_write_requires_approval if {
    obj := object.union(valid_input, {"action_scope": "write"})
    obs := p.obligations with input as obj
    has_obligation(obs, "review.queue", "escalation_target", "privacy_officer")
}

test_decision_allows_valid_request if {
    d := policy.decision with input as valid_input
    d.allow == true
}

test_decision_denies_non_baa_model if {
    obj := object.union(valid_input, {"model_requested": "gpt-4"})
    d := policy.decision with input as obj
    d.allow == false
}
