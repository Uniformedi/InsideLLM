# InsideLLM Risk Register

**Classification:** Internal / Uniformedi LLC
**Drafted:** 2026-04-22
**Review cadence:** Monthly (next review 2026-05-22)
**Owner:** Dan Medina

This is the operational risk ledger that pairs with the strategic view in
`html/SWOTanalysis.html`. Each risk carries a severity × likelihood score,
a mitigation plan, an owner, and a status. The goal is not to eliminate risk
— it is to know which risks are load-bearing and which are being actively
managed.

---

## Scoring

- **Severity:** 1 (cosmetic) → 5 (existential to the business or platform)
- **Likelihood:** 1 (vanishingly rare) → 5 (occurring regularly)
- **Score:** Severity × Likelihood (max 25)
- **Tier:** CRITICAL (≥16), HIGH (9–15), MEDIUM (4–8), LOW (≤3)

---

## R-001 · Demo-day failure — 2026-05-12

- **Tier:** CRITICAL (4 × 4 = 16)
- **Severity:** Lost reference customer + lost year of pipeline momentum
- **Likelihood:** Non-trivial; P1.2 is incomplete, live VMs include a hot-patched image
- **Mitigation:**
  1. `Demo-Prep-Checklist.html` completed in full before demo day
  2. Fresh redeploy of `10.0.0.9` Thursday 2026-05-11 (non-negotiable)
  3. Backup screen recording + phone screenshots + paper runbook
  4. Executive Summary printouts as fallback narrative
- **Status:** Actively managed; demo-prep artifacts shipped 2026-04-22

## R-002 · Bus factor of 1

- **Tier:** HIGH (5 × 3 = 15)
- **Severity:** Platform cannot be maintained or sold without Dan Medina
- **Likelihood:** Unchanged until second engineer hired
- **Mitigation:**
  1. Aggressive documentation: README, CLAUDE.md, CODEMAP-equivalent per subtree, demo runbook, architecture walkthrough all in place
  2. Source code is open; FOSS components are well-maintained by external teams
  3. Enterprise contracts to include source-code escrow option
  4. Hiring plan: senior engineer Q3 2026 (compliance/security background preferred)
- **Status:** Partially mitigated via documentation; unmitigated on personnel until Q3 2026 hire

## R-003 · BSL 1.1 procurement friction

- **Tier:** HIGH (3 × 4 = 12)
- **Severity:** Lose 20-40% of enterprise deals where procurement policy forbids source-available
- **Likelihood:** Observed in real prospect conversations
- **Mitigation:**
  1. Licensing addendum included in Professional + Enterprise tiers giving OSI-equivalent terms
  2. Published FAQ clarifying BSL 1.1 restrictions (`Pricing.html`)
  3. Automatic conversion to Apache 2.0 on 2030-04-11 documented
- **Status:** Addendum drafted; test in first procurement cycle post-demo

## R-004 · SOC 2 absence blocks enterprise deals

- **Tier:** HIGH (4 × 3 = 12)
- **Severity:** Many enterprise buyers (especially financial + healthcare) will not proceed without SOC 2
- **Likelihood:** Observed in every enterprise sales conversation to date
- **Mitigation:**
  1. SOC 2 Type I engagement begins Q2 2026; completion Q3 2026
  2. SOC 2 Type II observation window starts Q4 2026; completion Q1 2027
  3. Interim: design-partner pricing + control-mapping memos to buyers
- **Status:** Engagement not yet kicked off; critical-path item for Q2

## R-005 · Stale image in production (10.0.0.9 hot-patch)

- **Tier:** HIGH (4 × 3 = 12)
- **Severity:** Demo-day failure or inconsistent behavior; known deviation from source
- **Likelihood:** High unless redeployed
- **Mitigation:**
  1. Fresh redeploy from synced `c:/insidellm/` source before 2026-05-11
  2. Post-demo: automate deploy-state verification so this never recurs
- **Status:** Redeploy scheduled; automation roadmapped for v3.2

## R-006 · Upstream license shift (Open WebUI / LiteLLM / etc.)

