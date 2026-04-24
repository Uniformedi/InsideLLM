# Demo-Prep Fast Iteration

**Companion to:** [DefaultDeployment.md](DefaultDeployment.md)
**Scope:** temporary, iteration-focused Terraform + operator patterns used
between "clone the repo" and "demo-ready." Never ship these settings to a
customer — §12 has the revert checklist.

---

## 1. Why this doc exists

`DefaultDeployment.md` documents the variables that make a production-grade
InsideLLM deployment. Those defaults are correct for production and
actively wrong for demo prep. Under demo-prep pressure, every minute of
deploy time compounds — a 6-minute `terraform apply` × 40 iterations is
4 hours you don't have.

This doc is the iteration profile: what to turn off, what to cache, what
to snapshot, and — the part most speedup guides miss — **what *not* to
touch** even when you're tempted.

## 2. The three iteration loops

Under pressure, engineers reach for "make deploy faster" when the real
win is often "stop redeploying." There are three loops, each with its
own right tool:

| Loop | Trigger | Right tool | Target time |
|---|---|---|---|
| **Inner** (seconds) | "Does this YAML parse? Does this Rego compile?" | `opa test`, `python -m json.tool`, local lint. **No VM.** | 1–5 s |
| **Middle** (tens of seconds) | "Does this config change produce the decision I expect?" | `docker compose restart <service>`, `docker exec psql`, bind-mount config + `curl` | 20–60 s |
| **Outer** (minutes) | "Does the full demo path still work end-to-end?" | Snapshot restore → scripted smoke test | 2–5 min |

**Rule:** never use an outer-loop tool for an inner-loop question. Most
velocity loss comes from running `terraform apply` when `opa test` would
have answered the question in 3 seconds.

### 2.1 Inner-loop tools already in the repo (use them!)

- **OPA tests** in `configs/opa/policies/tests/*.rego` — run locally:
  ```bash
  opa test configs/opa/policies/ -v
  ```
  No VM, no containers. 10 rego files + 5 test files cover the shipped
  profiles. If you're changing `tier_fdcpa_regulated.rego` or
  `rag_scope.rego`, this is the right loop.

- **JSON Schema validation** for agent manifests and action catalogs —
  validate locally before committing to DB.

- **YAML lint** on industry-pack agents before they hit the governance
  hub.

## 3. The demo-prep Terraform profile

Copy this block into `terraform.tfvars` during iteration. Revert
selectively for final rehearsal (§12).

```hcl
# =============================================================================
# DEMO-PREP PROFILE — iterate fast. Do not ship to customers.
# =============================================================================

# --- VM resources: smaller + dynamic ---------------------------------------
vm_processor_count             = 4
vm_memory_startup_bytes        = 17179869184     # 16 GB (default: 32 GB)
vm_memory_dynamic              = true            # lazy-allocate; run 2-3 VMs per host
vm_disk_size_bytes             = 42949672960     # 40 GB (default: 80 GB)

# --- Ollama: OFF unless the demo path uses it -------------------------------
# Ollama pulls ~18 GB on first boot. Skip it during iteration, flip ON for
# rehearsal only if a demo segment uses a local model.
ollama_enable                  = false

# --- Ops / background services: OFF during iteration ------------------------
# Each adds boot time, background CPU, and log noise you don't want while
# debugging. None are demo-path.
ops_trivy_enable               = false
ops_watchtower_enable          = false
ops_uptime_kuma_enable         = false
cockpit_enable                 = false

# --- Identity: keep local/admin-only until rehearsal ------------------------
# AD join is flaky and slow. SSO adds IdP round-trips. Use local admin for
# iteration; turn both on Thursday evening for the final walkthrough.
ad_domain_join                 = false
sso_provider                   = "none"
ldap_enable_services           = false

# --- Non-demo optional services ---------------------------------------------
chat_enable                    = false
guacamole_enable               = false

# --- DEMO PATH — keep ON --------------------------------------------------
# These are in the demo narrative. Do not turn off.
policy_engine_enable           = true
policy_engine_industry_policies = ["fdcpa", "sox", "pci_dss"]
policy_engine_fail_mode        = "closed"
dlp_enable                     = true
dlp_mode                       = "block"
governance_hub_enable          = true
docforge_enable                = true
ops_grafana_enable             = true            # operator observability during demo

# --- Local package cache — point at primary ---------------------------------
# Single biggest speedup for 2nd+ VM (~20 min/deploy saved). See
# docs/LocalPackageCache.md for the full story.
apt_mirror_host                = "192.168.100.10"      # or your primary IP
docker_mirror_host             = "192.168.100.10"

# --- Industry + defaults for Collections demo ------------------------------
industry                       = "collections"
governance_tier                = "tier3"
data_classification            = "restricted"
```

