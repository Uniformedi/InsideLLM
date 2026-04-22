# Collections — Sample Industry Pack

This is the **reference implementation** of an InsideLLM Industry Pack. Other
industry packs (Healthcare, Financial Services, Education, Property Management,
etc.) pattern after the structure in this directory.

## What an Industry Pack is

An Industry Pack is a curated bundle of the things a specific regulated
vertical needs on day one, layered on top of the platform's already-shipped
OPA profile + industry overlays. A pack never replaces platform code — it
adds configuration.

```
configs/industry-packs/<industry>/
├── manifest.yaml           # pack metadata, regulatory scope, what it adds
├── README.md               # this file
├── agents/                 # pre-authored agent manifests (YAML)
├── dlp/                    # industry-specific DLP patterns
├── documents/              # DocForge document templates
├── prompts/                # system-prompt fragments / Humility overlays
├── dashboards/             # Grafana dashboard JSON
└── seed/                   # demo-only sample data, clearly marked
```

When an admin selects an industry in the setup wizard, the platform:
1. Writes `industry=<id>` onto the instance's `governance_instances` row.
2. Activates the pack's declared `guardrail_profile` in OPA.
3. Registers the pack's agents into `governance_agents`.
4. Registers the pack's DLP patterns into the LiteLLM DLP callback.
5. Installs the DocForge templates.
6. Seeds the pack's Grafana dashboards (if present).

## What already ships in 3.1.0 that this pack reuses

- **Guardrail profile**: `configs/opa/policies/profiles/tier_fdcpa_regulated.rego`
  (enforces FDCPA §1692c 8am–9pm contact hours, consumer-communication
  approval escalation, model allowlist, Discord block).
- **Industry overlays**: `configs/opa/policies/industry/{fdcpa,sox,pci_dss}.rego`
- **Hash-chained audit**: `services/audit_chain.py` — every decision this pack
  produces is chained and tamper-evident.
- **Humility base**: `configs/opa/policies/humility/base.rego` — mandatory
  alignment layer, never disabled.
- **DLP pipeline**: LiteLLM callback that consumes pattern YAMLs.
- **DocForge**: generates .docx / .pdf / .md from templates.

This pack does not duplicate any of the above — it references them.

## What this pack adds

### Agents (pre-authored, published as `draft`)

| Agent | Purpose | Guardrail profile |
|---|---|---|
| `dispute-handler` | Opens an FDCPA §1692g dispute record, looks up the account, drafts an acknowledgment letter | `tier_fdcpa_regulated` |
| `validation-notice-writer` | Produces a §1692g(a) validation notice on first contact | `tier_fdcpa_regulated` |
| `skip-tracer` | Read-only debtor lookup (no communication, no comms authority) | `tier_fdcpa_regulated` |
| `compliance-reviewer` | Supervisor-only; reviews pending consumer communications in the approval queue | `tier_fdcpa_regulated` |

Every agent ships as `draft`. Nothing auto-publishes. Operator reviews the
manifest in the Admin Center and clicks publish.

### DLP patterns

Collections-specific PII that the generic pack doesn't carry: debtor account
numbers, bankruptcy case numbers, medical-collection flags, bank-level routing
numbers in ACH-related prompts, garnishment case identifiers.

### Document templates (DocForge)

Pre-drafted, §1692g-compliant boilerplate for the four communications an
agent most commonly produces. Each template includes mandatory FDCPA
disclosures; removing them is a compile-time check in the template engine.

### System prompts

A Humility overlay that carries Collections-specific "what to refuse" scripts:
mini-Miranda compliance ("this is a communication from a debt collector,
any information obtained will be used for that purpose"), no abusive language,
no threats of action not intended to be taken, no misrepresentation of legal
status.

## What this pack explicitly does NOT do

- **Does not collect debt.** No payment rails, no ACH, no card capture. The
  agents draft letters and look up records; they do not move money.
- **No credit bureau reporting.** FCRA Metro 2 out of scope.
- **No litigation workflow.** If a matter goes to legal, it leaves InsideLLM.

## Roadmap (declared in manifest.yaml `roadmap:`)

- **0.2.0** — Reg F §1006.14(b) 7-in-7 call-frequency guard (new
  `industry/reg_f.rego` overlay, with tests). TCPA consent obligation.
- **0.3.0** — State overlays (NY DFS, CA Rosenthal, IL) selectable at setup.

## Honesty check

This pack is a **starting point**, not a finished compliance program. The
FDCPA/Reg F policies embedded here are configurable defaults; your
compliance counsel will want to review them before production use. The
platform reduces the effort of building and auditing a collections desk. It
does not eliminate the effort. Your counsel's sign-off is still required.

## How other industry packs pattern after this

A new industry pack (e.g. `healthcare`, `financial-services`) copies this
directory structure, swaps:
- `manifest.yaml` regulatory scope and `guardrail_profile`
- `agents/` for vertical-appropriate agents
- `dlp/` for the industry's PII categories
- `documents/` for the industry's standard forms

…and leaves the platform plumbing untouched.
