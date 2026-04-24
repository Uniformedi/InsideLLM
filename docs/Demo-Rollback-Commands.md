# Demo Rollback Commands — Friday 2026-04-24 preview

**Context:** Per-segment rollback commands. Pairs with `Plan-v3.2.md §5.6`
(narrative fallbacks); this doc is the concrete command cheatsheet.

**Conventions:**
- `<vm>` = demo VM hostname or IP (e.g., the primary gov-hub host)
- `<key>` = `LITELLM_MASTER_KEY` from `/opt/InsideLLM/.env`
- Terminal pre-authed via: `MK=$(ssh <vm> 'sudo grep ^LITELLM_MASTER_KEY /opt/InsideLLM/.env | cut -d= -f2')`
- All `curl` examples use `-sk` (silent + skip TLS verify for the self-signed demo cert)

---

## Pre-demo sanity (T-30 min)

Run these as a one-shot health check. All should pass before the demo starts.

```bash
# Host + gateway health
curl -sk https://<vm>/health                              # expect: 200
curl -sk https://<vm>/nginx-health                        # expect: 200
curl -sk https://<vm>/litellm/health/liveliness           # expect: 200
curl -sk https://<vm>/governance/api/v1/health            # expect: 200

# Container inventory
ssh <vm> 'docker ps --format "{{.Names}}\t{{.Status}}"'   # all Up

# Agent live state
curl -sk https://<vm>/governance/api/v1/agents/example-tenant/dispute-handler \
  | jq '{status, runtime_sync_state}'
# expect: { "status": "published", "runtime_sync_state": "provisioned" }

# Tenant + portfolio
curl -sk https://<vm>/governance/api/v1/portfolio/overview | jq '.total_instances, .compliance_score_avg'
# expect: integer >= 2, number between 0–100

# Worker reachable via action catalog
curl -sk -X POST https://<vm>/governance/api/v1/actions/example-tenant/lookup_account/invoke \
  -H "Content-Type: application/json" \
  -d '{"account_number":"ACME0001"}' \
  | jq '.account_summary.balance'
# expect: a number

# Audit chain intact
curl -sk https://<vm>/governance/api/v1/audit/chain/verify | jq '{valid, length, broken_at}'
# expect: { "valid": true, "length": ~100, "broken_at": null }

# Clock (for segment 4)
ssh <vm> 'date'
# expect: HH:MM in 22:00–23:00 local range after intentional clock skew
```

---

## Segment 0 — Framing (3 min)

**Flake mode:** slide deck doesn't render.

**Rollback:**
- Open `html/one-pager.html` in the browser instead. It has the same narrative in condensed form.
- Narrate verbally: "Integrity is the buying decision, not capability. Everything we're about to demo is a control that makes AI adoption auditable for your portfolio."

---

## Segment 1 — Portfolio overview (4 min)

**Flake mode:** dashboard doesn't load, or loads with empty counters.

**Rollback commands:**

```bash
# Hit the underlying API to show the data exists
curl -sk https://<vm>/governance/api/v1/portfolio/overview | jq

# If API works but UI doesn't: manually walk the response
curl -sk https://<vm>/governance/api/v1/portfolio/overview | jq '.instances[] | {name, industry, compliance_score, at_risk}'

# If API returns empty: re-seed
ssh <vm> 'docker exec insidellm-governance-hub python -m scripts.seed_tenants'
```

**Narration fallback:** "The dashboard is the Admin Center rollup. For each portfolio company, it shows compliance score, spend, DLP blocks, and audit chain health. One row per tenant."

---

## Segment 2 — Industry Packs slide (2 min)

**Flake mode:** slide missing; can't show the packs list.

**Rollback commands:**

```bash
# Show the packs on disk
ssh <vm> 'ls /opt/InsideLLM/configs/industry-packs/'
# Expect: collections  financial-services  healthcare  README.md

# Or read the pack manifest
cat configs/industry-packs/collections/manifest.yaml | head -20
```

**Narration fallback:** "Five packs: Collections is the reference sample; Healthcare and Financial Services are scaffolded; Education and Property Management are v3.3. Each pack is a vertical starter kit — agents, DLP patterns, document templates, and policy overlay — layered on the shipped guardrail profiles."

