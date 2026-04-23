# InsideLLM — Ticketing Design

**Classification:** Internal engineering design
**Drafted:** 2026-04-22
**Owner:** Dan Medina
**Status:** Design draft — candidate scope for v3.3
**Related artifacts:**
- `docs/Zero-Trust-Design.md` — companion; the ZT work enables secure multi-actor transport
- `html/Architecture.html` — baseline architecture this extends
- `html/SWOTanalysis.html` — Opportunities #3 (cross-portfolio governance dashboard) aligns

This document scopes a real-time multi-actor ticketing capability that
treats employees, AI agents, clients, vendors, and InsideLLM instance
integrations as first-class ticketing participants. Protocol surfaces
vary by proximity to the enterprise boundary; exterior links use only
the most secure technologies.

---

## Why this belongs in InsideLLM

A governance platform already owns the approval queue for agent-initiated
high-stakes actions (demonstrated by the Dispute Handler `send_letter`
flow). Expanding that from "approval queue for internal agents" to "full
multi-actor ticketing surface" turns a single-purpose primitive into a
governance-aware operational work system.

Three buyer-relevant capabilities unlock:

1. **Client incident channel.** Customers at Parent Organization's 32
   portfolio companies can file tickets that are already governance-scoped,
   DLP-scanned, and auditable.
2. **Vendor coordination.** Partners and integrations can submit + receive
   tickets over a secure surface without being handed broad platform access.
3. **Agent-originated tickets.** AI agents file tickets as an OPA-governed
   action (`file_ticket`) rather than escaping governance by going out-of-band
   to human channels like Slack.

All three are expressible as extensions of mechanisms already present; none
of them require bolting on a new governance model.

---

## What exists today (adjacent pieces)

| Piece | Role in a future ticketing system |
| --- | --- |
| Governance Hub approval queue (`/governance/changes`) | Single-actor-class ticket surface; the foundation |
| Hash-chained audit | Ticket lifecycle events land here for free |
| LiteLLM callback framework | Inbound pipeline for agent-originated tickets (DLP + OPA + rate-limit) |
| OPA policy engine | Routing, scope, escalation decisions |
| Governance Hub FastAPI (:8090) | Natural mount point for `/tickets/api/v1/` |
| PostgreSQL + Redis | Durable ticket state + real-time pub/sub |
| Slack + Uptime Kuma alerts | Outbound notification leg |
| LiteLLM multi-client auth | Employee / agent / API-consumer identity pattern already proven |
| OIDC / LDAP / three-mode auth | Identity for employees and admin users |

What's **missing** for true multi-actor real-time ticketing:

- Ticket lifecycle schema and state machine
- Multi-actor identity model (employees, agents, clients, vendors, fleet peers)
- Real-time transport layer (not pure polling)
- Protocol-adapter layer (different surfaces for different proximity tiers)
- Integrations with external ticketing systems (bidirectional)
- Per-actor DLP + scope enforcement

---

## Design principles

1. **Tickets are first-class governance objects.** Every ticket is scoped to a tenant, identity, and policy profile. No "free-text issue" that escapes policy.
2. **Actor-agnostic interface, actor-specific identity.** One ticket schema; different authentication and authorization adapters.
3. **Protocol tier follows proximity.** Inside the enterprise boundary uses fast / simple protocols. Cross-boundary uses only the most secure surfaces (mTLS + OAuth client credentials + narrow scopes). Exterior tier is explicitly constrained.
4. **Real-time is server-push, not client-poll.** Server-Sent Events (SSE) over HTTPS for delivery. Reliable through corporate proxies; simpler than WebSockets.
5. **Human-in-the-loop where it matters.** OPA decides whether a ticket fires obligations (notify, escalate, require attestation, route to review queue).
6. **Audit chain captures lifecycle.** Every ticket creation, state transition, comment, close event lands in the hash chain.
7. **Integrate, don't replace.** Most enterprises run Zendesk / ServiceNow / PagerDuty. Bidirectional connectors are the goal; being the system of record is optional.

