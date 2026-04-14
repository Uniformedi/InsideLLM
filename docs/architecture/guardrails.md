# Guardrail Architecture — OPA, DLP, and Humility

How InsideLLM enforces policy on every chat request. Every layer runs at the
**LiteLLM gateway**, so enforcement applies identically to Open WebUI, Claude
Code CLI, Chrome extensions, and any custom `/v1/` consumer.

## Request flow

```mermaid
flowchart TB
    client(["<b>Client</b><br/>Open WebUI · CLI<br/>Extension · Custom app"])
    nginx["<b>Nginx</b><br/>TLS · reverse proxy<br/>SSO subrequest"]
    client -- "HTTPS" --> nginx
    nginx -- "/v1/* · /litellm/*" --> litellm

    subgraph litellm ["<b>LiteLLM Gateway</b> — callback chain runs in order"]
        direction TB
        rl["<b>1. dynamic_rate_limiter_v3</b><br/>per-key tpm/rpm + budget"]
        hp["<b>2. humility_prompt</b><br/>inject system prompt from Redis<br/>(tier-specific)"]
        hg["<b>3. humility_guardrail</b><br/>evaluate rules (local or OPA)<br/>allow / reframe / hard-deny"]
        dlp_in["<b>4. dlp_guardrail (inbound)</b><br/>regex scan user messages<br/>+ inlined file content"]
        model[["<b>Anthropic API</b><br/>claude-haiku · sonnet · opus"]]
        dlp_out["<b>5. dlp_guardrail (outbound)</b><br/>scan assistant response<br/>redact echoed secrets"]

        rl --> hp --> hg --> dlp_in
        dlp_in -- "allowed" --> model
        model --> dlp_out
    end

    opa[("<b>OPA</b><br/>package insidellm.humility<br/>+ industry overlays")]
    hg <-. "policy decision<br/>{allow, deny_reasons, obligations}" .-> opa

    redis[("<b>Redis</b><br/>prompt cache<br/>rate-limit state")]
    hp <-. "tier prompt" .-> redis
    rl <-. "counters" .-> redis

    hub["<b>Governance Hub</b><br/>hash-chained audit<br/>SHA-256 chain"]
    hg -. "deny events" .-> hub
    dlp_in -. "detection events" .-> hub
    dlp_out -. "redaction events" .-> hub

    client_resp(["client receives<br/><b>200 OK</b> · <b>400 blocked</b>"])
    dlp_out --> client_resp
    hg -- "hard-deny<br/>(compassionate msg)" --> client_resp
    dlp_in -- "HTTP 400<br/>DLP block" --> client_resp

    classDef layer fill:#1e293b,stroke:#475569,color:#f1f5f9
    classDef enforce fill:#7f1d1d,stroke:#dc2626,color:#fee2e2
    classDef ext fill:#064e3b,stroke:#059669,color:#d1fae5
    classDef store fill:#1e3a8a,stroke:#3b82f6,color:#dbeafe
    class rl,hp layer
    class hg,dlp_in,dlp_out enforce
    class opa,hub ext
    class redis store
```

## Defense in depth

Humility is enforced at **four independent layers**. Breaking any one layer
doesn't break enforcement — the next layer catches.

| # | Layer | File | Disabling |
|---|-------|------|-----------|
| 1 | Prompt injection (soft) | `configs/litellm/callbacks/humility_prompt.py` | Cannot be disabled |
| 2 | Guardrail (hard) | `configs/litellm/callbacks/humility_guardrail.py` | Cannot be disabled |
| 3 | OPA policy (enterprise overlay) | `configs/opa/policies/humility/base.rego` | `policy_engine_enable=false` falls back to layer 2's local Python rules |
| 4 | Frontend pipeline (optional) | `configs/open-webui/opa-policy-pipeline.py` | Operator toggle in Open WebUI Functions |

Layers 1–2 run in the gateway for **all** clients. Layer 3 adds industry
overlays (HIPAA, SOX, FERPA, GLBA, FDCPA) via OPA. Layer 4 is a
frontend-only belt-and-suspenders for Open WebUI.

## DLP — what it catches and where

