# =============================================================================
# Regulation F — CFPB 12 CFR Part 1006 (2021)
#
# Modernizes FDCPA enforcement. This overlay implements the two provisions
# that matter most for the InsideLLM Collections industry pack:
#
#   1. §1006.14(b) — Call frequency. A debt collector may not contact a
#      consumer more than 7 times in a 7-day period per account, or at
#      all within 7 days after a prior telephone conversation (the
#      "7-in-7" rule; "1-in-7 after a conversation").
#
#   2. §1006.18(d) — Required mini-Miranda in electronic communications.
#      Same §1692e(11) disclosure as in FDCPA but explicitly required for
#      SMS, email, and portal messages.
#
# Rules only fire when the governing input fields are present. If a call
# is happening but `call_attempt_count_7d` isn't set, this overlay stays
# silent — graceful degradation for integrations that don't yet supply
# the counters.
#
# Planned for future versions of this overlay:
#   - §1006.6(e) consent + opt-out tracking for SMS/email
#   - §1006.34 validation notice content check (CFPB model notice fields)
# =============================================================================
package insidellm.industry.reg_f

import rego.v1

# -- §1006.14(b) — 7-in-7 call frequency -----------------------------------

deny_reasons contains reason if {
    input.trigger_type == "consumer_call_attempt"
    input.call_attempt_count_7d
    to_number(input.call_attempt_count_7d) >= 7
    reason := sprintf(
        "Reg F §1006.14(b): 7-in-7 call-frequency cap reached (%d calls in prior 7 days on this account)",
        [to_number(input.call_attempt_count_7d)],
    )
}

# -- §1006.14(b)(1)(ii)(A) — 1-in-7 after a conversation -------------------

deny_reasons contains reason if {
    input.trigger_type == "consumer_call_attempt"
    input.had_telephone_conversation_in_prior_7d == true
    reason := "Reg F §1006.14(b)(1)(ii)(A): call attempted within 7 days of a prior telephone conversation on this account"
}

# -- §1006.18(d) — Mini-Miranda in electronic comms ------------------------

deny_reasons contains reason if {
    input.trigger_type == "consumer_communication"
    input.channel in {"sms", "email", "portal_message"}
    not input.mini_miranda_present
    reason := sprintf(
        "Reg F §1006.18(d): %s communication lacks required §1692e(11) disclosure",
        [input.channel],
    )
}

# -- Obligations ------------------------------------------------------------

# Tag any outbound electronic communication so downstream systems can
# include it in the Reg F compliance evidence bundle.
obligations contains ob if {
    input.trigger_type == "consumer_communication"
    input.channel in {"sms", "email", "portal_message"}
    ob := {
        "type": "audit.tag",
        "priority": 3,
        "params": {"tags": ["reg_f_electronic_comm", sprintf("reg_f_channel_%s", [input.channel])]},
    }
}

# Log every call attempt so §1006.14(b) counter math stays reconstructable
# from audit trail alone.
obligations contains ob if {
    input.trigger_type == "consumer_call_attempt"
    ob := {
        "type": "audit.log",
        "priority": 2,
        "params": {
            "event_type": "consumer_call_attempt",
            "regulation": "reg_f",
            "log_level": "full",
        },
    }
}
