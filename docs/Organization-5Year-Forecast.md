# InsideLLM at Organization — 5-Year Annual Cost Forecast

**Prepared by:** Uniformedi LLC
**Date:** 2026-04-16 (rev. 2026-04-19: RHEL 9 guest OS, labor breakout)
**Platform version:** 3.1
**Guest OS:** Red Hat Enterprise Linux 9 (this revision; supersedes Ubuntu 24.04 baseline)
**Currency:** USD, nominal (excludes inflation unless noted)
**Horizon:** Year 1 (2026) through Year 5 (2030)

This document projects the total cost to operate InsideLLM at Organization over
five fiscal years under three infrastructure scenarios. All figures
are annual run-rate costs including both capital amortization and
operating expenses. Cost categories are explicit so Organization finance can
substitute its own values.

---

## 1. Executive summary

Figures below include **RHEL 9 subscriptions** on the VM guests (see Section 2.6). Detail-table totals (Sections 4.2, 5.2, 6.2) are authoritative; the rounded values here are for at-a-glance planning.

| Scenario | Y1 | Y2 | Y3 | Y4 | Y5 | 5-yr total |
|---|---|---|---|---|---|---|
| **A — Existing Equipment** (Precision 7920 → R6615 refresh Y4) | $68k | $100k | $158k | $251k | $335k | **$914k** |
| **B — New Latest Equipment** (R6615 Balanced from Y1) | $76k | $108k | $166k | $251k | $335k | **$934k** |
| **C — Virtualized** (AWS reserved, 1-yr terms) | $90k | $152k | $267k | $413k | $571k | **$1,492k** |

**Recommendation:** Scenario A — Existing Equipment. Organization's existing Precision 7920 carries the first 3 years without strain; hardware refresh to a single R6615 Balanced at Y4 handles the growth curve through Y5. Saves ~$20k vs new-equipment greenfield and ~$578k vs the virtualized path over 5 years (RHEL-inclusive).

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

| Line | Annual | Labor? | Notes |
|---|---|---|---|
| Fractional SRE / platform admin | $35,000 | **Labor** | 0.15 FTE at $230k loaded cost (~$110/hr, ~312 hrs/yr) |
| Backup storage + offsite copy | $600 | Non-labor | ~50 GB/month to cloud object storage |
| Monitoring SaaS (optional) | $0 | — | Using self-hosted Grafana/Loki included in stack |
| Security posture review | $2,500 | **Labor** | Quarterly scan + annual pen-test allowance (~10–12 hrs senior security rate) |
| Uniformedi support contract | TBD | **Labor** | Agreement TBD; modeled on a ramp below. Blended engineering rate ~$200–250/hr |

**Labor rate derivation (for breakout purposes):**

- **Fractional SRE** — $230,000/year fully loaded (salary + benefits + overhead + tools) × 0.15 FTE = $34,500 ≈ $35,000. Equivalent hourly: ~$110/hr loaded × ~312 hours/year. Scenario C uses 0.11 FTE ($25k) because cloud hosting removes hardware-side operations burden (no BIOS, firmware, disk replacement, power/cooling oversight).
- **Uniformedi support ramp** — $0/$5k/$8k/$12k/$15k across Y1–Y5 reflects ~0/25/40/60/75 hours/year at a blended $200/hr engineering rate. Ramp is tied to user-count growth, not platform complexity.
- **Security posture review** — $2,500/year reflects quarterly automated scans (~4 × $250 = $1,000) plus a ~6 hour annual internal review at ~$250/hr (= $1,500). External pentest is separate (see Section 8).

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

### 2.6 Operating system choice: RHEL 9 (this revision)

This revision of the forecast models **Red Hat Enterprise Linux 9** as the guest OS for the InsideLLM VMs, replacing the prior Ubuntu 24.04 baseline. The change applies to all three infrastructure scenarios.

**Why RHEL:**

- **Compliance posture** — FIPS 140-3 validated cryptographic modules, DISA STIG, CIS Benchmark, and formal Common Criteria certification. Material for regulated industries (healthcare, finance, government). Ubuntu Pro offers comparable FIPS but is a separately-priced subscription.
- **Support lifecycle** — RHEL 9 maintenance support through May 2032, extended life-cycle support through 2035. Removes Y1–Y5 upgrade forcing function.
- **Vendor-backed support** — included with subscription. Reduces pressure on the fractional SRE line for OS-layer issues (kernel panics, package conflicts, security patches). Not modeled as a labor reduction in this forecast (conservative assumption).
- **SELinux enforcing by default** — hardens container escape boundaries; already part of STIG posture.

