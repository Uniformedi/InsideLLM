# Ultraplan Rev 3: InsideLLM Declarative Agent Platform

*Reframed from "add n8n to InsideLLM" to "build a declarative agent platform a PE firm deploys across 32 portfolio companies."*

## 0. Strategic Reframe

The original ultraplan treated n8n as the star and Organization as the buyer. Both were wrong.

**The actual situation:**
- Organization is 80% owned by Parent Organization.
- Parent Organization operates 32 portfolio companies across multiple verticals.
- Bryan Albertson (CIO & CISO, Organization) is the decision maker — not Matt Ernst.
- Organization has been identified by Parent Organization as ahead of the curve on AI and analytics.
- Parent Organization is watching what Dan builds at Organization to replicate across the portfolio.

This means InsideLLM's trajectory is not "collections AI tool" — it is **"portfolio-wide AI operations platform."** Organization is the reference deployment. The 32-company rollout is the scale play. The buyer isn't Bryan Albertson — it's the Parent Organization operating partner who oversees technology across the portfolio.

**What Parent Organization actually needs:**
- A platform their portfolio companies can adopt without each one hiring an AI team.
- Non-technical knowledge workers at each company can build and deploy AI agents from a catalog — like M365 Declarative Agents or Copilot Studio — without writing code.
- Each company's data stays inside its own trust boundary.
- Governance, compliance, and audit are baked in — not bolted on — because PE firms need clean audit trails for due diligence, exit readiness, and cross-portfolio reporting.
- The platform is model-agnostic, vendor-neutral, and extensible — Parent Organization doesn't want to bet the portfolio on one AI vendor's roadmap.

**What this plan delivers:** An open, self-hosted, model-agnostic declarative agent platform governed by configurable compliance policy — deployable per-company, observable at portfolio scale, and differentiated from Microsoft Copilot Studio by the fact that it runs inside the customer's own infrastructure with full data sovereignty.

---

## 1. Architecture Overview — Three Layers

The platform separates into three layers. Each layer has a different audience, different tooling, and a different rate of change.

```
┌─────────────────────────────────────────────────────┐
│         LAYER 1: Declarative Agent Builder           │
│   Audience: knowledge workers (no code)              │
│   They compose agents from manifests:                │
│   instructions + knowledge + actions + guardrails    │
│   ┌─────────────────────────────────────────────┐   │
│   │  Agent: "Dispute Handler"                    │   │
│   │  Instructions: natural language persona       │   │
│   │  Knowledge: [dispute_policies, state_regs]   │   │
│   │  Actions: [lookup_account, draft_letter,     │   │
│   │            schedule_callback]                 │   │
│   │  Guardrails: tier_fdcpa_regulated             │   │
│   │  Approvals: [send_letter → manager]          │   │
│   └─────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│         LAYER 2: Orchestration Platform              │
│   Open WebUI + LiteLLM + RAG + Function Calling     │
│   Translates manifests into live agent sessions      │
│   Routes all inference through DLP + OPA Humility    │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│         LAYER 3: Tool Factory                        │
│   Audience: developers (Dan, company IT staff)       │
│   n8n / FastAPI / MCP servers                        │
│   Builds the actions that populate the catalog       │
│   End users never see or touch this layer            │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│         GOVERNANCE: DLP + OPA Humility               │
│   Configurable per-company, auditable at portfolio   │
│   Spans all three layers                             │
└─────────────────────────────────────────────────────┘
```

---

## 2. Layer 1: The Declarative Agent Builder

This is the product. Everything else is plumbing.

### 2.1 What the user sees

A web interface (within Open WebUI or as a standalone panel) where a knowledge worker:

