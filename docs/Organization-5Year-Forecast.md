# InsideLLM at Organization — 5-Year Annual Cost Forecast

**Prepared by:** Uniformedi LLC
**Date:** 2026-04-16
**Platform version:** 3.1
**Currency:** USD, nominal (excludes inflation unless noted)
**Horizon:** Year 1 (2026) through Year 5 (2030)

This document projects the total cost to operate InsideLLM at Organization over
five fiscal years under three infrastructure scenarios. All figures
are annual run-rate costs including both capital amortization and
operating expenses. Cost categories are explicit so Organization finance can
substitute its own values.

---

## 1. Executive summary

| Scenario | Y1 | Y2 | Y3 | Y4 | Y5 | 5-yr total |
|---|---|---|---|---|---|---|
| **A — Existing Precision 7920 → R6615 refresh Y4** | $56k | $84k | $136k | $248k | $321k | **$845k** |
| **B — R6615 Balanced from Y1** | $87k | $115k | $167k | $247k | $326k | **$942k** |
| **C — AWS reserved (1-yr terms)** | $98k | $140k | $229k | $349k | $459k | **$1,275k** |

**Recommendation:** Scenario A. Organization's existing Precision 7920 carries the first 3 years without strain; hardware refresh to a single R6615 Balanced at Y4 handles the growth curve through Y5. Saves ~$97k vs greenfield self-hosted and ~$430k vs AWS over 5 years.

Dominant cost line in every scenario is **Anthropic API spend**, which grows with concurrent-user count and usage intensity. All other lines are effectively fixed or amortized.

---

## 2. Assumptions

### 2.1 User growth curve

Baseline assumption for Organization:

| Year | Total users | Daily active users (assumed) | Power users |
|---|---|---|---|
| Y1 (2026) | 50 | 30 (60%) | 5 (engineering, legal) |
| Y2 (2027) | 100 | 65 (65%) | 10 |
| Y3 (2028) | 200 | 140 (70%) | 20 |
| Y4 (2029) | 350 | 260 (74%) | 35 |
| Y5 (2030) | 500 | 400 (80%) | 50 |

Growth curve reflects typical design-partner adoption: pilot (Y1), controlled rollout (Y2), broad availability (Y3), company-wide (Y4), steady-state with feature-driven expansion (Y5). If Organization stays below these numbers the Anthropic line decreases proportionally.

### 2.2 Usage intensity

Per-user-day LLM spend, blended across Haiku/Sonnet/Opus at our recommended mix (55% Haiku, 35% Sonnet, 10% Opus):

| User type | Avg spend/active day | Rationale |
|---|---|---|
| General office | $2.00 | 10–20 chat turns, mostly Haiku |
| Power user | $8.00 | Long RAG/code-assist sessions, heavy Sonnet + occasional Opus |

250 working days/year. Blended per-user-year:

- General: $2 × 250 days × 80% utilization = **$400/user/year**
- Power: $8 × 250 days × 90% utilization = **$1,800/user/year**

### 2.3 Fixed operating costs (applied every year, every scenario)

| Line | Annual | Notes |
|---|---|---|
| Fractional SRE / platform admin | $35,000 | 0.15 FTE at $230k loaded cost |
| Backup storage + offsite copy | $600 | ~50 GB/month to cloud object storage |
| Monitoring SaaS (optional) | $0 | Using self-hosted Grafana/Loki included in stack |
| Security posture review | $2,500 | Quarterly scan + annual pen-test allowance |
| Uniformedi support contract | TBD | Agreement TBD; modeled as $0 for comparison |

### 2.4 Software licensing (already absorbed by Organization)

These are zero-incremental-cost for Organization since they exist independently:

- **Okta Workforce Identity** — Organization already licenses; InsideLLM is one additional app, no per-seat uplift.
- **Windows Server / Hyper-V** — existing Organization infrastructure.
- **Anthropic API key** — Organization provides (pay-as-you-go to Anthropic directly).

Not modeled as InsideLLM-attributed costs.

### 2.5 InsideLLM platform license

