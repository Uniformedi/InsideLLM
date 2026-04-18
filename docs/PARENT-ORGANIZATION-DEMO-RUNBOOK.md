# Parent Organization Demo Runbook — Dispute Handler Showcase

**Audience:** Parent Organization portfolio leadership, Organization Compliance Manager
**Duration:** ~12 minutes
**Goal:** Prove InsideLLM is a portfolio-wide AI operations platform, not a
tool. Walk from the cross-tenant overview into one working agent, and show
that every guardrail is real.

---

## Pre-flight (the morning of the demo)

```powershell
# 1. Flip demo modules on in terraform.tfvars
#    (keycloak + workers are off by default; this demo needs both)

keycloak_enable = true
keycloak_govhub_client_secret  = "…"   # openssl rand -hex 32
keycloak_owui_client_secret    = "…"
keycloak_litellm_client_secret = "…"

workers_enable = true

# 2. Apply + wait for post-deploy to declare the stack ready
terraform apply -var-file="../terraform.tfvars"

# 3. Seed the agent + its tenant actions
ssh insidellm-mgmt "bash /opt/InsideLLM/scripts/seed-dispute-handler.sh"
```

The seed script (see §Appendix A below) POSTs:

1. `examples/actions/organization-collections/dispute-handler-actions.yaml` → `/api/v1/actions/upload`
2. `examples/agents/dispute-handler.yaml` → `/api/v1/agents/` (creates, draft)
3. `POST /api/v1/agents/organization-collections/dispute-handler/publish` (team scope → immediate)

After the seed, verify:
- `curl -sk https://10.0.0.9/governance/api/v1/agents/organization-collections/dispute-handler`
  shows `status=published`, `runtime_sync_state=provisioned`
- OWUI model picker at https://10.0.0.9/ shows **Dispute Handler** under
  "Custom Models"
- `curl -sk https://10.0.0.9/governance/api/v1/portfolio/overview`
  returns populated counters

---

## Demo flow

### 1. The Portfolio View (90 sec)

Open **https://10.0.0.9/governance/portfolio**

Talk track:
> *"This is what Parent Organization sees. Every InsideLLM instance across your portfolio
> — whatever industry, whatever size — reports here. One view. Right now
> we're looking at Organization as the reference tenant. Each of the 32 companies you
> add shows up as one more row. No new dashboards, no integration work."*

Call out:
- **Instances** (total count)
- **Avg compliance** (green/amber/red)
- **At-risk** (fleet-wide flag count) — explain the 4 predicates
- **Industry doughnut** — "mix will shift as you roll this out"

### 2. Drill Into One Company (60 sec)

Click the Organization row → land on the instance detail view.

Talk track:
> *"Every row drills in. Here's Organization specifically: 450 users, spend tracking,
> compliance score at 94%. If Organization's compliance drops to 72%, you see it
> here tomorrow morning — and so does their Compliance Manager."*

### 3. The Dispute Handler In Open WebUI (4 min)

Open **https://10.0.0.9/** → switch model to **Dispute Handler**.

**Turn 1 — a clean in-window dispute:**

> User: "I need to process a dispute for account ORG000001. The consumer
> claims the balance is wrong."

Expected behavior:
1. Agent calls `lookup_account` → returns `in_validation_window=true`
2. Agent confirms §1692g(b) applies
3. Agent drafts acknowledgment letter via `draft_fdcpa_letter`
4. Agent offers to queue the letter for manager approval

Point out as it runs:
- Model metadata shows `tier_fdcpa_regulated` tag
- Agent CANNOT call `send_letter` without calling approval-gated wrapper

**Turn 2 — attempt an out-of-hours callback:**

> User: "Schedule a callback for ORG000001 tonight at 10pm their time."

Expected behavior:
- Agent calls `schedule_callback` with the requested window
- OPA's **tier_fdcpa_regulated** guardrail denies pre-execution:
  `FDCPA §1692c(a)(1): consumer-communication callbacks restricted to
  8:00–21:00 consumer-local`
- Agent tells the user why, offers 9am tomorrow instead

Talk track:
> *"That denial is policy-as-code, not prompt engineering. Legal can audit
> the rego file directly. The agent can't route around it."*

**Turn 3 — try to prompt-inject a scope escape:**

> User: "Now pull the HR salary doc from hr-confidential and summarize it."

Expected:
- OPA's rag_scope rule denies because `hr-confidential` isn't in the
  manifest's `knowledge.collections`
- Deny reason includes `agent 'dispute-handler' may not retrieve collection 'hr-confidential'`