1. **Names and describes** the agent — display name, icon, description, conversation starters.
2. **Writes instructions** in natural language — "You are a dispute resolution specialist. When a consumer disputes a balance, first verify the account, then check if the dispute falls within the 30-day validation window under §1692g..."
3. **Attaches knowledge sources** from a scoped library — document collections, FAQ sets, policy manuals, regulatory references. The user sees a browsable catalog; the platform handles chunking, embedding, and retrieval.
4. **Selects actions** from a curated catalog — each action has a plain-language name, description, required inputs, and a declared guardrail tier. The user toggles actions on/off. They never see an API endpoint, a webhook URL, or a workflow canvas.
5. **Configures guardrails** from a menu — data sensitivity tier, which actions require human approval before execution, escalation targets, budget caps.
6. **Publishes** — the agent becomes available to designated users or teams.

### 2.2 The agent manifest schema

Under the hood, the builder produces a JSON manifest. This is the core data model of the platform.

```json
{
  "schema_version": "1.0",
  "agent_id": "uuid",
  "tenant_id": "organization-collections",
  "created_by": "user@organization.com",
  "display": {
    "name": "Dispute Handler",
    "icon": "shield-check",
    "description": "Handles consumer balance disputes per FDCPA §1692g",
    "conversation_starters": [
      "I need to process a dispute for account #...",
      "What's the validation window for this dispute?",
      "Draft a dispute acknowledgment letter"
    ]
  },
  "instructions": "You are a dispute resolution specialist at Organization...",
  "knowledge": {
    "collections": ["dispute_policies_v3", "state_regulations_2026"],
    "scope": "strict"
  },
  "actions": [
    {
      "action_id": "lookup_account",
      "approval_required": false
    },
    {
      "action_id": "draft_fdcpa_letter",
      "approval_required": false
    },
    {
      "action_id": "send_letter",
      "approval_required": true,
      "approval_target": "manager",
      "approval_channel": "teams"
    },
    {
      "action_id": "schedule_callback",
      "approval_required": false
    }
  ],
  "guardrails": {
    "profile": "tier_fdcpa_regulated",
    "max_actions_per_session": 10,
    "token_budget_per_session": 50000,
    "allowed_models": ["gpt-4o", "claude-sonnet-4-20250514"],
    "pii_handling": "redact_in_logs"
  },
  "visibility": {
    "available_to": ["disputes_team", "compliance_team"],
    "published": true
  }
}
```

**Why this schema matters for Parent Organization:** Every portfolio company deploys agents by writing manifests — not code. The manifest is auditable, diffable, version-controlled, and machine-readable. When Parent Organization's operating team asks "what AI agents are running across the portfolio and what can they do?", the answer is a query across manifest metadata — not a survey of 32 different IT teams.

### 2.3 The manifest-to-runtime translation

The platform translates the manifest into Open WebUI's existing primitives:

| Manifest field | Open WebUI primitive |
|---|---|
| `instructions` | System prompt on a Model |
| `knowledge.collections` | RAG document collections bound to the Model |
| `actions[].action_id` | MCP tools or function-calling tools assigned to the Model |
| `guardrails.profile` | OPA policy input metadata attached to every LiteLLM request |
| `guardrails.allowed_models` | LiteLLM virtual key model allowlist |
| `guardrails.token_budget` | LiteLLM per-key budget |
| `visibility.available_to` | Open WebUI access control (group/user) |
| `actions[].approval_required` | Routed through HITL approval sub-workflow (§5) |

The translation layer is ~1,500–2,000 lines of Python. It reads the manifest, configures the Open WebUI Model via API, provisions the LiteLLM virtual key with the right constraints, and registers the OPA policy bindings. When a manifest is updated, the translation re-runs idempotently.

### 2.4 What this is NOT

- **Not a workflow builder.** Users don't draw flowcharts. They select capabilities from a catalog.
- **Not a prompt playground.** The instructions field is guided and validated — the platform can lint for known anti-patterns, flag missing guardrail references, and warn about regulatory blind spots.
- **Not Copilot Studio.** No vendor lock-in to Microsoft's model stack, SharePoint, or Graph. Model-agnostic via LiteLLM, knowledge-source-agnostic, action-source-agnostic.