**Subscription pricing assumptions (RHEL 9 Server):**

| SKU | Annual per instance | When used |
|---|---|---|
| RHEL Server, Standard (8×5 support) | ~$799 | Y1–Y2 (pilot + controlled rollout) |
| RHEL Server, Premium (24×7 support) | ~$1,299 | Y3+ (broad availability, production-critical) |
| RHEL via Red Hat Cloud Access (BYOS) | same per-instance, portable | Scenario C (AWS) |

On-prem scenarios run 2 instances (primary + edge). AWS scenario scales with EC2 instance count. Red Hat Virtual Datacenters ($2,499/yr per 2-socket host, unlimited VMs) is a viable alternative if Organization runs >3 VMs on the Precision 7920 — not used here to keep the cost conservative.

**One-time implementation delta vs Ubuntu baseline:**

- Port cloud-init / Terraform templates from `apt` → `dnf`, Ubuntu package names → RHEL AppStream equivalents: **~$5,000** Uniformedi-side engineering.
- Author SELinux policy module for Docker/Podman containers (Governance Hub, DocForge, LiteLLM): **~$3,000**.
- Total one-time RHEL port: **~$8,000** added to Y1 implementation labor (Section 8.1).

**Operational considerations (qualitative, not re-priced):**

- Docker runs on RHEL but Red Hat's supported container runtime is **Podman**. For subscription-compliance and support purposes, Organization may want to migrate to Podman over time. Docker Compose works via `podman-compose`. Modeled cost impact: zero; operational risk: low.
- `firewalld` replaces `ufw`; rule set is equivalent.
- Kernel is 5.14-based (RHEL 9.4) vs 6.8 (Ubuntu 24.04). No functional impact on the InsideLLM stack.

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

## 4. Scenario A — Existing Equipment (Precision 7920 primary → R6615 refresh Year 4)

Organization's current Dell Precision 7920 (2× Xeon Platinum 8160, 48c/96t, 768 GB RAM, ~7 TB NVMe) stays primary for Y1–Y3. Hardware refresh to a single R6615 Balanced at Y4 provides headroom through Y5. Second VM (existing or virtual) hosts the edge + one backend gateway.

### 4.1 Capex / amortization

| Item | Cost | Amortization |
|---|---|---|
| Precision 7920 (existing) | $0 | Already owned |
| R6615 Balanced (Y4 purchase) | $32,000 | $8,000/year over Y4 + Y5 (2-yr remaining life) — finance may choose to amortize 5 years instead |
| Small edge VM box (optional dedicated, e.g., Mini-PC) | $1,200 | $300/year over 4 years |

### 4.2 Annual cost table

| Line | Category | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---|---|---|---|---|---|
| Hardware amortization | Non-labor | $300 | $300 | $300 | $8,300 | $8,300 |
| Power + cooling (~2 boxes @ 400W avg) | Non-labor | $1,100 | $1,100 | $1,100 | $1,200 | $1,200 |
| Backup / monitoring | Non-labor | $600 | $600 | $600 | $600 | $600 |
| **RHEL 9 subscriptions (2 instances)** | Non-labor | $1,600 | $1,600 | $2,600 | $2,600 | $2,600 |
| Anthropic API | Non-labor | $27,000 | $54,000 | $108,000 | $189,000 | $270,000 |
| Other (DNS, TLS, misc) | Non-labor | $200 | $200 | $200 | $200 | $200 |
| **Non-labor subtotal** | | **$30,800** | **$57,800** | **$112,800** | **$201,900** | **$282,900** |
| Fractional SRE (0.15 FTE) | Labor | $35,000 | $35,000 | $35,000 | $35,000 | $35,000 |
| Security review | Labor | $2,500 | $2,500 | $2,500 | $2,500 | $2,500 |
| Uniformedi support | Labor | $0 | $5,000 | $8,000 | $12,000 | $15,000 |
| **Labor subtotal** | | **$37,500** | **$42,500** | **$45,500** | **$49,500** | **$52,500** |
| **Scenario A total** | | **$68,300** | **$100,300** | **$158,300** | **$251,400** | **$335,400** |
| *Labor as % of total* | | *55%* | *42%* | *29%* | *20%* | *16%* |

RHEL subscriptions: 2 × Standard ($799 each = $1,598 ≈ $1,600) in Y1–Y2; 2 × Premium ($1,299 each = $2,598 ≈ $2,600) from Y3 onward when the platform moves to broad availability and 24×7 support becomes warranted.

