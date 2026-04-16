# Session Resume — InsideLLM Platform Build

**Snapshot:** 2026-04-16
**Last commit:** `83e1cfd` — P1.1 agent CRUD router shipped
**Target:** **Parent Organization demo on 2026-05-12** (26 days out)
**Current phase:** Ultraplan v3 Phase 1 (core platform) — 1 of 6 done

This doc is the durable handoff so any assistant can resume exactly
where we left off without re-discovering context.

---

## 1. Where we are

### Live infrastructure

| VM | IP | Role | State | Dept |
|---|---|---|---|---|
| `insidellm-mgmt` | 10.0.0.9 | `primary` | healthy, 13 containers | exec |
| `insidellm-eng`  | 10.0.0.11 | `gateway` | healthy, 11 containers | engineering |

SSH with `-i "C:/Users/dmedina/.ssh/id_rsa" -o UserKnownHostsFile="C:/Users/dmedina/.ssh/known_hosts"` as `insidellm-admin`.

### Live break-glass

Break-glass account `insidellm-admin` on both VMs using `LITELLM_MASTER_KEY` from each VM's `/opt/InsideLLM/.env`.

```bash
# Mint a JWT on either VM
MK=$(sudo grep "^LITELLM_MASTER_KEY=" /opt/InsideLLM/.env | cut -d= -f2)
TOK=$(curl -sku "insidellm-admin:$MK" -X POST https://localhost/governance/auth/token | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
# Returns roles=[admin, approver, view]
```

### Live platform features

- **Fleet capability registry** — 10.0.0.9 publishes 7 caps, 10.0.0.11 publishes 4. Each VM has its own DB (cross-tenant aggregation deferred).
- **Governance Hub RBAC** (View / Admin / Approve) via LDAP or break-glass.
- **Guardrail profiles** deployed as OPA bundles: `tier_unrestricted`, `tier_general_business`, `tier_financial_regulated`, `tier_fdcpa_regulated`, `tier_hipaa_regulated`, `tier_custom`. **46/46 unit tests pass** via `opa test` in the openpolicyagent image.
- **Agent CRUD router** — `/api/v1/agents/*`. Dispute Handler YAML is ingested + published on 10.0.0.9 right now. Audit trail at seq 16/17.
- **Subsite break-glass** — OWUI, Grafana, LiteLLM, Uptime Kuma, pgAdmin, Guacamole all accept `insidellm-admin` + master key on fresh deploys.
- **Per-VM Claude Code CLI** (Nested Dan) in `post-deploy.sh.tpl` — ready for future deploys; not installed on current running VMs.

### Code-sync caveats (current running VMs)

- 10.0.0.9 was originally deployed from a **stale** `c:/insidellm/` tree (pre-Stream-A). We hot-patched it via `docker cp` after syncing the source and patching the compose env. **The VM works but on a patched image; a fresh deploy would be cleaner.**
- 10.0.0.11 was deployed from synced `c:/insidellm2/` and has all Stream A-E code baked in from Terraform-apply time.
- Next fresh deploy from either `c:/insidellm/` or `c:/insidellm2/` (both now synced) gets everything correctly.

---

## 2. Recent commit history (master)

```
83e1cfd  feat(agents): P1.1 — governance_agents table + CRUD router
bb49733  feat(opa): P0.2 + P0.3 — guardrail profiles + extended OPA input schema
c2d3c76  fix(runtime): nginx map_hash bucket + capability metadata column
3c5bfc6  feat(agents): P0.1 + P0.4 — manifest + action catalog schemas
dc0faa1  feat(agents): P0.1 — agent manifest schema v1.1 (reconciled v1 + v3)
7f25133  docs: absorb Ultraplan v3 + polyglot tool-factory assumption
b34be8b  docs(agents): declarative-agents implementation plan (v1 — superseded)
17089e7  feat(cache): local apt + Docker registry mirror on primary VM
28c4a23  feat(ops): auto-install Claude Code CLI for admin user on every VM
590ae89  docs(organization): Okta implementation guide + 5-year cost forecast
```

All pushed to `origin/master` (GitHub: Uniformedi/InsideLLM).

---

## 3. Task board state

Full list via `TaskList` tool. Key tasks:

