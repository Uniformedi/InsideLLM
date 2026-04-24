# InsideLLM — Plan (v3.2 cycle)

> **Single source of truth** for the v3.2 cycle through the
> 2026-05-12 portfolio showcase. Replaces and absorbs
> `docs/Master-Plan-v3.2.md` and `docs/Friday-Demo-Plan-2026-04-24.md`
> (both removed in the consolidation commit).
>
> **Status:** active as of 2026-04-23. If this doc and any source plan
> disagree, **this doc wins**.

---

## 0. What this plan replaces

| Source | Disposition |
|---|---|
| `docs/Master-Plan-v3.2.md` | **Consolidated here** — strategic framing + schedule + roadmap survive in §1–§3 and §7. File deleted. |
| `docs/Friday-Demo-Plan-2026-04-24.md` | **Consolidated here** — tactical demo plan survives in §5. File deleted. |
| `Project-Plan-3.2.html` | Archived in `../InsideLLM_Remnants/` — authoritative schedule survives as §4 below. |
| `Platform-Ultraplan-v3.md` | Archived in `../InsideLLM_Remnants/` — strategic north star survives as §1. |
| `Platform-Ultraplan-v3-GapAnalysis.md` | Archived — P0 queue survives as §3. |
| `Agents-Plan.md` (v1) | Archived — manifest schema survives in `configs/governance-hub/src/schemas/agent_manifest.schema.json`. |
| `PARENT-ORGANIZATION-DEMO-RUNBOOK.md` | Archived — showcase runbook survives as §6. |
| `TestPlan_V1.md` | Still in `docs/` — validation gate. |
| `FleetArchitecture.md` | Still in `docs/` — fleet topology reference. |
| `configs/industry-packs/README.md` | Still in place — Industry Pack platform concept. |
| `docs/sales/integrity-guardrail-briefing.md` | Archived — sales frame survives in §1 + §8. |

---

## 1. Strategic north star

InsideLLM is a self-hosted, on-premises **AI governance gateway** for
regulated organizations and portfolios of them. One deployment serves as
both platform (for one tenant) and reference tenant (for a portfolio of
many companies). The wedge is not capability — it is **integrity you can
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
FOSS on this platform. Paid vendors plug in as optional downstream
adapters that consume the platform's audit events. This is the FOSS-first,
no-vendor-lock-in principle — cost scales with team size, not the
other way around.

---

## 2. Product concept map

### 2.1 What shipped in 3.1.0 (the substrate)

- Fleet modularity (6 VM roles, capability registry, 60-second heartbeat)
- Unified SSO (Azure AD / Okta / AD / Keycloak)
- LiteLLM gateway with per-user budgets, rate limits, virtual keys
- Open WebUI with RAG, document Q&A
- **DLP** — inlet/outlet scanning, BLOCK/REDACT actions, 7 default categories
- **OPA policy engine** with:
  - Humility base (mandatory alignment, never disabled)
  - Six guardrail profiles: `tier_unrestricted`, `tier_general_business`,
    `tier_financial_regulated`, `tier_fdcpa_regulated`,
    `tier_hipaa_regulated`, `tier_custom`
  - Six industry overlays: FDCPA, HIPAA, SOX, PCI-DSS, FERPA, GLBA
- **Hash-chained audit** (SHA-256, periodic checkpoints, verify walker)
- DocForge (document generation)
- External data connectors with team RBAC + audit
- Admin Center SPA
- Claude Code CLI on every VM
- Ollama local models, Watchtower, Trivy, Grafana + Loki, Uptime Kuma,
  automated Postgres backups

### 2.2 What's planned for v3.2 (2026-05-12 target)

- **Declarative agent builder UI** — form authoring (Phases 2A + 2B of
  Project Plan 3.2)
- **Action catalog** — FastAPI core actions + Activepieces workflow
  piece (`insidellm-agent`) for portfolio-company IT teams
- **Portfolio dashboard** — seeded multi-tenant view
- **Dispute Handler** published agent exercising the full stack
- Eight merge-blocker fixes from Phase 1 (Activepieces pin, key splits,
  Postgres init, pgvector, LiteLLM bootstrap, VERSION plumbing, etc.)

### 2.3 New platform concept: Industry Packs *(this cycle)*

**Industry Packs** are curated bundles of vertical-specific configuration
layered on top of the already-shipped guardrail profiles + industry
overlays. One pack = one industry = starter kit for a regulated operation.

See `configs/industry-packs/README.md` for the full pattern.

**Shipping status (2026-04-23):**

