# InsideLLM OPA Policy Contract

This directory contains the complete OPA policy tree that governs every
LLM request and every catalog-action invocation on the platform. It is
the single source of truth for "what can this agent do right now, given
its profile, tenant, session state, and the data in context."

## Directory layout

```
configs/opa/policies/
├── README.md                    — this file
├── decision.rego                — aggregation layer (Humility + profile + industry)
├── humility/
│   └── base.rego                — SAIVAS core (never disabled)
├── profiles/                    — named guardrail profiles (Ultraplan v3 §5.1)
│   ├── README.md
│   ├── tier_unrestricted.rego
│   ├── tier_general_business.rego
│   ├── tier_financial_regulated.rego
│   ├── tier_fdcpa_regulated.rego
│   ├── tier_hipaa_regulated.rego
│   └── tier_custom.rego
├── industry/                    — regulation-specific overlays (selected by profiles)
│   ├── fdcpa.rego
│   ├── ferpa.rego
│   ├── glba.rego
│   ├── hipaa.rego
│   ├── pci_dss.rego
│   ├── reg_f.rego               — CFPB 12 CFR Part 1006 (7-in-7, §1006.18(d))
│   └── sox.rego
└── tests/                       — unit tests (package insidellm.tests.*)
    ├── reg_f_test.rego
    ├── tier_fdcpa_regulated_test.rego
    ├── tier_financial_regulated_test.rego
    ├── tier_general_business_test.rego
    ├── tier_hipaa_regulated_test.rego
    └── tier_unrestricted_test.rego
```

## Input schema (v1.1, Ultraplan v3 §5.2)

Every request to OPA carries an input document with the following shape.
The LiteLLM callback + Gov-Hub request handlers populate it; the
manifest-to-runtime translator (Phase 1) sets the agent-specific fields.
Fields not present are treated as absent (rules fail closed — missing
data never permits an action that required it).

```json
{
  "// --- Tenant + session identity ---": null,
  "tenant_id": "example-tenant",
  "agent_id": "dispute-handler",
  "agent_version_hash": "sha256:abc123...",
  "user_id": "jsmith@organization.com",
  "execution_id": "7f1b1e2a-...",
  "session_id": "...",

  "// --- Invocation context ---": null,
  "trigger_type": "human_chat",
  "action_id": "send_letter",
  "action_scope": "read|write|admin",
  "iteration_count": 3,
  "session_token_count": 12450,
  "session_action_count": 4,
  "max_actions_per_session": 10,
  "token_budget_per_session": 50000,

  "// --- Classification ---": null,
  "guardrail_profile": "tier_fdcpa_regulated",
  "data_classes_in_context": ["pii", "financial"],
  "data_classification": "confidential|restricted|internal|public",

  "// --- Model selection ---": null,
  "model_requested": "claude-sonnet-4-6",
  "allowed_models": ["claude-sonnet-4-6", "claude-haiku-4-5"],
  "baa_models": ["claude-sonnet-4-6"],

  "// --- Notification / channel ---": null,
  "notification_targets": ["teams"],

  "// --- Time / locale (FDCPA) ---": null,
  "time_of_day": "14:30",
  "consumer_timezone": "America/Chicago",

  "// --- Authorization witnesses (industry policies) ---": null,
  "hipaa_authorized": true,
  "break_glass": false,
  "fdcpa_compliant_template": true,

  "// --- Message history ---": null,
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

### Authorization witnesses — how they're set

| Witness | Who sets it | When |
|---|---|---|
| `hipaa_authorized` | Manifest translator | When `guardrails.profile == tier_hipaa_regulated` |
| `fdcpa_compliant_template` | Action catalog runtime | When the invoked action's template is the approved FDCPA form |
| `break_glass` | Gov-Hub audit router | When an operator invokes the break-glass flow (triggers `audit.break_glass` obligation) |

## Output contract

OPA's `data.insidellm.policy.decision` returns:

```json
{
  "allow": true,
  "deny_reasons": [],
  "obligations": [
    {"type": "audit.log", "priority": 1, "params": {"event_type": "..."}},
    {"type": "filter.fields", "priority": 2, "params": {"redact_classes": ["pii"]}},
    {"type": "review.queue", "priority": 4, "params": {"escalation_target": "..."}}
  ],
  "profile": "tier_fdcpa_regulated"
}
```

### Obligation types

| `type` | Priority (for execution order) | Consumer | Params |
|---|---|---|---|
| `audit.log` | 1 | Gov-Hub audit chain | `event_type`, `severity`, `profile` |
| `audit.tag` | 2 | Gov-Hub audit chain | `tags` (list) |
| `audit.break_glass` | 2 | Gov-Hub audit chain + alert | `reason`, `data_classification` |
| `filter.fields` | 1–2 | LiteLLM DLP callback / audit emitter | `fields`, `action` (`redact` / `drop`), `redact_classes` |
| `review.queue` | 4 | Gov-Hub approvals router | `review_type`, `regulation`, `escalation_target` |
| `require.attestation` | 3 | Gov-Hub approvals router | `attestation_type`, `regulation` |

Obligations are executed in priority order (lower = earlier). OPA never
executes obligations itself — the enforcement layer (LiteLLM callback
+ Gov-Hub router) is responsible.

## Testing

```bash
# Static check
opa check ./configs/opa/policies/