- **Tier:** HIGH (4 × 3 = 12)
- **Severity:** Could force costly rework if a core component relicenses to AGPL or commercial
- **Likelihood:** Historical precedent (Redis, HashiCorp, Elastic, MongoDB) shows this happens to mature OSS
- **Mitigation:**
  1. Multiple components already alternatives-ready: OPA has no close substitute but is Apache 2.0 CNCF-graduated (unlikely to flip)
  2. LiteLLM: alternative gateways exist (Vercel AI SDK, Helicone, custom)
  3. Open WebUI: alternatives exist (Chatbot UI, Librechat, custom)
  4. Monitor license change announcements quarterly
- **Status:** Monitoring; no action required

## R-007 · Regulatory interpretation drift

- **Tier:** HIGH (3 × 4 = 12)
- **Severity:** Compliance claims become stale; customer audits flag gaps
- **Likelihood:** CFPB, HHS OCR, state AGs issuing new AI guidance regularly
- **Mitigation:**
  1. Quarterly compliance-mapping review in `Compliance-Map.html`
  2. Industry policy bundles updated as regulations change
  3. Customer-facing compliance advisory notes shipped with each v3.x release
- **Status:** Process in place; next review 2026-07-22

## R-008 · Microsoft Copilot bundling squeeze

- **Tier:** MEDIUM (4 × 2 = 8)
- **Severity:** Microsoft-shop enterprises default to Copilot included in E5
- **Likelihood:** Observed in competitive conversations; limited to Microsoft-first buyers
- **Mitigation:**
  1. Position as governance layer alongside Copilot, not competitor
  2. Emphasize IDE-vs-whole-stack scope distinction
  3. Target non-Microsoft-first buyers for direct competition
- **Status:** Positioning documented in `Competitors.html`

## R-009 · LiteLLM pivots to enterprise SaaS

- **Tier:** MEDIUM (4 × 2 = 8)
- **Severity:** BerriAI could compete directly on gateway layer
- **Likelihood:** BerriAI has funded product team; commercial SaaS is a natural move
- **Mitigation:**
  1. InsideLLM's value is the full stack + OPA + audit + SAIVAS, not the gateway
  2. BSL license + on-prem differentiator independent of LiteLLM
  3. Evaluate alternative gateways if BerriAI competes aggressively
- **Status:** Monitoring

## R-010 · Anthropic / OpenAI ship on-prem enterprise

- **Tier:** MEDIUM (5 × 2 = 10)
- **Severity:** Direct model-vendor on-prem offering would cannibalize core InsideLLM use case
- **Likelihood:** Neither has announced; both hesitant due to model-weight protection
- **Mitigation:**
  1. Governance layer is defensible regardless of where inference runs — policies, audit, SAIVAS all remain valuable
  2. Multi-model story (Anthropic + OpenAI + Ollama) insulates from any single vendor's strategy
  3. Monitor for announcements quarterly
- **Status:** Monitoring

## R-011 · Secret leakage in LLM-generated summaries (Secular integration)

- **Tier:** MEDIUM (4 × 2 = 8)
- **Severity:** Regulated customer surfaces PHI / PII in AGENTS.md files generated by Secular
- **Likelihood:** Latent; depends on Secular annotate being used against sensitive repos
- **Mitigation:**
  1. Secular integration routes annotate through InsideLLM DLP gateway — PHI / PII blocked before write
  2. Default-gitignore pattern for Secular-generated files
  3. Drift-detection flags prevent long-running stale context from being trusted
- **Status:** Design-level mitigation in `docs/integrations/insidellm.md`; implementation post-2026-05-12

## R-012 · Economic downturn pauses AI budgets

- **Tier:** MEDIUM (3 × 3 = 9)
- **Severity:** Enterprise AI spend is discretionary; recession could halt adoption
- **Likelihood:** Macro condition outside Uniformedi's control
- **Mitigation:**
  1. Community tier is free — captures interest even during budget freezes
  2. Regulatory compliance value-prop is non-discretionary (compliance spend remains in downturns)
  3. Professional services revenue smooths license-revenue variance
- **Status:** Monitoring

## R-013 · Enterprise sales cycle length

- **Tier:** MEDIUM (3 × 3 = 9)
- **Severity:** 6-18 month cycles delay cash conversion; founder-funded runway matters
- **Likelihood:** Normal for B2B enterprise
- **Mitigation:**
  1. Design-partner pricing shortens first-contract cycle
  2. Professional tier pricing reduces sales complexity vs. Enterprise
  3. Community tier drives inbound leads vs. pure outbound
