# =============================================================================
# Guardrail Profile: tier_financial_regulated
# SOX-scope / PCI-scope operations. Loads both SOX and PCI-DSS industry
# overlays. Full audit trail, approval required for external actions,
# strict model allowlist.
# =============================================================================
package insidellm.profile.tier_financial_regulated

import rego.v1

active_industries := {"sox", "pci_dss"}

# Deny: model not in allowlist (tighter than general_business — we require
# the agent manifest's allowed_models to be set).
deny_reasons contains reason if {
    input.guardrail_profile == "tier_financial_regulated"
    not input.allowed_models
    reason := "tier_financial_regulated requires allowed_models to be set"
}

deny_reasons contains reason if {
    input.guardrail_profile == "tier_financial_regulated"
    input.model_requested
    input.allowed_models
    not input.model_requested in input.allowed_models
    reason := sprintf(
        "model '%s' not in allowed_models (financial-regulated)",
        [input.model_requested],
    )
}

# Deny: credentials class in context (financial systems must not accept
# credential material as input — Humility blocks, this is reinforcement).
deny_reasons contains reason if {
    input.guardrail_profile == "tier_financial_regulated"
    "credentials" in input.data_classes_in_context
    reason := "credentials data class forbidden in tier_financial_regulated"
}

# Deny: notification target is a consumer chat platform AND the request
# touches PII/financial data.
deny_reasons contains reason if {
    input.guardrail_profile == "tier_financial_regulated"
    "discord" in input.notification_targets
    some cls in ["pii", "financial", "credentials"]
    cls in input.data_classes_in_context
    reason := "Discord is forbidden as a notification target for regulated data"
}

# Obligation: full audit trail — log inputs AND outputs.
obligations contains ob if {
    input.guardrail_profile == "tier_financial_regulated"
    ob := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "financial_regulated_usage",
            "profile": "tier_financial_regulated",
            "log_level": "full",
        },
    }
}

# Obligation: any write action requires approval when financial data is
# in context.
obligations contains ob if {
    input.guardrail_profile == "tier_financial_regulated"
    input.action_scope == "write"
    "financial" in input.data_classes_in_context
    ob := {
        "type": "review.queue",
        "priority": 4,
        "params": {
            "review_type": "financial_write",
            "escalation_target": "finance_supervisor",
        },
    }
}

# Obligation: tag all activity for SOX audit pull.
obligations contains ob if {
    input.guardrail_profile == "tier_financial_regulated"
    ob := {
        "type": "audit.tag",
        "priority": 2,
        "params": {
            "tags": ["sox_auditable", "financial_regulated"],
        },
    }
}
