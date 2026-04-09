
# InsideLLM Governance & Policy Enforcement
## Normative Requirements Specification (v1.0)

---

## 0. Scope and Non‑Goals

### 0.1 Scope
This specification defines mandatory requirements for integrating:
- Humility (Mandatory AI Alignment Policy)
- Optional industry regulatory policies (e.g., HIPAA)
- OPA (Open Policy Agent) for authorization decisions
- InsideLLM as the policy enforcement host

### 0.2 Non‑Goals
- This specification does NOT define user interfaces or model architecture.
- It does NOT define metaphysical ontology.
- It does NOT permit policies to execute side effects.
- It does NOT address training data or learning methods.

All requirements herein are normative unless explicitly marked OPTIONAL.

---

## 1. Definitions

| Term | Definition |
|-----|------------|
| InsideLLM | Runtime system that invokes LLMs and tools |
| OPA | Open Policy Agent — a pure, side‑effect‑free policy evaluation engine (see Section 1.1) |
| Pure evaluation | OPA receives input, evaluates rules, returns a decision. It never logs, persists, filters, queues, or calls external systems. |
| Humility | Mandatory alignment constraints ensuring AI outputs remain humble, transparent, and human‑centered |
| Obligation | Mandatory enforcement action executed by InsideLLM (not OPA) after a policy decision |
| Fail‑Closed | Any error results in denial |
| PHI | Protected Health Information |

---

## 1.1 Why OPA (Open Policy Agent)

OPA is the only mature, FOSS, language‑agnostic policy engine that enforces a critical architectural constraint: **policy evaluation must be pure and side‑effect free.**

This specification requires that policy rules never log, persist, filter, queue, or call external systems. OPA is purpose‑built for exactly this — rules are written in Rego, the engine receives input as JSON, and it returns a structured decision (`allow`, `deny_reasons`, `obligations`). It never touches a database, never writes a file, never makes an HTTP call. It is a **pure function evaluator**.

### Why not alternatives?

| Option | Why it does not fit |
|--------|---------------------|
| Hardcoded rules in Python | Mixes policy logic with enforcement code. Cannot test policies independently. Cannot version or audit rules separately from application code. |
| Casbin | Primarily RBAC/ABAC access control. Does not support the obligation model (returning structured actions for the host to execute). |
| Cedar (AWS) | New, AWS‑coupled, limited ecosystem. No obligation return type. |
| Custom rules engine | Reinvents what OPA already provides. No community, no tooling, no built‑in test framework. |
| DLP pipeline only | DLP scans content patterns. Policy decisions are about context — who is asking, what governance tier applies, what data classification, whether attestation is needed. Different concern. |

### What "pure evaluation" means in practice

- **Testable offline:** `opa test ./policies/` — unit test every rule without Docker, without a database, without network access.
- **Replayable:** Feed the same input JSON, get the same decision. No hidden state.
- **Auditable:** Prove to regulators exactly what the policy evaluated, with no side effects muddying the result.
- **Fast:** OPA evaluates in‑memory in under 5 ms. The heavy lifting (logging, redacting, blocking, queueing for supervisor review) happens in the InsideLLM enforcement pipeline *after* OPA returns its decision.
- **Separation of concerns:** Rules (Rego files) are versioned and deployed independently from application code. Updating a policy does not require redeploying InsideLLM.

### Architecture summary

```
Request → InsideLLM Pipeline → OPA (pure decision) → InsideLLM Pipeline (side effects)
                                    │                         │
                              Receives JSON input       Executes obligations:
                              Returns: allow/deny        - filter.fields
                                       deny_reasons      - audit.log
                                       obligations       - audit.break_glass
                              Never writes, logs,        - audit.tag
                              or calls anything.         - require.attestation
                                                         - review.queue
```

---

## 2. Architectural Invariants (MUST)

### 2.1 Separation of Concerns
- OPA MUST be pure and side‑effect free.
- InsideLLM MUST execute all side effects.
- Policies MUST NOT log, persist, filter, queue, or call external systems.

### 2.2 Precedence Order (HARD)
1. Humility
2. Industry Policy (if enabled)
3. Application Logic

If Humility denies, no downstream policy may allow.

---

## 3. Humility Requirements (MANDATORY)

### 3.1 Status
- Humility MUST ALWAYS be enabled.
- Humility MUST NOT be configurable off.

### 3.2 Prohibited Outputs (MUST DENY)
The system MUST deny when:
1. Output produces unsupported directives or objectives.
2. High‑confidence output lacks explicit uncertainty declaration.
3. Authority or superiority is claimed.
4. Abstract correctness overrides lived human experience.
5. High‑impact output lacks documented human consensus.
6. Asymmetric persuasion is attempted.
7. Goals originate from unvalidated or speculative models.

### 3.3 Epistemic Constraint (NULL Condition)
- Unknowns MUST be declared.
- Confidence MUST be bounded.
- Extrapolation beyond validated domains is prohibited.

---

## 4. Policy Engine Contract (OPA)

### 4.1 Decision Interface
OPA MUST return:

```json
{
  "allow": false,
  "obligations": [],
  "deny_reasons": []
}

## 5. Obligations Model (MANDATORY)

### 5.1 Obligation Semantics
- Obligations are **mandatory**, **blocking**, and **non-negotiable**.
- Obligations are **not advisory**.
- Obligations are **not best-effort**.

### 5.2 Enforcement Rule
If **any obligation fails**, the request **MUST be denied** and **MUST fail closed**.

### 5.3 Supported Obligation Types

| Obligation Type | Required Behavior |
|-----------------|-------------------|
| audit.log | Write an immutable audit record |
| audit.break_glass | Capture emergency justification and incident ID |
| audit.tag | Attach classification or risk tags |
| filter.fields | Enforce minimum-necessary data filtering |
| require.attestation | Require explicit human acknowledgment |
| review.queue | Enqueue post-access compliance review |

### 5.4 Mandatory Execution Order
Obligations MUST be executed in the following order:

1. `filter.*`
2. `audit.*`
3. `require.attestation`
4. `review.queue`

Failure at any stage MUST deny output and release.

---

## 6. InsideLLM Enforcement Contract (MANDATORY)

InsideLLM **MUST**:

1. Query OPA for every sensitive request.
2. Immediately deny when `allow == false`.
3. Execute **all returned obligations** when `allow == true`.
4. Block output until obligations complete successfully.
5. Record obligation execution success or failure.
6. Fail closed on system, network, or dependency error.

InsideLLM **MUST NOT**:

- Skip obligations for performance reasons
- Defer obligations asynchronously
- Return partial or speculative results
- Override policy results

---

## 7. Industry Policy Enablement (OPTIONAL)

### 7.1 Feature Flag Requirement
Industry policies **MUST** be toggled via runtime data, not code changes.

Example:

```json
{
  "features": {
    "industry": {
      "hipaa": { "enabled": true }
    }
  }
}