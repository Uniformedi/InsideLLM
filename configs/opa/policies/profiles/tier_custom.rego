# =============================================================================
# Guardrail Profile: tier_custom
# Operator-defined profile for company-specific rules not covered by the
# standard tiers. Defaults to the general_business baseline; operators
# layer their own rules by editing this file or dropping additional rego
# files under insidellm.profile.tier_custom_*.
#
# This is the only profile that can be modified without changing the
# platform — changes here are audited via governance_changes but don't
# require a platform release.
# =============================================================================
package insidellm.profile.tier_custom

import rego.v1

# Default to general_business posture. Operators can add industries by
# appending names to this set, e.g. `active_industries := {"sox", "glba"}`.
default active_industries := set()

# Operator adds deny_reasons here. Example (commented):
#
# deny_reasons contains reason if {
#     input.guardrail_profile == "tier_custom"
#     # Your company-specific rule here
#     reason := "Custom rule reason"
# }
deny_reasons := set()

# Baseline audit log so tier_custom usage is always tracked.
obligations contains ob if {
    input.guardrail_profile == "tier_custom"
    ob := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "custom_profile_usage",
            "profile": "tier_custom",
        },
    }
}