### Done (P0 — Foundations)
- ✅ **#32 P0.1** — Agent manifest schema v1.1 (JSON Schema + pydantic, `configs/governance-hub/src/schemas/agents.py`)
- ✅ **#33 P0.2** — OPA input schema extended (`configs/opa/policies/README.md`, `humility_guardrail.py::_build_opa_input`)
- ✅ **#34 P0.3** — Guardrail profiles as OPA bundles (6 profiles + 46 tests in `configs/opa/policies/profiles/` + `tests/`)
- ✅ **#35 P0.4** — Action catalog schema (`configs/governance-hub/src/schemas/actions.py`)

### Done (P1)
- ✅ **#36 P1.1** — `governance_agents` table + CRUD router + audit (`routers/agents.py`, `services/agent_service.py`)

### Next up (P1 — Core Platform)
- ⏳ **#37 P1.2** — Manifest-to-runtime translation layer (**NEXT; this is the IP core**)
- ⏳ **#38 P1.3** — Wrap existing Tools as catalog actions
- ⏳ **#39 P1.4** — RAG per-agent scope enforcement
- ⏳ **#40 P1.5** — Agent builder UI in Admin Hub
- ⏳ **#41 P1.6** — First showcase agent at Organization: Dispute Handler end-to-end

### Later phases
- P2 (#42) — Teams/Slack approval flow
- P3 (#43, 45, 46, 47) — Polyglot tool factory (n8n CE, Activepieces, FastAPI+Celery, parity tests)
- P4 (#44) — Parent Organization portfolio dashboard

### Parked / deprioritized
- #16 H1 — Modular defer (superseded by Stream A)
- #21 Agent-Assist — deleted (superseded by declarative-agents direction)
- #28 P1.B — Keycloak local fallback (can do if Okta demo-day access is blocked)
- #29 P1.C — Edge VM deploy (the code is committed; can stand one up any time)

---

## 4. Next concrete step: P1.2 — Manifest-to-runtime translation layer

**Goal:** take a published agent manifest and configure the runtime so the agent becomes invokable.

### What the translator must do

For each published agent:

1. **LiteLLM virtual key provisioning**
   - `POST http://litellm:4000/user/new` with `user_id=agent:<tenant_id>:<agent_id>`
   - `POST /key/generate` with:
     - `user_id` above
     - `max_budget = manifest.guardrails.daily_usd_budget`
     - `budget_duration = "1d"`
     - `rpm_limit = manifest.guardrails.rpm_limit`
     - `tpm_limit` derived
     - `models = manifest.guardrails.allowed_models`
     - `metadata = {"guardrail_profile": manifest.guardrails.profile, "agent_id", "tenant_id", "manifest_hash"}`
   - Persist the returned `sk-...` key somewhere keyed on (tenant_id, agent_id, version)
   - On update: if manifest_hash changed → mint new key + delete old

2. **Open WebUI "Custom Model" registration**
   - OWUI's `/api/v1/models/create` (internal admin API)
   - Map manifest fields:
     - `id` = `agent:<tenant_id>:<agent_id>`
     - `name` = `manifest.display.name`
     - `base_model_id` = `manifest.guardrails.allowed_models[0]`
     - `params.system` = `manifest.instructions`
     - `meta.description`, `meta.suggestion_prompts` = `manifest.display.description`, `conversation_starters`
     - `meta.knowledge` = RAG collection IDs from `manifest.knowledge.collections`
     - `access_control` = per `manifest.visibility`
   - Existing pattern: `post-deploy.sh.tpl` already calls OWUI's Functions API via `docker exec python3 -c`

3. **OPA policy binding**
   - No runtime call. The LiteLLM callback `_build_opa_input()` (already written) reads `agent_meta` fields from the request metadata. The translator's job is to make sure `guardrail_profile`, `data_classes_in_context`, `allowed_models`, `baa_models`, `max_actions_per_session`, `token_budget_per_session` are attached to every request via LiteLLM key metadata or passed in litellm request body `metadata`.

4. **Action registration (Phase-2 scope)** — wire function-calling tools. For MVP, catalog action IDs pass through; LiteLLM receives them as `tools=[...]` on chat completions. Full MCP wiring is P1.3 follow-on.

5. **Idempotency + tear-down**
   - Hash-stamp every provisioned resource with `manifest_hash`; skip if unchanged
   - On retire / delete: revoke LiteLLM key + delete OWUI model + clean up RAG bindings

### File to create

`configs/governance-hub/src/services/agent_translator.py`

Skeleton:

```python
class AgentTranslator:
    async def provision(self, agent_row: Agent) -> dict:
        """Ensure the runtime reflects this agent's manifest. Idempotent."""
        ...
    async def deprovision(self, agent_row: Agent) -> dict:
        """Revoke runtime resources for a retired / deleted agent."""
        ...
```

Hook: call `translator.provision(row)` at the end of `agent_service.publish_agent` (when published immediately) AND on `change_service.approve_or_reject` when approval is granted for an `operation: publish_agent` change.

### Aggressive timeline

- **Day 1 (~4h):** LiteLLM virtual-key provisioning + tests. Can verify directly — mint a key via the translator, curl `/v1/chat/completions` with that key, confirm it works.
- **Day 2 (~4h):** OWUI model registration. Pattern already exists in `post-deploy.sh.tpl`. The tricky part is access control — manifest `visibility.scope` → OWUI groups.
- **Day 3 (~4h):** End-to-end: publish Dispute Handler → see it appear in OWUI model picker → chat works → audit log shows every call tagged with agent_id.

That unlocks P1.6 showcase.

### Critical dependencies unresolved

- **OWUI admin API stability** — we assume it's stable. Ultraplan v3 Section 13 NULL #7 flagged this. Pin OWUI version in `docker-compose.yml.tpl` if not already (`main` tag is moving).
- **RAG collection naming** — manifest references collections by name (`organization-dispute-policies-v3`). Who creates those collections? The translator can't; it's an operator task upstream. For the demo, pre-create one collection by hand at `https://10.0.0.9/` → Knowledge → Create.

---

## 5. Demo critical path to May 12

Compressed from the full v3 timeline (2-3 months) to 26 days:

```
Week 1 (Apr 17-23)  — P0 foundations DONE, P1.1 DONE (ahead of sched)
Week 2 (Apr 24-30)  — P1.2 translation layer
Week 3 (May 1-7)    — P1.3 wrap tools + P1.5 builder UI (minimal)
Week 4 (May 8-12)   — P1.6 Dispute Handler showcase + demo rehearsal
```

For Parent Organization (not Organization), the pitch is portfolio-wide platform, not collections-specific. The Dispute Handler is the reference-tenant agent proving the workflow; the Parent Organization story is "this works across 32 portfolio companies via fleet.yaml manifest."

### What Parent Organization sees on May 12

Minimum viable demo (prioritized):

1. **Build an agent by filling a form** (Admin Hub → Agents → +New) — shows no-code authoring
2. **Publish → governance_changes approval for org-visibility** — shows approval workflow
3. **Invoke agent in Open WebUI chat** — shows runtime
4. **Show hash-chained audit trail** — shows compliance story
5. **Fleet topology view** — shows 32-company scale story (even if only 2 VMs live)
6. **Portfolio dashboard mockup** — Figma screenshot of P4.1, "coming in Q3"

### What we're explicitly cutting for May 12

- Teams/Slack approval UI (show Gov-Hub approval queue; claim "Teams coming Phase 2")
- n8n / Activepieces (talk about polyglot; don't deploy)
- Portfolio dashboard backend (Figma mockup only)
- RAG per-agent scope enforcement (showcase agent uses one collection)
- Edge VM (can stand up in 30 min if needed, but not critical)

---

## 6. Key files + paths

### Specs / schemas (P0 output)
- `configs/governance-hub/src/schemas/agent_manifest.schema.json` — JSON Schema
- `configs/governance-hub/src/schemas/agents.py` — pydantic models
- `configs/governance-hub/src/schemas/action_catalog.schema.json`
- `configs/governance-hub/src/schemas/actions.py`
- `configs/governance-hub/src/schemas/README.md` — authoring / lifecycle doc

### OPA policies
- `configs/opa/policies/decision.rego` — aggregator (v3 with static dispatch)
- `configs/opa/policies/profiles/` — 6 guardrail profiles
- `configs/opa/policies/tests/` — 46 unit tests (run: `opa test /policies`)
- `configs/opa/policies/README.md` — input/output contract
- `configs/opa/policies/humility/base.rego` — SAIVAS core (untouched)
- `configs/opa/policies/industry/*.rego` — per-regulation overlays

### Gov-Hub code (P1.1 output)
- `configs/governance-hub/src/db/models.py::Agent` (class)
- `configs/governance-hub/src/routers/agents.py`
- `configs/governance-hub/src/services/agent_service.py`
- `configs/governance-hub/src/services/audit_chain.py` — reused for agent events
- `configs/litellm/callbacks/humility_guardrail.py::_build_opa_input()` — OPA input contract implementation

### Examples
- `examples/agents/dispute-handler.yaml` — showcase agent manifest
- `examples/actions/lookup_account.yaml` — catalog action it references

### Design docs
- `docs/Platform-Ultraplan-v3.md` — canonical plan (610 lines)
- `docs/Platform-Ultraplan-v3-GapAnalysis.md` — built vs. needed
- `docs/Agents-Plan.md` — v1 (superseded; kept for first-PR pseudocode)
- `docs/Organization-Okta-Implementation.md` — Organization-side Okta setup
- `docs/Organization-5Year-Forecast.md` — 5-year cost projection
- `docs/FleetArchitecture.md` — Stream A-E fleet model
- `docs/ClaudeCode-On-VMs.md` — Nested Dan pattern
- `docs/LocalPackageCache.md` — apt/Docker mirror

### Scripts
- `scripts/Render-Fleet.ps1` — fleet.yaml → per-VM tfvars
- `scripts/Deploy-Fleet.ps1` — terraform apply per VM, staged
- `scripts/Join-Fleet.ps1` — registration-token join flow
- `scripts/Backup-Fleet.ps1` — (not yet written; in ultraplan Phase 3)
- `scripts/patch-primary-capability-env.py` — hot-patch helper used this session
- `scripts/patch-primary-master-key.py` — hot-patch helper used this session
- `scripts/seed-test-data.py` — 50-user synthetic spend generator

---

## 7. Known issues / gotchas

1. **Primary VM's docker-compose.yml was hand-patched** (master key env var + capability-publish CAP_* vars) because of stale deploy. Fresh deploy from synced source makes this unnecessary. Do not `docker compose up -d` gov-hub again without also re-applying the `docker cp` of the new source — `up -d` recreates the container and drops the writable layer. See commit `c2d3c76` comments.
2. **Each VM has its own Postgres** — capability registry is per-VM. Cross-fleet aggregate view requires either central MSSQL fleet DB wired (scripted but not on this deploy) or federated topology endpoint (not built).
3. **OPA container isn't in the old compose** on 10.0.0.9. Policies are validated directly via `docker run openpolicyagent/opa:latest test /policies`. For May 12 demo, OPA needs to be running as a compose service — add to docker-compose.yml.tpl or verify Stream-A render adds it.
4. **Watchtower restart loop** on 10.0.0.9 — known cosmetic. Ignore for demo.
5. **Uptime Kuma subdomain routing** — broken via nginx sub-path, works via direct port 3001. Note for demo.
6. **Fleet.yaml never tested end-to-end** with the full render → deploy cycle. The scripts are committed but P1.C (edge VM) was skipped; full fleet-as-code demo requires either a redeploy or running `Render-Fleet.ps1 -WhatIf`.

---

## 8. How to resume

### Option A — Fresh assistant, cold start
1. Read this file (`docs/SESSION-RESUME.md`) end to end.
2. Read `docs/Platform-Ultraplan-v3.md` for strategic context.
3. Read `docs/Platform-Ultraplan-v3-GapAnalysis.md` for what's built vs. what's needed.
4. Run `TaskList` to see in-progress tasks.
5. Pick up at **P1.2 translation layer** (task #37). The "Next concrete step" section above has full detail.

### Option B — Me returning
1. Skim the commit log (`git log --oneline -20 origin/master`).
2. Verify live state: SSH 10.0.0.9, `docker ps`, confirm gov-hub healthy.
3. Confirm Dispute Handler still present: `GET /api/v1/agents/organization-collections/dispute-handler`.
4. Start P1.2 with the aggressive 3-day timeline.

### Quick health check command (either case)

```bash
ssh -i "C:/Users/dmedina/.ssh/id_rsa" \
    -o UserKnownHostsFile="C:/Users/dmedina/.ssh/known_hosts" \
    insidellm-admin@10.0.0.9 \
    'sudo docker ps --format "{{.Names}} {{.Status}}" | head
     MK=$(sudo grep "^LITELLM_MASTER_KEY=" /opt/InsideLLM/.env | cut -d= -f2)
     TOK=$(curl -sku "insidellm-admin:$MK" -X POST https://localhost/governance/auth/token | python3 -c "import json,sys; print(json.load(sys.stdin).get(\"access_token\",\"FAIL\"))")
     curl -sk -H "Authorization: Bearer $TOK" https://localhost/governance/api/v1/agents/ | python3 -m json.tool | head -30'
```

If that returns healthy Dispute Handler status, the live platform is intact.

---

**End of handoff document.** Safe to reboot.