**5-year Scenario A labor total:** $227,500 (25% of 5-yr TCO of $913,700). Labor is a larger share in Y1–Y2 but becomes fixed-cost noise by Y5 as Anthropic API scales linearly with users. RHEL adds $11,000 to the 5-year TCO vs the Ubuntu baseline (+1.2%).

### 4.3 Capacity headroom

- Y1–Y2 (50–100 users): P7920 runs at <25% load, very comfortable.
- Y3 (200 users): P7920 at ~55% load, still comfortable. Guacamole + edge on the second box stay at <20%.
- Y4+: R6615 replaces or augments P7920; load stays <40%.

---

## 5. Scenario B — New Latest Equipment (R6615 Balanced from Year 1)

Full greenfield on dedicated server-class hardware. Primary = R6615 Balanced from Day 1. P7920 becomes the second node (edge + backup gateway) for 2-node HA from the start.

### 5.1 Capex / amortization

| Item | Cost | Amortization |
|---|---|---|
| R6615 Balanced (Y1 purchase) | $32,000 | $6,400/year over 5 years |
| Network switch, cabling, rack | $3,500 | $700/year over 5 years |
| Small edge mini-PC | $1,200 | $240/year over 5 years |

### 5.2 Annual cost table

| Line | Category | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---|---|---|---|---|---|
| Hardware amortization | Non-labor | $7,340 | $7,340 | $7,340 | $7,340 | $7,340 |
| Power + cooling | Non-labor | $1,400 | $1,400 | $1,400 | $1,400 | $1,400 |
| Backup / monitoring | Non-labor | $600 | $600 | $600 | $600 | $600 |
| **RHEL 9 subscriptions (2 instances)** | Non-labor | $1,600 | $1,600 | $2,600 | $2,600 | $2,600 |
| Anthropic API | Non-labor | $27,000 | $54,000 | $108,000 | $189,000 | $270,000 |
| Other | Non-labor | $200 | $200 | $200 | $200 | $200 |
| **Non-labor subtotal** | | **$38,140** | **$65,140** | **$120,140** | **$201,140** | **$282,140** |
| Fractional SRE (0.15 FTE) | Labor | $35,000 | $35,000 | $35,000 | $35,000 | $35,000 |
| Security review | Labor | $2,500 | $2,500 | $2,500 | $2,500 | $2,500 |
| Uniformedi support | Labor | $0 | $5,000 | $8,000 | $12,000 | $15,000 |
| **Labor subtotal** | | **$37,500** | **$42,500** | **$45,500** | **$49,500** | **$52,500** |
| **Scenario B total** | | **$75,640** | **$107,640** | **$165,640** | **$250,640** | **$334,640** |
| *Labor as % of total* | | *50%* | *40%* | *27%* | *20%* | *16%* |

RHEL subscription pricing identical to Scenario A (2 instances; Standard Y1–Y2, Premium Y3+).

**5-year Scenario B labor total:** $227,500 — identical to Scenario A. Hardware-mode choice does not move the labor line because the SRE fraction is driven by what it takes to keep a 2-node on-prem cluster healthy, which is roughly the same for one or two server-class boxes. RHEL adds $11,000 to the 5-year TCO vs the Ubuntu baseline.

### 5.3 Capacity headroom

- R6615 Balanced handles 160 RDSH agents, 700 voice channels, or 2,500 Guacamole sessions per node. Y1–Y5 never approaches capacity. Scenario B front-loads capital but gives greatest resilience.

---

## 6. Scenario C — Virtualized (AWS reserved instances, 1-year terms)

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