# Unit tests
opa test -v ./configs/opa/policies/

# One-off eval
opa eval -d ./configs/opa/policies/ -i input.json "data.insidellm.policy.decision"
```

Run locally with any opa binary, or against the VM with:

```bash
sudo docker run --rm \
    -v /opt/InsideLLM/opa/policies:/policies \
    openpolicyagent/opa:latest test /policies
```

### Test coverage (as of 2026-04-16)

```
46 / 46 tests passing
```

| Profile | Tests | Coverage |
|---|---|---|
| `tier_fdcpa_regulated` | 18 | hours rule all boundaries, model allowlist, discord block, supervisor approval, dispute attestation, decision.rego E2E |
| `tier_general_business` | 10 | active_industries, model allowlist, session caps, PII redaction, iteration warn, decision E2E |
| `tier_financial_regulated` | 8 | active_industries, credentials deny, discord block, write-approval, SOX tag, decision E2E |
| `tier_hipaa_regulated` | 10 | active_industries, BAA models, minimum-necessary cross-profile, channel restriction, write-approval, decision E2E |
| `tier_unrestricted` | 4 | active_industries=empty, no denies, audit.log always, decision E2E |

## Adding a new guardrail profile

1. Create `profiles/tier_<name>.rego` with `package insidellm.profile.tier_<name>`.
2. Export `active_industries` (set of industry-package names), `deny_reasons`
   (set of strings), `obligations` (set of objects matching the obligation
   schema above).
3. Add dispatch lines to `decision.rego`:
   ```rego
   profile_deny_reasons := tier_<name>.deny_reasons     if input.guardrail_profile == "tier_<name>"
   profile_obligations  := tier_<name>.obligations      if input.guardrail_profile == "tier_<name>"
   active_industries    := tier_<name>.active_industries if input.guardrail_profile == "tier_<name>"
   ```
4. Register the profile name in `GuardrailProfile` enum
   (`configs/governance-hub/src/schemas/agents.py`) so manifests can
   reference it.
5. Write `tests/tier_<name>_test.rego` — target coverage: every deny
   rule, every obligation branch, plus one E2E test via
   `data.insidellm.policy.decision`.
6. Verify: `opa check` + `opa test` (or `docker run` equivalents).
7. Commit.

## Fail-closed guarantees

- If any policy fails to evaluate (syntax error, missing input field),
  `decision` falls through to the `default decision` rule which returns
  `allow: false`.
- If a profile is not recognized, `profile_deny_reasons` = empty set but
  `active_industries` = empty set — so no industry overlays apply. The
  Humility base layer still runs. **No profile = Humility-only eval**.
- `input.guardrail_profile` missing entirely = same as unrecognized.

## Portfolio policy inheritance (Ultraplan v3 §5.3)

```
Parent Portfolio portfolio baseline
  └── Company override
       └── Agent manifest profile
            └── Session context
```

A child can only tighten the parent. Enforcement: `all_deny_reasons` is
a union — any layer's deny = overall deny. Obligations also union —
tighter policies add to the set, never remove.

Implementation of portfolio-level inheritance (Phase 4) will layer
additional `.rego` files under `configs/opa/policies/portfolio/` with a
similar dispatch pattern keyed on `input.tenant_id`.
