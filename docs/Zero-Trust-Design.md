# InsideLLM — Zero Trust Design

**Classification:** Internal engineering design
**Drafted:** 2026-04-22
**Owner:** Dan Medina
**Status:** Design draft — scopes v3.3 Zero Trust work
**Related artifacts:**
- `html/Architecture.html` — the architecture baseline this builds on
- `html/Roadmap.html` — where v3.3 sits
- `docs/Ticketing-Design.md` — companion design (ZT is a prerequisite for the vendor/partner ticketing tier)

This document captures the engineering scope for closing InsideLLM's
remaining gaps against NIST SP 800-207 Zero Trust Architecture, including
the v3.3 WireGuard-based fleet mesh via Headscale and the customer-facing
Zero Trust whitepaper that ships alongside the release. A subset of this
document is promoted to the whitepaper at v3.3 GA.

---

## Design principles

1. **Identity-centric, not network-centric.** Location on the network never grants trust. Every request carries verifiable identity. InsideLLM already follows this principle; v3.3 documents and extends it.
2. **Continuous verification.** There is no "trusted session" that outlives the OIDC token. Every LiteLLM request re-evaluates policy against current manifest + current rules + current spend + current rate-limit state.
3. **Layered enforcement.** Transport encryption (TLS / WireGuard / mTLS) is necessary but not sufficient. Application-layer policy (OPA + LiteLLM callbacks) is the real control. The framework is the sum; no single layer is the framework.
4. **Encrypted everywhere.** External, internal-to-fleet, cross-site — all encrypted. No "trusted internal network" exception.
5. **Microsegmentation at every layer.** Docker bridge intra-VM; WireGuard inter-VM; OPA scope per-request.
6. **Auditable, tamper-evident.** Every decision lands in the hash-chained audit chain. Customer auditors can verify directly.
7. **Fail closed.** Any control failure results in denial, not permission.
8. **Don't confuse the tube with the framework.** WireGuard is transport. Zero Trust is architecture. Marketing language must reflect this distinction.

---

## NIST SP 800-207 alignment

NIST SP 800-207 defines a reference architecture with named components
(Policy Engine, Policy Administrator, Policy Enforcement Point, etc.) and
supporting data sources (ID Management, CDM, Threat Intelligence, SIEM,
Activity Logs, Data Access Policies, PKI, Industry Compliance).

InsideLLM's current alignment:

### Core ZT components — fully aligned today

| NIST component | InsideLLM mechanism | Evidence |
| --- | --- | --- |
| Policy Engine (PE) | OPA sidecar at :8181 | `configs/opa/policies/`; `opa test` returns 46/46 |
| Policy Administrator (PA) | Governance Hub FastAPI | `configs/governance-hub/src/` |
| Policy Enforcement Point (PEP) | LiteLLM callbacks + Nginx `auth_request` + OWUI pipelines | `configs/litellm/callbacks/`, `configs/open-webui/` |
| Policy Decision Point (PDP) | OPA returns `{allow, deny_reasons, obligations}` | `_build_opa_input` in `humility_guardrail.py` |

### Supporting data sources

| NIST data source | InsideLLM mechanism | Status |
| --- | --- | --- |
| ID Management | OIDC (Entra / Okta) + LDAP + three-mode admin auth | ✅ complete |
| Data Access Policies | Agent manifests + OPA scope rules | ✅ complete |
| Activity Logs | Langfuse + Governance Hub hash-chained audit | ✅ complete |
| Industry Compliance | Humility + 6 industry policy bundles | ✅ complete |
| CDM (Continuous Diagnostics + Mitigation) | Netdata + Uptime Kuma + LiteLLM callbacks | ⚠️ partial — no active threat-hunting |
| Threat Intelligence | none | ❌ **Gap — close v3.4** |
| PKI / workload identity | implicit per-service TLS; no SPIFFE or mTLS | ❌ **Gap — close v3.3–v3.4** |
| SIEM correlation | Loki stores; no correlation engine | ❌ **Gap — close v3.4 via SIEM forwarder** |

### Network / transport

| Element | Current state | Gap? |
| --- | --- | --- |
| External encryption | HTTPS via Nginx TLS 1.2/1.3 | ✅ |
| Intra-VM encryption | Docker bridge isolation (not required per NIST guidance for intra-host traffic) | ✅ |
| Inter-VM same-fleet | Customer-managed (Hyper-V switch or public internet) | ❌ **Gap — close v3.3 via WireGuard mesh** |
| Cross-site / multi-region | Public internet or customer VPN | ❌ **Gap — close v3.3 via WireGuard mesh** |
| Workload identity at transport layer | none | ❌ **Gap — close v3.4** |

### Overall posture

InsideLLM is ~70% aligned with NIST SP 800-207 today. Three concrete gaps:

1. **Fleet-to-fleet / cross-site secure transport** → close in v3.3 via WireGuard + Headscale
2. **Workload identity / PKI** → close in v3.3–v3.4 via mTLS for vendor/partner APIs + internal SPIFFE consideration
3. **SIEM correlation + threat intelligence** → close in v3.4 via forwarder + feed integration

---

## Gap 1 — Fleet mesh secure transport (v3.3)

### Problem

A fleet spanning multiple physical sites or multiple enterprise boundaries
has no built-in secure overlay. Parent Organization's use case — 32
portfolio companies, potentially diverse networks and regions — hits this
gap directly. Aggregating Portfolio View data over public internet is not
attractive to security-conscious buyers.

### Options considered

| Option | Pros | Cons | Verdict |
| --- | --- | --- | --- |
| Customer-managed VPN (IPSec, OpenVPN) | Familiar to IT teams | Heavy config; customer operational burden; InsideLLM can't ship it as default | Reject |
| mTLS on public internet between Governance Hubs | No overlay; uses existing TLS | Every Governance Hub exposed to internet; heavier PKI burden | Reject for multi-site; keep for vendor API |
| Raw WireGuard peer-to-peer | Modern crypto; simple; fast | Manual peer config doesn't scale beyond 3-4 nodes | Reject — doesn't scale |
| **Tailscale (SaaS)** | Mature; OIDC ACLs; excellent UX | SaaS dependency on Tailscale Inc.; conflicts with on-prem positioning | Reject for default; acceptable as option |
| **Headscale (self-hosted Tailscale control plane)** | Same client experience as Tailscale; self-hostable; OIDC identity | Less mature operationally than Tailscale | ✅ **Selected as default** |
| Netbird (self-hostable OSS) | Open source; comparable feature set | Smaller community than Headscale | Alternative; not default |

### Chosen design: Headscale + WireGuard

**Architecture:**

```
                          +-----------------------+
                          |   Headscale control   |
                          |   plane (FastAPI-      |
                          |   adjacent service)    |
                          |   + OIDC backend       |
                          +-----------+-----------+
                                      | OIDC login
                                      | ACL push
                                      |
         +-----------------+----------+----------+-----------------+
         |                 |                     |                 |
   +-----v-----+     +-----v-----+         +-----v-----+     +-----v-----+
   | InsideLLM |     | InsideLLM |         | InsideLLM |     | InsideLLM |
   | instance  |<--->| instance  |<------->| instance  |<--->| instance  |
   |  (Site A) |     |  (Site A) | WG mesh |  (Site B) |     |  (Site C) |
   +-----------+     +-----------+         +-----------+     +-----------+

         Each instance runs a WireGuard daemon; Headscale distributes
         keys + ACLs; identity anchored to the customer's OIDC provider.
```

**Key properties:**

- **One Headscale control plane per customer.** Self-hosted, typically co-located with the primary Governance Hub. Customer owns the identity.
- **Every InsideLLM instance in the fleet becomes a Headscale peer.** Auto-registration on first boot via the existing fleet-registration token.
- **Identity-bound ACLs.** A fleet node's access scope (primary / gateway / workstation / voice / edge) maps to a WireGuard ACL group. A primary node can reach everyone; a workstation node can reach only the primary.
- **Fleet sync flows over WireGuard only.** Governance Hub fleet-sync API moves from `/governance/api/v1/fleet/*` over public internet to the same path over the WireGuard overlay (`100.64.0.0/10` by default in Tailscale-family addressing).
- **OIDC integration.** Same IdP used for admin auth is used by Headscale. No new identity system.
- **TCP fallback (DERP relay equivalent).** For fleet nodes behind firewalls that block UDP, run a TCP relay on the primary. Keeps the mesh functional for locked-down network environments.

**Terraform variables added (v3.3):**

```
zerotrust_enable                = true
zerotrust_headscale_enable      = true   # deploy Headscale on this instance
zerotrust_headscale_url         = "https://ts.corp.example"
zerotrust_oidc_issuer_url       = "..."  # reuses admin OIDC config
zerotrust_fleet_role            = "primary" | "gateway" | "workstation" | "voice" | "edge"
zerotrust_tcp_relay_enable      = false  # enable DERP-equivalent relay
zerotrust_acl_preset            = "strict" | "standard" | "open"
```

**What changes operationally:**

- Fleet registration token now returns a WireGuard key + Headscale enrollment code instead of a raw JWT only.
- Post-deploy script adds WireGuard setup + Headscale client enrollment.
- Governance Hub's fleet-sync endpoints move to listen only on the WireGuard interface.
- Admin UI adds a "Fleet Mesh" tab showing peer status, last-seen, ACL group membership.

### Non-goals for v3.3