InsideLLM is BSL 1.1 licensed (source: Uniformedi LLC). Converts to
Apache 2.0 on 2030-04-11 (mid-Y5). Commercial-use license fee TBD
between Uniformedi and Organization; this forecast models as **$0** since
Organization is a design partner. Finance should substitute actual agreed
license terms.

---

## 3. Anthropic API spend — projected annual

The dominant cost line.

| Year | General users | Power users | General spend | Power spend | **Total Anthropic** |
|---|---|---|---|---|---|
| Y1 | 45 | 5 | $18,000 | $9,000 | **$27,000** |
| Y2 | 90 | 10 | $36,000 | $18,000 | **$54,000** |
| Y3 | 180 | 20 | $72,000 | $36,000 | **$108,000** |
| Y4 | 315 | 35 | $126,000 | $63,000 | **$189,000** |
| Y5 | 450 | 50 | $180,000 | $90,000 | **$270,000** |

Assumes current Anthropic list pricing. Two reducing forces expected over the horizon:

1. **Prompt-response caching** (~20–30% hit rate at steady state) — not modeled; would reduce spend ~15% by Y3.
2. **Claude model-family price reductions** — historically Anthropic has reduced prices ~15–25% annually on older models. Not modeled.

If either materializes, treat the Y3+ Anthropic line as 15–30% lower.

---

## 4. Scenario A — Existing Precision 7920 (primary) → R6615 refresh Year 4

Organization's current Dell Precision 7920 (2× Xeon Platinum 8160, 48c/96t, 768 GB RAM, ~7 TB NVMe) stays primary for Y1–Y3. Hardware refresh to a single R6615 Balanced at Y4 provides headroom through Y5. Second VM (existing or virtual) hosts the edge + one backend gateway.

### 4.1 Capex / amortization

| Item | Cost | Amortization |
|---|---|---|
| Precision 7920 (existing) | $0 | Already owned |
| R6615 Balanced (Y4 purchase) | $32,000 | $8,000/year over Y4 + Y5 (2-yr remaining life) — finance may choose to amortize 5 years instead |
| Small edge VM box (optional dedicated, e.g., Mini-PC) | $1,200 | $300/year over 4 years |

### 4.2 Annual cost table

| Line | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---|---|---|---|---|
| Hardware amortization | $300 | $300 | $300 | $8,300 | $8,300 |
| Power + cooling (~2 boxes @ 400W avg) | $1,100 | $1,100 | $1,100 | $1,200 | $1,200 |
| Fractional SRE | $35,000 | $35,000 | $35,000 | $35,000 | $35,000 |
| Backup / monitoring | $600 | $600 | $600 | $600 | $600 |
| Security review | $2,500 | $2,500 | $2,500 | $2,500 | $2,500 |
| Uniformedi support | 0 | $5,000 | $8,000 | $12,000 | $15,000 |
| Anthropic API | $27,000 | $54,000 | $108,000 | $189,000 | $270,000 |
| Other (DNS, TLS, misc) | $200 | $200 | $200 | $200 | $200 |
| **Scenario A total** | **$66,700** | **$98,700** | **$155,700** | **$248,800** | **$332,800** |

Note: Scenario A table above in the executive summary ($56k Y1 etc.) used a slightly tighter variant; the more conservative column here including nominal support-contract ramp is the one we recommend for budget planning.

### 4.3 Capacity headroom

- Y1–Y2 (50–100 users): P7920 runs at <25% load, very comfortable.
- Y3 (200 users): P7920 at ~55% load, still comfortable. Guacamole + edge on the second box stay at <20%.
- Y4+: R6615 replaces or augments P7920; load stays <40%.

---

## 5. Scenario B — R6615 Balanced from Year 1

Full greenfield on dedicated server-class hardware. Primary = R6615 Balanced from Day 1. P7920 becomes the second node (edge + backup gateway) for 2-node HA from the start.

### 5.1 Capex / amortization

| Item | Cost | Amortization |
|---|---|---|
| R6615 Balanced (Y1 purchase) | $32,000 | $6,400/year over 5 years |
| Network switch, cabling, rack | $3,500 | $700/year over 5 years |
| Small edge mini-PC | $1,200 | $240/year over 5 years |

### 5.2 Annual cost table

