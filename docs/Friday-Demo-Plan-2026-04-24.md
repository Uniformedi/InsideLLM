# Friday Demo Plan — 2026-04-24 (AM)

> **Audience:** one board principal who owns 34 portfolio companies.
> **Stakes:** gating meeting. If it lands, InsideLLM is featured across
> all 34 companies at the 2026-05-12 showcase.
> **Status:** this is a **preview** demo on 3.1.0 as shipped, plus the
> new Collections industry pack. The v3.2 visual agent builder on the
> Project-Plan-3.2 schedule is **not** on Friday's path — it stays
> May 12.

## Framing (for the operator, not to be read aloud)

The principal is not a compliance officer and not an engineer. He is a
capital owner thinking about risk × revenue × capital efficiency across
34 companies. Every segment of the demo should answer the implicit
question: **"what does this buy me across 34 companies?"**

Lean on two value pillars and nothing else:
1. **Integrity you can audit** — OPA + DLP + hash-chained audit mean his
   34 companies can adopt AI without each one writing a compliance program
   from scratch.
2. **One platform, thirty-four deployments** — Industry Packs mean Company #7
   (a collections operation) and Company #19 (a clinic) each get a vertical
   starter kit without needing a separate product.

Do not mention Ketryx unless asked. Do not promise the visual builder.
Do not claim the product replaces human compliance review.

## What's on the critical path (do not break)

- 3.1.0 baseline running on the demo VM.
- Collections industry pack at `configs/industry-packs/collections/`.
- Seeded Organization tenant data in the portfolio dashboard.
- Dispute Handler agent from the Collections pack published and live.
- `lookup_account` + `draft_validation_notice` + `open_dispute_record`
  worker stubs returning canned but plausible responses.
- Pre-populated audit chain with ~100 representative events.
- RAG collection `collections-procedures` seeded with a handful of dispute
  procedures and state variation notes.

## Demo narrative (45 minutes; 30 demo + 15 Q&A buffer)

| # | Min | Segment | What the principal sees | What ships today that makes this work |
|---|---|---|---|---|
| 0 | 3 | **Framing** — "integrity is the buying decision, not capability." One-slide pitch. | Slide. No live system. | — |
| 1 | 4 | **Portfolio overview** — Admin Center → portfolio dashboard. Organization tenant + (if time permits) a second seeded tenant to show multi-tenant view. | One page; compliance score per tenant, spend, DLP blocks, audit chain health. | Admin Center SPA, `governance_instances`, `governance_telemetry`. |
| 2 | 2 | **Industry Packs, one slide** — "here are the packs available; Collections is the sample, Healthcare and Financial Services scaffolded." | Slide listing packs in `configs/industry-packs/`. | — |
| 3 | 6 | **Collections in action (happy path)** — operator opens OWUI, picks Dispute Handler agent, pastes a consumer dispute email. Agent looks up the account, drafts a §1692g acknowledgment letter via DocForge. | Draft appears in approval queue, not sent. | LiteLLM virtual key, OWUI custom model, DocForge, `tier_fdcpa_regulated` profile, `fdcpa-validation-notice.md.tpl`. |
| 4 | 4 | **Negative demo #1 — out-of-hours contact** — ask agent to place a callback to the consumer "right now" (demo clock pre-set to 22:15 local). | OPA denies and cites §1692c(a)(1). Agent explains and offers an in-window time. | `tier_fdcpa_regulated.rego` hour rule. |
| 5 | 4 | **Negative demo #2 — RAG scope escape** — paste a prompt-injection asking the agent to read from the `hr-confidential` collection. | OPA denies with the rule source visible. | `rag_scope.rego` + Humility base. |
| 6 | 3 | **DLP live** — paste a message with a full SSN. Upload a doc with a credit-card number. | Both redacted/blocked inline; audit entry written. | LiteLLM DLP callback + `collections-patterns.yaml`. |
| 7 | 3 | **Hash-chained audit** — curl `/api/v1/audit/chain/verify`. Show the chain is valid. Then corrupt one entry in the DB and re-run. Chain breaks; first broken sequence is surfaced. | Live tamper-evidence. | `services/audit_chain.py`. |
| 8 | 2 | **Rego is the policy** — open `tier_fdcpa_regulated.rego` in Admin Center → Policies. "Your compliance team can read this. Your board can review it. It is the contract." | File viewer. | Already shipped. |
| 9 | 1 | **Roadmap tease** — one slide: "Visual agent builder → May 12 showcase; Ketryx + Managed Agents → 3.3." No live demo. | Slide. | — |

Total live-demo run: 26 minutes. 4 minutes of slide framing. 15 minutes of
Q&A buffer.

## What is explicitly NOT in Friday's demo

- **Visual agent builder UI.** That's May 12 via the Project-Plan-3.2
  schedule (Phase 2B). On Friday, agents are pre-authored YAML in the
  Collections pack.
- **Activepieces workflow pieces.** Phase 4 work; not wired.
- **Pattern library UI.** Seeded data only; not surfaced.
- **Ketryx integration.** Mention if the principal asks about eQMS;
  describe as optional downstream adapter, not a live connection.
