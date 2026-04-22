# InsideLLM — Master Plan (v3.2 cycle)

> **Authoritative, merged plan** superseding the role of any single
> pre-existing plan doc for day-to-day execution. The source docs remain
> in `docs/` as references; this file is the single doc the team works
> against for the v3.2 cycle through the 2026-05-12 portfolio showcase.
>
> **Status:** active as of 2026-04-22.

## 0. Plan provenance — what this merges

| Source | Contribution | Disposition |
|---|---|---|
| `Project-Plan-3.2.html` | **Binding schedule** — task-level Gantt to 2026-05-12 | Authoritative for dates and phase gates |
| `Platform-Ultraplan-v3.md` | **Strategic north star** — 3-layer architecture, 34-company portfolio story | Authoritative for "why"; non-binding on dates |
| `Platform-Ultraplan-v3-GapAnalysis.md` | **Pre-Phase-1 queue** — P0.1–P0.4 spec tasks + 3.1.0 inventory | Folded into §3 below |
| `Agents-Plan.md` (v1) | Manifest schema kernel | **Superseded.** Schema survives inside §4.2 of v3 |
| `PARENT-ORGANIZATION-DEMO-RUNBOOK.md` | May 12 showcase script | Authoritative for May 12 demo execution |
| `TestPlan_V1.md` | Smoke-test checklist (8 items) | Authoritative validation gate |
| `FleetArchitecture.md` | Fleet topology shipped in 3.1.0 | Reference only |
| `docs/sales/integrity-guardrail-briefing.md` | Integrity-as-buying-decision pitch | Authoritative sales frame |
| `docs/Friday-Demo-Plan-2026-04-24.md` | **NEW — Friday preview demo** to portfolio principal | Gating meeting; see §5 |
| `configs/industry-packs/README.md` | **NEW — Industry Pack platform concept** | See §2.3 |

---

## 1. Strategic north star (from Ultraplan v3, condensed)

InsideLLM is a self-hosted, on-prem **AI governance gateway** for regulated
organizations and portfolios of them. One deployment serves as both
platform (for one tenant) and reference tenant (for a portfolio of
~34 companies). The wedge is not capability — it is **integrity you can
audit**. Buyers do not need capability differentiation from Claude; they
need an auditable substrate that makes AI safe to adopt in their regulated
operations.

The platform is three layers:

1. **Declarative agent builder** — visual authoring of `Agent` manifests
   (ships May 12 with v3.2).
2. **Orchestration** — Open WebUI, LiteLLM with DLP, OPA with Humility +
   industry profiles, hash-chained audit (shipped 3.1.0).
3. **Tool factory** — FastAPI + Activepieces + MCP backends for catalog
   actions (partial; core catalog shipping May 12, portfolio extensibility
   later).

A customer entering a regulated market should be able to do so using only
FOSS on this platform. Paid vendors (Ketryx, eQMS suites) plug in as
optional downstream adapters that consume the platform's audit events.
This is the FOSS-first, no-vendor-lock-in principle — cost scales with
team size, not the other way around.

---

## 2. Product concept map

### 2.1. What shipped in 3.1.0 (the substrate)

- Fleet modularity (6 VM roles, capability registry, 60s heartbeat).
- Unified SSO (Azure AD / Okta / AD / Keycloak).
- LiteLLM gateway with per-user budgets, rate limits, virtual keys.
- Open WebUI with RAG, document Q&A.
- **DLP** — inlet/outlet scanning, BLOCK/REDACT actions, 7 default categories.
- **OPA policy engine** with:
  - Humility base (mandatory alignment, never disabled).
  - Six guardrail profiles: `tier_unrestricted`, `tier_general_business`,
    `tier_financial_regulated`, `tier_fdcpa_regulated`,
    `tier_hipaa_regulated`, `tier_custom`.
  - Six industry overlays: FDCPA, HIPAA, SOX, PCI-DSS, FERPA, GLBA.
- **Hash-chained audit** (SHA-256, periodic checkpoints, verify walker).
- DocForge (document generation).
- External data connectors with team RBAC + audit.
- Admin Center SPA.
- Claude Code CLI on every VM.
- Ollama local models, Watchtower, Trivy, Grafana + Loki, Uptime Kuma,
  automated Postgres backups.

### 2.2. What's planned for v3.2 (May 12 target)

- **Declarative agent builder UI** — form authoring (Phases 2A + 2B of
  Project Plan 3.2).
