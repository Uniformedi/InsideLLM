# Proposed Variables Additions

Small, self-contained additions to `terraform/variables.tf` that would
unlock measurable iteration-velocity wins and cleaner demo-prep. Not
committed — this doc describes the exact diffs for you to review and
apply yourself.

Each addition is non-breaking: defaults preserve current behavior.

---

## 1. `litellm_cache_enable` — Redis response cache

**Problem.** During demo-prep and rehearsal the same 3–5 prompts run
through the same agent 10+ times. Each run hits Anthropic end-to-end,
burns tokens, and adds unpredictable latency. LiteLLM supports a
Redis-backed response cache natively; Redis is already in the Compose
stack.

**Proposed diff** — add to `terraform/variables.tf`:

```hcl
variable "litellm_cache_enable" {
  type        = bool
  default     = false
  description = <<-EOT
    Enable LiteLLM's Redis-backed response cache. Recommended for
    demo-prep and rehearsal iterations (zero token spend on repeat
    prompts). Disable for production unless you understand the
    implications of serving cached completions across users/tenants.
  EOT
}

variable "litellm_cache_ttl_seconds" {
  type        = number
  default     = 3600
  description = "LiteLLM response cache TTL in seconds when cache is enabled."
}
```

**LiteLLM config wire-up** — edit `configs/litellm/config.yaml` (or
equivalent template) to consume the new vars:

```yaml
%{ if litellm_cache_enable ~}
litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: redis
    port: 6379
    ttl: ${litellm_cache_ttl_seconds}
%{ endif ~}
```

**Rehearsal rule.** Always run the final rehearsal round with cache
OFF to confirm real-path latency and correctness. Cached rehearsals
lie to you about what the principal will see.

---

## 2. `deployment_profile` — one flag to rule them all

**Problem.** `docs/DemoPrep-Fast-Iteration.md §3` lists ~12 tfvars
toggles that together define "demo-prep mode." Remembering all 12 on
each new VM is a foot-gun. One string flag that expands into a set of
locals makes this reliable.

**Proposed diff** — add to `terraform/variables.tf`:

```hcl
variable "deployment_profile" {
  type        = string
  default     = "prod"
  description = <<-EOT
    Profile that bundles sensible defaults for a class of deployment.

    - "prod"  : production defaults (current behavior; every feature ON).
    - "dev"   : developer-friendly (core services ON, background ops OFF).
    - "demo"  : demo-prep iteration (minimal boot, services OFF except
                demo-path; LiteLLM cache ON). See
                docs/DemoPrep-Fast-Iteration.md.

    Individual variables still override the profile. The profile sets
    the default; explicit var = value wins.
  EOT
  validation {
    condition     = contains(["prod", "dev", "demo"], var.deployment_profile)
    error_message = "deployment_profile must be one of: prod, dev, demo"
  }
}
```

**Wire-up** — a `locals` block that projects the profile into defaults
used by the rest of `main.tf`:

```hcl
locals {
  profile_defaults = {
    prod = {
      ollama_enable          = true
      ops_trivy_enable       = true
      ops_watchtower_enable  = true
      ops_uptime_kuma_enable = true
      cockpit_enable         = true
      litellm_cache_enable   = false
      vm_memory_dynamic      = false
    }
    dev = {
      ollama_enable          = true
      ops_trivy_enable       = false
      ops_watchtower_enable  = false
      ops_uptime_kuma_enable = false
      cockpit_enable         = true
      litellm_cache_enable   = false
      vm_memory_dynamic      = true
    }
    demo = {
      ollama_enable          = false
      ops_trivy_enable       = false
      ops_watchtower_enable  = false
      ops_uptime_kuma_enable = false
      cockpit_enable         = false
      litellm_cache_enable   = true
      vm_memory_dynamic      = true
    }
  }

  # Resolve: explicit variable value wins; otherwise profile default;
  # otherwise the variable's own default.
  effective_ollama_enable          = var.ollama_enable != null ? var.ollama_enable : local.profile_defaults[var.deployment_profile].ollama_enable
  effective_ops_trivy_enable       = var.ops_trivy_enable != null ? var.ops_trivy_enable : local.profile_defaults[var.deployment_profile].ops_trivy_enable
  # …etc. — one line per profile-governed variable
}
```

