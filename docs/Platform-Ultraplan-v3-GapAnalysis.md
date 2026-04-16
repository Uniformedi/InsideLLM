# Platform Ultraplan v3 — Gap Analysis

**Source plan:** [docs/Platform-Ultraplan-v3.md](Platform-Ultraplan-v3.md)
**Plan date:** 2026-04 (reframe from "add n8n" to "Parent Organization portfolio-wide platform")
**This doc:** 2026-04-16 — snapshot of what's built vs. what the plan requires

The v3 ultraplan reframes InsideLLM from "collections AI for Organization" to
"portfolio-wide AI operations platform deployed across 32 Parent Organization
companies, with Organization as reference tenant." Much of the plumbing already
exists. This document enumerates what's shipped, what's partial, and
what requires net-new work.

---

## Layer-by-layer status

### Layer 1 — Declarative Agent Builder (user-facing product)

| Capability (from plan §2) | Current state | Gap |
|---|---|---|
| Agent builder UI — name/describe/instructions/knowledge/actions/guardrails/publish | **Not built.** OWUI "Custom Models" is a primitive, not a structured builder. | **Build Phase 1.** |
| Agent manifest schema (JSON) | **Drafted** in [docs/Agents-Plan.md](Agents-Plan.md) v1.0 (YAML). Needs merge with v3 plan schema. | Schema reconciliation. |
| `governance_agents` table + CRUD router | **Not built.** (`docs/Agents-Plan.md` specified as Phase 1 step 1.) | Build. ~6h. |
| Manifest-to-runtime translation layer (~1500-2000 lines Python) | **Not built.** This is the IP core. | Build Phase 1. |
| Conversation starters, icons, descriptions | Not built. Trivial once manifest schema lands. | Build Phase 1. |
| Guided instruction lint (anti-patterns, missing guardrail refs) | Not built. | Phase 2. |
| Version pinning by manifest hash | Not built. | Phase 2. |

### Layer 2 — Orchestration Platform

| Capability | Current state | Gap |
|---|---|---|
| Open WebUI | ✅ Deployed on every primary/gateway VM |  |
| LiteLLM proxy with virtual keys + budgets | ✅ Deployed; per-key budgets working |  |
| DLP sidecar | ✅ Active as LiteLLM callback + frontend filter |  |
| OPA engine | ✅ Deployed; Humility + industry overlays |  |
| Per-agent virtual key (budget + model allowlist from manifest) | **Partial** — LiteLLM supports it; translation layer would mint/destroy per-agent keys. | Build in Phase 2. |
| RAG collections per-agent scope | **Partial** — OWUI has collections; need per-agent binding enforcement. | Build Phase 1. |
| Function calling / MCP tools | **Not wired.** LiteLLM 1.76 supports tool_use; we don't have an action catalog surfacing it. | Build Phase 1. |

### Layer 3 — Tool Factory (polyglot)

**Design assumption:** The tool factory is not a single product. It's a
deliberate polyglot mix so each action picks the right backend for its
shape — and so no single vendor's license or roadmap change can hold
the platform hostage.

| Backend | When to use | Lifecycle owner | License |
|---|---|---|---|
| **FastAPI** (sync HTTP) | Simple lookups, small API calls, anything <200 ms p95 | Platform dev (Dan) for core; company dev for custom | BSL 1.1 (same as platform) |
| **FastAPI + Celery** | Async / queued work, retries, long-running jobs, high-volume workloads | Platform dev | BSL 1.1 |
| **n8n Community Edition** | Multi-step orchestration visible to non-dev IT staff who want a canvas; webhook-triggered flows | Company IT (per-tenant) | Sustainable Use License (internal use OK) |
| **Activepieces** | Same niche as n8n but OSI-licensed (MIT) — hedges n8n license risk; simpler node library, quicker for basic SaaS integrations | Company IT (per-tenant, alternative to n8n) | MIT |
| **MCP server** (HTTP or stdio) | Tools that need to appear as first-class Claude function-calling targets; cross-agent reusable | Platform dev | Protocol-standard, backend license varies |

The action catalog abstracts all five behind one registration schema
(Ultraplan v3 §3.1) — the agent manifest never names a backend, only
an `action_id`.

**Per-tenant choice:** Each company picks n8n **or** Activepieces (not
both) based on which their IT staff prefers. FastAPI and Celery are
always present. MCP servers are shared across backends.

