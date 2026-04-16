# =============================================================================
# Unit tests — tier_unrestricted profile
# =============================================================================
package insidellm.tests.tier_unrestricted

import rego.v1

import data.insidellm.policy
import data.insidellm.profile.tier_unrestricted as p

valid_input := {
    "guardrail_profile": "tier_unrestricted",
    "action_scope": "read",
    "model_requested": "claude-opus-4-6",
    "data_classes_in_context": [],
    "messages": [{"role": "user", "content": "explore this dataset"}],
}

has_obligation_type(obs, kind) if {
    some o in obs
    o.type == kind
}

test_no_active_industries if {
    p.active_industries == set()
}

test_no_deny_reasons_ever if {
    reasons := p.deny_reasons with input as valid_input
    count(reasons) == 0
}

test_audit_log_obligation_always if {
    obs := p.obligations with input as valid_input
    has_obligation_type(obs, "audit.log")
}

test_decision_allows_valid_request if {
    d := policy.decision with input as valid_input
    d.allow == true
    d.profile == "tier_unrestricted"
}