```mermaid
flowchart LR
    user["user message<br/>+ inlined file text"] --> scan1
    scan1{"DLP regex scan<br/><b>PATTERNS</b> + custom"}
    scan1 -- "detection" --> mode{"mode"}
    scan1 -- "clean" --> model[[model]]
    mode -- "<b>block</b>" --> http400["HTTP 400<br/>+ governance audit"]
    mode -- "<b>redact</b>" --> rewrite["rewrite content<br/>→ █████"]
    rewrite --> model
    model --> scan2{"scan response<br/>(outbound)"}
    scan2 -- "clean" --> client[["client"]]
    scan2 -- "echoed secret" --> redact2["redact + log<br/>warning"]
    redact2 --> client

    classDef block fill:#7f1d1d,stroke:#dc2626,color:#fee2e2
    classDef ok fill:#064e3b,stroke:#059669,color:#d1fae5
    class http400,redact2 block
    class client,model ok
```

Categories (all valves in `terraform.tfvars`, all default-on):

- **Credentials** (`block_credentials`) — API keys, inline passwords, AWS keys, DB connection strings, private keys
- **PII** (`block_ssn`) — Social Security Numbers
- **PHI** (`block_phi`, `block_standalone_dates`) — ICD codes, DoB patterns
- **Financials** (`block_credit_cards`, `block_bank_accounts`) — card numbers, routing/account numbers
- **Custom regex** — `dlp_custom_patterns` JSON map for deployment-specific patterns

## OPA — pure policy, InsideLLM enforces

OPA is strictly a **decision engine**. It takes JSON input, returns a Decision,
and never calls external systems. InsideLLM executes the obligations after OPA
returns.

```mermaid
sequenceDiagram
    participant GW as LiteLLM (humility_guardrail)
    participant OPA as OPA<br/>insidellm.policy.decision
    participant EX as Obligation Executor
    participant HUB as Governance Hub<br/>(hash-chained audit)

    GW->>OPA: POST /v1/data/insidellm/policy/decision<br/>{messages, user_id, user_role,<br/>data_classification, ...}
    Note over OPA: humility/base.rego +<br/>industry/*.rego overlays<br/>(HIPAA, SOX, FERPA, ...)
    OPA-->>GW: {allow: bool,<br/>deny_reasons: [...],<br/>obligations: [...]}

    alt allow
        GW->>GW: forward to model
    else deny
        GW->>EX: execute obligations
        par
            EX->>HUB: audit.log
        and
            EX->>EX: filter.fields
        and
            EX->>EX: require.attestation
        and
            EX->>EX: review.queue
        end
        GW-->>GW: hard-deny → HTTP 400<br/>compassionate response
    end

    Note over GW,HUB: <b>Fail-closed:</b> any OPA error = deny
```

**Precedence** (higher wins):

1. **Humility** — mandatory, cannot be disabled
2. **Industry policies** — optional, feature-flagged per tenant
3. **Application logic** — last resort

## Why gateway-level (not frontend)

Platform 3.x moved DLP from the Open WebUI pipeline to LiteLLM. Reasons:

- **One enforcement point covers all clients.** A Chrome extension or a
  `curl` to `/v1/chat/completions` hits the same guardrails as Open WebUI.
- **File content is already inlined** by the time the request reaches
  LiteLLM — scanning the `messages` array catches uploaded file text with no
  per-format parser.
- **Audit trails are consistent.** Every enforced decision logs to
  Governance Hub through one path with the same shape.

Legacy `configs/open-webui/dlp-pipeline.py` is still deployed but registered
inactive. Operators can re-enable it as a pre-filter, but it's no longer the
primary defense.

## Ordering matters

Callbacks run in the exact order listed in `litellm-config.yaml`:

```yaml
callbacks:
  - dynamic_rate_limiter_v3
  - callbacks.humility_prompt.proxy_handler_instance
  - callbacks.humility_guardrail.proxy_handler_instance
  - callbacks.dlp_guardrail.proxy_handler_instance
```

This order is deliberate:

1. **Rate limit first** — cheap rejection before anything else runs.
2. **Humility prompt second** — inject guidance before rule evaluation so the
   model is already primed.
3. **Humility guardrail third** — reject disallowed intent before scanning content.
4. **DLP last** — a prompt that passes intent may still carry secrets; scan
   at the last mile before the model sees it.
