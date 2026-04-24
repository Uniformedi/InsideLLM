# Guardrail Profiles (OPA)

Named OPA policy bundles that an agent manifest references via
`guardrails.profile`. Each profile composes:

- **Humility** (always, non-negotiable) — SAIVAS framework from *Uniform
  Gnosis, Volume I*. Mandatory for every request.
- **Industry overlays** — HIPAA, FDCPA, SOX, PCI-DSS, FERPA, GLBA. The
  profile selects which ones apply.
- **Profile-specific rules** — e.g. `tier_fdcpa_regulated` adds the
  FDCPA-permitted-hours contact check and approval escalation for
  collection communications.

## Profiles (v1.0)

| Profile | Applies | Loads industry policies | Profile rules |
|---|---|---|---|
| `tier_unrestricted` | Internal analytics, R&D | none | Log only, no blocking |
| `tier_general_business` | General knowledge work | none | PII redaction in logs, standard budgets |
| `tier_financial_regulated` | SOX + PCI scope | `sox`, `pci_dss` | Full audit trail, approval for external actions, model allowlist |
| `tier_fdcpa_regulated` | Collections | `fdcpa` + financial | FDCPA hours check, §1692g validation tracking, consumer-comm approval |
| `tier_hipaa_regulated` | Healthcare | `hipaa` | PHI handling, minimum-necessary standard, BAA-covered models only |
| `tier_custom` | Operator-defined | configurable | Extends a base profile with company-specific rules |

## Selection at runtime

Every request carries `input.guardrail_profile` (set by the
manifest-to-runtime translator when it provisions the agent's LiteLLM
virtual key). The aggregation policy (`decision.rego`) consults the
profile's `active_industries` set and only evaluates those industry
policies for this request.

## Portfolio policy inheritance (Ultraplan v3 §5.3)

```
Parent Portfolio portfolio baseline
  └── Company override (company-specific additions)
       └── Agent manifest profile (per-agent constraints)
            └── Session context (runtime evaluation)
```

A child can only **tighten** the parent's rules, never loosen. Enforced
by the aggregation policy: `allow` = false if ANY level denies.

## Authoring new profiles

1. Create `tier_<name>.rego` in this directory.
2. Package name: `insidellm.profile.tier_<name>`.
3. Export:
   - `active_industries` — set of industry-package names (without
     `insidellm.industry.` prefix)
   - `deny_reasons` — set of profile-specific denials
   - `obligations` — set of profile-specific obligations
4. Test with `opa test ./configs/opa/policies/`.
5. Register the new value in the
   `GuardrailProfile` enum in
   `configs/governance-hub/src/schemas/agents.py` so manifests can
   reference it.

## Policy hygiene

- Every rule must include a `reason` or `audit.log` obligation — no
  silent effects.
- `default allow := false` everywhere. OPA evaluation errors fail closed.
- Denials carry a human-readable `reason` string for the UI.
- Obligations use the standard types: `audit.log`, `audit.tag`,
  `review.queue`, `filter.fields`, `require.attestation`.