### 3.1 Why each line saves time

| Variable | What happens when you flip it OFF | Saves |
|---|---|---|
| `ollama_enable = false` | Skip container + no model pulls | ~5–10 min on first deploy, ~18 GB disk |
| `ops_trivy_enable = false` | Skip CVE scan at boot | ~60 s per boot + background CPU |
| `ops_watchtower_enable = false` | Skip update-watcher container + no image churn under you | ~15 s + stability |
| `ops_uptime_kuma_enable = false` | One fewer container | ~20 s |
| `cockpit_enable = false` | Skip Cockpit install | ~30 s + /cockpit/ endpoint noise |
| `ad_domain_join = false` | Skip `sssd`, `realmd`, `adcli` — the slowest cloud-init step | ~2–4 min + flake risk |
| `sso_provider = "none"` | Skip OIDC client dance | ~1 min + external IdP dependency |
| `ldap_enable_services = false` | Skip LDAP wiring in Grafana/OWUI/pgAdmin | ~30 s |
| `chat_enable = false` | No Mattermost container | ~90 s + memory |
| `guacamole_enable = false` | No Guacamole + OAuth2-proxy | ~60 s |
| `vm_memory_dynamic = true` | Hyper-V lazy-allocates | Lets you run 2–3 demo VMs simultaneously |
| `apt_mirror_host`, `docker_mirror_host` | Pull through cached proxies | ~20 min/deploy after cache warms |

**Combined typical deploy time: ~25 min → ~5–6 min.**

## 4. Cache strategy — seven layers

"Enable the local package cache" is one of seven caches that affect
iteration speed. The biggest wins are layers 1–3; 4–7 are smaller but
cumulative.

| # | Cache | Location | What it saves | Status in 3.1.0 |
|---|---|---|---|---|
| 1 | apt | `/opt/InsideLLM/data/apt-cache/` (primary) | ~10 min/deploy | ✅ shipped (`LocalPackageCache.md`) |
| 2 | Docker images | `/opt/InsideLLM/data/registry/` (primary) | ~8 min/deploy | ✅ shipped |
| 3 | Ollama model weights | Docker volume | ~5–15 min/pull | ✅ shipped (bind mount) |
| 4 | Python wheels | — | ~30–90 s/rebuild | ❌ not cached. Fix: `pip download` warmup dir, or devpi. |
| 5 | LiteLLM response cache | Redis | Same prompt × 20 rehearsals = 20× free | ⚠️ LiteLLM supports it; not enabled by default. Worth a flag. |
| 6 | Terraform plan cache | `.terraform/` | ~10 s per plan | ✅ automatic; don't `rm -rf .terraform`. |
| 7 | Browser asset cache | operator's browser | Admin Center UI feels faster | Manual — use a dedicated "InsideLLM demo" browser profile. |

### 4.1 The LiteLLM response-cache opportunity

Rehearsal typically runs the same 3–5 prompts through the same agent 10+
times. Today every prompt hits Anthropic and burns tokens, adding
unpredictable latency and nonzero dollars. LiteLLM's response cache
(Redis-backed) lets identical prompts return in ~0.1 s from Redis with
zero token spend.

Not currently exposed in `variables.tf`. Small PR worth ~30 minutes:

```yaml
# configs/litellm/config.yaml (concept)
litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: redis
    port: 6379
    ttl: 3600
```

And a tfvar:

```hcl
variable "litellm_cache_enable" {
  type    = bool
  default = false       # default off for production
}
```