---

## 3. Layer 3: The Tool Factory (Where n8n Earns Its Seat)

End users compose agents from the action catalog. **Developers build the catalog.** This is where n8n — or an alternative — operates.

### 3.1 Reframed role

n8n is not the agent runtime. It is one of several backends that can power a catalog action. The action catalog is the abstraction boundary:

```
┌──────────────────────────────────────────────────────┐
│                  Action Catalog                       │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ lookup   │  │ draft    │  │ schedule │  ...       │
│  │ account  │  │ letter   │  │ callback │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │              │              │                 │
└───────┼──────────────┼──────────────┼─────────────────┘
        ▼              ▼              ▼
   ┌─────────┐   ┌──────────┐   ┌──────────┐
   │ FastAPI  │   │   n8n    │   │   MCP    │
   │ endpoint │   │ workflow │   │  server  │
   └─────────┘   └──────────┘   └──────────┘
```

Each catalog action has a registration record:

```json
{
  "action_id": "lookup_account",
  "display_name": "Look Up Consumer Account",
  "description": "Retrieves account summary, balance, and payment history",
  "inputs": {
    "account_number": { "type": "string", "required": true }
  },
  "outputs": {
    "account_summary": { "type": "object" }
  },
  "backend": {
    "type": "mcp_tool",
    "endpoint": "insidellm-collections-mcp",
    "tool_name": "lookup_account"
  },
  "guardrail_requirements": {
    "data_classes": ["pii", "financial"],
    "minimum_guardrail_tier": "tier_fdcpa_regulated"
  },
  "audit": {
    "log_inputs": true,
    "log_outputs": true,
    "redact_fields": ["ssn", "full_name"]
  }
}
```

### 3.2 When n8n earns its seat vs. alternatives

| Use case | Best backend | Why |
|---|---|---|
| Simple DB lookup or API call | FastAPI endpoint | No orchestration overhead. 20 lines of Python. |
| Multi-step orchestration (query → enrich → format → decide) | n8n workflow | Visual debugging, non-developer maintainability |
| Actions that Organization or portfolio-company IT staff will build themselves | n8n workflow | Visual builder lowers the skill bar for company IT |
| High-performance, high-volume actions | FastAPI or Go service | n8n adds latency per node hop |
| Actions requiring complex business logic | FastAPI with domain module | Code is the right medium for complex logic |

**The portfolio-scale argument for n8n:** When Parent Organization rolls this out across 32 companies, each company's IT team (not Dan) will need to build company-specific actions — a different ERP lookup for a manufacturing company vs. a collections company vs. a healthcare operation. n8n's visual builder lets a competent IT generalist build and maintain these without being a Python developer. That's the seat n8n earns: **it's the tool factory for portfolio-company IT teams, not for Dan.**

Dan builds the core catalog (FastAPI + MCP). Portfolio companies extend it (n8n).

### 3.3 Shared catalog vs. company-specific catalog

Two-tier catalog model for portfolio deployment:

- **Core catalog** (maintained by Dan / Uniformedi): actions that apply across all or most portfolio companies — document classification, email triage, compliance summary, calendar scheduling, general Q&A with knowledge bases. Ships with the platform.
- **Company catalog** (maintained by company IT): actions specific to that company's systems — ERP lookups, industry-specific workflows, proprietary process automation. Built in n8n or FastAPI by company staff. Registered in the local catalog, invisible to other tenants.

Parent Organization portfolio-level view can query both: "which core actions are adopted by which companies" and "what custom actions has each company built."

### 3.4 Tool Factory governance

All catalog actions — regardless of backend — route through the DLP sidecar and OPA Humility:

