# Industry Packs

Industry Packs are curated bundles of the things a specific regulated vertical
needs on day one — agents, DLP patterns, document templates, guardrail
profile selection — layered on top of the platform's already-shipped OPA
profile + industry overlays. A pack never replaces platform code; it adds
configuration.

## Why industry packs exist

Regulated operators don't want a blank `agents/` directory and a list of
OPA profiles. They want a starter kit for their vertical that is
defensible out of the box and cheap to modify. Industry Packs are that
starter kit. Each pack reduces time-to-value from *"now we configure a
compliance program"* to *"now we review our compliance program."*

This also matches the InsideLLM FOSS-first philosophy: **a customer can
enter their regulated market using only what ships with this repo.** No
paid vendor is required to stand up the integrity layer. Paid vendors
(Ketryx and equivalents) plug in as optional downstream adapters that
consume the same audit events the pack emits.

## Pack structure (pattern)

```
configs/industry-packs/<industry>/
├── manifest.yaml       # pack metadata, regulatory scope, what it adds
├── README.md           # overview, what's in scope vs. out of scope
├── agents/             # pre-authored agent manifests (YAML)
├── dlp/                # industry-specific DLP patterns
├── documents/          # DocForge document templates
├── prompts/            # system-prompt fragments / Humility overlays
├── dashboards/         # Grafana dashboard JSON
└── seed/               # demo-only sample data, clearly marked
```

Every pack uses the **same four levers** to localize to an industry:

1. **`guardrail_profile`** — one of the shipped tiers in `configs/opa/policies/profiles/`.
2. **`industry_overlays`** — one or more shipped Regos in `configs/opa/policies/industry/`.
3. **Agent manifests** — vertical-appropriate, shipped as `draft` (never auto-published).
4. **Document templates** — vertical-standard boilerplate with hardcoded compliance disclosures.

## Shipping status (2026-04-22)

| Pack | Status | Regulatory scope | Notes |
|---|---|---|---|
| [`collections`](collections/README.md) | **sample / reference** | FDCPA, Reg F, TCPA, SOX, PCI-DSS, GLBA | Reference implementation — other packs pattern after this structure. |
| [`healthcare`](healthcare/README.md) | scaffolded | HIPAA, HITECH, 42 CFR Part 2 | Manifest only. Agents + templates shipping 0.2.0. |
| [`financial-services`](financial-services/README.md) | scaffolded | SOX, GLBA, PCI-DSS, Reg E, Reg Z | Manifest only. Agents + templates shipping 0.2.0. |
| `education` | planned | FERPA, COPPA | Ships 0.3.0. |
| `property-management` | planned | FHA, state LL/T | Ships 0.3.0. |

Packs are **opt-in**. Selecting `industry=<id>` at setup activates the pack's
guardrail profile, registers its agents in `draft` state, and installs its
DLP patterns and document templates.

## How setup wires into packs

The governance-hub setup wizard reads this directory on first boot and
populates the industry dropdown with any pack whose status is `sample`,
`preview`, or `ga`. Packs in `scaffolded` or `planned` state are listed
under "coming soon" and do not appear in the dropdown.

When an admin selects an industry:

1. `governance_instances.industry` is set to the pack id.
2. OPA loads the pack's declared `guardrail_profile`.
3. Pack agents are registered in `governance_agents` with `status=draft`.
4. Pack DLP patterns are pushed into the LiteLLM DLP callback.
5. DocForge registers the pack's templates.
6. Grafana imports the pack's dashboards (if present).
7. A seed SQL file, if declared, is **not** auto-run — operator must
   execute it explicitly (sample data is demo-only).

## Honesty check

No Industry Pack is a finished compliance program. Every pack is a
**defensible starting point**. The platform reduces the labor of
building and auditing a regulated operation. It does not replace the
judgment of the operator's compliance counsel. Ship accordingly.

## How to author a new pack

1. Copy `collections/` to `<your-industry>/`.
2. Rewrite `manifest.yaml`: new id, regulatory scope, `guardrail_profile`
   (pick from shipped tiers), `industry_overlays` (pick from shipped
   Regos, or flag a new overlay as 0.2.0 work).
3. Rewrite `README.md` to describe the vertical and in/out-of-scope.
4. Replace agent YAMLs with vertical-appropriate drafts.
5. Replace DLP patterns with the vertical's PII set.
6. Replace document templates. Every template must include a
   `{# REQUIRED_BY_<REG> ... #}` marker on any mandatory disclosure so
   the template compiler can refuse removals.
7. Write the Humility overlay describing the vertical's refusal scripts.
8. Open a PR. Tests run against the OPA profile and the manifest schema.

The `collections/` pack is the canonical worked example; lean on it.