**Note:** this is slightly more invasive than the cache flag because
existing variables have non-null defaults that override the profile.
Two options:

1. **Change the existing variables to `default = null`** and use
   `coalesce(var.x, local.profile_defaults[...].x)` everywhere — cleanest,
   but touches more lines of main.tf.
2. **Leave existing defaults in place and document "profile only applies
   when the variable is omitted from tfvars"** — less clean, no code
   changes to existing consumers. The wording of the `description`
   block above hints at this semantics.

Option 2 is safer for demo week; Option 1 is better long-term.

---

## 3. `industry_packs_enable` — auto-seed at provision

**Problem.** Collections pack agents, DLP patterns, and doc templates
exist in `configs/industry-packs/collections/` but require manual
seeding (`scripts/seed-dispute-handler.py`). A `terraform apply` today
does not register the pack.

**Proposed diff**:

```hcl
variable "industry_packs_enable" {
  type        = list(string)
  default     = []
  description = <<-EOT
    List of industry-pack IDs to auto-register at provision time.
    Each ID corresponds to a directory under configs/industry-packs/.
    Packs are registered via the governance-hub's pack-loader on
    first boot after deploy. Agents are registered as `draft` unless
    the pack manifest says otherwise.

    Example: ["collections"]
  EOT
}
```

**Wire-up** — a new `post-deploy.sh.tpl` hook that iterates the list
and calls `scripts/seed-industry-pack.py <id>` for each. Seed scripts
must be idempotent (the Collections seed already is).

This lands after 3.2 cycle — it requires a pack loader we haven't
written yet. Flagging here so the variable name stays reserved.

---

## 4. `demo_mode_clock_offset_minutes` — mock-time for §1692c demo

**Problem.** `tier_fdcpa_regulated.rego` reads `input.time_of_day` to
enforce 8 AM – 9 PM contact hours. Today, rehearsing the "out of
hours" denial requires `sudo timedatectl set-ntp false && set-time
22:15:00` on the demo VM — breaks NTP and has to be manually reverted.

**Proposed diff**:

```hcl
variable "demo_mode_clock_offset_minutes" {
  type        = number
  default     = 0
  description = <<-EOT
    Number of minutes to add to wall-clock time when populating
    input.time_of_day for OPA decisions. Lets operators rehearse the
    §1692c out-of-hours denial without re-clocking the VM. Non-zero
    values should NEVER be used outside demo-prep — every policy
    decision becomes a lie about when it happened.
  EOT
}
```

**Wire-up** requires a small change in the LiteLLM callback or
governance-hub policy input builder: when computing `time_of_day`,
add the offset if set. Guard with a prominent WARN log every time a
decision uses a non-zero offset, so it can't silently affect
production.

---

## Priority order if time is tight

1. **`litellm_cache_enable`** — 30 minutes, saves real money + latency
   during rehearsal. Do first.
2. **`deployment_profile`** — 1 hour if you go with Option 2 above; 3
   hours if Option 1. Worth it for repeat demo setups.
3. **`demo_mode_clock_offset_minutes`** — 1 hour. Only worth it if the
   §1692c demo is being rehearsed daily.
4. **`industry_packs_enable`** — deferred past 3.2 cycle; reserves the
   variable name so the future PR has a stable API surface.

## What NOT to add

- A "disable_opa" or "disable_dlp" emergency flag. Those would create
  a way to serve demos with the integrity layer off, which is exactly
  what the product should never allow. If rehearsal requires bypassing
  OPA, the test is wrong, not the platform.