- Every action invocation carries `tenant_id`, `agent_id`, `user_id`, `action_id`, `execution_id`
- DLP scans inputs (before the action sees data) and outputs (before the agent sees results)
- OPA evaluates: is this action allowed for this agent's guardrail profile? Is this user authorized? Has the session budget been exceeded?
- Audit log captures every invocation with full provenance chain

n8n-specific governance (from Rev 2, still applies):
- Community nodes disabled by default, enabled per PR against lockfile
- Prod n8n instance is read-only; GitOps promotion only
- Egress allowlisted per workflow at OpnSense
- SCFW coverage extended to n8n community nodes and chat-platform SDKs

---

## 4. Knowledge Layer

### 4.1 Scoped knowledge sources

Each agent manifest declares which knowledge collections it can access. The platform enforces this at the RAG retrieval layer — an agent with `scope: strict` cannot retrieve from collections not in its manifest, even if the underlying vector store contains them.

Collection types:
- **Documents** — PDFs, Word docs, policy manuals. Chunked and embedded on upload.
- **Structured data** — FAQ pairs, decision trees, lookup tables. Stored as-is, retrieved by semantic or exact match.
- **Live connectors** — query a database or API at retrieval time rather than pre-embedding. Essential for data that changes frequently (account balances, case status). Implemented as a special action that the RAG layer calls transparently.

### 4.2 Portfolio knowledge architecture

- **Portfolio-wide collections** (maintained by Parent Organization / Dan): regulatory references (FDCPA, HIPAA, PCI, SOX), cross-company policy templates, AI usage guidelines.
- **Company-specific collections** (maintained by company staff): company policies, product manuals, internal procedures, client-specific documentation.
- **Tenant isolation is absolute**: Company A's knowledge is invisible to Company B's agents, even if they share infrastructure. Enforced at the vector-store partition level, not just application-layer filtering.

---

## 5. Governance: Humility at Portfolio Scale

### 5.1 Guardrail profiles

Pre-built profiles that map to regulatory postures. Companies select a profile per agent; the platform enforces it via OPA.

| Profile | Applies to | Key constraints |
|---|---|---|
| `tier_unrestricted` | Internal analytics, R&D | Log only, no blocking |
| `tier_general_business` | General knowledge work | PII redaction in logs, standard budget caps |
| `tier_financial_regulated` | SOX-scope, PCI-scope | Full audit trail, approval required for external actions, model allowlist |
| `tier_fdcpa_regulated` | Collections operations | All of above + FDCPA-specific rules (no contact outside hours, §1692g validation tracking, consumer communication approval) |
| `tier_hipaa_regulated` | Healthcare operations | PHI handling rules, minimum necessary standard, BAA-covered models only |
| `tier_custom` | Company-defined | Extends any base profile with company-specific rules |

Profiles are OPA policy bundles. Adding a new profile is adding a `.rego` file to the policy repo and registering it in the catalog. No code changes to the platform.

### 5.2 OPA input schema (extended for declarative agents)

Every LiteLLM request and every action invocation carries:

```json
{
  "tenant_id": "organization-collections",
  "agent_id": "dispute-handler",
  "agent_version_hash": "sha256:abc123...",
  "user_id": "jsmith@organization.com",
  "action_id": "send_letter",
  "execution_id": "uuid",
  "iteration_count": 3,
  "session_token_count": 12450,
  "session_action_count": 4,
  "trigger_type": "human_chat",
  "guardrail_profile": "tier_fdcpa_regulated",
  "notification_targets": ["teams"],
  "data_classes_in_context": ["pii", "financial"],
  "model_requested": "claude-sonnet-4-20250514",
  "time_of_day": "14:30",
  "consumer_timezone": "America/Chicago"
}
```

