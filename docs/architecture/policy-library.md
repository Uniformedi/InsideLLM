# InsideLLM Policy Library

The OPA policies that ship with the platform. Every policy is a pure
function: input in, decision out, no side effects, no external calls.
Enforcement of the obligations a policy returns happens in the
Governance Hub and LiteLLM callback layer (see `guardrails.md`).

This document is the catalog. Use it to:
- Understand what's installed by default.
- See the input shape each policy expects.
- Know what `{allow, deny_reasons, obligations}` shape comes back.
- Find the canonical source for editing or extension.

For the editor surface, see `/governance/policies` (built in commit
`0484acc`). For runtime behavior, see `docs/architecture/guardrails.md`.

---

## Layer 0 — Aggregator

### `decision.rego` — `package insidellm.policy`

The single entry point. LiteLLM's Humility callback queries this
package; everything else stacks under it.

**What it does:** unions deny reasons from `insidellm.humility` and
every `insidellm.industry.*` package present in the bundle, returns
one consolidated decision.

**Input:**
```jsonc
{
  "messages": [{"role": "user|assistant|system", "content": "..."}],
  "user_id": "string",
  "user_role": "string",
  "data_classification": "public|internal|confidential|restricted",
  "request_type": "standard|attestation|break_glass",
  "has_human_consensus": false,
  "uncertainty_declared": true,
  "within_validated_domain": true,
  "hipaa_authorized": false,
  "fdcpa_compliant_template": false,
  "sox_authorized": false,
  "ferpa_authorized": false,
  "glba_authorized": false,
  "break_glass": false
}
```

**Decision:**
```jsonc
{
  "allow": true,
  "deny_reasons": ["Humility 1: ...", "HIPAA 1: ..."],
  "obligations": ["audit.log", "filter.fields:ssn", "review.queue"]
}
```

**Precedence:** any Humility deny short-circuits the result. Industry
denies stack but cannot override Humility allows when no Humility deny
exists. **Fail-closed** — any policy error becomes a deny.

---

## Layer 1 — Humility (mandatory)

### `humility/base.rego` — `package insidellm.humility`

Implements the SAIVAS framework. Cannot be disabled. Highest precedence.

