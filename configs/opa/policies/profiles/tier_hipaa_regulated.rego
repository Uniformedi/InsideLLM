# =============================================================================
# Guardrail Profile: tier_hipaa_regulated
# Healthcare operations subject to HIPAA (45 CFR §164). Loads the HIPAA
# industry overlay and enforces:
#   - PHI is only allowed when the profile is this tier (Minimum Necessary)
#   - Only BAA-covered models may be used
#   - Approval required for any disclosure / external action
# =============================================================================
package insidellm.profile.tier_hipaa_regulated

import rego.v1

active_industries := {"hipaa"}

# -- BAA-covered models (must be maintained by the operator; default empty = deny all) --

# Deny if model is not in the tenant's BAA-covered allowlist.
# input.baa_models should be set by the translator from a tenant-level
# config; agent's allowed_models must be a subset.
deny_reasons contains reason if {
    input.guardrail_profile == "tier_hipaa_regulated"
    input.model_requested
    input.baa_models
    not input.model_requested in input.baa_models
    reason := sprintf(
        "model '%s' is not BAA-covered for HIPAA tier",
        [input.model_requested],
    )
}

# Deny if BAA list is empty — explicit configuration required for HIPAA.
deny_reasons contains reason if {
    input.guardrail_profile == "tier_hipaa_regulated"
    not input.baa_models
    reason := "tier_hipaa_regulated requires input.baa_models to be configured"
}

# -- Minimum-Necessary — PHI may not flow to non-HIPAA agents --------------

deny_reasons contains reason if {
    input.guardrail_profile != "tier_hipaa_regulated"
    "phi" in input.data_classes_in_context
    reason := "PHI detected in non-HIPAA context (Minimum Necessary violation)"
}

# -- Notification channel restriction --------------------------------------

deny_reasons contains reason if {
    input.guardrail_profile == "tier_hipaa_regulated"
    some channel in input.notification_targets
    not channel in {"teams", "email", "secure_inbox"}
    reason := sprintf(
        "notification channel '%s' not permitted for HIPAA-regulated data",
        [channel],
    )
}

# -- Obligations -----------------------------------------------------------

obligations contains ob if {
    input.guardrail_profile == "tier_hipaa_regulated"
    ob := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "hipaa_regulated_usage",
            "profile": "tier_hipaa_regulated",
            "log_level": "full",
        },
    }
}

obligations contains ob if {
    input.guardrail_profile == "tier_hipaa_regulated"
    ob := {
        "type": "audit.tag",
        "priority": 2,
        "params": {"tags": ["hipaa_regulated", "phi"]},
    }
}

# Any disclosure (write action) touching PHI requires supervisor approval.
obligations contains ob if {
    input.guardrail_profile == "tier_hipaa_regulated"
    input.action_scope == "write"
    "phi" in input.data_classes_in_context
    ob := {
        "type": "review.queue",
        "priority": 4,
        "params": {
            "review_type": "phi_disclosure",
            "regulation": "hipaa",
            "escalation_target": "privacy_officer",
        },
    }
}
