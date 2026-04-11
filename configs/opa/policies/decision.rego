# =============================================================================
# Decision Aggregation Policy
# Merges Humility (mandatory) + Industry (optional) into a single decision.
# Precedence: Humility denials override everything.
#
# Humility implements the SAIVAS framework from "Uniform Gnosis, Volume I"
# by Dan Medina. Copyright (c) 2026 Dan Medina. All rights reserved.
# =============================================================================
package insidellm.policy

import rego.v1

import data.insidellm.humility

# Aggregate deny reasons from all layers
all_deny_reasons := humility.deny_reasons | industry_deny_reasons

# Industry deny reasons come from any loaded industry packages
industry_deny_reasons contains reason if {
    some reason in data.insidellm.industry[_].deny_reasons
}

# Aggregate obligations from all layers
all_obligations := humility.obligations | industry_obligations

industry_obligations contains obligation if {
    some obligation in data.insidellm.industry[_].obligations
}

# Final decision
decision := result if {
    result := {
        "allow": count(all_deny_reasons) == 0,
        "deny_reasons": all_deny_reasons,
        "obligations": sort_obligations(all_obligations),
    }
}

# Sort obligations by priority for execution order
sort_obligations(obs) := sorted if {
    sorted := [o | some o in obs]
}

# Default decision if evaluation fails — fail closed
default decision := {
    "allow": false,
    "deny_reasons": ["Policy evaluation error — fail closed"],
    "obligations": [],
}
