# InsideLLM Declarative Agents — Implementation Plan (v1 — superseded)

> **Superseded by** [Platform-Ultraplan-v3.md](Platform-Ultraplan-v3.md).
> v3 reframes from "M365-like agents for Organization" to "portfolio-wide platform
> deployed across 32 Parent Organization companies, Organization as reference tenant." The gap
> analysis is at [Platform-Ultraplan-v3-GapAnalysis.md](Platform-Ultraplan-v3-GapAnalysis.md).
> This v1 document is retained for its manifest-schema sketch and the
> "first concrete step" Phase 1 kickoff pseudocode, which remain valid.

**Status:** Superseded 2026-04-16. Kept as reference for the single-VM
manifest schema and first-PR scaffolding.

**Audience:** platform maintainers evaluating the initial storage +
router surface before layering the broader v3 plan on top.

**Last updated:** 2026-04-16

---

## 1. What we're matching

Microsoft 365 Declarative Agents are user-authored mini-assistants defined by a manifest (no code), combining:

- **Persona** — system prompt + instructions + conversation starters
- **Knowledge** — scoped RAG / tool / URL grounding
- **Tools** — allowlisted actions the agent can call
- **Governance** — visibility + approval workflow
- **Surfacing** — `@agent` inside existing chat, or a picker

On-prem equivalent means: user creates manifest → platform validates + registers → invokable from Open WebUI → audited and governed under InsideLLM's existing guardrails.

---

## 2. What already exists in InsideLLM (the bones)

About 70% of the required plumbing is already committed.

| Need | Existing piece | Gap |
|---|---|---|
| Per-agent system prompts | OWUI "Custom Models" | Fragmented; no governance ties |
| RAG | OWUI collections | Can't scope to one agent cleanly |
| Tool invocation | LiteLLM `tool_policies` | Sparse; not composable |
| Governance / approvals | Gov-Hub `governance_changes` | Not wired to agent lifecycle |
| Audit chain | `governance_audit_chain` | Per-request exists; per-agent aggregation missing |
| Cross-fleet sync | `governance_framework_sections` + central DB | Needs `governance_agents` mirror |
| DLP / Humility | LiteLLM guardrails | Apply automatically; no per-agent override |
| Budgets | LiteLLM virtual keys | Per-user, not per-agent |

This is an assembly + authoring-UI project, not a greenfield build.

---

## 3. Proposed architecture

```
┌─ Admin Hub "Agents" tab (new) ──────────────────────────────┐
│  Authoring form + YAML preview + test pane                  │
│  Publish → Draft | Team | Org (approval) | Fleet (approval) │
└───────────────────┬─────────────────────────────────────────┘
                    │ POST /api/v1/agents (manifest)
                    ▼
┌─ Gov-Hub: agent_service.py (new) ───────────────────────────┐
│  - Validates manifest against JSON schema                   │
│  - Routes through governance_changes if tier ≥ 2            │
│  - Stores in governance_agents                              │
│  - Registers w/ OWUI "Models" via existing admin API        │
│  - Grants MCP/tool permissions via LiteLLM tool_policies    │
│  - Syncs to central DB for cross-fleet                      │
└───────────────────┬─────────────────────────────────────────┘
                    │
         ┌──────────┴────────────┐
         ▼                       ▼
┌──────────────────┐   ┌──────────────────────┐
│ Open WebUI       │   │ LiteLLM (Claude)     │
│ - @agent picker  │   │ - agent manifest →   │
│ - Rich agent     │   │   prompt + tools     │
│   card           │   │ - Humility + DLP     │
│ - Test sandbox   │   │ - Per-agent budget   │
└──────────────────┘   └──────────────────────┘
```

Authoring happens in Gov-Hub. Discovery + invocation happens in OWUI.
Execution + guardrails happen in LiteLLM. No new runtime surface.

---

## 4. Agent manifest schema (YAML, schema v1.0)

