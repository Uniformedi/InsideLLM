# =============================================================================
# Guardrail Profile: tier_fdcpa_regulated
# Consumer collections operations under the Fair Debt Collection Practices
# Act (15 USC §1692). Loads FDCPA + SOX + PCI-DSS industry overlays and
# adds FDCPA-specific rules on top:
#   - Permitted contact hours (8 AM - 9 PM in consumer's timezone)
#   - §1692g validation-window tracking
#   - Consumer communication approval escalation
# =============================================================================
package insidellm.profile.tier_fdcpa_regulated

import rego.v1

active_industries := {"fdcpa", "reg_f", "sox", "pci_dss"}

# -- FDCPA permitted contact hours (§1692c(a)(1)) --------------------------
# FDCPA permits contact only between 8 AM and 9 PM in the consumer's local
# time. input.time_of_day is 24-hour local time in consumer's timezone.

deny_reasons contains reason if {
    input.guardrail_profile == "tier_fdcpa_regulated"
    input.trigger_type == "consumer_communication"
    is_outside_permitted_hours
    reason := sprintf(
        "FDCPA §1692c(a)(1): contact attempted outside permitted hours (8 AM - 9 PM) in consumer timezone %s (current: %s)",
        [input.consumer_timezone, input.time_of_day],
    )
}

# Split into two rule bodies (logical OR in Rego v1 idiom).
# Block before 8:00 (480 min).
is_outside_permitted_hours if {
    parts := split(input.time_of_day, ":")
    hour := to_number(parts[0])
    minute := to_number(parts[1])
    minutes := (hour * 60) + minute
    minutes < 480
}

# Block at or after 21:00 (1260 min).
is_outside_permitted_hours if {
    parts := split(input.time_of_day, ":")
    hour := to_number(parts[0])
    minute := to_number(parts[1])
    minutes := (hour * 60) + minute
    minutes >= 1260
}

# -- Model allowlist (same as financial_regulated) -------------------------

deny_reasons contains reason if {
    input.guardrail_profile == "tier_fdcpa_regulated"
    input.model_requested
    input.allowed_models
    not input.model_requested in input.allowed_models
    reason := sprintf("model '%s' not in allowed_models (FDCPA-regulated)", [input.model_requested])
}

# -- Consumer-facing channels cannot route regulated data ------------------

deny_reasons contains reason if {
    input.guardrail_profile == "tier_fdcpa_regulated"
    "discord" in input.notification_targets
    reason := "Discord is forbidden for FDCPA-regulated consumer communications"
}

# -- Obligations -----------------------------------------------------------

# Always audit at full fidelity.
obligations contains ob if {
    input.guardrail_profile == "tier_fdcpa_regulated"
    ob := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "fdcpa_regulated_usage",
            "profile": "tier_fdcpa_regulated",
            "log_level": "full",
        },
    }
}

# Tag for FDCPA audit pulls.
obligations contains ob if {
    input.guardrail_profile == "tier_fdcpa_regulated"
    ob := {
        "type": "audit.tag",
        "priority": 2,
        "params": {"tags": ["fdcpa_regulated", "consumer_regulated"]},
    }
}

# Any write action touching a consumer requires supervisor approval.
obligations contains ob if {
    input.guardrail_profile == "tier_fdcpa_regulated"
    input.action_scope == "write"
    input.trigger_type == "consumer_communication"
    ob := {
        "type": "review.queue",
        "priority": 4,
        "params": {
            "review_type": "consumer_communication",
            "regulation": "fdcpa",
            "escalation_target": "compliance_manager",
        },
    }
}

# Require §1692g validation-notice attestation on dispute-related work.
obligations contains ob if {
    input.guardrail_profile == "tier_fdcpa_regulated"
    some msg in input.messages
    msg.role == "user"
    contains(lower(msg.content), "dispute")
    ob := {
        "type": "require.attestation",
        "priority": 3,
        "params": {
            "attestation_type": "validation_notice_reviewed",
            "regulation": "fdcpa_1692g",
        },
    }
}