---

## Architecture

### New service: Ticketing Hub

FastAPI service mounted alongside Governance Hub. Same container image
deployment pattern; separate port (:8091); separate process for isolation.

```
+------------------------+         +--------------------------+
|  Governance Hub        |         |  Ticketing Hub           |
|  :8090  /governance/   |         |  :8091  /tickets/api/v1  |
|                        |         |                          |
|  - agents, actions     |         |  - tickets CRUD          |
|  - approvals, changes  |<------->|  - lifecycle state       |
|  - fleet sync          |  shared |  - SSE stream            |
|  - audit chain         |  DB     |  - external connectors   |
+-----------+------------+         +-----------+--------------+
            |                                  |
            +------------+---------+-----------+
                         |         |
                   +-----v-----+  +v----------+
                   | PostgreSQL|  | Redis     |
                   | (tickets, |  | (pub/sub, |
                   | events,   |  | SSE fan-  |
                   | watchers) |  | out)      |
                   +-----------+  +-----------+
```

### Data model

Five new PostgreSQL tables:

**`tickets`**
```sql
id                uuid primary key
tenant_id         text not null
title             text not null
body              text              -- DLP-scanned
category          text              -- 'incident' | 'request' | 'question' | 'change' | 'agent-flag'
priority          text              -- 'low' | 'medium' | 'high' | 'critical'
state             text              -- 'open' | 'triage' | 'in_progress' | 'waiting' | 'resolved' | 'closed'
created_by_type   text              -- 'employee' | 'agent' | 'client' | 'vendor' | 'fleet_peer'
created_by_id     text              -- OIDC sub | agent_id | JWT sub | vendor_id | peer fqdn
assigned_to_type  text
assigned_to_id    text
created_at        timestamptz
updated_at        timestamptz
resolved_at       timestamptz
closed_at         timestamptz
guardrail_profile text              -- OPA profile for this ticket's policy decisions
external_ref      text              -- Zendesk ID, ServiceNow sys_id, etc.
```

**`ticket_events`** (append-only)
```sql
id                uuid primary key
ticket_id         uuid references tickets(id)
event_type        text              -- 'created' | 'state_changed' | 'comment' | 'assigned' | 'escalated' | 'closed' | 'dlp_redacted'
actor_type        text
actor_id          text
payload           jsonb             -- event-type-specific data (DLP-scanned if contains PII)
occurred_at       timestamptz
audit_chain_seq   bigint            -- pointer to Governance Hub audit entry
```

**`ticket_watchers`**
```sql
ticket_id         uuid references tickets(id)
watcher_type      text
watcher_id        text
subscribed_at     timestamptz
notification_mode text              -- 'sse' | 'email' | 'slack' | 'teams' | 'webhook'
```

**`ticket_comments`**
```sql
id                uuid primary key
ticket_id         uuid references tickets(id)
author_type       text
author_id         text
body              text              -- DLP-scanned; may be redacted per-recipient on read
visibility        text              -- 'public' | 'internal' | 'actor_type_restricted'
created_at        timestamptz
```

**`ticket_connectors`** (for bidirectional external integration)
```sql
id                uuid primary key
tenant_id         text
connector_type    text              -- 'zendesk' | 'servicenow' | 'pagerduty' | 'jira'
config            jsonb             -- endpoint, auth, field mappings
direction         text              -- 'inbound' | 'outbound' | 'bidirectional'
enabled           boolean
```

### Lifecycle state machine

```
                         (optional)
                          triage
                           |
 open ──────────────────> in_progress ──────> waiting ──────> resolved ──────> closed
  |                           ^                   |
  |                           |                   |
  └─── (agent-flagged) ───────+                   |
                              |                   |
                    (needs customer response)─────+
```

