# =============================================================================
# Unit tests — tier_financial_regulated profile
# =============================================================================
package insidellm.tests.tier_financial_regulated

import rego.v1

import data.insidellm.policy
import data.insidellm.profile.tier_financial_regulated as p

valid_input := {
    "guardrail_profile": "tier_financial_regulated",
    "action_scope": "read",
    "model_requested": "claude-sonnet-4-6",
    "allowed_models": ["claude-sonnet-4-6"],
    "data_classes_in_context": ["financial"],
    "notification_targets": ["teams"],
    "messages": [{"role": "user", "content": "summarize Q3 revenue trends"}],
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

has_obligation_tag(obs, tag) if {
    some o in obs
    o.type == "audit.tag"
    tag in o.params.tags
}

test_active_industries if {
    p.active_industries == {"sox", "pci_dss"}
}

test_deny_credentials_in_context if {
    obj := object.union(valid_input, {"data_classes_in_context": ["credentials"]})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "credentials data class forbidden")
}

test_deny_discord_with_financial if {
    obj := object.union(valid_input, {"notification_targets": ["discord"]})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "Discord")
}

test_write_on_financial_requires_approval if {
    obj := object.union(valid_input, {"action_scope": "write"})
    obs := p.obligations with input as obj
    has_obligation(obs, "review.queue", "escalation_target", "finance_supervisor")
}

test_sox_audit_tag_present if {
    obs := p.obligations with input as valid_input
    has_obligation_tag(obs, "sox_auditable")
}

test_decision_allows_valid_request if {
    d := policy.decision with input as valid_input
    d.allow == true
}

test_decision_denies_discord_with_financial if {
    obj := object.union(valid_input, {"notification_targets": ["discord"]})
    d := policy.decision with input as obj
    d.allow == false
}