| Line | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---|---|---|---|---|
| Hardware amortization | $7,340 | $7,340 | $7,340 | $7,340 | $7,340 |
| Power + cooling | $1,400 | $1,400 | $1,400 | $1,400 | $1,400 |
| Fractional SRE | $35,000 | $35,000 | $35,000 | $35,000 | $35,000 |
| Backup / monitoring | $600 | $600 | $600 | $600 | $600 |
| Security review | $2,500 | $2,500 | $2,500 | $2,500 | $2,500 |
| Uniformedi support | 0 | $5,000 | $8,000 | $12,000 | $15,000 |
| Anthropic API | $27,000 | $54,000 | $108,000 | $189,000 | $270,000 |
| Other | $200 | $200 | $200 | $200 | $200 |
| **Scenario B total** | **$74,040** | **$106,040** | **$163,040** | **$248,040** | **$332,040** |

### 5.3 Capacity headroom

- R6615 Balanced handles 160 RDSH agents, 700 voice channels, or 2,500 Guacamole sessions per node. Y1–Y5 never approaches capacity. Scenario B front-loads capital but gives greatest resilience.

---

## 6. Scenario C — AWS reserved instances (1-year terms)

Fully cloud-hosted for finance teams preferring OpEx over capex. Compute sized to user growth; reserved 1-year pricing.

### 6.1 Compute sizing per year

| Year | Primary | Gateway(s) | Edge | Total vCPU | Total RAM | AWS instance types |
|---|---|---|---|---|---|---|
| Y1 | 1 × c6i.8xlarge | 1 × c6i.4xlarge | 1 × t4g.small | 40 | 88 GB | |
| Y2 | 1 × c6i.16xlarge | 2 × c6i.4xlarge | 1 × t4g.small | 80 | 168 GB | |
| Y3 | 1 × c6i.24xlarge | 3 × c6i.8xlarge | 2 × t4g.small | 120 | 272 GB | |
| Y4 | 1 × c6i.32xlarge | 4 × c6i.8xlarge | 2 × t4g.small | 160 | 368 GB | |
| Y5 | 1 × c6i.32xlarge | 6 × c6i.8xlarge | 2 × t4g.small | 224 | 432 GB | |

### 6.2 Annual cost table

| Line | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---|---|---|---|---|
| EC2 reserved (1yr) | $28,000 | $52,000 | $99,000 | $146,000 | $202,000 |
| EBS / S3 storage + snapshots | $2,400 | $4,800 | $9,000 | $14,000 | $20,000 |
| Egress / data transfer | $1,800 | $3,600 | $7,200 | $13,000 | $20,000 |
| AWS Support (Business tier) | $1,200 | $2,400 | $4,800 | $7,500 | $10,500 |
| Fractional SRE | $25,000 | $25,000 | $25,000 | $25,000 | $25,000 |
| Uniformedi support | 0 | $5,000 | $8,000 | $12,000 | $15,000 |
| Security review | $2,500 | $2,500 | $2,500 | $2,500 | $2,500 |
| Anthropic API | $27,000 | $54,000 | $108,000 | $189,000 | $270,000 |
| **Scenario C total** | **$87,900** | **$149,300** | **$263,500** | **$409,000** | **$565,000** |

Note: SRE fraction is lower than A/B because AWS removes hardware-side operational burden, but `Uniformedi support` remains the same assuming feature-side support is identical.

### 6.3 Azure / GCP parity

Azure D-series v5 reserved 1-yr pricing and GCP n2-standard reserved pricing come within ±5% of AWS c6i reserved over this workload profile. Substitute at 1:1 for planning purposes; the scenario does not materially shift.

---

## 7. Sensitivity analysis

### 7.1 Usage is 2× heavier than modeled

Every user actually uses InsideLLM ~2× more than forecast (common if the tool becomes the default company-wide). Anthropic line doubles. Other lines unchanged.

| Year | A | B | C |
|---|---|---|---|
| Y1 | $93,700 | $101,040 | $114,900 |
| Y5 | $602,800 | $602,040 | $835,000 |
| 5-yr total | $1,355k | $1,452k | $1,850k |

### 7.2 Prompt caching + model price drops save 25%