Flip on during iteration only. Rehearse once with it OFF to confirm
real-path behavior before the demo.

## 5. Snapshot discipline — the three-named-snapshot pattern

**This is the biggest iteration-velocity multiplier in the whole doc.**
It's not a Terraform knob; it's a workflow. A full redeploy is ~6 min. A
Hyper-V checkpoint restore is ~30 s. The difference is 12×.

Maintain exactly three named snapshots on the demo VM. Don't accumulate
more — snapshot sprawl becomes its own problem.

| Snapshot | When you take it | What you revert *to* |
|---|---|---|
| **`seeded-clean`** | Right after the first successful full deploy + all seed scripts run + smoke test green | After any iteration that leaves the VM in an unknown state |
| **`rehearsal-ready`** | After final Thursday-evening rehearsal, with demo VM clock NOT set to 22:15 yet | Demo morning, if overnight anything changed the VM |
| **`pre-demo`** | Friday AM, after clock is set to 22:15 and the operator browser tabs are preloaded | During demo, if absolutely everything goes sideways — the ultimate "reset the room" |

```powershell
# Take snapshot (from the Hyper-V host)
Checkpoint-VM -Name InsideLLM -SnapshotName "seeded-clean"

# Restore
Restore-VMCheckpoint -Name "seeded-clean" -VMName InsideLLM -Confirm:$false
```

**Prerequisite:** seed scripts must be idempotent (§6). If they aren't,
"revert to seeded-clean and re-seed" leaves you in a different state
each time, and the pattern breaks.

## 6. Seed idempotency — the quiet demo blocker

`TestPlan_V1.md` §4f calls for:

```bash
bash /opt/InsideLLM/scripts/seed-dispute-handler.sh
```

**This script does not exist in the repo.** Grep confirms. The Dispute
Handler is the centerpiece of both the Friday demo and the May 12
showcase; the seed that creates it is a ghost reference.

This is an iteration-velocity issue (can't snapshot without a
deterministic seed) AND a demo-day risk (no seed script means demo
prep relies on manual DB inserts). Before Friday:

1. Write `scripts/seed-dispute-handler.sh` (or `.py`, matching the
   existing `seed-test-data.py` / `seed-owui-bg.py` style).
2. Make it idempotent: use `ON CONFLICT DO NOTHING` in SQL (the pattern
   in `seed-test-data.py:152`), or check-then-insert.
3. Drive it from the Collections industry pack YAML
   (`configs/industry-packs/collections/agents/dispute-handler.yaml`) so
   that editing the YAML = re-seed = correct agent state.
4. Test it runs 5 times in a row, ending with the same DB state every
   time.

Effort: ~1 hour. Saves every subsequent iteration a manual seed step
and makes snapshots trustworthy.

## 7. The critical path: what must work, what can break

For the Friday demo, 8 things matter. Everything else can be broken
with impunity during iteration.

**Must work (demo path):**
1. Demo VM boots, Admin Center loads at `https://192.168.100.10/`
2. Portfolio dashboard renders seeded data
3. Open WebUI chat works, Dispute Handler appears in model picker
4. `lookup_account` action returns canned response
5. `draft_validation_notice` renders a DocForge template
6. OPA denies out-of-hours callback (clock-sensitive)
7. DLP redacts/blocks on sample PII + credit card
8. `GET /api/v1/audit/chain/verify` returns `{"valid": true}`

**Can break during iteration (non-demo):**
- Grafana dashboards (only matter for operator observability pane)
- Loki log aggregation
- Ollama and local models
- Trivy, Watchtower, Uptime Kuma
- Guacamole, Mattermost
- External data connectors
- Claude Code CLI on the VM
- Keycloak (unless the demo includes SSO segment)

During iteration, **ignore non-demo-path failures**. Triaging Watchtower
crash loops when you should be rehearsing the Dispute Handler is how
demo prep burns.

## 8. Anti-patterns — things that look like speedups but aren't

Under time pressure these will tempt you. Don't.