- **Status:** Managed via tier design

## R-014 · Agent manifest schema drift from upstream patterns

- **Tier:** MEDIUM (2 × 3 = 6)
- **Severity:** InsideLLM's agent manifests diverge from emerging ecosystem patterns (MCP, AGENTS.md, OpenAI function calling)
- **Likelihood:** Ecosystem is actively evolving
- **Mitigation:**
  1. Monitor AAIF standards quarterly
  2. Schema version in manifest frontmatter allows forward migration
  3. Secular sibling project keeps us informed about AGENTS.md direction
- **Status:** Monitoring

## R-015 · OPA single point of failure

- **Tier:** MEDIUM (3 × 2 = 6)
- **Severity:** OPA outage halts request flow (fail-closed)
- **Likelihood:** OPA is mature + battle-tested; outage rare
- **Mitigation:**
  1. Humility guardrail callback evaluates core rules locally in Python if OPA unavailable
  2. Health-check monitor; auto-restart via Docker Compose
  3. Defense in depth: prompt layer + guardrail layer fire regardless of OPA
- **Status:** Mitigated

## R-016 · Customer deploys competing internal fork

- **Tier:** LOW (2 × 2 = 4)
- **Severity:** BSL permits internal fork; customer could maintain independently
- **Likelihood:** Low — customers prefer vendor-maintained code
- **Mitigation:**
  1. Platform complexity favors vendor-maintained path
  2. Support + updates are real value
  3. BSL Apache-conversion in 2030 eventually permits forking anyway
- **Status:** Accepted

## R-017 · Humility / SAIVAS IP challenge

- **Tier:** LOW (3 × 1 = 3)
- **Severity:** Legal challenge to SAIVAS attribution in *Uniform Gnosis, Vol. I*
- **Likelihood:** Unlikely — published IP with clear authorship
- **Mitigation:**
  1. NOTICE file documents attribution
  2. humility-guardrail package published openly
  3. Implementation is original work under MIT
- **Status:** Accepted

## R-018 · Fleet cross-tenant data leak

- **Tier:** LOW (5 × 1 = 5)
- **Severity:** One tenant's data surfacing in another tenant's view would be catastrophic
- **Likelihood:** Very low — each VM has its own DB; aggregation is read-only and explicit
- **Mitigation:**
  1. Per-tenant PostgreSQL isolation on current architecture
  2. Cross-tenant aggregation is deferred (documented in SESSION-RESUME)
  3. Multi-tenant work for v4 will include explicit tenant-isolation design review
- **Status:** Mitigated by architecture

## R-019 · Certifications outpaced by competitors

- **Tier:** LOW (3 × 2 = 6)
- **Severity:** Larger vendors ship certifications faster
- **Likelihood:** Structural — they have more resources
- **Mitigation:**
  1. Target specific regulated-industry certifications (HITRUST for healthcare) vs. racing on general ones
  2. Open-source components inherit upstream certifications (Docker, PostgreSQL, Nginx)
- **Status:** Managed

## R-020 · Founder burnout

- **Tier:** MEDIUM (5 × 2 = 10)
- **Severity:** Catastrophic to project continuity
- **Likelihood:** Solo founder on aggressive schedule
- **Mitigation:**
  1. Q3 2026 hiring commitment reduces load
  2. Post-demo: deliberate 1-week decompression period
  3. Project documentation depth enables time-off without platform degradation
- **Status:** Active self-management

---

## Top 5 risks — eyes-on

1. **R-001 Demo failure** — until 2026-05-13, this is the only risk that matters
2. **R-002 Bus factor** — hiring by end of Q3 2026 is load-bearing
3. **R-003 BSL procurement friction** — addendum must land in first three post-demo deals
4. **R-004 SOC 2 absence** — engagement must kick off Q2 or Q3 2026 deals will stall
5. **R-005 Stale image** — fresh redeploy Thursday is non-negotiable

---

## Risks newly added since last review

This is a first draft. No additions yet. Format for future reviews:

```
## R-0XX · <short name> (added YYYY-MM-DD)
[standard fields]
```

## Risks retired since last review

(none yet)

---

*Next review: 2026-05-22 · Update scoring after demo outcome is known*