- **Action catalog** — FastAPI core actions + Activepieces workflow
  piece (`insidellm-agent`) for portfolio-company IT teams.
- **Portfolio dashboard** — seeded multi-tenant view.
- **Dispute Handler** published agent exercising the full stack.
- Eight merge-blocker fixes from Phase 1 (Activepieces pin, key splits,
  Postgres init, pgvector, LiteLLM bootstrap, VERSION plumbing, etc.).

### 2.3. New platform concept: Industry Packs *(added this cycle)*

**Industry Packs** are curated bundles of vertical-specific configuration
layered on top of the already-shipped guardrail profiles + industry
overlays. One pack = one industry = starter kit for a regulated operation.

See `configs/industry-packs/README.md` for the full pattern.

**Shipping status (2026-04-22):**

| Pack | Status | Regulatory scope |
|---|---|---|
| `collections` | **sample / reference** | FDCPA, Reg F (planned), TCPA, SOX, PCI-DSS, GLBA |
| `healthcare` | scaffolded | HIPAA, HITECH, 42 CFR Part 2 |
| `financial-services` | scaffolded | SOX, GLBA, PCI-DSS, Reg E/Z |
| `education` | planned (0.3.0) | FERPA, COPPA |
| `property-management` | planned (0.3.0) | FHA, state LL/T |

**Why this is a first-class concept now:** Friday's portfolio-principal
demo needs to answer "what about my 34 companies?" in a single breath.
Industry Packs are the answer — one platform, thirty-four deployments,
each with a vertical starter kit. This also reinforces the FOSS-first
principle: no external vendor is needed to stand up the vertical.

### 2.4. Planned: industry-discriminated event schema *(designed this cycle, not yet coded)*

A typed event payload schema discriminated on `governance_instances.industry`,
plugging into the existing `audit_chain.append_event()` path as a
validation layer. Enables:

- Vendor-neutral event export (webhook, git, OpenTelemetry, SARIF).
- Industry-specific required fields — e.g. FDCPA contact-window flags and
  §1692g dispute-window state on Collections events, HIPAA
  minimum-necessary justification on Healthcare events, SOX control
  references on Financial Services events.
- Clean seams for downstream adapters without forcing any specific
  vendor into the canonical stream.

Design complete. **Implementation deferred** — not on the May 12 path.
Tracked in §4 as a v3.3 deliverable.

### 2.5. Planned: Ketryx integration *(optional adapter)*

Adapter inside the Governance Hub that forwards validated compliance
events to Ketryx for customers in regulated markets. Strictly optional
toggle; customers must be able to meet regulatory requirements with FOSS
alone.

Design complete. Implementation tracked as a v3.3 deliverable.

---

## 3. Pre-Phase-1 spec queue (from Gap Analysis P0.1–P0.4)

These must be specced before Project Plan 3.2 Phase 1 proceeds. All are
spec / schema work — no runtime code.

- **P0.1** — Merge agent manifest schemas. Consolidate the v1 YAML schema
  (from Agents-Plan v1) and the v3 JSON schema (from Ultraplan v3 §2.2)
  into a single canonical JSON Schema. Source of truth: `configs/governance-hub/src/schemas/agent_manifest.schema.json`.
- **P0.2** — Extend OPA input schema (tenant_id, agent_id, execution_id,
  session counters, data_classes). Per Ultraplan v3 §5.2.
- **P0.3** — Define guardrail profiles as versioned OPA bundles and align
  with the shipped profile tiers in `configs/opa/policies/profiles/`.
- **P0.4** — Finalize action catalog schema + registration API. Already
  drafted in `configs/governance-hub/src/schemas/action_catalog.schema.json`
  — confirm coverage.

Status: queued; 1–2 days of spec work.

---

## 4. Binding schedule (from Project Plan 3.2)

```
2026-04-20 (Mon) ── Phase 1 start — 8 merge-blockers
2026-04-22 (Wed) ── TODAY — Friday demo prep begins; Collections pack scaffolded
2026-04-24 (Fri) ── FRIDAY PREVIEW DEMO to portfolio principal (§5)
2026-04-29 (Wed) ── Phase 2A start — 3 designer backend endpoints
2026-04-30 (Thu) ── Phase 2B start — form UI + 6 components (overlaps 2A by 1d)
2026-04-29 (Wed) ── Phase 3 start — apply Phase 1 fixes, seed 2,184 patterns (parallel)
2026-05-04 (Mon) ── Phase 4 start — custom Activepieces piece, audit webhook (parallel)
2026-05-08 (Fri) ── Phases 2B, 3, 4 converge
2026-05-09 (Sat) ── Demo prep begins (integration smoke + bug bash + rehearsal)
2026-05-12 (Tue) ── MAY 12 PORTFOLIO SHOWCASE — 34 companies (§6)
```

