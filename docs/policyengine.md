
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
| OPA | Open Policy Agent used for evaluations only |
| Humility | Mandatory alignment constraints ensuring AI outputs remain humble, transparent, and human‑centered |
| Obligation | Mandatory enforcement action |
| Fail‑Closed | Any error results in denial |
| PHI | Protected Health Information |

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