---

## Segment 3 — Dispute Handler happy path (6 min)

**Flake mode:** agent hangs, tool call errors, or doesn't return a draft.

**Rollback commands:**

```bash
# Verify LiteLLM routing
curl -sk https://<vm>/litellm/health/liveliness
ssh <vm> 'docker logs insidellm-litellm --tail 30'

# Directly invoke the four actions the agent would call
curl -sk -X POST https://<vm>/governance/api/v1/actions/example-tenant/lookup_account/invoke \
  -H "Content-Type: application/json" \
  -d '{"account_number":"ACME0001"}' | jq

curl -sk -X POST https://<vm>/governance/api/v1/actions/example-tenant/draft_fdcpa_letter/invoke \
  -H "Content-Type: application/json" \
  -d '{"account_number":"ACME0001","dispute_reason":"billing error","in_validation_window":true}' | jq '.letter_markdown'

# Show the resulting draft already in the approval queue
curl -sk https://<vm>/governance/api/v1/changes?type=send_letter\&status=pending | jq '.[0]'
```

**Narration fallback:** "Production routes the response faster than the demo stub. The key moment is that the draft lands in the approval queue — not in the consumer's inbox. No letter goes out without a compliance manager signing off."

---

## Segment 4 — Out-of-hours OPA deny (4 min) 🎯 money moment

**Flake mode:** OPA allows when it should deny. Most commonly: demo clock not set.

**Rollback commands:**

```bash
# Confirm clock is actually skewed
ssh <vm> 'date'
# If NOT showing 22:15+: set it
ssh <vm> 'sudo date -s "22:15"'
ssh <vm> 'docker exec insidellm-opa date'   # OPA should see the same time

# Manually evaluate OPA for the scenario
curl -sk -X POST https://<vm>/governance/api/v1/opa/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "agent_meta": {"guardrail_profile": "tier_fdcpa_regulated"},
      "action": "schedule_callback",
      "request": {"callback_window_start": "2026-04-24T22:00:00-05:00"}
    }
  }' | jq '{allow, deny_reasons}'
# Expect: { "allow": false, "deny_reasons": ["FDCPA §1692c(a)(1): ..."] }

# If still no deny, show the rego file directly
cat configs/opa/policies/profiles/tier_fdcpa_regulated.rego | grep -A 10 "is_outside_permitted_hours"
```

**Narration fallback:** "If the deny doesn't fire in the UI, we know why — the clock or the policy loader. But the rule itself is right here in the rego file. This is what enforces §1692c(a)(1) in production. Legal can audit the file directly."

---

## Segment 5 — RAG scope escape (4 min)

**Flake mode:** agent accesses `hr-confidential` when it shouldn't.

**Rollback commands:**

```bash
# Verify the scope rule is loaded
curl -sk https://<vm>/governance/api/v1/opa/bundles | jq '.[] | select(.name | contains("rag_scope"))'

# Directly test RAG scope denial
curl -sk -X POST https://<vm>/governance/api/v1/opa/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "agent_meta": {
        "agent_id": "dispute-handler",
        "knowledge": {"collections": ["dispute-procedures","fdcpa-reference","state-variations"]}
      },
      "action": "rag_retrieve",
      "request": {"collection": "hr-confidential"}
    }
  }' | jq '{allow, deny_reasons}'
# Expect: allow=false, reason cites hr-confidential not in scope

# Show the rule
cat configs/opa/policies/humility/rag_scope.rego | head -30
```

**Narration fallback:** "The agent's allowed knowledge collections are in its manifest. Anything else is denied at the OPA layer before retrieval runs. Prompt injection can ask all it wants; the guardrail doesn't care what the prompt says, only what the manifest permits."

---

## Segment 6 — DLP live (3 min)

**Flake mode:** DLP fails to redact SSN or credit card.

**Rollback commands:**

```bash
# Direct DLP pattern test
curl -sk -X POST https://<vm>/governance/api/v1/dlp/scan \
  -H "Content-Type: application/json" \
  -d '{"text":"My SSN is 123-45-6789 and card 4111-1111-1111-1111"}' | jq

# Show the DLP pattern file
cat configs/industry-packs/collections/dlp/collections-patterns.yaml | head -40

# Verify LiteLLM callback is registered
ssh <vm> 'docker exec insidellm-litellm cat /app/litellm_config.yaml' | grep -A 3 dlp
```

