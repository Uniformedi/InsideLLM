# InsideLLM Declarative Agent Schemas

Canonical JSON Schema + pydantic models for the declarative agent platform.
These schemas are authoritative — routers, translators, and the agent builder
UI all consume them via the files in this directory.

## Files

| File | Purpose |
|---|---|
| `agent_manifest.schema.json` | JSON Schema (draft 2020-12) for the agent manifest. Wire format. |
| `agents.py` | Pydantic models matching the JSON Schema. In-process validation. |
| `README.md` | This file. |

## Schema version

**v1.1** (released 2026-04-16) — reconciles the v1 YAML draft from
[docs/Agents-Plan.md](../../../../docs/Agents-Plan.md) with the v3 JSON
manifest from [docs/Platform-Ultraplan-v3.md](../../../../docs/Platform-Ultraplan-v3.md)
§2.2. Pinned — translators refuse unknown schema versions.

Any breaking change to the manifest cuts a new major version (2.0) with a
written migration path. Non-breaking additions bump minor (1.2, 1.3, …).

## Authoring

Two equivalent authoring paths — YAML and JSON are one-to-one via PyYAML
round-trip. The API accepts both; the DB stores JSON.

- **YAML** — humans author; see [examples/agents/dispute-handler.yaml](../../../../examples/agents/dispute-handler.yaml)
- **JSON** — wire format; API produces/consumes this

## Lifecycle

```
author manifest (YAML or JSON)
        │
        ▼
POST /api/v1/agents              ← pydantic validation
        │
        ▼
governance_agents row inserted   ← status=draft, is_active=false
        │
        ▼
POST /agents/{id}/publish         ← governance_changes approval if scope≥org
        │
        ▼
manifest-to-runtime translator   ← configures OWUI Model + LiteLLM key + OPA
        │
        ▼
agent live in OWUI @agent picker
```

## Integration points

| Manifest field | Consumed by |
|---|---|
| `schema_version` | router version-gate |
| `agent_id`, `tenant_id` | governance_agents PK, OPA input, audit scope |
| `display.*` | OWUI Model card, agent picker render |
| `instructions` | OWUI Model system prompt |
| `knowledge.collections`, `.scope` | RAG server-side scope enforcement |
| `knowledge.connectors`, `.urls` | Data connector registry + URL allowlist |
| `actions[]` | MCP/OpenAI function-calling tool list; approval gates |
| `guardrails.profile` | OPA policy binding (`tier_fdcpa_regulated` etc.) |
| `guardrails.allowed_models`, `daily_usd_budget`, `rpm_limit` | LiteLLM virtual key config |
| `guardrails.token_budget_per_session` | LiteLLM per-key budget |
| `guardrails.dlp_overrides` | DLP callback per-agent exceptions (profile-gated) |
| `visibility.scope`, `.available_to` | OWUI model access control; governance_changes approval gating |

See [docs/Platform-Ultraplan-v3-GapAnalysis.md](../../../../docs/Platform-Ultraplan-v3-GapAnalysis.md)
for the full layer-by-layer view.