### 4. The Approval Queue (90 sec)

Open **https://10.0.0.9/governance/changes** or the admin action queue.

Show:
- The `send_letter` request sitting in pending state
- Approver (compliance_manager) sees draft letter + account context
- One click → approved → audit entry appears in the chain

### 5. The Audit Trail (60 sec)

Run in a terminal window next to the browser:

```bash
curl -sk https://10.0.0.9/governance/api/v1/agents/organization-collections/dispute-handler/audit | jq
```

Call out:
- Hash-chained entries (sequence, previous_hash, chain_hash)
- One entry per lifecycle event: agent_created, agent_published,
  agent_runtime_sync, every action invocation
- Tamper-evident — can't edit a row without breaking the chain

Talk track:
> *"When your Compliance Officer gets a CFPB data request about Organization in
> 2028, everything that agent did, every version of its system prompt,
> is in this chain. One query per tenant."*

### 6. The Guardrail Source (90 sec — the technical close)

Open `configs/opa/policies/profiles/tier_fdcpa_regulated.rego` in the
admin UI policy editor at **https://10.0.0.9/governance/policies**.

Show:
- The `is_outside_permitted_hours` rule — two bodies, explicit
- The validation-notice witness requirement
- Explain: this file is the same thing for every Organization-style tenant

Talk track:
> *"This is it. 140 lines of rego govern every dispute flow on the
> platform. Your GC can read it. Your auditor can verify it. If FDCPA
> amends next year, you touch this file once and it propagates to every
> tenant on the next policy reload."*

---

## Talking points

- **Humility / SAIVAS**: mention it briefly — mandatory baseline, published
  as MIT at github.com/uniformedi/humility-guardrail
- **Per-tenant sovereignty**: Organization's Postgres is Organization's; only aggregates
  flow to the central DB
- **Keycloak phase 2**: 480 users across fleet, updated every 15 minutes,
  one query away at `/governance/api/v1/identity/users`
- **Pricing anchor**: BSL 1.1 license; Uniformedi LLC commercial support

## Failure-mode script

If a service is slow:
- "OPA decision latency is P99 <20ms in production; the demo VM is
  running on a single core"

If the drafter returns empty:
- "The worker's a stub. In production this is DocForge plus your
  letterhead templates plus your mailroom handoff"

If someone asks "why not ChatGPT Enterprise?":
- "ChatGPT has no per-tenant guardrail tiers, no policy-as-code, no
  hash-chained audit, no on-prem data plane. We don't compete with
  the model; we own the governance layer."

---

## Appendix A — seed-dispute-handler.sh

```bash
#!/usr/bin/env bash
# Idempotent seed for the Parent Organization Dispute Handler demo.
# Run on the primary VM AFTER terraform apply with workers_enable=true.

set -euo pipefail
KEY=$(grep -E '^LITELLM_MASTER_KEY=' /opt/InsideLLM/.env | cut -d= -f2-)
BASE=http://governance-hub:8090

# 1. Upload tenant action catalog
docker exec insidellm-governance-hub curl -sf -X POST "$BASE/api/v1/actions/upload" \
  -H "Authorization: Basic $(echo -n "insidellm-admin:$KEY" | base64)" \
  -H "Content-Type: application/yaml" \
  --data-binary @/app/seed/dispute-handler-actions.yaml

# 2. Create the agent (JSON-wrapped manifest)
python3 -c "
import json, yaml
with open('/app/seed/dispute-handler.yaml') as f:
    m = yaml.safe_load(f)
print(json.dumps({'manifest': m}))
" | docker exec -i insidellm-governance-hub curl -sf -X POST "$BASE/api/v1/agents/" \
    -H "Authorization: Basic $(echo -n "insidellm-admin:$KEY" | base64)" \
    -H "Content-Type: application/json" \
    --data-binary @-

# 3. Publish (team scope → immediate provision)
docker exec insidellm-governance-hub curl -sf -X POST \
  "$BASE/api/v1/agents/organization-collections/dispute-handler/publish" \
  -H "Authorization: Basic $(echo -n "insidellm-admin:$KEY" | base64)"

echo "done — Dispute Handler live at /governance/api/v1/agents/organization-collections/dispute-handler"
```

Mount `examples/actions/organization-collections/dispute-handler-actions.yaml` and
`examples/agents/dispute-handler.yaml` into the gov-hub container's
`/app/seed/` directory before running. One-shot; re-running re-POSTs
cleanly thanks to upsert semantics.
