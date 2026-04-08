# =============================================================================
# Decision Aggregation Policy
# Merges SAIVAS (mandatory) + Industry (optional) into a single decision.
# Precedence: SAIVAS denials override everything.
# =============================================================================
package insidellm.policy

import rego.v1

import data.insidellm.saivas

# Aggregate deny reasons from all layers
all_deny_reasons := saivas.deny_reasons | industry_deny_reasons

# Industry deny reasons come from any loaded industry packages
industry_deny_reasons contains reason if {
    some reason in data.insidellm.industry[_].deny_reasons
}

# Aggregate obligations from all layers
all_obligations := saivas.obligations | industry_obligations

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
