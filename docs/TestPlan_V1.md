# InsideLLM — Test Plan V1

**Scope:** apply the 16 new platform commits (P0 through P4.1 + drift guard) to
the running primary VM at `192.168.100.10` and validate every module end-to-end
before the Parent Portfolio demo.

**Audience:** Dan + anyone pairing on the smoke run.

**Time budget:** ~20 minutes start-to-finish on a green path; ~45 minutes with
one or two triage loops.

---

## 0. Pre-flight (your workstation)

Confirm everything's pushed. Nothing on the VM should be ahead of origin.

```bash
cd C:\Users\dmedina\Documents\Projects\InsideLLM
git status              # must be clean
git log --oneline -5    # verify fc0be1d (P3.2) is tip
git push                # if the remote is behind
```

---

## 1. Land code on 192.168.100.10

```bash
ssh insidellm-primary
cd /opt/InsideLLM       # (OR wherever the repo lives on the VM)

# Safety: back up .env before anything touches Terraform
sudo cp /opt/InsideLLM/.env /opt/InsideLLM/.env.backup.$(date +%F)

# Pull the 16 new commits
git fetch origin
git log --oneline HEAD..origin/master   # review what's coming in
git pull origin master
```

---

## 2. Pick opt-ins in `terraform.tfvars`

**Conservative smoke run** — enable only the things that make the demo
narrative meaningful:

```hcl
# Already on — leave alone
governance_hub_enable          = true
policy_engine_enable           = true
chat_enable                    = true   # if already true

# NEW — turn on to validate
workers_enable                 = true   # unblocks the Dispute Handler
keycloak_enable                = true   # SSO story
keycloak_govhub_client_secret  = "REPLACE_openssl_rand_hex_32"
keycloak_owui_client_secret    = "REPLACE_openssl_rand_hex_32"
keycloak_litellm_client_secret = "REPLACE_openssl_rand_hex_32"

# LEAVE OFF for first pass — add later if time permits
n8n_enable                     = false
activepieces_enable            = false
```

Generate the secrets:

```bash
for v in govhub owui litellm; do
  echo "keycloak_${v}_client_secret = \"$(openssl rand -hex 32)\""
done
```

---

## 3. Apply

```bash
cd /opt/InsideLLM/terraform
terraform plan -var-file="../terraform.tfvars" -out tfplan 2>&1 | tee /tmp/plan.log
```

Review the plan. Expect recreates on `docker_compose.yml`, `.env`, cloud-init,
possibly the VM itself.

> **If Terraform wants to REPLACE the VM — STOP.** That destroys state. The
> intent is in-place updates to the config files + `docker compose up -d`.

```bash
terraform apply tfplan
```

Post-deploy takes ~4–6 minutes. Tail it:

```bash
sudo tail -f /var/log/InsideLLM-deploy.log
# Wait for: "Inside LLM — READY"
```

---

## 4. Smoke tests (simplest → end-to-end)

### 4a. Containers healthy

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep -v healthy
# Expect empty output (everything healthy)
# — or at most watchtower on a crash loop (cosmetic)
```

### 4b. Gov-Hub alive + new tables created

```bash
KEY=$(grep -E '^LITELLM_MASTER_KEY=' /opt/InsideLLM/.env | cut -d= -f2-)
curl -sk https://192.168.100.10/governance/health | jq
docker exec insidellm-postgres psql -U litellm -d litellm \
  -c "\dt governance_*" | grep -E "agents|actions|identity"
# Expect: governance_agents, governance_actions, governance_identity_*
```

### 4c. Core catalog auto-seeded (P1.3 + P3.1 + P3.2 + P3.3)

```bash
curl -sk -u insidellm-admin:$KEY \
  https://192.168.100.10/governance/api/v1/actions/?tenant_id=core | jq '.total'
# Expect ≥20 actions across the 7 wrapper files
```

### 4d. Portfolio dashboard (P4.1)

Open in a browser: **https://192.168.100.10/governance/portfolio**

Or curl the JSON:

```bash
curl -sk -u insidellm-admin:$KEY \
  https://192.168.100.10/governance/api/v1/portfolio/overview | jq
