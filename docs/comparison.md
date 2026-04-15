# InsideLLM in the AI Control Plane Landscape

Where InsideLLM sits among AI gateways, AI control planes, and
alignment frameworks. Written to be honest, not defensive — if a peer
does a given thing better for your deployment, the right answer is to
use the peer and turn the overlapping InsideLLM module off.

This document pairs with the
[Vendor Directory](../configs/governance-hub/src/services/vendor_seed.py)
and [Attributions](ATTRIBUTIONS.md). Peers listed here earn stars there
like anyone else.

---

## Summary matrix

| Capability | InsideLLM | LiteLLM | Tyk AI Studio | Kong AI Gateway | Portkey |
|---|---|---|---|---|---|
| OpenAI-compatible model gateway | ✅ (via LiteLLM) | ✅ (primary) | ✅ | ✅ | ✅ |
| Self-hosted on-prem (not Kubernetes-first) | ✅ | ✅ | ✅ | ⚠️ K8s preferred | ⚠️ SaaS-first |
| Policy-driven routing / cost control | ✅ | ✅ | ✅ | ✅ | ✅ |
| Observability + spend tracking | ✅ | ✅ | ✅ | ✅ | ✅ |
| Hash-chained tamper-evident audit trail | ✅ | ❌ | ❌ | ❌ | ❌ |
| DLP at the gateway (PII / PHI / credentials / financials) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Humility / SAIVAS alignment enforcement | ✅ | ❌ | ❌ | ❌ | ❌ |
| OPA industry overlays (HIPAA / SOX / FERPA / GLBA / FDCPA / PCI-DSS) shipped as Rego | ✅ | ❌ | ❌ | ❌ | ❌ |
| Policy editor with dry-run evaluator | ✅ | ❌ | ⚠️ plugin SDK | ⚠️ plugin SDK | ❌ |
| Shared-skill catalog with AD-group gating | ✅ | ❌ | ❌ | ❌ | ❌ |
| Values-aligned vendor directory | ✅ | ❌ | ❌ | ❌ | ❌ |
| Browser extension for "AI-everywhere" sidebar | ✅ | ❌ | ❌ | ❌ | ❌ |
| Admin form for realm-join / AD integration | ✅ | ❌ | ❌ | ❌ | ❌ |
| Per-VM Linux web management (Cockpit integrated) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Fleet-wide audit aggregation to central SQL | ✅ | ❌ | ❌ | ❌ | ❌ |

`✅` = first-class feature. `⚠️` = partial / requires plugin / different deployment model. `❌` = not offered by that tool.

---

## Honest overlap, by peer

### LiteLLM

LiteLLM is **the model gateway** inside InsideLLM — the two aren't peers,
they're stack layers. Every DLP / Humility / OPA callback in the
platform plugs into LiteLLM's callback chain. If you're running LiteLLM
today and you want the governance layer, InsideLLM is the addition,
not the replacement.

### Tyk AI Studio

Tyk is our **closest architectural peer**. Both ship a control plane
over AI traffic. Tyk's March 2026 open-source move validated the
category; their announcement emphasizes "extensibility and plugins" as
the differentiator.

**Overlapping surface** (if you run Tyk, you can defer these from
InsideLLM):
- Basic model routing / cost control / observability
- Plugin-based custom guardrails
- UI control plane for gateway operations

**Non-overlapping surface** (InsideLLM-only, on by default regardless):
- Humility / SAIVAS alignment as enforced policy
- DLP at the gateway as a first-class feature
- OPA industry overlays as shipped Rego (not plugin-you-write)
- Hash-chained audit trail
- Values-aligned vendor directory + attribution document
- Governance Hub's AD-join form, Cockpit, Hyper-V host page

### Kong AI Gateway

Kong AI Gateway is a plugin on top of Kong Gateway — phenomenal if your
organization is already a Kong shop on Kubernetes. Similar overlap to
Tyk on the gateway/policy layer. Same non-overlap story: no Humility,
no DLP-at-gateway, no compliance-overlay Rego.

### Portkey

Portkey is SaaS-first with a strong observability/ops story. If your
constraint is "no customer data may leave our VPC," Portkey isn't a
fit and InsideLLM's on-prem posture is. If it's "we want spend
analytics and don't care about on-prem," Portkey is simpler.

---

## The defer-to-peer principle

**If a customer already runs a peer tool that serves an overlapping
surface better for them, InsideLLM should shut off the overlapping
module — not fight it.** Two reasons:

1. **Customer welfare beats platform completeness.** A well-run Tyk
   instance configured by a team that knows Tyk beats a generic
   InsideLLM re-implementation of the same feature.
2. **Our edge is the unique surface, not the commodity surface.**
   Routing, cost tracking, and basic policy are commodities now — five
   tools ship them. Humility, SAIVAS enforcement, hash-chained audit,
   and opinionated alignment are where InsideLLM is actually load-
   bearing. Keeping only those always-on means our differentiator gets
   the focus.

The implementation of the actual deferral (Terraform variables like
`tyk_ai_studio_endpoint = "..."` that render compose with overlapping
services skipped) is queued as task H1. This document is the
philosophical foundation; the code follows.

---

## "Piecemeal contribution" as a distinct signal

The vendor directory tracks a separate contribution type called
`MODULE_EXTRACTION` for vendors who decouple meaningful parts of their
own commercial platform into standalone FOSS components — and gives it
2x the points of a standard OSS contribution, because it takes real
design work and usually loses some commercial leverage.

Why it's tracked separately: maintaining a large monorepo and slapping
an MIT license on it isn't the same commitment as actively breaking
your own product apart into independently adoptable pieces. Uniformedi
did this with `humility-guardrail` (extracted from InsideLLM so it can
run inside any LLM gateway, not just ours). Tyk just did it with AI
Studio Community Edition.

**KPI:** `MODULE_EXTRACTION` count surfaces on the vendor directory as
a separate ⚙ badge alongside ★ stars. Vendors high on that metric are
the ones actively enlarging the commons.

---

## Where InsideLLM defers outright

There are already things we don't try to reimplement:

- **Vault / OpenBAO / Azure Key Vault** — InsideLLM doesn't ship a
  secrets backend. Once the key-management integration is done
  (the ultraplan-that-died; revisit per roadmap), it'll be another
  native defer.
- **Windows Admin Center** — we ship a thin functional subset for the
  Hyper-V bits that matter to us; the full product is Microsoft's
  and should stay there.
- **Grafana, Loki, Netdata, Uptime Kuma** — observability stack.
  InsideLLM integrates them, doesn't reimplement them.
- **Open WebUI** — chat UI. We don't build our own.

Every one of these is also in the vendor directory with stars. That's
the pattern: credit the work, use the work, don't rebuild the work.

---

## What this means for a prospective buyer

If you already operate Tyk or Kong or Portkey and are shopping for AI
governance: **don't replace**. Adopt InsideLLM for the
Humility/DLP/compliance/audit layer, keep your existing gateway. The
deferral path is a first-class supported topology, not a workaround.

If you're starting fresh: the full InsideLLM stack gives you the
integrated path. You can always extract later if your needs grow into
a best-of-breed component elsewhere.
