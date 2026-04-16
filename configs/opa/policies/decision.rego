# =============================================================================
# Decision Aggregation Policy (v3 — profile-aware with static dispatch)
#
# Three layers merge into a single allow/deny decision:
#
#   1. Humility (mandatory, always applied) — SAIVAS framework from
#      "Uniform Gnosis, Volume I" by Dan Medina. No agent can bypass.
#   2. Named guardrail profile (input.guardrail_profile) — e.g.
#      tier_fdcpa_regulated. Each profile declares active_industries;
#      only those industry packages are evaluated for this request.
#   3. Industry overlays (FDCPA, HIPAA, SOX, PCI-DSS, GLBA, FERPA) —
#      evaluated only when the active profile lists them.
#
# Precedence: any deny from any layer = deny.
#
# Why static (else-if) dispatch instead of data.insidellm.profile[name]:
# a dynamic lookup makes every package under `insidellm.profile.*` a
# potential dependency in OPA's static analyzer, which creates a recursion
# path back through test packages and fails compilation. Static dispatch
# is explicit, inspectable, and OPA-friendly.
#
# Humility implements SAIVAS from "Uniform Gnosis, Volume I"
# by Dan Medina. Copyright (c) 2026 Dan Medina. All rights reserved.
# =============================================================================
package insidellm.policy

import rego.v1

import data.insidellm.humility
import data.insidellm.profile.tier_fdcpa_regulated
import data.insidellm.profile.tier_financial_regulated
import data.insidellm.profile.tier_general_business
import data.insidellm.profile.tier_hipaa_regulated
import data.insidellm.profile.tier_unrestricted
import data.insidellm.profile.tier_custom

# -- Profile dispatch (static) --------------------------------------------

profile_deny_reasons := tier_fdcpa_regulated.deny_reasons     if input.guardrail_profile == "tier_fdcpa_regulated"
else := tier_financial_regulated.deny_reasons                 if input.guardrail_profile == "tier_financial_regulated"
else := tier_hipaa_regulated.deny_reasons                     if input.guardrail_profile == "tier_hipaa_regulated"
else := tier_general_business.deny_reasons                    if input.guardrail_profile == "tier_general_business"
else := tier_unrestricted.deny_reasons                        if input.guardrail_profile == "tier_unrestricted"
else := tier_custom.deny_reasons                              if input.guardrail_profile == "tier_custom"
else := set()

profile_obligations := tier_fdcpa_regulated.obligations       if input.guardrail_profile == "tier_fdcpa_regulated"
else := tier_financial_regulated.obligations                  if input.guardrail_profile == "tier_financial_regulated"
else := tier_hipaa_regulated.obligations                      if input.guardrail_profile == "tier_hipaa_regulated"
else := tier_general_business.obligations                     if input.guardrail_profile == "tier_general_business"
else := tier_unrestricted.obligations                         if input.guardrail_profile == "tier_unrestricted"
else := tier_custom.obligations                               if input.guardrail_profile == "tier_custom"
else := set()

active_industries := tier_fdcpa_regulated.active_industries   if input.guardrail_profile == "tier_fdcpa_regulated"
else := tier_financial_regulated.active_industries            if input.guardrail_profile == "tier_financial_regulated"
else := tier_hipaa_regulated.active_industries                if input.guardrail_profile == "tier_hipaa_regulated"
else := tier_general_business.active_industries               if input.guardrail_profile == "tier_general_business"
else := tier_unrestricted.active_industries                   if input.guardrail_profile == "tier_unrestricted"
else := tier_custom.active_industries                         if input.guardrail_profile == "tier_custom"
else := set()

# -- Industry layer --------------------------------------------------------
# Only industries listed in the profile's active_industries are eval'd.

industry_deny_reasons contains reason if {
    some ind in active_industries
    some reason in data.insidellm.industry[ind].deny_reasons
}

industry_obligations contains obligation if {
    some ind in active_industries
    some obligation in data.insidellm.industry[ind].obligations
}

# -- Aggregate -------------------------------------------------------------

all_deny_reasons := humility.deny_reasons | profile_deny_reasons | industry_deny_reasons
all_obligations  := humility.obligations  | profile_obligations  | industry_obligations

# Final decision
decision := result if {
    result := {
        "allow": count(all_deny_reasons) == 0,
        "deny_reasons": all_deny_reasons,
        "obligations": sort_obligations(all_obligations),
        "profile": input.guardrail_profile,
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
    "profile": "",
}