| Capability | Current state | Gap |
|---|---|---|
| Action catalog (registration + backend abstraction) | **Not built.** | Build Phase 1. |
| FastAPI-backed actions | **Partial** — DocForge, Governance Advisor, Fleet Mgmt, System Designer, Data Connector exist as one-off OWUI Tools. Not registered as a catalog. | Wrap existing tools in catalog registration. ~1 day. |
| Celery worker + Redis queue for async actions | **Not built.** Redis already deployed. | Build Phase 1-2. ~2 days. |
| MCP server for catalog actions | **Not built.** | Build Phase 1. |
| n8n Community Edition (per-tenant opt-in) | **Not built.** | Build Phase 3. |
| Activepieces (per-tenant opt-in, n8n alternative) | **Not built.** | Build Phase 3. |
| Backend parity test (any backend type satisfies the catalog contract) | Not written. | Part of Phase 1 catalog API. |
| Company-specific vs core catalog | Conceptual. | Derives from catalog API shape. |

### Governance — Humility at portfolio scale

| Capability | Current state | Gap |
|---|---|---|
| OPA Humility policy base | ✅ `configs/opa/policies/humility/base.rego` |  |
| Industry overlays (HIPAA, SOX, FERPA, GLBA, FDCPA, PCI-DSS) | ✅ `configs/opa/policies/industry/*.rego` |  |
| `tier_fdcpa_regulated` / `tier_hipaa_regulated` as named guardrail profiles | **Partial** — policies exist; no "profile" object the manifest can reference. | Build Phase 1. |
| Portfolio policy inheritance (Parent Organization → Company → Agent) | **Not built.** Current model is per-VM, no parent-child composition. | Build Phase 4. |
| OPA input schema extended (tenant_id, agent_id, execution_id, iteration_count, session_token_count, data_classes_in_context, etc.) | **Partial.** Some fields present. Needs expansion + instrumentation. | Build Phase 1. |
| Hash-chained audit (SHA-256) | ✅ `governance_audit_chain` |  |
| Dual sink (Datadog + WORM) | **Missing WORM.** Datadog not wired. | Phase 2. |

### Multi-Tenant (Parent Organization portfolio, 32 companies)

| Capability | Current state | Gap |
|---|---|---|
| Per-tenant stack isolation | ✅ Stream A-E fleet work; each VM is a tenant | Plan calls for one stack per **company** (not per department). Small reframe. |
| Tenant provisioning automation | ✅ `fleet.yaml` + `Render-Fleet.ps1` + `Deploy-Fleet.ps1` + `Join-Fleet.ps1` | Good enough for 10 tenants; revisit at 10. |
| Vector store with tenant-isolated partitions | **Not in architecture.** Each VM has its own OWUI → implicit isolation. Need explicit enforcement for shared-stack future. | Phase 5. |
| Portfolio observability dashboard (Parent Organization cross-tenant view) | **Not built.** Admin Hub shows fleet-wide via capability registry but not aggregates. | Build Phase 4. |
| Anonymized aggregate export (no raw data) | **Not built.** | Phase 4. |
| Fleet manifest for 32 tenants | ✅ `fleet.yaml` handles this shape today. | May need upgrade at N>10. |

### Event Notifications & ChatOps

| Capability | Current state | Gap |
|---|---|---|
| Slack webhook | ✅ `ops_alert_webhook` var exists in Gov-Hub | Single URL, ops-only. |
| Teams integration | **Not built.** | Build Phase 2. |
| Notification emitter sub-workflow with DLP in-path | **Not built.** | Build Phase 2. |
| Adaptive Cards (Teams) / Block Kit (Slack) | **Not built.** | Build Phase 2. |
| Human-in-the-loop approval via chat | **Not built.** Gov-Hub approvals exist as router `/api/v1/changes/{id}/approve` but not chat-delivered. | Build Phase 2. |
| Slash commands `/insidellm agents`, `/catalog`, `/usage` | **Not built.** | Build Phase 2. |
| Channel topology (`#insidellm-ops`, `-security`, `-audit`, `-agents`) | **Not built.** | Config-only; operator sets up. |

### Supporting Infrastructure