| Anti-pattern | Why it backfires |
|---|---|
| **Disable OPA to speed up requests.** | Policy decisions are ~5 ms. Irrelevant latency. And your demo narrative hinges on OPA denials. |
| **Set `log_retention_days = 1`.** | When something breaks in the final rehearsal, you'll wish for more than 1 day of logs. |
| **Turn off hash-chain checkpointing.** | Cheap. The chain-verify demo depends on it. |
| **Lower `litellm_default_user_rpm` to "save quota".** | A tight RPM limit will fire *during* the demo, not in rehearsal. Keep it generous. |
| **`docker system prune -a` when things feel slow.** | Wipes the image cache you just spent 8 minutes warming. Prune selectively. |
| **`terraform apply --auto-approve` blindly.** | TestPlan §3 warns: if Terraform wants to REPLACE the VM, STOP. Approve-before-apply saves 40 minutes of state recovery. |
| **Skip the `terraform plan` review.** | Same reason. |
| **`docker compose up --force-recreate` on the whole stack for one service change.** | Use `docker compose restart <service>` or `up -d <service>`. |
| **`:latest` image tags for "latest features".** | Registry mirror will serve stale, and production pins versions. Don't diverge. |
| **Run rehearsal against Opus for best quality.** | Ratings quality does not depend on Opus; latency does. Rehearse on Sonnet, demo on Sonnet. |
| **"Just one more optimization" at 10 PM Thursday.** | Freeze the stack by Thursday afternoon. Rehearse with the stack you will demo on. |

## 9. Risk / revert matrix

Every speedup has a revert cost. Optimize where revert is cheap;
be conservative where it isn't.

| Speedup | Revert path | Revert time | Risk if you forget to revert |
|---|---|---|---|
| `vm_memory_dynamic = true` | tfvars flip, `terraform apply` | 6 min | Contention lag during demo |
| `ollama_enable = false` | tfvars flip + 18 GB download | 10+ min | Demo segment needing local model breaks |
| `ops_trivy/watchtower/uptime_kuma = false` | tfvars flip, `terraform apply` | 6 min | None for demo; production posture degraded |
| `ad_domain_join = false` | tfvars + AD credentials + IdP sync | ~15 min | Domain users can't auth |
| `sso_provider = "none"` | tfvars + IdP client secrets | ~10 min | No SSO demo segment possible |
| `apt_mirror_host` / `docker_mirror_host` | Empty the vars, restart VM | ~5 min | Slower second deploy, no correctness risk |
| `policy_engine_enable = false` | NEVER do this during prep | — | Demo narrative breaks entirely |
| `dlp_enable = false` | NEVER do this during prep | — | Same |
| LiteLLM response cache ON | Disable flag | 1 min | Stale responses in rehearsal — always rehearse last round with cache OFF |
| Hyper-V snapshot | Hyper-V snapshot delete | 1 min | Snapshot chain sprawl slows Hyper-V |

## 10. Knobs that don't exist today but should

Quick PRs worth doing before or during demo-prep week — each unlocks
faster iteration or removes manual steps.

| Knob | What it does | Effort |
|---|---|---|
| `deployment_profile = "demo"\|"dev"\|"prod"` | Bundles the tfvars in §3 under one flag | ~30 min; locals + conditionals in variables.tf |
| `litellm_cache_enable` | Turns on Redis response cache | ~30 min |
| `industry_packs_enable` (list) | Auto-seeds pack agents on provision | ~1–2 h, depends on loader |
| `demo_mode_clock_offset_minutes` | Lets OPA §1692c demo work without manually re-clocking the VM | ~1 h; adds a mock-time pin to Rego input |
| `skip_optional_healthchecks` | Reduces compose healthcheck intervals 15s → 3s during iteration | ~20 min |
| `demo_seed_deterministic = true` | Forces stable UUIDs + timestamps in seed scripts so snapshots stay byte-identical | ~1 h |

## 11. Operator toolkit — one-liners for the Friday-prep week

Bookmark these. Every one saves 30 seconds × dozens of uses.