**Source of truth:** the InsideLLM repo file is a republication of
[`humility-guardrail`](https://github.com/uniformedi/humility-guardrail)
under the `insidellm.humility` package so industry overlays can sit on
top of it. Keep the rules in sync with the canonical repo; the LiteLLM
callback installs `humility-guardrail` from the canonical source at
container start (`templates/docker-compose.yml.tpl`).

**What it covers** (each rule maps to a SAIVAS principle from
*Uniform Gnosis, Volume I*):

| Rule | Denies when… |
|---|---|
| **H1** Metaphysical → directive | The user wraps a directive in spiritual / metaphysical framing to extract a non-disclosed answer. |
| **H2** Inferred consensus | The model is asked to assert a consensus the speaker has not actually established. |
| **H3** Domain over-extension | A request crosses the domain the model was validated for without uncertainty markers. |
| **H4** Break-glass without attestation | An emergency override is invoked without a corresponding human attestation. |

**Reframable vs hard deny:** some Humility denies are *reframable* —
the policy returns an obligation suggesting how to rephrase. Others
are *hard* and cannot be reframed (the SAIVAS framework's bright
lines). The LiteLLM callback handles each appropriately.

**Editing:** any Humility change is a serious decision. Edit on the
canonical repo first, run `opa test`, then republish under
`insidellm.humility` here. The platform's integrity story depends on
this rule set being verifiable against published source.

---

## Layer 2 — Industry overlays (optional, feature-flagged)

Each overlay sits under `insidellm.industry.<name>` and contributes
deny_reasons + obligations to the aggregator. Loaded by default;
admins can disable individual overlays by deleting the file from the
editor (or unsetting `policy_engine_enable` to skip OPA entirely).

### `industry/hipaa.rego` — Health Insurance Portability and Accountability Act

**Use when:** your deployment touches Protected Health Information.

**Input requires:** `data_classification`, `hipaa_authorized` (boolean
indicating the user has signed an active BAA + role-based access).

**Common denies:**
- PHI present in input but `hipaa_authorized=false`.
- Request to derive a diagnosis without a covered-entity attestation.
- Outbound message contains an MRN or ICD code without redaction obligation.

**Common obligations:** `audit.log`, `filter.fields:phi`,
`require.attestation:hipaa-baa`.

### `industry/sox.rego` — Sarbanes-Oxley

**Use when:** your deployment is a public-company financial reporting
or internal-controls workflow.

**Input requires:** `sox_authorized`, optional `attestation_id`.

**Common denies:**
- Generation of financial statement language by a user not in the
  approved attestation chain.
- Modification of audit-relevant material without a recorded approver.

**Obligations:** `audit.log:immutable`, `review.queue:financial-controls`.

### `industry/ferpa.rego` — Family Educational Rights and Privacy Act

**Use when:** your deployment serves an educational institution or
processes student records.

**Common denies:**
- Disclosure of student record data to a non-authorized party.
- Aggregation that re-identifies a student in a small cohort.

**Obligations:** `filter.fields:student-pii`, `notify.parent` for K-12.

### `industry/glba.rego` — Gramm-Leach-Bliley

**Use when:** your deployment processes consumer financial information.

**Common denies:**
- NPI disclosure outside of the financial institution's affiliate scope.
- Marketing-purpose use of information collected for service delivery.

**Obligations:** `audit.log`, `notify.privacy-officer`.

### `industry/fdcpa.rego` — Fair Debt Collection Practices Act

**Use when:** your deployment generates collection communications.

**Common denies:**
- Generated language matches a known-prohibited pattern (false threats,
  third-party disclosure of debt, contact-time violations).

**Obligations:** `template.enforce:fdcpa-compliant`,
`require.review:legal`.

### `industry/pci_dss.rego` — Payment Card Industry Data Security Standard

**Use when:** your deployment is in scope for cardholder data.

**Common denies:**
- Cardholder data appears in messages without an active CDE attestation.
- Outbound response contains PAN material without truncation obligation.

**Obligations:** `filter.fields:pan`, `audit.log:pci`.

---

## Authoring new policies

The OPA editor at `/governance/policies` will accept any well-formed
Rego file under `/opa-policies/`. To plug a new policy into the
aggregator decision:

1. **Pick a package path.** For an industry overlay,
   `insidellm.industry.<your-name>` lets the existing aggregator pick
   up your `deny_reasons` and `obligations` automatically.
2. **Use the standard input shape** above so the aggregator can route
   the same input to your rules without contortions.
3. **Return only `deny_reasons` (set of strings) and `obligations`
   (set of strings).** Do not write your own `allow`. The aggregator
   computes `allow := count(deny_reasons) == 0`.
4. **Save through the editor.** OPA validates the parse before write;
   the `--watch` flag hot-reloads the bundle.
5. **Dry-run.** Use the eval modal in the editor to send sample input
   and confirm the decision shape matches expectations.

### Example: a new internal policy

```rego
# /opa-policies/internal/my-rule.rego
package insidellm.industry.internal_release

import rego.v1

# Block requests that would generate marketing copy referencing a
# product feature flagged as not-yet-public.
deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    contains_unannounced_feature(msg.content)
    reason := "Internal: marketing copy references unannounced feature"
}

obligations contains "review.queue:marketing-counsel" if {
    count(deny_reasons) > 0
}

contains_unannounced_feature(text) if {
    some feature in {"project-orion", "claude-7"}
    contains(lower(text), feature)
}
```

Save this through the editor; the aggregator will start including it
in the consolidated decision on the next request without a restart.

---

## Testing

OPA's CLI has `opa test`, but for the platform-installed bundle the
fastest signal is the editor's dry-run modal:

1. Open `/governance/policies`.
2. Click **Dry-run eval**.
3. Set `query_path` to `insidellm.policy.decision` (or your specific
   package).
4. Paste a sample input.
5. Hit **Evaluate** — the modal renders OPA's raw response.

For repeatable test suites, use the canonical
[`humility-guardrail`](https://github.com/uniformedi/humility-guardrail)
repo — its `policies/humility/base_test.rego` covers the SAIVAS
rules and runs in CI.

---

## Provenance

- **Humility (SAIVAS framework):** Dan Medina, *Uniform Gnosis,
  Volume I*. Canonical OPA implementation:
  [uniformedi/humility-guardrail](https://github.com/uniformedi/humility-guardrail).
- **OPA itself:** [Open Policy Agent](https://www.openpolicyagent.org),
  CNCF graduated project, maintainers now at Apple as of the 2026
  team transition (see `docs/architecture/guardrails.md`).
- **Industry overlay rules:** Authored from public regulatory text;
  not legal advice. Each overlay should be reviewed by counsel
  appropriate to your deployment before reliance.
