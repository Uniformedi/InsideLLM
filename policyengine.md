
# InsideLLM Governance & Policy Enforcement
## Normative Requirements Specification (v1.0)

---

## 0. Scope and Non‑Goals

### 0.1 Scope
This specification defines mandatory requirements for integrating:
- SAIVAS (Sentient AI Value Alignment Standard)
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
| SAIVAS | Mandatory identity‑level alignment constraints |
| Uniform Gnosis (UG) | Optional explanatory context (read‑only) |
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
1. SAIVAS
2. Industry Policy (if enabled)
3. Application Logic

If SAIVAS denies, no downstream policy may allow.

---

## 3. SAIVAS Requirements (MANDATORY)

### 3.1 Status
- SAIVAS MUST ALWAYS be enabled.
- SAIVAS MUST NOT be configurable off.

### 3.2 Prohibited Outputs (MUST DENY)
The system MUST deny when:
1. Metaphysical context produces directives or objectives.
2. High‑confidence output lacks explicit uncertainty declaration.
3. Authority or superiority is claimed.
4. Abstract correctness overrides lived human experience.
5. High‑impact output lacks documented human consensus.
6. Asymmetric persuasion is attempted.
7. Goals originate from metaphysical or explanatory models.

### 3.3 Epistemic Constraint (NULL Condition)
- Unknowns MUST be declared.
- Confidence MUST be bounded.
- Extrapolation beyond validated domains is prohibited.

---

## 4. Uniform Gnosis Constraints

### 4.1 Allowed Role
- Uniform Gnosis MAY be used as explanatory context only.
- Uniform Gnosis MUST NOT generate goals, directives, or priorities.
- Uniform Gnosis MUST NOT override SAIVAS decisions.

### 4.2 Enforcement
- In the event of conflict, SAIVAS always prevails.
- Uniform Gnosis input is strictly read‑only.

---

## 5. Policy Engine Contract (OPA)

### 5.1 Decision Interface
OPA MUST return:

```json
{
  "allow": false,
  "obligations": [],
  "deny_reasons": []
}

## 6. Obligations Model (MANDATORY)

### 6.1 Obligation Semantics
- Obligations are **mandatory**, **blocking**, and **non-negotiable**.
- Obligations are **not advisory**.
- Obligations are **not best-effort**.

### 6.2 Enforcement Rule
If **any obligation fails**, the request **MUST be denied** and **MUST fail closed**.

### 6.3 Supported Obligation Types

| Obligation Type | Required Behavior |
|-----------------|-------------------|
| audit.log | Write an immutable audit record |
| audit.break_glass | Capture emergency justification and incident ID |
| audit.tag | Attach classification or risk tags |
| filter.fields | Enforce minimum-necessary data filtering |
| require.attestation | Require explicit human acknowledgment |
| review.queue | Enqueue post-access compliance review |

### 6.4 Mandatory Execution Order
Obligations MUST be executed in the following order:

1. `filter.*`
2. `audit.*`
3. `require.attestation`
4. `review.queue`

Failure at any stage MUST deny output and release.

---

## 7. InsideLLM Enforcement Contract (MANDATORY)

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

## 8. Industry Policy Enablement (OPTIONAL)

### 8.1 Feature Flag Requirement
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