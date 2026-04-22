# =============================================================================
# Unit tests — Regulation F industry overlay (§1006.14(b), §1006.18(d))
# Run: opa test ./configs/opa/policies/
# =============================================================================
package insidellm.tests.reg_f

import rego.v1

import data.insidellm.industry.reg_f as r

# -- Helpers ---------------------------------------------------------------

has_reason_contains(reasons, needle) if {
    some reason in reasons
    contains(reason, needle)
}

has_obligation_tag(obs, tag) if {
    some o in obs
    o.type == "audit.tag"
    tag in o.params.tags
}

has_audit_log(obs, event_type) if {
    some o in obs
    o.type == "audit.log"
    o.params.event_type == event_type
}

# -- §1006.14(b) 7-in-7 cap --------------------------------------------------

test_7_in_7_hit_denies if {
    input := {
        "trigger_type": "consumer_call_attempt",
        "call_attempt_count_7d": 7,
        "had_telephone_conversation_in_prior_7d": false,
    }
    reasons := r.deny_reasons with input as input
    has_reason_contains(reasons, "7-in-7 call-frequency cap")
}

test_7_in_7_at_eight_still_denies if {
    input := {
        "trigger_type": "consumer_call_attempt",
        "call_attempt_count_7d": 8,
        "had_telephone_conversation_in_prior_7d": false,
    }
    reasons := r.deny_reasons with input as input
    has_reason_contains(reasons, "7-in-7 call-frequency cap")
}

test_under_7_allows if {
    input := {
        "trigger_type": "consumer_call_attempt",
        "call_attempt_count_7d": 6,
        "had_telephone_conversation_in_prior_7d": false,
    }
    reasons := r.deny_reasons with input as input
    not has_reason_contains(reasons, "7-in-7 call-frequency cap")
}

test_counter_missing_stays_silent if {
    # Graceful degradation: integrations that haven't yet wired the counter
    # should not cause spurious denies.
    input := {"trigger_type": "consumer_call_attempt"}
    reasons := r.deny_reasons with input as input
    count(reasons) == 0
}

# -- §1006.14(b)(1)(ii)(A) 1-in-7 after conversation -----------------------

test_conversation_in_window_denies if {
    input := {
        "trigger_type": "consumer_call_attempt",
        "call_attempt_count_7d": 1,
        "had_telephone_conversation_in_prior_7d": true,
    }
    reasons := r.deny_reasons with input as input
    has_reason_contains(reasons, "within 7 days of a prior telephone conversation")
}

test_no_conversation_no_deny_from_this_rule if {
    input := {
        "trigger_type": "consumer_call_attempt",
        "call_attempt_count_7d": 1,
        "had_telephone_conversation_in_prior_7d": false,
    }
    reasons := r.deny_reasons with input as input
    not has_reason_contains(reasons, "within 7 days of a prior telephone conversation")
}

# -- §1006.18(d) mini-Miranda in electronic comms --------------------------

test_sms_missing_mini_miranda_denies if {
    input := {
        "trigger_type": "consumer_communication",
        "channel": "sms",
        "mini_miranda_present": false,
    }
    reasons := r.deny_reasons with input as input
    has_reason_contains(reasons, "§1692e(11) disclosure")
}

test_email_missing_mini_miranda_denies if {
    input := {
        "trigger_type": "consumer_communication",
        "channel": "email",
        "mini_miranda_present": false,
    }
    reasons := r.deny_reasons with input as input
    has_reason_contains(reasons, "§1692e(11) disclosure")
}

test_email_with_mini_miranda_allows if {
    input := {
        "trigger_type": "consumer_communication",
        "channel": "email",
        "mini_miranda_present": true,
    }
    reasons := r.deny_reasons with input as input
    not has_reason_contains(reasons, "§1692e(11) disclosure")
}

test_mailed_letter_not_subject_to_this_rule if {
    # Mini-Miranda is still required for all FDCPA comms (handled elsewhere),
    # but the §1006.18(d) rule specifically targets electronic channels.
    input := {
        "trigger_type": "consumer_communication",
        "channel": "mail",
        "mini_miranda_present": false,
    }
    reasons := r.deny_reasons with input as input
    not has_reason_contains(reasons, "§1692e(11) disclosure")
}

# -- Obligations -----------------------------------------------------------

test_sms_obligation_tags if {
    input := {
        "trigger_type": "consumer_communication",
        "channel": "sms",
        "mini_miranda_present": true,
    }
    obs := r.obligations with input as input
    has_obligation_tag(obs, "reg_f_electronic_comm")
    has_obligation_tag(obs, "reg_f_channel_sms")
}

test_call_attempt_audit_log if {
    input := {
        "trigger_type": "consumer_call_attempt",
        "call_attempt_count_7d": 3,
        "had_telephone_conversation_in_prior_7d": false,
    }
    obs := r.obligations with input as input
    has_audit_log(obs, "consumer_call_attempt")
}

test_nothing_fires_on_unrelated_trigger if {
    input := {"trigger_type": "human_chat"}
    reasons := r.deny_reasons with input as input
    obs := r.obligations with input as input
    count(reasons) == 0
    count(obs) == 0
}
