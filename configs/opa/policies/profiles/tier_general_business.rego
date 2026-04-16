# =============================================================================
# Guardrail Profile: tier_general_business
# Default for general knowledge work. PII redaction in logs, standard
# budget caps. No regulated-industry overlays.
# =============================================================================
package insidellm.profile.tier_general_business

import rego.v1

active_industries := set()

# Deny: model request outside the agent's allowlist.
deny_reasons contains reason if {
    input.guardrail_profile == "tier_general_business"
    input.model_requested
    input.allowed_models
    not input.model_requested in input.allowed_models
    reason := sprintf(
        "model '%s' not in agent's allowed_models list",
        [input.model_requested],
    )
}

# Deny: session action count exceeded.
deny_reasons contains reason if {
    input.guardrail_profile == "tier_general_business"
    input.session_action_count > input.max_actions_per_session
    reason := sprintf(
        "session exceeded max_actions_per_session (%d > %d)",
        [input.session_action_count, input.max_actions_per_session],
    )
}

# Deny: session token budget exceeded.
deny_reasons contains reason if {
    input.guardrail_profile == "tier_general_business"
    input.session_token_count > input.token_budget_per_session
    reason := sprintf(
        "session token budget exceeded (%d > %d)",
        [input.session_token_count, input.token_budget_per_session],
    )
}

# Obligation: audit every request with profile metadata.
obligations contains ob if {
    input.guardrail_profile == "tier_general_business"
    ob := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "general_business_usage",
            "profile": "tier_general_business",
        },
    }
}

# Obligation: redact PII from logs.
obligations contains ob if {
    input.guardrail_profile == "tier_general_business"
    "pii" in input.data_classes_in_context
    ob := {
        "type": "filter.fields",
        "priority": 2,
        "params": {
            "scope": "audit_log",
            "redact_classes": ["pii"],
        },
    }
}

# Warn (soft alert via audit.tag) if iteration count is elevated — possible
# agent loop.
obligations contains ob if {
    input.guardrail_profile == "tier_general_business"
    input.iteration_count > 5
    ob := {
        "type": "audit.tag",
        "priority": 3,
        "params": {
            "tags": ["elevated_iteration_count"],
            "iteration_count": input.iteration_count,
        },
    }
}