| Pack | Status | Regulatory scope |
|---|---|---|
| `collections` | **sample / reference** | FDCPA, Reg F (shipped), TCPA, SOX, PCI-DSS, GLBA |
| `healthcare` | scaffolded | HIPAA, HITECH, 42 CFR Part 2 |
| `financial-services` | scaffolded | SOX, GLBA, PCI-DSS, Reg E/Z |
| `education` | planned (v3.3) | FERPA, COPPA |
| `property-management` | planned (v3.3) | FHA, state LL/T |

**Why this is first-class now.** The Friday portfolio-principal demo
needs to answer *"what about my thirty-four companies?"* in one breath.
Industry Packs are that answer — one platform, many deployments, each
with a vertical starter kit. This reinforces the FOSS-first principle:
no external vendor is needed to stand up a vertical.

### 2.4 Designed but deferred

- **Industry-discriminated event schema** — typed event payloads
  discriminated on `governance_instances.industry`, plugging into
  `audit_chain.append_event()` as a validation layer. Enables
  vendor-neutral audit export (webhook, git, OpenTelemetry, SARIF) and
  industry-specific required fields. Design complete; implementation is
  v3.3.
- **Ketryx adapter** — Governance Hub → Ketryx outbound adapter, strictly
  optional toggle. Design complete; implementation is v3.3.
- **Zero Trust posture** — NIST SP 800-207 alignment whitepaper +
  WireGuard fleet-mesh transport (via Headscale). Design complete;
  implementation is v3.3–v3.4.
- **Ticketing Hub** — multi-actor real-time ticketing (employees, agents,
  clients, vendors, fleet peers). Design complete; implementation is
  v3.3 depending on demand.

---

## 3. Pre-Phase-1 spec queue (from Gap Analysis P0.1–P0.4)

All are spec / schema work — no runtime code.

- **P0.1** — Merge agent manifest schemas (v1 YAML + v3 JSON) into a
  single canonical JSON Schema. Source of truth:
  `configs/governance-hub/src/schemas/agent_manifest.schema.json`.
- **P0.2** — Extend OPA input schema (tenant_id, agent_id, execution_id,
  session counters, data_classes).
- **P0.3** — Define guardrail profiles as versioned OPA bundles and
  align with `configs/opa/policies/profiles/`.
- **P0.4** — Finalize action catalog schema + registration API. Drafted
  in `configs/governance-hub/src/schemas/action_catalog.schema.json` —
  confirm coverage.

Status: queued; 1–2 days of spec work.

---

## 4. Binding schedule

```
2026-04-20 (Mon) ─ Phase 1 start — 8 merge-blockers
2026-04-22 (Wed) ─ Friday demo prep begins; Collections pack scaffolded
2026-04-24 (Fri) ─ FRIDAY PREVIEW DEMO to portfolio principal (§5)
2026-04-29 (Wed) ─ Phase 2A start — 3 designer backend endpoints
2026-04-30 (Thu) ─ Phase 2B start — form UI + 6 components (overlaps 2A by 1d)
2026-04-29 (Wed) ─ Phase 3 start — apply Phase 1 fixes, seed 2,184 patterns (parallel)
2026-05-04 (Mon) ─ Phase 4 start — custom Activepieces piece, audit webhook (parallel)
2026-05-08 (Fri) ─ Phases 2B, 3, 4 converge
2026-05-09 (Sat) ─ Demo prep begins (integration smoke + bug bash + rehearsal)
2026-05-12 (Tue) ─ MAY 12 PORTFOLIO SHOWCASE — portfolio of ~34 companies (§6)
```

**Critical path alert:** 19 working days of critical-path work vs. 17
working days available. Contingency: freeze designer at form-only +
YAML I/O, demo as draft, land preview + publish in 3.2.1 on
Friday 2026-05-15.

---

## 5. Friday preview demo — 2026-04-24

**Audience:** one board principal who owns a portfolio of ~34 companies.
**Stakes:** gating meeting. If it lands, InsideLLM is featured across
all portfolio companies at the 2026-05-12 showcase.
**Scope:** 3.1.0 as shipped + the Collections industry pack. **No v3.2
work.** The v3.2 visual agent builder stays May 12.

### 5.1 Operator framing

The principal is not a compliance officer and not an engineer. He is a
capital owner thinking about risk × revenue × capital efficiency across
a portfolio. Every segment of the demo should answer the implicit
question: *"what does this buy me across my portfolio?"*

Two value pillars, nothing else:

1. **Integrity you can audit** — OPA + DLP + hash-chained audit mean
   portfolio companies can adopt AI without each one writing a
   compliance program from scratch.