| Capability | Current state | Gap |
|---|---|---|
| Per-VM Claude Code CLI (Nested Dan) | ✅ **Just shipped** (commit `28c4a23`, task #31) |  |
| Local package cache (apt + Docker registry) | ✅ Shipped (`17089e7`, task #30) |  |
| Gov-Hub RBAC (View/Admin/Approve) | ✅ Shipped |  |
| Break-glass local admin on all subsites | ✅ Shipped |  |
| Guacamole remote access | ✅ Opt-in service |  |
| Fleet topology API + Admin UI matrix | ✅ Shipped |  |
| Edge VM (OIDC router) | ✅ Shipped, not yet tested live |  |

---

## Dependency graph for Phase 1

The plan's Phase 1 (Core Platform at Organization, 3-4 weeks) requires these land in order:

```
1. Agent manifest schema v1.0 finalized (+ OPA input schema extension)
        │
        ▼
2. governance_agents table + CRUD router + validation
        │
        ▼
3. Guardrail profiles as named OPA bundles
        │
        ▼
4. Action catalog API + registration schema
        │
        ▼
5a. Manifest-to-runtime       5b. Action catalog
    translation layer             FastAPI + MCP backends
    (configures OWUI Model         (wrap existing tools)
     + LiteLLM virtual key
     + OPA policy binding)
        │                          │
        └──────────┬───────────────┘
                   ▼
6. Agent builder UI (Admin Hub tab)
        │
        ▼
7. RAG per-agent scope enforcement
        │
        ▼
8. First showcase agent (Dispute Handler at Organization)
```

Items 1-4 are mostly spec/schema work + small routers — cheap.
Item 5a is the IP core — 1-2 weeks of focused Python work.
Item 5b unblocks everything else — 3-5 days to wrap 5 existing tools.
Item 6 is the user-visible surface — 1 week of UI work.

---

## What to deprioritize / what to defer

- **Datadog integration** — WORM store is the compliance-critical piece. Datadog is ops-nice-to-have. Defer to after Phase 2.
- **n8n** — not platform-core; deploy per-tenant when their IT team needs it. Build Phase 3, not Phase 1. Until then, catalog backends are FastAPI + MCP only.
- **Portfolio dashboard** — don't build until Organization is demonstrable and Parent Organization asks. Phase 4.
- **Kubernetes/advanced fleet** — current Terraform+PowerShell fleet is fine through 10 tenants. Revisit.
- **Agent-Assist (task #21, parked)** — still parked; orthogonal to declarative agents.

---

## Honest pace estimate vs. Organization timeline

- **Organization window:** original target 2026-04-18 (2 days out).
- **Plan's Phase 1 (core at Organization):** 3-4 weeks.
- **Plan's Phase 2 (showcase agents):** 2-3 additional weeks.
- **Plan's Phase 4 (Parent Organization dashboard presentation):** ~8-10 weeks total from start.

**Reality:** The v3 ultraplan is a 2-3 month build to first Parent Organization demo, not a 2-day build to Organization deployment. Friday's Organization deadline cannot include a working declarative agent builder. What it CAN include:

- Demo the existing OWUI custom-model flow (shows "we already do this, just without the structured manifest yet")
- Show the gap analysis in this doc: "these pieces are already in place" — the plan isn't starting from zero
- Show the roadmap — Phase 0/1/2 tasks queued, concrete deliverables per week
- The persisted `docs/Platform-Ultraplan-v3.md` itself — Bryan can read it

**For Organization deployment this week:** ship what we already have (RBAC, break-glass, Grafana, Nested Dan, local cache, fleet topology, Guacamole). Present the ultraplan v3 as the next-90-days roadmap.

---

## Immediate Phase 0 work (this week, before Organization)

1. **Reconcile agent manifest schemas** — merge v1 (from `docs/Agents-Plan.md`) with v3 (from ultraplan §2.2). Single source of truth. JSON, not YAML (matches plan).
2. **Extend OPA input schema** — add the fields from plan §5.2. Mostly documentation + router instrumentation.
3. **Define guardrail profiles as OPA bundles** — `tier_fdcpa_regulated.rego`, `tier_hipaa_regulated.rego`, etc. Compose from existing Humility + industry policies.
4. **Define the action catalog schema** (plan §3.1 registration record). Pydantic model + JSON Schema. No backend required yet.

Estimate: 1-2 days. All spec/schema, zero user-facing code. Lands Phase 1 ready.

---

## Tasks to create now

- P0.1 — Agent manifest schema v1.1 (merge v1 + v3)
- P0.2 — OPA input schema extension (tenant_id, agent_id, execution_id, session counters, data_classes)
- P0.3 — Guardrail profiles as named OPA bundles (tier_fdcpa, tier_hipaa, tier_financial, tier_general_business, tier_unrestricted)
- P0.4 — Action catalog schema + registration API
- P1.1 — `governance_agents` table + CRUD router + manifest validation
- P1.2 — Manifest-to-runtime translation layer
- P1.3 — Wrap 5 existing Tools (DocForge, Governance Advisor, Fleet Mgmt, System Designer, Data Connector) as catalog actions
- P1.4 — RAG per-agent scope enforcement
- P1.5 — Agent builder UI in Admin Hub
- P1.6 — First showcase agent at Organization: Dispute Handler

These supersede the older `docs/Agents-Plan.md` phases which were scoped before the portfolio reframe.