```

### 4e. Agent Builder UI (P1.5)

Open **https://192.168.100.10/governance/agents**.

- Sign in.
- Click **+ new agent**, fill the form.
- Publish to a `team` scope.
- Watch `runtime_sync_state` flip to `provisioned` in the UI.

### 4f. Dispute Handler end-to-end (P1.6)

```bash
# Seed it
bash /opt/InsideLLM/scripts/seed-dispute-handler.sh

# Verify
curl -sk -u insidellm-admin:$KEY \
  https://192.168.100.10/governance/api/v1/agents/example-tenant/dispute-handler | \
  jq '.status, .runtime_sync_state'
# Expect: "published", "provisioned"
```

Then: open **https://192.168.100.10/** (Open WebUI), model picker → **Dispute
Handler**. Run one turn against `HH000001` and confirm the agent calls
`lookup_account`.

### 4g. Keycloak (P1.B)

**https://192.168.100.10/keycloak/** — login: `insidellm-admin` / `<LITELLM_MASTER_KEY>`.
Switch to the `insidellm` realm and confirm the three groups
(`InsideLLM-View`, `InsideLLM-Admin`, `InsideLLM-Approve`).

```bash
curl -sk -u insidellm-admin:$KEY \
  https://192.168.100.10/governance/api/v1/identity/whoami | jq
# Expect: {"ok": true, "realm": "insidellm", ...}

curl -sk -u insidellm-admin:$KEY \
  https://192.168.100.10/governance/api/v1/identity/sync/status | jq '.runs[0]'
# Expect: most recent run with status=success
```

### 4h. DLP sidecar + notifications (P2.1)

```bash
# Dry-run scan (no webhook needed)
curl -sk -u insidellm-admin:$KEY -X POST \
  https://192.168.100.10/governance/api/v1/notifications/scan \
  -H 'Content-Type: application/json' \
  -d '{"text":"Customer SSN 123-45-6789 disputed account 12345678"}' | jq
# Expect: hit_count >= 2, has_critical=true,
#         sha12 fingerprints (no raw match)
```

---

## 5. If something breaks

| Symptom | Likely cause | Fast check |
|---|---|---|
| `governance-hub` unhealthy | PyYAML or Celery missing | `docker logs insidellm-governance-hub --tail 50` — look for `ModuleNotFoundError` |
| Agent publish fails with `0 columns` error | Column migration didn't run | `docker exec insidellm-postgres psql -U litellm -d litellm -c "\d governance_agents"` — check for `runtime_sync_state` column |
| Keycloak won't start | Postgres race | `docker logs insidellm-keycloak --tail 100`; usually resolves on retry |
| `/governance/portfolio` empty | Central DB empty | Expected on a fresh deploy — populate with `curl -sk -u insidellm-admin:$KEY -X POST https://192.168.100.10/governance/api/v1/sync/run` |
| OWUI shows no Dispute Handler | Translator partial-provisioned | `curl -sk -u insidellm-admin:$KEY -X POST .../agents/example-tenant/dispute-handler/sync` (idempotent retry) |
| Anything else | Check `/var/log/InsideLLM-deploy.log` + `docker logs insidellm-<service> --tail 100` |

---

## 6. Rollback if needed

Nuclear option — return to the last green tag before these 16 commits:

```bash
cd /opt/InsideLLM
git log --oneline | head -20            # find the last commit before d80dc9c
git checkout <sha>                      # detached HEAD is fine for smoke
cd terraform
terraform apply -var-file="../terraform.tfvars"
# Takes ~4 min to roll back
```

---

## Sign-off checklist

Mark each row ✅ before calling the validation complete:

- [ ] **4a.** Every container healthy
- [ ] **4b.** `governance_agents`, `governance_actions`, `governance_identity_*` present
- [ ] **4c.** ≥20 core catalog actions seeded
- [ ] **4d.** Portfolio dashboard loads
- [ ] **4e.** Agent created + published via UI
- [ ] **4f.** Dispute Handler responds correctly to HH000001
- [ ] **4g.** Keycloak whoami + sync green
- [ ] **4h.** DLP scan returns redacted fingerprints (no raw match)

When all eight rows are checked, the stack is Parent Portfolio-demo-ready.