2. **One platform, many deployments** — Industry Packs mean a collections
   operation and a clinic each get a vertical starter kit without needing
   a separate product.

Do not mention Ketryx unless asked. Do not promise the visual builder.
Do not claim the product replaces human compliance review.

### 5.2 Critical path (do not break)

- 3.1.0 baseline running on the demo VM
- Collections industry pack at `configs/industry-packs/collections/`
- Seeded example tenant data in the portfolio dashboard
- Dispute Handler agent from the Collections pack published and live
- `lookup_account` + `draft_validation_notice` + `open_dispute_record`
  worker stubs returning canned but plausible responses
- Pre-populated audit chain with ~100 representative events
- RAG collection `collections-procedures` seeded with a handful of
  dispute procedures and state variation notes

### 5.3 Demo narrative (45 min = 30 demo + 15 Q&A buffer)

| # | Min | Segment | What the principal sees | What ships today |
|---|---|---|---|---|
| 0 | 3 | **Framing** — "integrity is the buying decision, not capability." One-slide pitch. | Slide. | — |
| 1 | 4 | **Portfolio overview** — Admin Center → portfolio dashboard. Example tenant + (time permitting) a second seeded tenant for multi-tenant view. | One page; compliance score per tenant, spend, DLP blocks, audit chain health. | Admin Center SPA, `governance_instances`, `governance_telemetry`. |
| 2 | 2 | **Industry Packs, one slide** — "Collections is the sample, Healthcare and Financial Services scaffolded." | Slide listing packs in `configs/industry-packs/`. | — |
| 3 | 6 | **Collections happy path** — operator opens OWUI, picks Dispute Handler, pastes a consumer dispute email. Agent looks up the account, drafts a §1692g acknowledgment letter via DocForge. | Draft in approval queue, not sent. | LiteLLM virtual key, OWUI custom model, DocForge, `tier_fdcpa_regulated` profile, `fdcpa-validation-notice.md.tpl`. |
| 4 | 4 | **Negative demo #1 — out-of-hours contact** — ask agent to place a callback "right now" (demo clock pre-set to 22:15 local). | OPA denies and cites §1692c(a)(1). Agent explains and offers an in-window time. | `tier_fdcpa_regulated.rego` hour rule. |
| 5 | 4 | **Negative demo #2 — RAG scope escape** — paste a prompt-injection asking the agent to read from `hr-confidential`. | OPA denies with the rule source visible. | `rag_scope.rego` + Humility base. |
| 6 | 3 | **DLP live** — paste a message with a full SSN. Upload a doc with a credit-card number. | Both redacted/blocked inline; audit entry written. | LiteLLM DLP callback + `collections-patterns.yaml`. |
| 7 | 3 | **Hash-chained audit** — curl `/api/v1/audit/chain/verify`. Show chain is valid. Then corrupt one entry in the DB and re-run. Chain breaks; first broken sequence is surfaced. | Live tamper-evidence. | `services/audit_chain.py`. |
| 8 | 2 | **Rego is the policy** — open `tier_fdcpa_regulated.rego` in Admin Center → Policies. "Your compliance team can read this. Your board can review it. It is the contract." | File viewer. | Shipped. |
| 9 | 1 | **Roadmap tease** — one slide: "Visual agent builder → May 12; Ketryx + Managed Agents → v3.3." No live demo. | Slide. | — |

Total live run: 26 minutes. 4 minutes slide framing. 15 minutes Q&A buffer.

### 5.4 Explicitly NOT in Friday's demo