- **`open`** — newly created; awaiting triage or auto-routing
- **`triage`** — under review to classify / assign
- **`in_progress`** — actively being worked
- **`waiting`** — waiting on the requester or an external dependency
- **`resolved`** — work complete; awaiting requester confirmation
- **`closed`** — closed; read-only except for audit metadata

OPA enforces valid state transitions based on actor role + ticket tier.

---

## Actor identity model

The multi-actor nature is the core design challenge. Each actor class has
its own authentication, authorization scope, and protocol preference.

### Employees (enterprise boundary)

- **Authentication:** OIDC via Entra ID / Okta (existing); LDAP fallback
- **Authorization:** OIDC group → ticket scope mapping (e.g., `ops-team` can see infra tickets; `compliance` can see compliance tickets)
- **Protocol:** HTTPS via Nginx reverse proxy at `/tickets/`, SSE for real-time, standard REST for CRUD
- **Identity in ticket:** `created_by_type='employee'`, `created_by_id=<oidc-sub>`

### AI agents (internal, governance-scoped)

- **Authentication:** LiteLLM virtual key (existing per-agent)
- **Authorization:** Agent manifest declares which ticket categories the agent may file via new manifest field `ticket_scopes: [<categories>]`. OPA policy checks on each `file_ticket` action catalog call.
- **Protocol:** Agent invokes `file_ticket` / `update_ticket` / `close_ticket` / `comment_ticket` as catalog actions through LiteLLM → Ticketing Hub via internal HTTPS.
- **Identity in ticket:** `created_by_type='agent'`, `created_by_id=<tenant_id>:<agent_id>`
- **Example use:** Dispute Handler flags a suspicious pattern mid-flow → files a ticket under category `agent-flag` with priority `high` → routes to compliance team

### Clients (external, tenant-scoped)

- **Authentication:** Tenant-scoped JWT minted by Governance Hub; OIDC federation optional for enterprise clients
- **Authorization:** Tenant scope limits ticket visibility to the client's own tenant; client role (`standard` vs `admin`) limits category access
- **Protocol:** HTTPS via Nginx reverse proxy at `/tickets/api/v1/client/`; rate-limited via LiteLLM rate-limit primitives; SSE for real-time updates
- **DLP:** Inbound ticket bodies scanned; outbound (when they read tickets filed about their tenant) redacted per their role
- **Identity in ticket:** `created_by_type='client'`, `created_by_id=<tenant_id>:<user_id>`

### Vendors / partners (most-exterior, highest-risk)

- **Authentication:** OAuth 2.0 client credentials + **mTLS** (vendor has a client certificate issued by Governance Hub / Smallstep step-ca)
- **Authorization:** Narrow-scope tokens; category allow-list per vendor; rate-limited aggressively
- **Protocol:** HTTPS + mTLS; **no SSE for vendors** — they poll or receive webhook notifications at a customer-approved endpoint
- **Data posture:** Vendors **cannot** read ticket bodies beyond their own submissions; they can only see aggregate state on tickets they've filed or been explicitly CCd to
- **Identity in ticket:** `created_by_type='vendor'`, `created_by_id=<vendor_org_id>:<cert_serial>`
- **Explicit constraint:** vendors cannot file tickets against other tenants; they can only file vendor-scope tickets

### Fleet-peer integrations (inter-VM, intra-customer)

- **Authentication:** mTLS via Headscale-distributed certificates (see `Zero-Trust-Design.md`); WireGuard overlay already authenticates at transport layer
- **Authorization:** Peer role (primary / gateway / workstation / voice / edge) determines ticket categories accessible
- **Protocol:** HTTPS over WireGuard overlay; internal SSE for real-time between peers; no external exposure
- **Use case:** A workstation VM detects a degraded service → files an infra ticket against the primary's Ticketing Hub → ops team sees in unified queue

---

## Protocol matrix by proximity