| Line | Category | Y1 | Y2 | Y3 | Y4 | Y5 |
|---|---|---|---|---|---|---|
| EC2 reserved (1yr) | Non-labor | $28,000 | $52,000 | $99,000 | $146,000 | $202,000 |
| EBS / S3 storage + snapshots | Non-labor | $2,400 | $4,800 | $9,000 | $14,000 | $20,000 |
| Egress / data transfer | Non-labor | $1,800 | $3,600 | $7,200 | $13,000 | $20,000 |
| AWS Support (Business tier) | Non-labor* | $1,200 | $2,400 | $4,800 | $7,500 | $10,500 |
| **RHEL 9 subscriptions (BYOS via Cloud Access)** | Non-labor | $1,600 | $2,400 | $3,200 | $4,000 | $5,600 |
| Anthropic API | Non-labor | $27,000 | $54,000 | $108,000 | $189,000 | $270,000 |
| **Non-labor subtotal** | | **$62,000** | **$119,200** | **$231,200** | **$373,500** | **$528,100** |
| Fractional SRE (0.11 FTE) | Labor | $25,000 | $25,000 | $25,000 | $25,000 | $25,000 |
| Security review | Labor | $2,500 | $2,500 | $2,500 | $2,500 | $2,500 |
| Uniformedi support | Labor | $0 | $5,000 | $8,000 | $12,000 | $15,000 |
| **Labor subtotal** | | **$27,500** | **$32,500** | **$35,500** | **$39,500** | **$42,500** |
| **Scenario C total** | | **$89,500** | **$151,700** | **$266,700** | **$413,000** | **$570,600** |
| *Labor as % of total* | | *31%* | *21%* | *13%* | *10%* | *7%* |

RHEL on AWS via Red Hat Cloud Access (BYOS): scales with EC2 instance count — 2 instances Y1, 3 Y2, 4 Y3, 5 Y4, 7 Y5 at $800 Standard per instance. Premium tier optional but not assumed since AWS Business Support already provides 24×7 coverage on the AWS side. Alternative: pay Red Hat's hourly RHEL AMI premium directly through AWS billing (~10–15% higher annually; BYOS is the efficient path when Organization already buys on-prem RHEL subscriptions).

*AWS Support is a billed support contract (AWS-side labor), treated as non-labor from Organization's perspective since it's invoiced as a service. RHEL subscription is similarly vendor-backed support, billed as a service.

**5-year Scenario C labor total:** $177,500 — $50,000 less than Scenario A/B over 5 years (the SRE fraction drop from 0.15 → 0.11 FTE × 5 years = $50k). This is the only cost category where the cloud scenario actually wins; the savings are eaten many times over by EC2/egress/storage non-labor lines. RHEL adds $16,800 to the 5-year TCO (+1.1%), slightly higher than A/B because the AWS scenario scales RHEL subscriptions with instance count.

Note: SRE fraction is lower than A/B because AWS removes hardware-side operational burden (no BIOS updates, disk swaps, power/cooling, rack work). `Uniformedi support` remains the same assuming feature-side support (platform code, OPA policy updates, DLP tuning) is identical regardless of infrastructure mode.

### 6.3 Azure / GCP parity

Azure D-series v5 reserved 1-yr pricing and GCP n2-standard reserved pricing come within ±5% of AWS c6i reserved over this workload profile. Substitute at 1:1 for planning purposes; the scenario does not materially shift.

---

## 7. Sensitivity analysis

All sensitivity tables below are recomputed from the RHEL-inclusive base (Sections 4.2, 5.2, 6.2) to ensure internal consistency.

### 7.1 Usage is 2× heavier than modeled

Every user actually uses InsideLLM ~2× more than forecast (common if the tool becomes the default company-wide). Anthropic line doubles. Other lines unchanged.

| Year | A | B | C |
|---|---|---|---|
| Y1 | $95k | $103k | $117k |
| Y5 | $605k | $605k | $841k |
| 5-yr total | **$1,562k** | **$1,582k** | **$2,140k** |

### 7.2 Prompt caching + model price drops save 25%

If Anthropic caching kicks in (~20% hit rate) and model prices drop 15% annually on older models, Anthropic line is ~25% lower from Y3 onward.

| Year | A | B | C |
|---|---|---|---|
| Y3 | $131k | $139k | $240k |
| Y5 | $268k | $267k | $503k |
| 5-yr total | **$772k** | **$792k** | **$1,350k** |

### 7.3 User count is half (250 by Y5 instead of 500)

Slower rollout. Anthropic scales linearly (halved each year).

| Year | A | B | C |
|---|---|---|---|
| Y5 | $200k | $200k | $436k |
| 5-yr total | **$590k** | **$610k** | **$1,168k** |

---

## 8. Hidden / out-of-scope costs to budget separately

These are real but not attributed to InsideLLM in the above tables. Labor-heavy items are flagged explicitly.

### 8.1 Labor-heavy hidden costs