**Critical path alert (from Project Plan 3.2):** 19 working days of
critical-path work vs. 17 working days available. Contingency: freeze
designer at form-only + YAML I/O, demo as draft, land preview + publish
in 3.2.1 on Friday 2026-05-15. See `Project-Plan-3.2.html` §Risks.

---

## 5. Friday preview demo — 2026-04-24

**Audience:** one board principal who owns 34 portfolio companies.
**Stakes:** gating meeting for the May 12 showcase.

Full plan in `docs/Friday-Demo-Plan-2026-04-24.md`. Summary:

- **Scope:** 3.1.0 as shipped + the Collections industry pack. No v3.2 work.
- **Narrative:** Integrity you can audit × one platform / thirty-four
  deployments.
- **Live segments:** portfolio dashboard → industry packs overview →
  Dispute Handler happy path → two OPA denials (out-of-hours, scope
  escape) → DLP live → hash-chained audit tamper-evidence → Rego
  source visibility → roadmap tease.
- **Success criterion:** the principal leaves with one sentence —
  "This is the compliance substrate for AI at our companies."

Prep: ~17 h of focused work, fits the Wed–Thu window before the demo.

---

## 6. May 12 portfolio showcase

Full runbook in `docs/PARENT-ORGANIZATION-DEMO-RUNBOOK.md`. Adds the v3.2
visual builder demo to the Friday narrative, plus the Activepieces piece
and portfolio dashboard with multi-tenant data.

**Dependencies (from Project Plan 3.2):**
- Phase 2A endpoints live
- Phase 2B form UI functional (at minimum: fields + pickers + JSON preview)
- Phase 4 Activepieces piece registered
- Dispute Handler agent seeded and live

**Fallback (if Phase 2B slips):** freeze the designer as a YAML paste
interface, demo the Dispute Handler as a pre-authored YAML, land the
form UI in 3.2.1.

---

## 7. Post-v3.2 roadmap (v3.3 and beyond)

| Track | What | Status |
|---|---|---|
| Industry Packs 0.2.0 | Fill in Healthcare + Financial Services (agents, DLP, documents) | Queued |
| Industry Packs 0.3.0 | Education + Property Management packs | Planned |
| Reg F overlay | `configs/opa/policies/industry/reg_f.rego` — 7-in-7 call cap + §1006.18(d) mini-Miranda; loaded by `tier_fdcpa_regulated`. Unit-tested. | **Shipped (this cycle)** |
| Event schema implementation | `services/compliance_events.py` validator layer + industry-discriminated JSON Schemas | Designed |
| Ketryx adapter | Governance Hub → Ketryx outbound adapter, toggle in setup wizard | Designed |
| Managed Agents runtime | Bring agent invocation under platform control (deferred from 3.2 per Project Plan) | Planned 3.3 |
| SBOM + SLSA provenance | Syft + CycloneDX emission + cosign signing on release artifacts | Queued |
| State overlays (Collections) | NY DFS, CA Rosenthal, IL; selectable at setup | Planned |

---

## 8. Honesty check (read before any demo or sales conversation)

InsideLLM is a **substrate**, not a finished compliance program. It
reduces the labor of building and auditing AI operations in regulated
contexts. It does not replace the judgment of the operator's compliance
counsel. Every Industry Pack is a defensible starting point, not a
finished compliance program.

FOSS eliminates license cost, not compliance effort. Validation evidence,
audit prep, and SME time survive the tool choice. Saying this out loud
to regulated buyers builds trust faster than claiming otherwise.

---

## 9. How to use this doc

- **For day-to-day execution:** work against §4 (schedule) and §3
  (pre-phase queue).
- **For Friday 2026-04-24:** work against `docs/Friday-Demo-Plan-2026-04-24.md`.
- **For May 12 showcase:** work against `docs/PARENT-ORGANIZATION-DEMO-RUNBOOK.md`.
- **For sales / executive conversations:** frame from §1 + §8.
- **For v3.3 planning:** pull from §7.
- **For architecture questions about "can we ship a new vertical":**
  read `configs/industry-packs/README.md`.

If this doc and any of its source plans disagree, **this doc wins**.
If something in this doc is outdated, fix it here — do not silently
patch the source plan.