| Tier | Who | Protocol | Auth | Real-time |
| --- | --- | --- | --- | --- |
| T0 — Same container / VM | Service-to-service | Docker bridge IPC | Docker network namespace | N/A |
| T1 — Intra-fleet (WireGuard) | Fleet peer VMs | HTTPS over WireGuard overlay | WireGuard + mTLS | SSE internal |
| T2 — Employee client | Staff browsers | HTTPS via Nginx | OIDC / LDAP | SSE |
| T3 — Tenant client | External customer users | HTTPS via Nginx | Tenant JWT (+ optional OIDC fed) | SSE (rate-limited) |
| T4 — Vendor / partner | Third-party orgs | **HTTPS + mTLS + OAuth 2.0 client credentials** | Certificate + OAuth scope | **Webhook (no SSE)** |
| T5 — External ticketing (Zendesk, etc.) | Customer's existing tools | HTTPS + signed webhook / API key | API key + signature verification | Webhook inbound / outbound |

The **most-exterior tier (T4/T5) uses only mTLS + OAuth + signed webhooks**
— no token-only access, no bare API key for vendor-posted tickets. This
matches the design principle.

---

## Real-time delivery: Server-Sent Events

### Why SSE, not WebSockets

- SSE is one-way (server → client) — that's what ticketing needs. Updates flow down; commands flow up via normal HTTPS POST.
- Traverses corporate proxies more reliably than WebSockets (HTTP/1.1 keep-alive).
- Automatic reconnection + event ID resume built into the standard.
- Simpler implementation, fewer failure modes.
- Already works through the existing Nginx config without new directives.

### Implementation

- Redis pub/sub backs the fan-out layer
- Governance Hub publishes ticket events to Redis channels per tenant + per subscriber
- Ticketing Hub serves `/tickets/api/v1/stream?subscription=...` as an SSE endpoint
- Heartbeat every 15s keeps connections open through proxies with short idle timeouts
- Event resume via `Last-Event-ID` header handles dropped reconnects gracefully

### Scaling

- Single Redis instance handles 10,000+ concurrent SSE connections for this message-rate class (ticket events, not chat traffic)
- For fleet deployments, Redis is local to each Governance Hub; cross-instance events flow through the existing fleet-sync path, not Redis directly
- If Redis becomes a bottleneck in v4 multi-tenant scale-out, shift to Redis Streams or NATS JetStream

---

## OPA enforcement

Ticket actions are OPA-evaluated. New Rego policy bundle:
`configs/opa/policies/ticketing/base.rego`.

Policy surfaces:

- **Who can file which categories?** `ticket_scopes` in agent manifest / OIDC group / vendor scope / client role.
- **Which state transitions are valid for this actor?** Employee can move `open → in_progress`; client cannot; vendor can move vendor-scope tickets between `open` and `waiting` only.
- **Which tickets can this actor see?** Tenant isolation + visibility flags.
- **Escalation triggers.** High-priority tickets sitting in `open` for >N minutes auto-escalate (OPA obligation).
- **Cross-tenant barrier.** Hard deny any query that would surface tickets from a different tenant.
- **DLP-on-read.** Ticket body redaction varies by recipient. Role-aware redaction is an OPA obligation.

### Example Rego snippet

```rego
package insidellm.ticketing

# Agents can only file tickets in categories listed in their manifest
allow if {
    input.action == "file_ticket"
    input.actor.type == "agent"
    input.ticket.category in input.actor.manifest.ticket_scopes
}

# Vendors cannot file tickets in internal categories
deny[reason] if {
    input.action == "file_ticket"
    input.actor.type == "vendor"
    internal_categories := {"agent-flag", "internal-ops"}
    input.ticket.category in internal_categories
    reason := sprintf(
        "vendor '%s' may not file tickets in category '%s'",
        [input.actor.id, input.ticket.category]
    )
}

# Cross-tenant hard deny
deny[reason] if {
    input.action == "read_ticket"
    input.actor.tenant_id != input.ticket.tenant_id
    reason := "cross-tenant ticket access denied"
}
```

