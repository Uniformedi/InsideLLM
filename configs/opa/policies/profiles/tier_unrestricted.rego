# =============================================================================
# Guardrail Profile: tier_unrestricted
# Internal analytics / R&D. Log-only, no blocking beyond Humility.
# =============================================================================
package insidellm.profile.tier_unrestricted

import rego.v1

# No industry overlays for unrestricted usage.
active_industries := set()

# Profile never adds its own denials — Humility is the only gate.
deny_reasons := set()

# Log-only: emit an audit.log obligation so usage is tracked for review.
obligations contains ob if {
    input.guardrail_profile == "tier_unrestricted"
    ob := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "unrestricted_usage",
            "severity": "info",
            "profile": "tier_unrestricted",
        },
    }
}