- Cross-customer WireGuard (customer A cannot reach customer B; explicitly not a multi-tenant fabric)
- End-user VPN (employees don't connect via WireGuard; they use HTTPS + OIDC as today)
- AI agent connections via WireGuard (agents use LiteLLM keys; transport is HTTPS to LiteLLM)
- Replacing mTLS for vendor APIs (WireGuard is internal; external APIs use mTLS)

---

## Gap 2 — Workload identity / PKI (v3.3 partial, v3.4 complete)

### v3.3 scope: vendor / partner mTLS

For external API access (vendor integrations, partner APIs), add mTLS on
top of existing OAuth 2.0 client credentials. Implementation:

- Governance Hub issues per-vendor X.509 client certificates (Smallstep CA or self-hosted step-ca)
- Nginx validates client cert against the issuing CA before routing to upstream
- Certificate expiry + rotation automated (90-day cycle by default)
- Per-vendor scope maps to Nginx location + LiteLLM key restrictions

Terraform variables:

```
vendor_mtls_enable                 = true
vendor_mtls_ca_cert                = "..."  # CA root certificate
vendor_mtls_cert_lifetime_days     = 90
vendor_mtls_revocation_enable      = true   # OCSP stapling or CRL
```

### v3.4 scope: SPIFFE / workload identity

Introduce SPIFFE identities for inter-service traffic within the VM. This
is a bigger lift:

- SPIRE server deployed as a sidecar alongside Governance Hub
- Each service (LiteLLM, Open WebUI, Governance Hub, OPA, etc.) gets a SPIFFE ID and workload certificate
- Inter-service calls become mTLS with SPIFFE identity
- Closes the "trust the Docker bridge" assumption

Deferred to v3.4 because the Docker bridge isolation is already adequate
per NIST guidance for intra-host traffic. Benefit is defense-in-depth, not
closure of an urgent gap.

---

## Gap 3 — SIEM correlation + threat intelligence (v3.4)

### SIEM forwarder

Current state: Loki stores logs; no correlation engine; customer must
operate their own SIEM if they want one.

v3.4 adds a SIEM forwarder as a Governance Hub module:

- Structured event stream from LiteLLM callbacks + Governance Hub audit
- Standard formats: CEF, LEEF, STIX (configurable)
- Outbound adapters: Splunk HEC, Elastic Common Schema, Datadog, Microsoft Sentinel, Chronicle
- Customer configures the endpoint; InsideLLM emits events

### Threat intelligence

Inbound threat intelligence feed integration:

- MITRE ATT&CK for tactic/technique tagging of OPA denies
- Known bad IP / domain feeds → inform DLP + rate-limit + OPA scope decisions
- AI-specific threat feeds (prompt injection signatures, jailbreak patterns)

Integrated into OPA input schema as additional `threat_context` fields.
Feed ingestion is the customer's choice of provider; platform consumes
STIX-formatted inputs.

---

## Customer-facing whitepaper (v3.3 GA)

The internal engineering design above is promoted to a customer-facing
document shipped alongside the v3.3 release.

### Target audience

- Compliance officers / security architects at Parent Organization and similar regulated-industry buyers
- Procurement teams evaluating Zero Trust posture as a vendor-qualification criterion
- Federal-adjacent customers evaluating against OMB M-22-09 and CISA Zero Trust Maturity Model

### Whitepaper outline

```
InsideLLM and Zero Trust: A NIST SP 800-207-Aligned Architecture

1. Executive summary
   - InsideLLM as a ZT-aligned AI governance platform
   - v3.3 closes the multi-site transport gap
   - Roadmap to full alignment by v4

2. What Zero Trust is (and isn't)
   - NIST SP 800-207 definition
   - Common misconceptions ("Zero Trust is not a product")
   - The principle: identity-centric, continuous, least-privilege, encrypted

3. InsideLLM's alignment to NIST SP 800-207
   - Core ZT components mapping (PE / PA / PEP / PDP)
   - Supporting data sources mapping (CDM, ID, Activity Logs, etc.)
   - ~70% pre-v3.3 coverage; ~95% with v3.3; full alignment v3.4

4. WireGuard fleet mesh (v3.3)
   - Why WireGuard, why Headscale
   - Architecture overview (customer-friendly diagram)
   - What it closes, what it doesn't
   - Deployment model

5. Identity layer
   - OIDC / LDAP / agent manifests / vendor mTLS
   - Continuous verification in practice

6. Policy layer
   - OPA + Humility + industry bundles
   - Policy-as-code transparency for customer audit

7. Observability and audit
   - Hash-chained audit as tamper-evident ZT log
   - Verification endpoint
   - SIEM forwarder (v3.4 preview)

8. Alignment to CISA Zero Trust Maturity Model
   - Per-pillar self-assessment (Identity / Device / Network / Application / Data)
   - "Initial / Advanced / Optimal" maturity ratings with honest gaps

9. What customers still own
   - Certificate trust roots (customer CA for mTLS)
   - Model-provider privacy posture (Anthropic, OpenAI contracts)
   - Endpoint security (not in scope — separate product class)

10. Implementation checklist for customers
    - 30-day enablement plan
    - 90-day maturity ramp
    - Artifacts provided by InsideLLM (policy files, audit verification, conformity templates)

11. Verification
    - How to audit the claims in this paper directly against the running system
    - Independent audit artifacts (SOC 2 Type I, Type II, etc.)

Appendix A: NIST SP 800-207 mapping table
Appendix B: CISA Zero Trust Maturity Model self-assessment
Appendix C: OPA policy examples for ZT-relevant controls
Appendix D: WireGuard + Headscale deployment guide
```

Estimated length: 20-25 pages. Drafted in v3.2 window; refined + published
at v3.3 GA.

---

## Sequencing

| Version | Scope | Key deliverables |
| --- | --- | --- |
| v3.2 (Q2 2026) | Foundations + demo hardening | Nothing new for ZT. Document intent; draft whitepaper skeleton. |
| v3.3 (Q3 2026) | **Fleet mesh + vendor mTLS** | WireGuard + Headscale integration; vendor mTLS via Nginx; Terraform vars; admin UI mesh tab; customer-facing whitepaper GA |
| v3.4 (Q4 2026) | **Workload identity + SIEM** | SPIFFE / SPIRE for inter-service mTLS; SIEM forwarder with CEF/LEEF/STIX; threat intelligence feed integration |
| v4 (Q1 2027) | Multi-tenant ZT + federated identity | Cross-tenant policy composition; federated identity across Parent-Org portfolios |

---

## Risks

**Operational**

- WireGuard uses UDP by default; some corporate firewalls block arbitrary UDP. Mitigation: TCP relay (DERP-equivalent) ships in v3.3 default config.
- Overlay networks add debugging complexity. Mitigation: admin UI mesh tab surfaces peer connectivity; Headscale logs integrated into Grafana.
- Kernel WireGuard on Linux is fast; userspace on Windows is slower. InsideLLM VMs run Linux → kernel path → non-issue.

**Licensing / dependency**

- Tailscale is commercial — not the selected default — but Headscale is independent OSS (GPL-3). No recurring vendor dependency for core mesh functionality.
- If Headscale project stalls, Netbird is a drop-in-equivalent alternative.

**Positioning / marketing**

- Risk of overclaiming: "InsideLLM is a Zero Trust platform because we use WireGuard." Wrong. Correct framing: "InsideLLM is NIST SP 800-207 aligned; WireGuard closes the multi-site transport gap." Marketing language in the v3.3 whitepaper must be reviewed carefully.
- Competitor Tailscale positions as "Zero Trust networking" — customers may conflate. Counter in sales: "Tailscale is excellent; they do the network layer. InsideLLM adds the policy, audit, and governance layers on top of the same WireGuard foundation."

**Compliance**

- The whitepaper makes specific alignment claims against NIST SP 800-207. Every claim must be verifiable against the running system (same principle as Compliance-Map.html). Independent review of the whitepaper before publication.
- CISA Zero Trust Maturity Model self-assessment is a public self-rating; overstating maturity damages credibility.

**Technical debt**

- v3.4 SPIFFE work is a meaningful lift — order-of-magnitude larger than v3.3 WireGuard. Plan honestly; don't commit if Q4 is already loaded.

---

## Open questions — decide before v3.3 kickoff

1. **Self-hosted Headscale or optional Tailscale SaaS?** Default ship self-hosted Headscale; allow customer choice to use Tailscale if they prefer. Decision: DEFAULT self-hosted. Confirm.
2. **Certificate issuance for vendor mTLS — Smallstep step-ca or self-signed?** Recommendation: step-ca embedded in Governance Hub for turnkey. Confirm.
3. **Whitepaper distribution — public or NDA-gated?** Public increases reach; NDA-gated allows more detail on specific implementations. Recommendation: public whitepaper at v3.3 GA; NDA-gated "implementation appendix" with step-by-step deployment guide for Enterprise customers.
4. **Tailscale Inc. partnership?** They have an enterprise program. Low-priority but a partnership could produce a co-branded ZT asset. Evaluate post-v3.3.
5. **CISA Zero Trust Maturity Model v2 — align to v1 or v2?** v2 is the current reference (released 2023). Recommendation: align to v2; note v1 compatibility for federal customers still reporting against it.

---

## What this document is not

Not a commitment. Not a product announcement. An engineering design scope
that feeds into v3.3 planning. The scope will tighten as demo outcomes
(2026-05-12) inform priority shifts and customer feedback shapes which
gaps matter most to real buyers.

*Last updated 2026-04-22*