```yaml
schema_version: "1.0"
id: contract-reviewer
name: "Contract Reviewer"
description: "Reviews NDAs, flags non-standard terms"
icon: /icons/contract.svg
owner: jane.smith@organization.internal
team: legal

persona:
  system_prompt: |
    You are a contract-review specialist at Organization ...
  instructions:
    - Lead with a 3-sentence summary
    - Flag clauses deviating from the Organization standard NDA
  conversation_starters:
    - "Review this contract"
    - "Compare to our standard NDA"

model:
  preference: claude-sonnet-4-6
  temperature: 0.2
  budget: { daily_usd: 5.00, rpm: 20 }

knowledge:
  - { type: rag_collection, name: organization-standard-contracts }
  - { type: connector,      name: contract_templates_db,
      query: "SELECT * FROM templates WHERE active=true" }
  - { type: url, urls: [ "https://organization-legal-hub/policy" ] }

tools:
  - { id: docforge:generate-pdf }
  - { id: mcp:contract-lookup, scope: read }

governance:
  tier: tier2
  data_classification: confidential
  visibility: team            # private | team | org | fleet
  required_approvals: [legal_supervisor]
  dlp_overrides: { allow_pii: false }
```

### Manifest rules

- `id` is immutable once published. Forks create a new id.
- `system_prompt` is treated as `immutable` at runtime — a user's chat prompt cannot override it. Humility guardrail still enforces SAIVAS on top.
- `visibility: fleet` routes the manifest through `governance_changes` with tier-3 approval (cross-fleet change).
- Any unrecognized `type:` under `knowledge` or `tools` rejects validation. Whitelist is strict.
- Secret values (API keys, connection strings) MUST reference secret refs, never inline — same pattern as `env:VAR` in `fleet.yaml`.

---

## 5. Phased delivery

### Phase 1 — MVP (2 weeks, ~50 h)

**Goal:** user creates an agent and invokes it by name in Open WebUI.

- `governance_agents` table + CRUD router in Gov-Hub.
- Manifest JSON-Schema + pydantic validator.
- OWUI "Models" bridge (we already use its admin Python API in `post-deploy.sh.tpl`).
- Admin Hub "Agents" tab — form editor, YAML preview, test pane.
- `@agent` picker in OWUI chat via its model-selector.
- Visibility: Private + Team only. No approvals.
- Audit-chain entry on create / update / invoke.
- One pre-loaded example: **Governance Policy Explainer** shipped with every deployment.

**Out of Phase 1:** tools, MCP, marketplace, cross-fleet, per-agent budgets.

### Phase 2 — Tools + Governance (4 weeks, ~80 h)

**Goal:** agents take actions; shared ones require approval.

- MCP server registry in Gov-Hub (`governance_mcp_servers`).
- Tool allowlist per agent → mapped to LiteLLM `tool_policies`.
- Org-visibility agents route through `governance_changes` approval (tier 3+).
- Per-agent budget enforcement via a dedicated LiteLLM virtual key per agent.
- DocForge action pre-wired as an MCP tool.
- Connector-query action pre-wired.
- Agent observability panel (invocations / hour, cost, feedback score).

### Phase 3 — Directory + Cross-Fleet (6 weeks, ~120 h)

**Goal:** discoverable marketplace; agents travel across the fleet.

- Admin Hub "Agent Directory" tab with search, tags, ratings.
- Clone / fork flow.
- Semver'd versions; rollback.
- Cross-fleet sync (mirrors the `governance_framework_sections` sync pattern).
- Per-fleet-member overrides (e.g. different budget on the legal VM).
- Grafana dashboard: agent usage, cost attribution, policy-violation rate.
- Agent feedback loop (thumbs up / down in OWUI → aggregated score).

### Phase 4 — Composition (future)

- Agent-to-agent invocation (agent A calls agent B as a tool).
- Agent workflows (multi-step pipelines).
- Human-in-the-loop checkpoints.
- Marketplace rating + public agent registry across tenants.

---

## 6. Key technical decisions (locked-in)

| Decision | Rationale |
|---|---|
| **MCP as tool standard** | Anthropic's Model Context Protocol is natively Claude-compatible. Future-proofs against locked-in tool formats. |
| **Manifest in Git-friendly YAML** | Agents can be version-controlled, PR-reviewed, promoted between dev/prod like any config. |
| **Storage in existing `governance_*` tables** | No new schema pattern; inherits hash-chained audit + fleet sync. |
| **OWUI as the chat surface** | Don't fork a new UI; extend what users already open. |
| **LiteLLM as the runtime** | Per-agent virtual key = per-agent budget + rate limit + team mapping, all pre-built. |

---

## 7. Governance story (the differentiator vs M365)

M365 Declarative Agents have admin controls but weak runtime enforcement. InsideLLM agents inherit every existing guardrail **automatically**:

- **Humility alignment** on every invocation regardless of agent prompt.
- **DLP** scans transcripts + knowledge-source ingestion.
- **OPA policy** can gate per-agent (e.g., "finance agents forbidden on non-finance data").
- **Hash-chained audit** — every agent creation, edit, and invocation is signed.
- **Tier-based approval** — an agent with access to financial data auto-escalates to supervisor review.
- **Data classification inheritance** — an agent's classification cannot exceed the invoking user's clearance.

Pitch to regulated customers: "M365 agents without M365 governance gaps."

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| OWUI "Models" API doesn't accept tool allowlists | Dual registration: OWUI for chat, LiteLLM `tool_policies` for enforcement. OWUI model becomes an alias. |
| MCP schema volatility | Pin to MCP v0.1 baseline; wrap in our own adapter layer. |
| Agent prompt injection | Existing Humility guardrail + add agent-specific `system_prompt_immutable` flag so user prompts cannot override. |
| Runaway costs on a shared agent | Per-agent budget (Phase 2) + global kill-switch in Admin Hub. |
| Governance sprawl (100s of agents) | Directory with deprecation workflow; unused-for-60-days auto-flags for review. |
| Central-DB contention on high-traffic deployments | Agents resolve from each Gov-Hub's local cache; central DB is the write-through, not the read path. |

---

## 9. Scope fit to Organization timeline

- **Organization April 2026 deadline:** out of reach. Phase 1 is 2 weeks.
- **Phase 1 target:** 2026-05-10 (post-launch).
- **Phase 2 target:** 2026-06-28.
- **Phase 3 target:** 2026-08-23.
- **Phase 4:** Q4 2026.

**For the Organization demo**, showcase the existing OWUI custom-model flow (already works: user creates a named model with system prompt + RAG collection) and position Phase 1 as the coming structured upgrade. Honest; buys time to build it right.

---

## 10. First concrete step

Single, back-compatible PR to unblock everything downstream (~6 hours):

- Add `Agent` SQLAlchemy model in `configs/governance-hub/src/db/models.py`.
- Add `routers/agents.py` with CRUD endpoints and manifest validation.
- Wire into `main.py` alongside the existing routers.
- No UI yet. No OWUI bridge yet. Just the storage + API surface so Phase 1 work can layer onto a stable foundation.

```python
# Sketch — final shape may differ
class Agent(Base):
    __tablename__ = "governance_agents"
    id              = Column(String(255), primary_key=True)
    name            = Column(String(255), nullable=False)
    description     = Column(Text)
    owner_email     = Column(String(255), index=True)
    team            = Column(String(100), index=True)
    manifest_yaml   = Column(Text, nullable=False)
    manifest_schema = Column(String(20), default="1.0")
    visibility      = Column(String(20), default="private")
    status          = Column(String(20), default="draft")
    version         = Column(Integer, default=1)
    is_active       = Column(Boolean, default=False)
    dlp_classification = Column(String(20), default="internal")
    governance_tier = Column(String(20), default="tier1")
    created_at      = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at      = Column(DateTime(timezone=True),
                             default=datetime.utcnow, onupdate=datetime.utcnow)
```

Endpoints (RBAC per existing middleware):

- `POST   /api/v1/agents`               — create (admin)
- `GET    /api/v1/agents`               — list (view)
- `GET    /api/v1/agents/{id}`          — read (view)
- `PUT    /api/v1/agents/{id}`          — update (admin)
- `POST   /api/v1/agents/{id}/publish`  — promote draft → team / org (admin; tier-gated approval)
- `DELETE /api/v1/agents/{id}`          — soft delete (admin)
- `GET    /api/v1/agents/{id}/audit`    — agent-scoped audit trail (view)

Once the table + router land, every subsequent phase (UI, OWUI bridge, LiteLLM tool policies, cross-fleet sync) plugs into a stable surface.

---

## 11. References

- [Governance Hub architecture overview](architecture/governance-hub.md) _(to be written)_
- [Fleet architecture](FleetArchitecture.md)
- [Humility / SAIVAS policy](architecture/policy-library.md)
- Microsoft Declarative Agents manifest schema (external reference): https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/declarative-agent-manifest
- Anthropic MCP: https://modelcontextprotocol.io

---

**End of plan.** Awaiting go on Phase 1 kickoff.