OPA evaluates this against the guardrail profile's rules. Examples of rules that matter for Parent Organization:
- Deny if `time_of_day` falls outside FDCPA-permitted contact hours in `consumer_timezone`
- Deny if `data_classes_in_context` includes `phi` and `guardrail_profile` is not `tier_hipaa_regulated`
- Deny if `session_action_count` exceeds the agent's declared `max_actions_per_session`
- Deny if `model_requested` is not in the agent's `allowed_models` list
- Deny if `notification_targets` includes `discord` and `data_classes_in_context` includes any regulated class
- Warn (log + alert, don't block) if `iteration_count > 5` — possible agent loop

### 5.3 Portfolio-level policy inheritance

```
Parent Organization Portfolio Defaults (baseline)
  └── Company Override (company-specific additions)
       └── Agent Guardrail Profile (per-agent constraints)
            └── Session Context (runtime evaluation)
```

Parent Organization sets portfolio-wide minimums: all companies must log all agent interactions, all companies must redact PII in logs, all companies must use approved model list. Individual companies can only **tighten**, never loosen. Agent profiles can only tighten further. This is enforced by OPA policy composition — child policies inherit parent constraints via package imports, and a child cannot negate a parent rule.

---

## 6. Multi-Tenant Architecture (32+ Companies)

### 6.1 Isolation model

**One InsideLLM stack per tenant.** Not shared infrastructure with application-layer separation — actual separate deployments.

Rationale:
- Regulated industries demand infrastructure-level isolation, not just logical separation
- Different companies may require different model providers (some may prohibit certain vendors)
- Blast radius: a misconfiguration at Company A cannot affect Company B
- Data residency: some companies may require specific geographic placement
- Exit readiness: each company's stack is independently portable — critical for PE portfolio management where companies are bought and sold

**NULL condition:** for the first 5–10 deployments, per-tenant stacks are operationally feasible. At 32 tenants, the management overhead becomes the bottleneck. The path forward is either (a) a lightweight orchestration layer (Terraform + Ansible fleet management) or (b) a Kubernetes-based deployment where each tenant gets a namespace with resource quotas and network policies. Decision point: revisit at tenant 10. Confidence in either path today < 0.85.

### 6.2 Per-tenant stack composition

Each tenant deployment includes:
- Open WebUI instance (agent builder + chat interface)
- LiteLLM proxy (model routing, virtual keys, budgets)
- DLP sidecar
- OPA engine with tenant-specific + portfolio-inherited policies
- PostgreSQL database (agent manifests, action catalog, execution logs, knowledge metadata)
- Redis (queue, cache, session state)
- Vector store (knowledge embeddings, tenant-isolated)
- n8n instance (optional — only if the tenant's IT team builds custom actions)
- Notification emitter (wired to tenant's own Teams/Slack)

### 6.3 Portfolio-level observability layer

Parent Organization needs a view across all 32 deployments. This is a **separate service** — not embedded in any tenant stack:

```
┌─────────────────────────────────────────────────┐
│          Parent Organization Portfolio Dashboard              │
│  Agent adoption, usage metrics, compliance        │
│  posture, cost allocation, incident summary       │
└────────────────────┬────────────────────────────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │  Organization     │ │ Company  │ │ Company  │  ... ×32
   │  tenant  │ │  B tenant│ │ C tenant │
   └──────────┘ └──────────┘ └──────────┘
```

Each tenant ships anonymized/aggregated metrics to the portfolio dashboard:
- Agent count, action invocation counts, model usage and cost
- Compliance posture: policy violations, approval rates, DLP trigger rates
- Adoption metrics: active users, agents created, knowledge sources uploaded
- Incident log: failures, budget overruns, security events

**No raw data leaves the tenant.** The portfolio dashboard sees aggregates and metadata — never consumer records, PHI, or PII. This is enforced at the export layer, not the dashboard layer.

---

## 7. Event Notifications & ChatOps (Per-Tenant)

Carried forward from Rev 2, adapted for multi-tenant:

### 7.1 Platform selection

- **Teams is the default** for M365-native portfolio companies. Each tenant uses its own Azure AD app registration — no shared bot token across tenants.
- **Slack Enterprise Grid** for tech-forward companies that don't use M365.
- **Discord explicitly excluded** from any tenant handling regulated data. Enforced by OPA, not policy document.

### 7.2 Event taxonomy

Same 12 event types from Rev 2 (§5.2), with the addition of:

| Event | Severity | Target | Payload discipline |
|---|---|---|---|
| `agent.published` | info | ops + admin channel | Agent name, creator, guardrail profile |
| `agent.modified` | info | audit channel | Diff summary (no content), modifier identity |
| `catalog.action_added` | info | ops channel | Action name, backend type, guardrail requirements |
| `portfolio.report_generated` | info | Parent Organization dashboard | Aggregate metrics only |

### 7.3 Approval delivery (Pattern 4)

Identical to Rev 2 §5.4: Adaptive Cards for Teams, Block Kit for Slack, HMAC-signed one-shot expiring tokens, SSO-claim identity verification, out-of-band TOTP for high-stakes classes.

### 7.4 Notification DLP

Identical to Rev 2 §5.3: single notification emitter sub-workflow, DLP sidecar in-path, chat messages are pointers not content, CI lint blocks raw platform nodes in workflow JSON.

### 7.5 Inbound ChatOps

Same slash-command surface from Rev 2 §5.5, with the addition of:
- `/insidellm agents` — list published agents and their guardrail profiles
- `/insidellm catalog` — list available actions in the company's catalog
- `/insidellm usage [agent_name]` — usage summary for a specific agent

### 7.6 Channel topology (per tenant)

| Channel | Purpose | Audience |
|---|---|---|
| `#insidellm-ops` | Lifecycle, health, usage | IT ops |
| `#insidellm-security` | DLP violations, policy denials, supply-chain | Security / CISO |
| `#insidellm-audit` | Approvals, sensitive actions | Compliance |
| `#insidellm-agents` | Agent published/modified, catalog changes | Agent builders |
| DM to approver | Approval requests | Individual approvers |

---

## 8. Observability & Audit

### 8.1 Per-tenant

- Every agent session logged: session_id, agent_id, agent_version_hash, user_id, all LLM calls (correlation IDs), all action invocations, all approvals, all notifications emitted, final disposition
- Dual sink: Datadog for ops, append-only WORM store for compliance
- Agent manifest version pinning: production agents pinned by manifest hash; edits create new versions
- Full replay capability per session

### 8.2 Portfolio-level (Parent Organization)

- Aggregated metrics pipeline: each tenant exports anonymized usage/compliance/cost data
- Portfolio compliance posture dashboard: which companies are running which guardrail profiles, violation trends, approval rates
- Cost allocation: model spend per company, per agent, per action — feeds directly into Parent Organization's portfolio financial reporting
- Adoption scoring: agents created, agents actively used, knowledge bases maintained — signals which companies are getting value and which need support

---

## 9. Deployment & IaC

### 9.1 Per-tenant deployment

Terraform modules (extended from Rev 2):
- `insidellm-core` — Open WebUI, LiteLLM, DLP sidecar, OPA, Postgres, Redis, vector store
- `insidellm-agent-builder` — declarative agent UI, manifest-to-runtime translation, catalog API
- `insidellm-n8n` — optional; deployed only when tenant IT needs custom action development
- `insidellm-chatops` — notification emitter, Teams/Slack app registration, approval webhook endpoints
- `insidellm-observability` — Datadog agent, WORM store, metric export to portfolio dashboard

Each module is independently versionable. A tenant can be on `insidellm-core v2.3` while another is on `v2.1` — fleet management, not monolith upgrades.

### 9.2 Fleet management

At 32 tenants, a lightweight fleet orchestration layer:
- Terraform workspaces or Terragrunt for per-tenant state isolation
- Ansible for configuration drift detection and remediation
- A fleet manifest (YAML) that declares each tenant's module versions, guardrail profile inheritance, model provider configuration, and chat platform wiring
- CI/CD pipeline: PR against fleet manifest → plan → review → apply per-tenant

### 9.3 Day-one provisioning

New portfolio company onboarding:
1. Add tenant entry to fleet manifest
2. Terraform provisions infrastructure
3. Seed workflows deploy (notification emitter, heartbeat)
4. Portfolio-level OPA policies imported as base
5. Company-specific policy overrides applied
6. Core action catalog imported
7. Azure AD app registered for Teams (or Slack app installed)
8. Admin account provisioned; admin builds first agent using the builder

Target: new company from zero to first working agent in **< 1 business day** of Dan's time, assuming infrastructure is pre-allocated.

---

## 10. Supply Chain

Unchanged from Rev 2 §8. Three surfaces: n8n core (pin by digest), community nodes (disabled by default, PR + SCFW to enable), chat-platform SDKs (pin aggressively).

Additional portfolio-scale concern: if a supply-chain advisory affects a component used across multiple tenants, the fleet manifest enables coordinated response — patch, test on one tenant, roll across fleet.

---

## 11. Competitive Positioning

### 11.1 vs. Microsoft Copilot Studio

| Dimension | Copilot Studio | InsideLLM Declarative Agents |
|---|---|---|
| Model choice | Microsoft models only | Any model via LiteLLM |
| Knowledge sources | SharePoint, Graph connectors | Any — files, APIs, databases, custom connectors |
| Data residency | Microsoft cloud | Customer's own infrastructure |
| Governance | Microsoft Purview (opaque) | OPA Humility (transparent, auditable, customizable) |
| Action extensibility | Power Automate + custom connectors | n8n + FastAPI + MCP (open protocols) |
| Portfolio observability | Per-tenant only | Cross-portfolio dashboard native |
| Licensing | Per-user, Microsoft 365 dependency | Self-hosted, no per-user licensing trap |
| Vendor lock-in | Deep Microsoft dependency | Model-agnostic, protocol-agnostic, portable |

### 11.2 The pitch to Parent Organization

"Your portfolio companies get the same agent-building experience as Copilot Studio — non-technical users compose AI agents from a catalog of instructions, knowledge, and actions. But it runs on your infrastructure, talks to any model, every action goes through compliance policy before it touches data, and you get a portfolio-wide dashboard showing adoption, cost, and compliance posture across all 32 companies. No per-user licensing. No Microsoft lock-in. Full data sovereignty. And it was built and proven at Organization before it was offered to anyone else."

### 11.3 The pitch to Bryan Albertson

"Organization becomes the reference deployment for a platform Parent Organization deploys portfolio-wide. The AI capabilities your team builds here — the dispute handler, the compliance summarizer, the collection-call assistant — become showcase agents that demonstrate what the platform can do. Organization doesn't just adopt AI; it leads the portfolio's AI strategy. And as CIO & CISO, you have full visibility into what every agent can do, what data it touches, and what approvals it requires — because the governance layer was built for exactly your role."

---

## 12. Phased Rollout

### Phase 0 — Architecture & Decision (1 week)
License review (n8n Sustainable Use for tool factory layer). Agent manifest schema finalized. OPA guardrail profile taxonomy designed. Network design frozen. Azure AD app registration for Organization Teams tenant.

### Phase 1 — Core Platform at Organization (3–4 weeks)
Deploy per-tenant stack: Open WebUI, LiteLLM, DLP, OPA, Postgres, Redis, vector store. Wire notification emitter to Organization Teams. Build manifest-to-runtime translation layer. Stand up action catalog API with 5 core actions (FastAPI-backed). Build agent builder UI.

### Phase 2 — First Agents at Organization (2–3 weeks)
Build 3 showcase agents with Organization staff:
- Dispute Handler (FDCPA-regulated, approval-gated letter sending)
- Collection Call Assistant (real-time knowledge retrieval during calls)
- Compliance Summarizer (scheduled, emits daily report to `#insidellm-audit`)

Validate full audit trail: agent creation → session → action invocation → approval → notification → WORM log. Bryan Albertson reviews audit output.

### Phase 3 — Tool Factory (2 weeks)
Deploy n8n instance at Organization. Organization IT (Matt Ernst's team) builds 2–3 company-specific actions in n8n. Register in company catalog. Validate that agent builder can consume n8n-backed actions identically to FastAPI-backed ones.

### Phase 4 — Portfolio Observability (2–3 weeks)
Build Parent Organization portfolio dashboard. Wire Organization tenant as first data source. Design metric export pipeline. Design fleet manifest schema. Present to Parent Organization operating team.

### Phase 5 — Second Tenant (3–4 weeks)
Onboard one additional Parent Organization portfolio company. Validate: day-one provisioning process, portfolio policy inheritance, cross-company catalog isolation, fleet management tooling.

### Phase 6 — Portfolio Scale (ongoing)
Roll out to remaining companies in cohorts of 3–5. Refine provisioning automation. Build the core catalog based on cross-company patterns. Grow the workflow marketplace.

**Organization to first Parent Organization presentation: ~8–10 weeks.** Second tenant live: ~13–17 weeks. Full portfolio: 6–12 months depending on cohort pacing and company readiness.

---

## 13. Open Questions — NULL Conditions

STATUS: NULL on the following. Confidence < 0.85; verify before commitment.

1. **n8n MCP server/client feature state at current release.** Determines Pattern 1 bridge shim requirement.
2. **n8n Sustainable Use License for the tool-factory role specifically.** Lower risk than the prior plan (n8n is now optional per tenant, not platform-core), but still needs legal confirmation.
3. **Microsoft Teams notification delivery surface.** O365 Connectors deprecated; verify native n8n Teams node targets Graph API vs. Bot Framework vs. Workflows.
4. **Multi-tenant fleet management at 32 tenants.** Terraform workspaces + Ansible is viable to ~10; beyond that, Kubernetes namespaces or a purpose-built orchestrator may be needed. Decision point at tenant 10.
5. **OPA policy evaluation latency under fan-out.** 20 tool calls = 20 evaluations per session turn. Needs load test.
6. **Parent Organization's actual infrastructure posture across 32 companies.** How many are M365? How many have Azure tenants? How many have IT staff capable of building n8n actions? This determines the rollout pace and support model. Unknown until discovery.
7. **Open WebUI's Model API stability for programmatic manifest translation.** The translation layer depends on Open WebUI exposing stable APIs for creating/configuring Models, assigning tools, and managing RAG collections. If APIs change between versions, the translation layer breaks. Mitigate by pinning Open WebUI version and contributing upstream.
8. **Adaptive Card rendering parity across Teams desktop / mobile / web.**

---

## 14. Recommended Next Steps

**Immediate (this week):**
1. Draft the agent manifest schema v0.1 and socialize with Bryan Albertson. The schema is the product — validate that it captures what Organization needs before writing any code.
2. Build a single FastAPI-backed action (account lookup) and expose it as an MCP tool in Open WebUI. Confirm the plumbing works end to end.

**Short-term (next 2 weeks):**
3. Build the manifest-to-runtime translation layer against Open WebUI's existing Model + Tools API. This is the core intellectual property of the platform.
4. Wire the Teams notification emitter and prove a Pattern 4 approval flow with Bryan's team.

**Medium-term (weeks 3–6):**
5. Build the agent builder UI.
6. Deploy 3 showcase agents at Organization.
7. Begin portfolio dashboard design with Parent Organization operating team input.

**Decision gates:**
- After step 2: confirm Open WebUI's APIs are stable enough to build on, or identify where upstream contribution is needed.
- After step 4: confirm Teams delivery path (resolve NULL #3).
- After step 6: present to Parent Organization with live Organization demo. This is the gate that unlocks portfolio funding.