| Item | Est. range | Labor hours (implied) | Timing | Who bears it |
|---|---|---|---|---|
| Initial implementation — Uniformedi | ~$25,000 | ~125 hrs @ $200/hr over 2–4 weeks | Y1 one-time | Uniformedi (billed to Organization) |
| **RHEL port — cloud-init + SELinux (Uniformedi)** | **~$8,000** | **~40 hrs @ $200/hr (templates + SELinux policy module)** | **Y1 one-time** | **Uniformedi (billed to Organization)** |
| Initial implementation — Organization internal | ~$10,000 | ~60–80 hrs (Okta admin, IT, legal) | Y1 one-time | Organization staff time |
| Legal + compliance review | $5,000–$15,000 | ~20–50 hrs at legal/compliance rates | Y1 one-time | Organization (counsel, in-house or outside) |
| Training / change management | $10,000–$25,000 | ~50–120 hrs across Y1–Y2 | Spread over Y1–Y2 | Organization (L&D + champions program) |
| External pentest | $15,000–$40,000 | Vendor engagement, ~40–100 hrs vendor-side | Every 18–24 months from Y2 | Organization (pentest firm) |
| Anthropic contract renegotiation | Time only; yields 10–15% savings | ~10–20 hrs procurement + legal | Late Y1 / early Y2 | Organization (procurement + counsel) |

**Total labor-heavy hidden costs (mid-range estimate):**

- **Y1 one-time labor:** $25k (Uniformedi impl) + $8k (RHEL port) + $10k (Org impl) + $10k (legal) + $10k (training) = **~$63,000**
- **Y2 labor:** $15k (training tail) + $25k (first pentest if done) = **~$40,000**
- **Y3–Y5 labor:** pentest every 18–24 months (~$25k avg spread) + ongoing training refreshes (~$5k/yr)

### 8.2 Non-labor hidden costs

1. **Data retention / archival** — long-term storage of audit logs beyond the platform's default retention could require cold-storage (S3 Glacier) if Organization wants 7-year retention. Negligible until Y3, then ~$1–3k/year.

### 8.3 Adjusted 5-year total with hidden labor (Scenario A, RHEL)

| | Base forecast | Hidden labor (mid) | Hidden non-labor | Adjusted total |
|---|---|---|---|---|
| Y1 | $68,300 | $63,000 | $0 | $131,300 |
| Y2 | $100,300 | $40,000 | $0 | $140,300 |
| Y3 | $158,300 | $12,500 | $2,000 | $172,800 |
| Y4 | $251,400 | $27,500 | $2,000 | $280,900 |
| Y5 | $335,400 | $12,500 | $3,000 | $350,900 |
| **5-yr** | **$913,700** | **~$155,500** | **~$7,000** | **~$1,076,200** |

The hidden labor adds ~17% to the 5-year Scenario A TCO. RHEL port work (+$8k in Y1 one-time) is the only RHEL-specific hidden-cost line; ongoing RHEL operations are absorbed by the existing SRE fraction. Budget accordingly.

---

## 8.5 Labor cost breakout summary (all scenarios)

Consolidated view across the three scenarios, on-plan operating labor only (hidden one-time labor excluded — see Section 8.3 for those):

| Labor line | Scenario | Y1 | Y2 | Y3 | Y4 | Y5 | 5-yr total |
|---|---|---|---|---|---|---|---|
| Fractional SRE | A | $35,000 | $35,000 | $35,000 | $35,000 | $35,000 | $175,000 |
| Fractional SRE | B | $35,000 | $35,000 | $35,000 | $35,000 | $35,000 | $175,000 |
| Fractional SRE | C | $25,000 | $25,000 | $25,000 | $25,000 | $25,000 | $125,000 |
| Security review | A/B/C | $2,500 | $2,500 | $2,500 | $2,500 | $2,500 | $12,500 |
| Uniformedi support | A/B/C | $0 | $5,000 | $8,000 | $12,000 | $15,000 | $40,000 |
| **Labor subtotal (A)** | | **$37,500** | **$42,500** | **$45,500** | **$49,500** | **$52,500** | **$227,500** |
| **Labor subtotal (B)** | | **$37,500** | **$42,500** | **$45,500** | **$49,500** | **$52,500** | **$227,500** |
| **Labor subtotal (C)** | | **$27,500** | **$32,500** | **$35,500** | **$39,500** | **$42,500** | **$177,500** |

### Labor as share of total (RHEL-inclusive)

| Scenario | Labor 5-yr | Total 5-yr | Labor % |
|---|---|---|---|
| A | $227,500 | $913,700 | **25%** |
| B | $227,500 | $934,200 | **24%** |
| C | $177,500 | $1,491,500 | **12%** |

(RHEL subscriptions are treated as non-labor vendor-service cost, so labor subtotals are unchanged from the Ubuntu baseline.)

### Key labor observations