**Narration fallback:** "The DLP engine runs at the LiteLLM gateway — inlet and outlet. Every pattern is in a YAML file, per industry, versioned. Your team can read them. Your auditor can verify them."

---

## Segment 7 — Hash-chained audit (3 min)

**Flake mode:** chain verify times out or returns invalid.

**Rollback commands:**

```bash
# Pre-compute and cache
curl -sk https://<vm>/governance/api/v1/audit/chain/verify > /tmp/chain-verify.json
jq '{valid, length, broken_at}' /tmp/chain-verify.json

# Tamper-evidence demo on a 10-entry sample (faster than full chain)
curl -sk https://<vm>/governance/api/v1/audit/chain/verify?limit=10 | jq

# Induce tamper
ssh <vm> 'docker exec insidellm-postgres psql -U litellm -c "UPDATE governance_audit SET event_payload = jsonb_set(event_payload, \"{note}\", \"\\\"tampered\\\"\") WHERE seq = 50"'

# Re-verify — should return invalid=true, broken_at=50
curl -sk https://<vm>/governance/api/v1/audit/chain/verify | jq '{valid, broken_at}'

# Undo the tamper after the demo segment
ssh <vm> 'docker exec insidellm-postgres psql -U litellm -c "UPDATE governance_audit SET event_payload = event_payload - \"note\" WHERE seq = 50"'
```

**Narration fallback:** "The chain is SHA-256 over every event's prior hash. Corrupting any row forks the chain at that point and everything downstream fails verify. A regulator can verify the chain directly — the endpoint is public to authorized users."

---

## Segment 8 — Rego is the policy (2 min)

**Flake mode:** policy editor UI fails.

**Rollback commands:**

```bash
# Show the file on disk via SSH
ssh <vm> 'cat /opt/InsideLLM/configs/opa/policies/profiles/tier_fdcpa_regulated.rego' | less

# Or from the local repo clone
cat configs/opa/policies/profiles/tier_fdcpa_regulated.rego | head -60

# Or via GitHub
# https://github.com/Uniformedi/InsideLLM/blob/master/configs/opa/policies/profiles/tier_fdcpa_regulated.rego
```

**Narration fallback:** "The policy file is ~140 lines of Rego. Two rules — `is_outside_permitted_hours` and the validation-notice witness — anchor FDCPA enforcement. A General Counsel can read this in five minutes. That is the contract between AI behavior and the regulation."

---

## Segment 9 — Roadmap tease (1 min)

**Flake mode:** slide fails.

**Rollback:** hand the principal the printed one-pager (`html/one-pager.html`). Everything in segment 9 is on the one-pager.

---

## Post-demo immediate actions (within 2 hours)

```bash
# 1. Reset the VM clock — non-negotiable
ssh <vm> 'sudo ntpdate -u pool.ntp.org' || ssh <vm> 'sudo systemctl restart systemd-timesyncd'
ssh <vm> 'date'                    # confirm back to real time

# 2. Undo any tamper-evidence demo corruption (if not already done in segment 7)
ssh <vm> 'docker exec insidellm-postgres psql -U litellm -c "UPDATE governance_audit SET event_payload = event_payload - \"note\" WHERE seq = 50"'

# 3. Verify chain is healthy again
curl -sk https://<vm>/governance/api/v1/audit/chain/verify | jq '{valid, broken_at}'
# Expect: {valid: true, broken_at: null}
```

---

## If the whole network drops mid-demo

1. Close laptop screen; acknowledge the drop verbally with no apology
2. Open phone; swipe to the screenshot album (per `§5.5` prep checklist, you have 7 images ready: portfolio dashboard, OWUI model picker, OWUI after turn 1, OPA deny modal, approval queue, audit `jq` output, rego file)
3. Narrate each image using the Plan-v3.2.md §5.3 segment text verbatim
4. Hand the principal the printed one-pager as the close
5. Propose a working-session reschedule within 48 hours

---

*Last updated 2026-04-24. Owner: Dan Medina. Paired with `Plan-v3.2.md §5.6`.*