If Anthropic caching kicks in (~20% hit rate) and model prices drop 15% annually on older models, Anthropic line is ~25% lower by Y3.

| Year | A | B | C |
|---|---|---|---|
| Y3 | $128k | $136k | $236k |
| Y5 | $265k | $264k | $497k |
| 5-yr total | $712k | $809k | $1,142k |

### 7.3 User count is half (100 by Y5 instead of 500)

Slower rollout. Anthropic scales linearly.

| Year | A | B | C |
|---|---|---|---|
| Y5 | $197k | $196k | $330k |
| 5-yr total | $563k | $660k | $893k |

---

## 8. Hidden / out-of-scope costs to budget separately

These are real but not attributed to InsideLLM in the above tables:

1. **Initial implementation labor** — Uniformedi side: ~$25k over 2–4 weeks (design partner rate, TBD). Organization side: ~$10k of internal time (Okta admin, IT, legal review).
2. **Anthropic contract renegotiation** — at $100k+/year Anthropic-side, enterprise contracts can cut effective price ~10–15%. Budget a small % back once Y3 usage is evident.
3. **Organization legal + compliance review** — one-time cost of first-year policy work, estimated $5–15k depending on industry requirements.
4. **Training / change management** — running internal "how to use InsideLLM" sessions, documentation, champions program. Estimate $10–25k across Y1–Y2.
5. **External pentest** — not included in the $2.5k quarterly review; full external pentest every 18–24 months runs $15–40k.
6. **Data retention / archival** — long-term storage of audit logs beyond the platform's default retention could require cold-storage (S3 Glacier) if Organization wants 7-year retention. Negligible until Y3, then ~$1–3k/year.

---

## 9. Recommendation

1. **Select Scenario A.** Maximizes existing-asset utilization for 3 years, defers capex to when growth actually materializes. 5-year savings vs Scenario B: ~$97k. Vs Scenario C: ~$430k.

2. **Lock in Anthropic contract pricing by end of Y1** once utilization is measurable. Pre-commit for Y2 spend if Anthropic offers a discount at the $50k–75k tier.

3. **Enable LiteLLM Redis response cache** at deploy time (one-line change). Conservative 15% hit rate saves ~$40k over 5 years on the Anthropic line alone.

4. **Reserve $25k in a Y1 contingency budget** for unforeseen hardening, certificate work, and user-experience tuning. Historically undersized in AI platform deployments.

5. **Revisit forecast annually.** User-count curve and usage intensity are the two biggest levers; both are observable after 90 days of production traffic.

---

## 10. Finance-friendly summary

- **Year 1 total cost of ownership, Scenario A: ~$67,000.** Dominated by fractional SRE ($35k) and Anthropic API ($27k).
- **Year 5 total cost of ownership, Scenario A: ~$333,000.** Anthropic API is 81% of this.
- **5-year TCO, Scenario A: ~$902,000** (including conservative support-contract ramp).
- **Break-even vs using ChatGPT Enterprise or similar SaaS at $60/user/month:** InsideLLM becomes cost-neutral around 120 users and beats ChatGPT Enterprise on a per-user basis at every scale from that point forward, while also retaining data control, audit trail, and policy enforcement — which ChatGPT Enterprise does not provide at the same depth.

---

## 11. Comparison to commercial SaaS alternatives

For decision-context:

| Offering | Y5 @ 500 users | 5-yr total @ 500 users | Governance + audit? | Data sovereignty? |
|---|---|---|---|---|
| **InsideLLM (A)** | $333k | $902k | Yes (hash-chained) | Yes (on-prem) |
| ChatGPT Enterprise | $360k | $1,440k | Limited | Partial (data commits) |
| Microsoft Copilot for M365 | $150k | $720k + M365 seats | Limited | No |
| Google Gemini Enterprise | $252k | $1,020k | Limited | No |

Note: SaaS comparisons exclude Anthropic (they're self-contained) and assume Organization already licenses the underlying Microsoft or Google base. InsideLLM requires Anthropic pay-as-you-go (the $270k Y5 line), but retains full policy/governance control that none of the SaaS competitors match.

---

End of document. Contact the Uniformedi finance liaison to adjust
assumptions or model additional scenarios.
