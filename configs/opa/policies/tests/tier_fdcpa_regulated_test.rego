# =============================================================================
# Unit tests — tier_fdcpa_regulated profile
# Run: opa test ./configs/opa/policies/
# =============================================================================
package insidellm.tests.tier_fdcpa_regulated

import rego.v1

import data.insidellm.policy
import data.insidellm.profile.tier_fdcpa_regulated as p

# -------- Fixtures --------------------------------------------------------

valid_input := {
    "guardrail_profile": "tier_fdcpa_regulated",
    "action_scope": "read",
    "trigger_type": "human_chat",
    "time_of_day": "14:30",
    "consumer_timezone": "America/Chicago",
    "allowed_models": ["claude-sonnet-4-6"],
    "model_requested": "claude-sonnet-4-6",
    "data_classes_in_context": ["pii"],
    "notification_targets": ["teams"],
    "messages": [{"role": "user", "content": "hello"}],
}

# -------- Helpers ---------------------------------------------------------

has_reason_prefix(reasons, prefix) if {
    some r in reasons
    startswith(r, prefix)
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

has_any_attestation(obs) if {
    some o in obs
    o.type == "require.attestation"
}

# -------- Active industries -----------------------------------------------

test_active_industries if {
    p.active_industries == {"fdcpa", "reg_f", "sox", "pci_dss"}
}

# -------- Permitted-hours rule (§1692c(a)(1)) -----------------------------

test_allow_at_14_30 if {
    obj := object.union(valid_input, {"trigger_type": "consumer_communication"})
    reasons := p.deny_reasons with input as obj
    not has_reason_prefix(reasons, "FDCPA §1692c")
}

test_deny_at_07_45 if {
    obj := object.union(valid_input, {"trigger_type": "consumer_communication", "time_of_day": "07:45"})
    reasons := p.deny_reasons with input as obj
    has_reason_prefix(reasons, "FDCPA §1692c")
}

test_deny_at_21_00 if {
    obj := object.union(valid_input, {"trigger_type": "consumer_communication", "time_of_day": "21:00"})
    reasons := p.deny_reasons with input as obj
    has_reason_prefix(reasons, "FDCPA §1692c")
}

test_deny_at_23_45 if {
    obj := object.union(valid_input, {"trigger_type": "consumer_communication", "time_of_day": "23:45"})
    reasons := p.deny_reasons with input as obj
    has_reason_prefix(reasons, "FDCPA §1692c")
}

test_hours_only_applies_to_consumer_communication if {
    obj := object.union(valid_input, {"trigger_type": "human_chat", "time_of_day": "23:45"})
    reasons := p.deny_reasons with input as obj
    not has_reason_prefix(reasons, "FDCPA §1692c")
}

# -------- Model allowlist -------------------------------------------------

test_deny_model_not_in_allowlist if {
    obj := object.union(valid_input, {"model_requested": "gpt-4", "allowed_models": ["claude-sonnet-4-6"]})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "allowed_models")
}

test_allow_model_in_allowlist if {
    reasons := p.deny_reasons with input as valid_input
    not has_reason_contains(reasons, "allowed_models")
}

# -------- Consumer-channel restriction ------------------------------------

test_deny_discord_notification if {
    obj := object.union(valid_input, {"notification_targets": ["discord"]})
    reasons := p.deny_reasons with input as obj
    has_reason_contains(reasons, "Discord")
}

test_allow_teams_notification if {
    reasons := p.deny_reasons with input as valid_input
    not has_reason_contains(reasons, "Discord")
}

# -------- Obligations -----------------------------------------------------

test_always_audit_log if {
    obs := p.obligations with input as valid_input
    has_obligation(obs, "audit.log", "profile", "tier_fdcpa_regulated")
}

test_always_audit_tag_fdcpa_regulated if {
    obs := p.obligations with input as valid_input
    has_obligation_tag(obs, "fdcpa_regulated")
}

test_consumer_write_requires_supervisor_approval if {
    obj := object.union(valid_input, {"action_scope": "write", "trigger_type": "consumer_communication"})
    obs := p.obligations with input as obj
    has_obligation(obs, "review.queue", "escalation_target", "compliance_manager")
}

test_dispute_triggers_validation_attestation if {
    obj := object.union(valid_input, {"messages": [{"role": "user", "content": "This is a dispute about account 12345"}]})
    obs := p.obligations with input as obj
    has_obligation(obs, "require.attestation", "regulation", "fdcpa_1692g")
}

test_non_dispute_does_not_trigger_attestation if {
    obs := p.obligations with input as valid_input
    not has_any_attestation(obs)
}

# -------- End-to-end through decision.rego --------------------------------

test_decision_allows_valid_request if {
    d := policy.decision with input as valid_input
    d.allow == true
    d.profile == "tier_fdcpa_regulated"
}

test_decision_denies_after_hours_consumer_communication if {
    obj := object.union(valid_input, {"trigger_type": "consumer_communication", "time_of_day": "22:30"})
    d := policy.decision with input as obj
    d.allow == false
    has_reason_prefix(d.deny_reasons, "FDCPA §1692c")
}