```bash
# Is every container healthy? (empty output = all green)
docker ps --format '{{.Names}}\t{{.Status}}' | grep -v healthy

# Tail only the governance-hub logs (the demo-path service)
docker logs -f --tail 100 insidellm-governance-hub

# Reload Collections agent YAML without a redeploy
docker compose restart governance-hub && \
  sleep 3 && \
  curl -sk -u insidellm-admin:$KEY \
    https://192.168.100.10/governance/api/v1/agents/example-tenant/dispute-handler/sync

# Verify the audit chain — core demo moment
curl -sk -u insidellm-admin:$KEY \
  https://192.168.100.10/governance/api/v1/audit/chain/stats | jq

# Force a governance-hub sync (default is every 6 h; force during prep)
curl -sk -u insidellm-admin:$KEY -X POST \
  https://192.168.100.10/governance/api/v1/sync/run

# OPA tests — inner loop. Run anywhere with OPA installed, no VM needed.
opa test configs/opa/policies/ -v

# OPA evaluation — middle loop. Test a policy decision against a JSON input.
opa eval -d configs/opa/policies/ \
  -i /tmp/decision-input.json \
  "data.insidellm.profile.tier_fdcpa_regulated.deny_reasons"

# Hyper-V snapshot (from Windows host PowerShell)
Checkpoint-VM -Name InsideLLM -SnapshotName "seeded-clean"
Restore-VMCheckpoint -Name "seeded-clean" -VMName InsideLLM -Confirm:$false

# Set demo clock to 22:15 for §1692c out-of-hours demo
# (run on the demo VM; no NTP when you do this)
sudo timedatectl set-ntp false
sudo timedatectl set-time 22:15:00

# Reset clock after rehearsal — DO NOT FORGET
sudo timedatectl set-ntp true
```

## 12. Demo-day revert checklist — Thursday evening

At the end of Thursday, flip these back ON for final rehearsal. Re-rehearse
the full 45-minute flow **after** flipping. Any segment that works only
in demo-prep mode should be investigated before Friday AM.

```hcl
# Thursday-evening production-aligned overrides
# (run this as a second apply, atop the §3 demo-prep tfvars)

sso_provider                   = "azure_ad"        # or "okta"
# …and set the client id/secret/tenant_id…

ad_domain_join                 = true              # if the demo shows AD groups
ldap_enable_services           = true              # if the demo shows LDAP login

# Leave these OFF — they are not demo-path and add flake:
# ops_watchtower_enable        = false
# ops_trivy_enable             = false
# ops_uptime_kuma_enable       = false
```

Then:
- Take snapshot **`rehearsal-ready`**.
- Walk the full 9-segment demo flow from `Friday-Demo-Plan-2026-04-24.md`.
- Fix anything. Take **`pre-demo`** snapshot.
- Go to sleep.

## 13. The higher-order principle

**Clock time isn't the bottleneck. Uncertainty about state is.**

A 6-minute redeploy you trust completely is less expensive than a
30-second restart that sometimes leaves the system in an unknown
state. A fast iteration you then spend 15 minutes debugging was slower
than the slow iteration that worked.

Every recommendation in this doc is in service of that principle:

- **Named snapshots** are "known states I can return to cheaply."
- **Idempotent seeds** are "the same state, every time I run."
- **Inner-loop tools** (`opa test`) are "the answer, not the rollout."
- **Non-demo-path failures** (Watchtower etc.) are "don't let irrelevant
  uncertainty consume attention."
- **Image tag pinning + cache freshness checks** are "the container I
  started last hour is the same container I'm starting now."

When an optimization is tempting but introduces new uncertainty
("hmm, is my change in the image yet, or is it the cached one?"), the
optimization is a net loss. Be willing to slow down for determinism.

## 14. Honesty check

This profile exists to make *you* faster. It is not a product
recommendation. Do not:

- Ship these settings to a customer's production VM.
- Show a customer a rehearsal built on LiteLLM response cache without
  warning — "our response times" shouldn't mean "our cache hit rate."
- Commit `terraform.tfvars` with the demo-prep profile to the repo
  default branch without a banner making clear it's demo-prep.

The production defaults in `DefaultDeployment.md` are correct. This
doc is a temporary companion for the operator — read it on Wednesday,
delete the mental model on Monday.