---

## DLP + PII / PHI handling

Every ticket body and comment is scanned by DLP on write. Configurable
per-category policy:

- **Block:** reject the ticket if PII/PHI detected (for categories where no PII should ever appear)
- **Redact:** replace PII with tokens before storage
- **Warn:** allow but flag for review

On read, DLP runs again with the reader's identity as context:

- An employee in the compliance team sees full ticket body
- A client filing a ticket about themselves sees their own PII (not redacted)
- A vendor sees redacted content
- An agent's view depends on its guardrail profile

This is defense-in-depth: even if DLP-on-write missed something, DLP-on-read
catches it before it leaves the boundary.

---

## Integration with existing ticketing systems

### Inbound (external → InsideLLM)

Configurable per tenant via `ticket_connectors`. Initial connectors:

- **Zendesk** — ticket.created webhook → POST to `/tickets/api/v1/inbound/zendesk`; signed payload verification
- **ServiceNow** — REST API polling (ServiceNow doesn't reliably push)
- **PagerDuty** — incident.trigger webhook for P1/P2 tickets
- **Jira** — webhook for specific issue types (customer choice)

Inbound tickets:
- Hash-chain audit entry on receipt
- Run through OPA for policy checks (tenant mapping, category allow)
- Store in `tickets` with `external_ref` pointing back to the source
- DLP scan as normal

### Outbound (InsideLLM → external)

- **PagerDuty / Slack / Teams / email** — OPA obligations fire notifications via existing alerting infrastructure
- **Zendesk / ServiceNow** — bidirectional sync: ticket creation in InsideLLM creates a mirror in the external system; state changes propagate; comments sync

### Why bidirectional vs. unidirectional

Most enterprises already have a system of record for tickets. InsideLLM's
value is **governance + multi-actor + agent-originated**, not replacing
the enterprise ticketing platform. Bidirectional sync means:

- Existing ticketing remains the operational workspace
- InsideLLM ensures every AI-governance-relevant event is captured
- Audit chain links both systems
- Customer can gradually migrate if they want, without forced cutover

---

## Hash-chain audit integration

Every `ticket_events` row has an `audit_chain_seq` pointer to the Governance
Hub's existing hash-chained audit. The audit chain itself stores a compact
summary (ticket ID, event type, actor, timestamp, content hash); the full
payload stays in `ticket_events` with the summary hash linking them.

This means:
- A customer auditor can walk the hash chain to verify ticket-lifecycle integrity
- Modifying a ticket_event row breaks the chain
- `/governance/api/v1/audit/verify` already supports this pattern

No new audit infrastructure required.

---

## Fleet sync + Parent-Organization aggregation

Per-tenant tickets stay on the tenant's instance. For Parent-Organization-
scale deployments, aggregate views surface through the same fleet-sync
channels used for Portfolio View:

- Each fleet node publishes a summary `ticket_metrics` record per sync cycle (counts by category, open/triage/closed, escalated, at-risk)
- Central Governance Hub aggregates for Portfolio dashboard
- Drill-down into a specific ticket requires either federated identity (the user at Parent Org level has access to the specific tenant) or explicit tenant admin permission
- **No cross-tenant ticket body visibility without explicit permission.** Aggregates only; no ticket content.

---

## Sequencing

### v3.3 (Q3 2026) — core ticketing

Scope:
- Ticketing Hub service (FastAPI)
- Five database tables + migrations
- Core CRUD API (T0-T3 proximity tiers)
- Employee + agent identity adapters
- SSE real-time delivery
- Internal OPA ticketing bundle (`tier_internal_ticketing`)
- Hash-chain audit integration
- Admin UI ticket list + detail pages

### v3.4 (Q4 2026) — external integrations + vendor tier

Scope:
- T4 vendor tier with mTLS + OAuth client credentials (depends on Zero-Trust-Design v3.4 workload identity work)
- Client tier (T3) with tenant-scoped JWT
- Inbound connectors: Zendesk, PagerDuty
- Outbound connectors: Slack, Teams, email, PagerDuty
- DLP-on-read with recipient-aware redaction
- Ticket-scope field in agent manifest schema v1.2

### v4 (Q1 2027) — cross-tenant + federation

Scope:
- Cross-tenant ticket aggregation at Parent-Org level
- Federated identity across portfolio (one employee identity visible across N tenants)
- ServiceNow + Jira connectors
- Workflow DSL for customer-authored ticket routing logic
- Per-tenant SLA tracking

---

## Risks

**Product scope creep**

- Risk: ticketing grows to replace Zendesk / ServiceNow. That's a different product with a different customer and a different sales motion.
- Mitigation: explicitly position as "governance-aware ticketing layer that integrates with your existing system," not "replacement." Bidirectional connectors are the primary story.

**Actor-model complexity**

- Risk: five actor classes × multiple protocols × OPA policies × DLP flavors = combinatorial test matrix
- Mitigation: ship T0-T2 only in v3.3. Add T3 in v3.4 alongside workload identity. T4 vendor tier waits for mTLS infra. Don't launch all five at once.

**Real-time performance under fleet load**

- Risk: Redis pub/sub for SSE has limits; cross-fleet event propagation could lag
- Mitigation: per-instance Redis; cross-fleet via existing fleet-sync (not Redis). Benchmark before v3.3 GA.

**Security / leakage**

- Risk: a misconfigured OPA bundle could leak ticket content across tenants
- Mitigation: cross-tenant deny is a hard-coded rule in the `tier_internal_ticketing` base bundle (not overridable by tenant customization). Test coverage.

**Dependency on Zero Trust work**

- Risk: v3.4 vendor ticketing tier depends on v3.3 Zero Trust mTLS infrastructure landing on schedule
- Mitigation: sequence vendor tier for v3.4 post Zero Trust GA; don't couple v3.3 ticketing to ZT work.

**Marketing confusion**

- Risk: customers confuse "InsideLLM ticketing" with "InsideLLM replacing ServiceNow"
- Mitigation: positioning language in docs + sales materials: "AI-governance-aware ticketing that plugs into your existing ticketing platform." See Discovery-Questions.html for sales-enablement framing.

---

## Open questions — decide before v3.3 kickoff

1. **Ship Ticketing Hub as a separate container or in-process with Governance Hub?** Recommendation: separate container; shared DB; aligns with single-responsibility-per-service posture. Confirm.
2. **SSE fan-out: Redis pub/sub or Redis Streams?** Pub/sub is simpler; Streams give durability. Start with pub/sub; revisit at v4 scale-out.
3. **Ticket body size limit?** Recommend 64 KB for plain text; attachments via existing DocForge surface. Confirm.
4. **Default OPA ticketing profile for new tenants?** Recommend `tier_internal_ticketing` as the starting point, with customer explicit opt-in for `tier_external_clients` and `tier_vendors`. Confirm.
5. **ServiceNow connector in v3.4 or v4?** ServiceNow is high-effort + high-value. Customer demand signal needed. Decide after demo feedback (2026-05-12).
6. **Cross-tenant visibility defaults at Parent-Org level?** Aggregate metrics yes; ticket body content never unless explicit grant. Confirm as hard-coded.

---

## What this document is not

Not a commitment to v3.3 scope — it's a design sketch intended to inform
the v3.3 planning conversation after the 2026-05-12 demo outcome is known.
Customer demand (especially from Parent Organization) will shape actual
prioritization. The Ticketing Hub could slip to v3.4 if Zero Trust or
other v3.3 scope consumes the quarter.

*Last updated 2026-04-22*