1. **Labor is stable across Scenarios A and B.** Choosing between "use existing hardware + refresh at Y4" (A) versus "buy new server-class hardware Y1" (B) doesn't change what it takes to run the platform. Same SRE fraction, same support ramp.
2. **Scenario C saves ~$50k over 5 years on labor** by offloading hardware operations to AWS (0.15 → 0.11 FTE). This is real but much smaller than the ~$578k total gap that same scenario incurs once RHEL subscriptions and other non-labor lines are added.
3. **Labor share decreases over time** in all scenarios because Anthropic API spend scales with users while labor is roughly flat. At Y5 labor is 8–16% of annual cost; at Y1 it's 31–56%.
4. **The biggest unmodeled labor risk** is the fractional SRE assumption. If Organization cannot secure 0.15 FTE at the loaded rate used here, this line could be 1.5–2× higher. Worth validating with HR before signing off on the forecast.
5. **Security review line is underfunded if pentest is expected annually.** Current $2,500/year only covers internal review + automated scans. Full external pentests (Section 8.3) sit in hidden costs.

---

## 9. Recommendation

1. **Select Scenario A on RHEL 9.** Maximizes existing-asset utilization for 3 years, defers capex to when growth actually materializes. 5-year savings vs Scenario B: ~$20k. Vs Scenario C: ~$578k. RHEL adds $11k over 5 years vs Ubuntu but provides FIPS 140-3 compliance, vendor-backed support through 2032, and reduces OS-layer audit burden.

2. **Lock in Anthropic contract pricing by end of Y1** once utilization is measurable. Pre-commit for Y2 spend if Anthropic offers a discount at the $50k–75k tier.

3. **Enable LiteLLM Redis response cache** at deploy time (one-line change). Conservative 15% hit rate saves ~$40k over 5 years on the Anthropic line alone.

4. **Reserve $25k in a Y1 contingency budget** for unforeseen hardening, certificate work, and user-experience tuning. Historically undersized in AI platform deployments.

5. **Revisit forecast annually.** User-count curve and usage intensity are the two biggest levers; both are observable after 90 days of production traffic.

---

## 10. Finance-friendly summary

- **Year 1 total cost of ownership, Scenario A: ~$68,000.** Dominated by fractional SRE ($35k) and Anthropic API ($27k). Labor = $37,500 (55%). Includes RHEL 9 subscriptions (~$1,600/yr).
- **Year 5 total cost of ownership, Scenario A: ~$335,000.** Anthropic API is 81% of this. Labor = $52,500 (16%).
- **5-year TCO, Scenario A (RHEL): ~$914,000** (including conservative support-contract ramp and RHEL 9 subscriptions). Labor = $227,500 (25%).
- **RHEL premium vs Ubuntu baseline: ~$11,000 over 5 years** — small relative to total TCO; buys FIPS-validated crypto, DISA STIG compliance, and vendor-backed support through 2032.
- **5-year labor-only spend, Scenario A: $227,500** operational + ~$155,500 hidden one-time labor (now includes $8k RHEL port) = **~$383,000** total labor commitment across 5 years.
- **Break-even vs using ChatGPT Enterprise or similar SaaS at $60/user/month:** InsideLLM becomes cost-neutral around 120 users and beats ChatGPT Enterprise on a per-user basis at every scale from that point forward, while also retaining data control, audit trail, and policy enforcement — which ChatGPT Enterprise does not provide at the same depth.

---

## 11. Comparison to commercial SaaS alternatives

For decision-context:

| Offering | Y5 @ 500 users | 5-yr total @ 500 users | Governance + audit? | Data sovereignty? | OS / compliance |
|---|---|---|---|---|---|
| **InsideLLM (A, RHEL 9)** | $335k | $914k | Yes (hash-chained) | Yes (on-prem) | RHEL 9, FIPS 140-3, DISA STIG |
| ChatGPT Enterprise | $360k | $1,440k | Limited | Partial (data commits) | n/a |
| Microsoft Copilot for M365 | $150k | $720k + M365 seats | Limited | No | n/a |
| Google Gemini Enterprise | $252k | $1,020k | Limited | No | n/a |

Note: SaaS comparisons exclude Anthropic (they're self-contained) and assume Organization already licenses the underlying Microsoft or Google base. InsideLLM requires Anthropic pay-as-you-go (the $270k Y5 line), but retains full policy/governance control that none of the SaaS competitors match.

---

End of document. Contact the Uniformedi finance liaison to adjust
assumptions or model additional scenarios.