- Visual agent builder UI (May 12, Phase 2B)
- Activepieces workflow pieces (Phase 4, not wired)
- Pattern library UI (seeded only, not surfaced)
- Ketryx integration (mention only if asked)
- Multi-tenant view with real data from every portfolio company (seed
  example + 1–2 synthetic; don't pretend)
- Claude Code CLI on the VMs (worth mentioning in conversation; no slot)

### 5.5 Prep checklist (Wed afternoon → Thu EOD)

| Task | Est. | Owner | Risk |
|---|---|---|---|
| Clean deploy of 3.1.0 on the demo VM (or snapshot-restore) | 2 h | ops | Low |
| Seed `governance_instances` with 2–3 tenants including the example tenant | 1 h | backend | Low |
| Register Collections pack agents in `governance_agents` as published | 1 h | backend | Low |
| Stub workers for `lookup_account`, `draft_validation_notice`, `open_dispute_record` — canned, deterministic, idempotent | 4 h | backend | **Med** |
| Pre-populate audit chain with ~100 events that tell a coherent story | 1 h | backend | Low |
| Seed RAG `collections-procedures` collection | 1 h | backend | Low |
| Seed RAG `hr-confidential` decoy collection (negative demo #2) | 0.5 h | backend | Low |
| Set demo VM system clock to 22:15 local for out-of-hours demo; verify OPA fires; **reset after rehearsal** | 0.5 h | ops | **Med** |
| Pre-draft rollback commands for each segment (skip if flaky) | 1 h | operator | Low |
| Rehearse end-to-end twice with fallback narration | 4 h | operator | Low |
| Print one-pager: Industry Packs list + "what's next" roadmap | 0.5 h | operator | Low |
| **Total** | **~17 h** | — | Fits in window |

### 5.6 Fallback scripts (one per segment)

- **Segment 1** (dashboard won't load): skip to Segment 2 slide; narrate.
- **Segment 3** (agent flakes): "the worker returns a canned response
  in this demo; production is faster." Move to 3a: open the
  already-approved draft in the approval queue manually.
- **Segment 4** (OPA doesn't deny): check demo clock. If wrong, fix and
  retry. If still broken, open the Rego file, read the rule aloud:
  "this is what's enforced in production."
- **Segment 5** (RAG denial doesn't fire): same fallback — open
  `rag_scope.rego`, read aloud.
- **Segment 6** (DLP doesn't redact): show the DLP pattern file
  (`collections-patterns.yaml`) and narrate.
- **Segment 7** (chain verify is slow): pre-run; present the result.
  Do tamper-evidence on a 10-entry sample for speed.

### 5.7 Success criteria

The demo succeeds if the principal leaves with one sentence he can
repeat to portfolio CEOs:

> **"This is the compliance substrate for AI at our companies."**

The demo also succeeds if he asks about two or more of: Ketryx, Managed
Agents, specific non-Collections industry packs, pricing/licensing.
Each is a buy signal.

The demo fails if the narrative becomes feature-centric ("look at the
DLP rules!") instead of outcome-centric ("your portfolio can adopt AI
without each company writing a compliance program").

### 5.8 Honesty check — say this out loud

> "This platform reduces the work of building and auditing AI operations
> in regulated contexts. It does not eliminate that work. Your companies'
> compliance teams still own the judgment calls. What we ship is the
> substrate — the OPA layer, the audit chain, the DLP, the document
> templates — that makes their judgment faster to exercise and easier
> to prove to a regulator."

Regulated buyers trust operators who say this out loud.

### 5.9 After the demo

- Send the principal a one-page PDF: portfolio dashboard screenshot,
  Industry Packs shipping table, short "how to pilot" note.
- No 30-page deck follow-up. The demo was the deck.
- If the principal signals yes, transition into v3.2 execution mode.
  The Gantt is already tight (19 crit-path days vs. 17 available);
  a Friday-go cannot slip the schedule further.

---

## 6. 2026-05-12 portfolio showcase

Adds the v3.2 visual builder demo to the Friday narrative, plus the
Activepieces piece and portfolio dashboard with multi-tenant data.

**Dependencies:**
- Phase 2A endpoints live
- Phase 2B form UI functional (at minimum: fields + pickers + JSON preview)
- Phase 4 Activepieces piece registered
- Dispute Handler agent seeded and live

**Fallback (Phase 2B slips):** freeze the designer as a YAML paste
interface, demo the Dispute Handler as pre-authored YAML, land the
form UI in 3.2.1.

---

## 7. What's left — best-value ranking

Ranked by value-per-effort for portfolio-company adoption and
regulated-market expansion. Every item here is post-May-12 unless
explicitly in v3.2 scope.

### 7.1 Near-term — v3.2 finish (by 2026-05-12)

| # | Item | Value | Effort | Status |
|---|---|---|---|---|
| 1 | P0.1–P0.4 spec work | Unblocks Phase 1 | 1–2 days | Queued |
| 2 | Eight merge-blocker fixes | Gates Phase 2/3/4 | Phase 1 (~5 days) | In progress |
| 3 | Declarative agent builder UI (Phases 2A + 2B) | **Demo centerpiece** | ~8 days | Critical path |
| 4 | Action catalog (FastAPI core + Activepieces piece) | Agent invocability | ~4 days | Phase 4 |
| 5 | Portfolio dashboard multi-tenant | Demo visual | ~1 day | Phase 3 |
| 6 | Dispute Handler end-to-end showcase | Demo proof | ~2 days | Phase 3 |

### 7.2 Post-May-12 — v3.3 priority stack

Ranked by value impact on **features / deployment speed / operating speed**.

| # | Item | Value lever | Effort |
|---|---|---|---|
| 1 | **Industry Packs 0.2.0 — Healthcare + Financial Services** | **Features** — widest TAM expansion per ship. One pack ≈ one vertical ≈ one sales cycle opened. | 2 weeks per pack |
| 2 | **Managed Agents runtime** | **Operating speed** — moves agent invocation under platform control; enables SaaS-like UX, fewer operator touch-points. | 3 weeks |
| 3 | **SBOM + SLSA provenance** (Syft + CycloneDX + cosign) | **Features** — regulated-buyer trust signal; supply-chain assurance unlocks federal-adjacent procurement. Cheap, high-leverage. | 1 week |
| 4 | **Event schema implementation** (industry-discriminated JSON Schemas + validator layer) | **Operating speed** — enables vendor-neutral audit export; prerequisite for Ketryx; also stands alone for customer OT integrations. | 2 weeks |
| 5 | **State overlays for Collections** (NY DFS, CA Rosenthal, IL) | **Features** — expands Collections pack TAM; ships on top of proven Reg F pattern. | 3 days per state |
| 6 | **Ketryx adapter** (Governance Hub → Ketryx) | **Features** — optional eQMS integration for regulated-medical-device-adjacent customers. Dependency on #4. | 1 week after #4 |
| 7 | **Zero Trust posture whitepaper + WireGuard fleet mesh** (Headscale) | **Deploy speed** + buyer trust — closes NIST SP 800-207 alignment gap; unlocks federal-adjacent procurement. | 2 weeks |
| 8 | **Industry Packs 0.3.0 — Education + Property Management** | **Features** — smaller TAM; lower priority unless a specific customer pulls. | 2 weeks per pack |
| 9 | **Ticketing Hub** (multi-actor real-time: employees / agents / clients / vendors / fleet peers) | **Features + operating speed** — novel differentiator, meaningful scope. Fit if a customer pulls for it. | 4 weeks |

### 7.3 Always-on infrastructure quality

| Item | Value | Effort |
|---|---|---|
| SOC 2 Type I engagement start | Procurement unlock (enterprise + public-sector) | 90-day audit cycle |
| Hyperscaler marketplace listings (Azure, AWS) post-SOC 2 | Passive lead flow + easier procurement | 1 week per listing |
| One MSP channel partner (regulated-industry) | Faster sales cycle than direct | 2 weeks onboarding |
| Industry conference talk submission (ACA International, HIMSS, RSA) | Pipeline + domain credibility | 1 day per submission |

### 7.4 Ecosystem & adjacencies

- **Secular sibling FOSS project** (public at `github.com/Uniformedi/secular`): AAIF-aligned AGENTS.md maintenance toolchain. Complements InsideLLM; both share Uniformedi authorship. Already shipped, no blocker.
- **AAIF participation** — membership / contribution evaluation. Low effort, passive credibility.
- **Humility / SAIVAS standalone licensing** — optional product split for Uniformedi IP. Decision deferred to Q4 2026.

### 7.5 Honest caveats on the ranking

- Customer demand can reshuffle this at any time. If a portfolio company
  signals urgency on state overlays, those promote above Industry Packs 0.2.0.
- Effort estimates assume founder-led engineering. A second engineer
  (targeted Q3 2026) compresses the stack roughly 2×.
- Regulatory environment can force reordering — an EU AI Act enforcement
  uptick or a state-AI-law effective date can pull items #7 (Zero Trust)
  or industry packs forward.

---

## 8. Honesty check (for demos and sales conversations)

InsideLLM is a **substrate**, not a finished compliance program. It
reduces the labor of building and auditing AI operations in regulated
contexts. It does not replace the judgment of the operator's compliance
counsel. Every Industry Pack is a defensible starting point, not a
finished compliance program.

FOSS eliminates license cost, not compliance effort. Validation
evidence, audit prep, and SME time survive the tool choice. Saying this
out loud to regulated buyers builds trust faster than claiming otherwise.

---

## 9. Usage guide

- **Day-to-day execution:** §3 (pre-phase queue) + §4 (schedule)
- **Friday 2026-04-24:** §5 (full tactical plan)
- **2026-05-12 showcase:** §6 (dependencies + fallback)
- **Sales / executive conversations:** §1 + §8
- **v3.3 roadmap decisions:** §7
- **Architecture questions ("can we ship a new vertical?"):**
  `configs/industry-packs/README.md`

If this doc and any source plan disagree, **this doc wins.** If this
doc is outdated, fix it here — do not silently patch a source plan.

---

*Consolidated 2026-04-23 from `Master-Plan-v3.2.md` + `Friday-Demo-Plan-2026-04-24.md`. Owner: Dan Medina, Uniformedi LLC.*