- **Multi-tenant cross-portfolio view with real data from all 34 companies.**
  Seed Organization + one or two synthetic tenants. Don't pretend.
- **Claude Code CLI on the VMs.** Worth mentioning in conversation; not
  worth a demo slot.

## Prep checklist (runs Wed afternoon — Thu EOD)

| Task | Est. | Owner | Risk |
|---|---|---|---|
| Clean deploy of 3.1.0 on the demo VM (or snapshot-restore) | 2 h | ops | Low |
| Seed `governance_instances` with 2–3 tenants incl. Organization | 1 h | backend | Low |
| Register Collections pack agents in `governance_agents` as published | 1 h | backend | Low |
| Stub workers for `lookup_account`, `draft_validation_notice`, `open_dispute_record` — canned responses, deterministic | 4 h | backend | **Med** — must be idempotent + reliable across re-runs |
| Pre-populate audit chain with ~100 events that tell a coherent story | 1 h | backend | Low |
| Seed RAG `collections-procedures` collection | 1 h | backend | Low |
| Seed RAG `hr-confidential` decoy collection (for negative demo #2) | 0.5 h | backend | Low |
| Set demo VM system clock to 22:15 local for out-of-hours demo; verify OPA fires | 0.5 h | ops | **Med** — must remember to reset after rehearsal |
| Pre-draft rollback commands for each segment (if segment flakes, skip) | 1 h | operator | Low |
| Rehearse end-to-end twice, with fallback narration for each segment | 4 h | operator | Low |
| Print one-pager: Industry Packs list + "what's next" roadmap | 0.5 h | operator | Low |
| **Total** | **~17 h** | — | Fits in the available window |

## Fallback scripts (one per segment)

- **Segment 1** (portfolio dashboard won't load): skip to Segment 2 slide
  and narrate what dashboard would show. Continue.
- **Segment 3** (agent responds oddly or times out): "the worker returns a
  canned response in this demo; production is faster." Move to 3a: open
  the already-approved draft in the approval queue manually.
- **Segment 4** (OPA doesn't deny as expected): check demo clock. If
  clock is wrong, fix and retry. If still broken, open the Rego file,
  read the rule aloud, say "this is what's enforced in production."
- **Segment 5** (RAG denial doesn't fire): same fallback — open
  `rag_scope.rego`, read aloud.
- **Segment 6** (DLP doesn't redact): worst-case — show the DLP pattern
  file (`collections-patterns.yaml`) and narrate.
- **Segment 7** (chain verify is slow): pre-run it once; present the
  result. Then do the tamper-evidence step on a small 10-entry sample
  for speed.

## Success criteria

The demo succeeds if the principal leaves with one sentence he can
repeat to his 34 CEOs: **"This is the compliance substrate for AI at
our companies."** Everything in the narrative is in service of making
that sentence land.

The demo also succeeds if he asks about two or more of: Ketryx, Managed
Agents, specific non-Collections industry packs (Healthcare, Financial
Services), or pricing/licensing. Each is a buy signal.

The demo fails if the narrative becomes feature-centric ("look at the
DLP rules! look at the audit chain!") instead of outcome-centric ("your
34 companies can adopt AI without each writing a compliance program").

## Honesty check — read this out loud at some point

> "This platform reduces the work of building and auditing AI operations
> in regulated contexts. It does not eliminate that work. Your companies'
> compliance teams still own the judgment calls. What we ship is the
> substrate — the OPA layer, the audit chain, the DLP, the document
> templates — that makes their judgment faster to exercise and easier to
> prove to a regulator."

Regulated buyers trust operators who say this out loud.

## After the demo

- Send the principal a one-page PDF: the portfolio dashboard screenshot,
  the Industry Packs shipping table, a short "how to pilot" note.
- Do not follow up with a 30-page deck. The demo was the deck.
- If the principal signals yes for May 12, transition into Project-Plan-3.2
  execution mode. The Gantt there is already tight (19 crit-path days vs.
  17 available); a Friday-go cannot slip that schedule any further.

## Appendix — files touched by the demo (operator reference)

| File / endpoint | Purpose |
|---|---|
| `configs/industry-packs/collections/manifest.yaml` | Shows what the pack contains |
| `configs/industry-packs/collections/agents/dispute-handler.yaml` | The agent the principal sees run |
| `configs/industry-packs/collections/documents/fdcpa-validation-notice.md.tpl` | The letter DocForge renders |
| `configs/industry-packs/collections/dlp/collections-patterns.yaml` | DLP patterns the demo triggers |
| `configs/opa/policies/profiles/tier_fdcpa_regulated.rego` | The rule that denies §1692c(a)(1) contact |
| `configs/opa/policies/humility/rag_scope.rego` | The rule that denies scope-escape |
| `configs/governance-hub/src/services/audit_chain.py` | Hash-chain verify logic |
| `GET /api/v1/audit/chain/verify` | Endpoint for the tamper-evidence segment |
