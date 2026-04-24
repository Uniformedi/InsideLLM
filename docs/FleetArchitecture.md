# InsideLLM Fleet Architecture

**Status:** Tier 1 modularity in progress. Streams A (capability registry +
heartbeat) and B (topology API + Admin matrix) are shipped. Stream C (edge
router VM, keepalived VIP, OIDC department routing) is shipping in parallel.
Streams D and E complete the docs and admin-surface work.

This document describes the target topology, the current state, the
protocols in place, and the upgrade path from a single-VM deployment to
a multi-node fleet. It is deliberately factual about what is committed
versus what is planned.

---

## 1. The three tiers of "Lego-ness"

InsideLLM has always shipped as a single Hyper-V VM running every
service in one Docker Compose stack. That is the right shape for
proof-of-concept and for teams smaller than ~50 users. As customers
scale up, some services (LiteLLM, Open WebUI, Ollama) grow hot while
others (Governance Hub, Grafana, Loki) stay small — so it makes sense
to split them across VMs. The fleet work gets the platform to modular
without forcing every operator into that complexity.

```
Tier 1 — Role switch                    Tier 2 — Declarative fleet
───────────────────                     ──────────────────────────
Same terraform/ templates.              fleet.yaml describes the
vm_role = "..." toggles which           whole topology. A control
services start.                         plane renders per-role
                                        tfvars and applies.
Single operator, many VMs.
                                        One terraform apply targets
                                        N VMs at once. VIP failover
                                        is part of the plan.

Tier 3 — Self-assembly
──────────────────────
Nodes boot, discover the primary
via mDNS / registration token,
request their role, and pull
the correct config by themselves.

Operator owns intent
("I want 2 gateways, 1 edge"),
not per-node tfvars.
```

The current work lands Tier 1. Tier 2 is plausible within 2026-Q3. Tier
3 is research. The important point: each tier composes on the previous
one — the Stream A/B capability registry and heartbeat is also the
foundation for Tiers 2 and 3, and the role switch introduced in Tier 1
becomes the declarative field in Tier 2.

---

## 2. Roles

A role is a single string (`vm_role` in `terraform.tfvars`) that
determines which containers start on a given VM. The same codebase,
templates, and cloud-init ship to every role; the role picks which
subset runs.

| Role | Runs | Purpose |
|---|---|---|
| `""` (empty) | Everything | Standalone VM — the historical default. |
| `primary` | Gov-Hub, Grafana, Loki, Postgres, Redis, LiteLLM, Open WebUI | First node of a fleet. Hosts the central DB, the governance console, and telemetry collection. |
| `gateway` | LiteLLM, Open WebUI, local Redis | Horizontally-scaled API gateway + chat UI. Points Promtail / sync at the primary. |
| `workstation` | Open WebUI, Ollama | Thick-client node for data-sensitive teams. Local Ollama for on-device inference. API calls still flow through primary's LiteLLM. |
| `voice` | Whisper, Piper, small LLM | Voice-in / voice-out endpoint. Optional. Bridges to LiteLLM for transcript-based chat. |
| `edge` | Nginx + Lua, keepalived | Public-facing reverse proxy with TLS termination and OIDC-based department routing. Owns the fleet VIP. |
| `storage` | MinIO / SMB gateway | Document and model store. Optional. Used when a team wants local-only RAG ingest. |

"Role" is not a hard schema — a single VM can technically answer for
multiple. The conventions above are what the generated `docker-compose`
ships.

```
                              ┌──────────────────┐
                              │   edge VM (keepalived VIP)        │
                              │   Nginx + Lua + oidc-auth         │
                              └──┬──────────────┬──────────────┬──┘
                                 │              │              │
                 ┌───────────────┘              │              └────────────────┐
                 ▼                              ▼                               ▼
   ┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────────┐
   │  primary                 │   │  gateway-eng             │   │  gateway-legal           │
   │  Gov-Hub, Grafana, Loki  │   │  LiteLLM + Open WebUI    │   │  LiteLLM + Open WebUI    │
   │  Postgres, LiteLLM, OWUI │   │  (points Promtail →      │   │  (points Promtail →      │
   │                          │   │   primary's Loki)        │   │   primary's Loki)        │
   └──────────────────────────┘   └──────────────────────────┘   └──────────────────────────┘
                                              │
                                              ▼
                              ┌──────────────────────────┐
                              │  workstation-secure      │
                              │  OWUI + local Ollama     │
                              └──────────────────────────┘
```

### When to pick which role

| Scenario | Recommendation |
|---|---|
| POC, small team, first install | Standalone (`vm_role = ""`). Don't over-engineer. |
| Two departments, shared governance | `primary` + one `gateway` per department. Optional `edge` in front. |
| Regulated industry with mixed classifications | `primary` + department `gateway`s + `edge` enforcing OIDC claim routing. |
| High-availability gateway | Multiple `gateway` VMs behind the `edge` VIP. |
| Air-gapped lab | Single `workstation` with local Ollama, periodic sync to a `primary` elsewhere. |
| Voice-first use case | Add `voice` alongside the other roles. |

---

## 3. Capability registry

Each Governance Hub publishes its own capabilities on startup and every
60 seconds thereafter. Peers read the aggregate via
`GET /api/v1/fleet/capabilities` (filterable) and
`GET /api/v1/fleet/topology` (pre-aggregated view).

### Schema

Stored in `governance_fleet_capabilities`:

```
instance_id        VARCHAR(255)  NOT NULL    — unique fleet member id
capability         VARCHAR(100)  NOT NULL    — "litellm" | "open-webui" | ...
endpoint           VARCHAR(500)  NOT NULL    — "http://insidellm-01:4000"
role               VARCHAR(50)   DEFAULT ''  — the vm_role
status             VARCHAR(20)   DEFAULT 'live'  — live | degraded | down
capability_metadata JSONB        DEFAULT '{}' — free-form per-capability extras
updated_at         TIMESTAMPTZ   ON UPDATE now()

UNIQUE (instance_id, capability)
```

### Heartbeat protocol

```
t=0s   Gov-Hub boots.
       capability_service.publish_all() writes one row per local capability.
       (status='live', role from settings, updated_at=now)

t=60s  capability_service.publish_all() again, UPSERT on (instance_id, capability).
       updated_at advances. Missing rows re-created.

t=∞    Any reader can call GET /api/v1/fleet/capabilities.
       A row with updated_at older than 180s is considered stale.
```

180s = three missed heartbeats. That's tight enough to notice real
outages and loose enough to tolerate slow container restarts. The
"stale" classification happens at read time — there is no background
reaper.

### Topology endpoint (Stream B)

`GET /api/v1/fleet/topology` collapses the capability table into:

```json
{
  "primary_id": "insidellm-primary",
  "instances": [
    {
      "instance_id": "insidellm-primary",
      "role": "primary",
      "capabilities": [
        {"name": "governance-hub", "endpoint": "...", "status": "live",
         "metadata": {}, "updated_at": "..."}
      ],
      "last_seen": "2026-04-16T21:10:00Z",
      "health": "healthy"
    }
  ],
  "capabilities_index": {
    "governance-hub": ["insidellm-primary"],
    "litellm":        ["insidellm-primary", "insidellm-gateway"]
  }
}
```

`primary_id` resolution: first instance with `role=primary`; if none,
first instance that provides `governance-hub`; else `null`.

Health is healthy if the instance's newest heartbeat is < 180s old,
stale otherwise. The client (Admin Hub's Fleet tab) renders the
capabilities as a matrix: columns are canonical capabilities, rows are
instances, cells are green (live), amber (stale), or grey (not
present).

---

## 4. Department routing

The purpose of the edge tier is to map a single public-facing URL and
cert into the right backend `gateway` based on the authenticated
user's department. The mechanism is deliberately simple.

### OIDC claim → backend

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser                                                         │
│  GET https://ai.corp.example.com/                                │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  edge VM — Nginx (TLS) + lua-resty-openidc                       │
│                                                                  │
│  1. Enforce OIDC login (Azure AD / Okta)                         │
│  2. Read department claim (e.g. id_token.department or           │
│     extension_department)                                        │
│  3. local department_map = { "engineering" = "gateway-eng",      │
│                              "legal"       = "gateway-legal",    │
│                              "finance"     = "gateway-finance" } │
│  4. proxy_pass http://<mapped backend>/                          │
│  5. Forward JWT as X-Forwarded-User + X-Forwarded-Groups         │
└────────────────────────────┬─────────────────────────────────────┘
                             │
            ┌────────────────┼───────────────────┐
            ▼                ▼                   ▼
   gateway-eng         gateway-legal       gateway-finance
   (LiteLLM+OWUI)      (LiteLLM+OWUI)      (LiteLLM+OWUI)
```

The department map is itself driven by terraform variables
(`department`, `fallback_department`) — each edge VM knows which
backend it routes to and which sibling to fail over to. The OIDC
integration is shared with the rest of the platform (same client_id,
tenant, group claim field as the in-VM services).

### Backend trust

Each `gateway` backend trusts the edge only. It does this by:

1. Binding LiteLLM's public-facing listener to the VLAN IP (not
   0.0.0.0 externally).
2. Checking `X-Forwarded-For` against an allowlist of edge VIPs.
3. Using the forwarded JWT (re-verified by LiteLLM using the same
   OIDC config) to populate `user_api_key_user_id` / team mapping.

If the edge is bypassed (direct hit to the gateway VLAN IP), the
request falls back to LiteLLM's standard virtual-key auth. That is
the break-glass path — see §6.

---

## 5. Upgrade path: standalone → fleet

The transition should be low-surprise. Here is the expected sequence
for an operator who starts with one VM and wants to split off a
department gateway.

### Phase 0 — standalone
```
vm_role            = ""
fleet_primary_host = ""
# Everything on one VM. No central DB.
```

### Phase 1 — name it the primary
```
vm_role            = "primary"
fleet_primary_host = "10.0.1.10"   # its own IP, for clarity
# Nothing else changes. The role string is recorded in capabilities.
```

At this point the standalone VM is identical in behavior, but it has
declared itself `primary`. It starts publishing capabilities on boot
(this behavior is enabled in all roles, including standalone).

### Phase 2 — add a gateway
```
# On a fresh VM:
vm_role            = "gateway"
fleet_primary_host = "10.0.1.10"
department         = "engineering"
```

The gateway's cloud-init reads `fleet_primary_host` and configures:

- Promtail to ship logs to `http://<primary>:3100/loki/api/v1/push`
- Sync job to POST telemetry to primary's Gov-Hub
- LiteLLM to use the primary's Redis for rate-limit counters
  (optional — can use local Redis for independence)

The primary's Admin Hub Fleet tab now shows two rows in the topology
matrix.

### Phase 3 — add the edge
```
# On a fresh VM:
vm_role            = "edge"
fleet_virtual_ip   = "10.0.1.100"
edge_tls_source    = "letsencrypt"
edge_domain        = "ai.corp.example.com"
department         = "engineering"            # default backend
fallback_department = "finance"               # on eng failure
```

The edge boots, acquires the VIP via keepalived, terminates TLS, and
starts routing by OIDC claim. The primary and gateway VMs learn about
it through the capability publish (the edge publishes itself too,
capability = `edge-router`).

### Phase 4 — horizontal scale
More gateways join, each with their own `department` label. The
fleet.yaml of Tier 2 is the natural next step: instead of editing N
tfvars files, the operator writes one intent file and the control
plane reconciles.

---

## 6. Failure modes & break-glass

The platform is designed so that single-component outages degrade
gracefully rather than taking the whole fleet offline.

### 6.1 Primary outage

Symptoms: Gov-Hub unreachable. Grafana and Loki down. Fleet tab can't
load. Central sync stops.

What keeps working:

- Local LiteLLM gateways on each `gateway` VM still serve requests.
  Each gateway's rate-limit counters are either in local Redis or
  cached with a TTL in the primary's Redis — a 60-minute primary
  outage won't kill gateway throughput.
- DLP and Humility guardrails run in-process in LiteLLM. They do not
  need the Gov-Hub.
- OPA policies are cached in each LiteLLM container. Policy updates
  pause, but enforcement continues with the last known good policy
  bundle.

What stops:

- New governance changes (proposals, approvals, sync).
- Aggregate telemetry. Local audit logs still write to the local DB
  and will back-fill when the primary returns.
- Fleet-wide dashboards.

Recovery: restore the primary VM from its Hyper-V checkpoint or the
backed-up Postgres volume. Everything else stitches itself back
together on next heartbeat.

### 6.2 Edge outage

Symptoms: `ai.corp.example.com` returns 502 / connection refused.

Mitigations:

- keepalived moves the VIP to a standby edge VM (Tier 2 feature).
  Until then, a DNS failover record can be swung manually.
- Direct bearer auth to the gateway's VLAN IP remains available as a
  break-glass. Operators can document this in the runbook:
  `curl -H "Authorization: Bearer $VIRTUAL_KEY" https://10.0.1.21/v1/...`
- Open WebUI on each gateway is still reachable over VLAN for users
  who know the internal address.

### 6.3 Gateway outage

The edge failover map (`fallback_department`) catches this: requests
for the outaged department route to the sibling gateway. Users see a
small banner noting they are on the fallback; audit logs mark the
request with `fallback=true`.

If `fallback_department` is empty, the edge returns 503 immediately —
a deliberate fail-fast so the incident is visible.

### 6.4 Edge bypass (abuse path)

Because each gateway's LiteLLM is listening on the VLAN, a motivated
insider who has VLAN access could skip the edge (and therefore the
department routing) and talk to any gateway directly with a valid
virtual key. Mitigations:

- Per-team virtual keys. An engineering user's key is only provisioned
  on `gateway-eng`, not on `gateway-legal`, so cross-department bypass
  fails auth.
- Network ACLs: gateways can be configured to reject connections whose
  source IP is not the edge VIP. This is off by default because it
  breaks the break-glass path in §6.2; operators who care about abuse
  more than availability enable it.
- OPA policy: the `X-Forwarded-User` / `X-Forwarded-Groups` claims are
  re-verified against the gateway's own OIDC config. If the forwarded
  claims don't match the virtual-key owner, the request is denied.

---

## 7. Terraform variables for fleet deployment

The nine new variables introduced by Stream A (see
`docs/DefaultDeployment.md` → **Fleet / Edge**):

```hcl
vm_role              = "primary"                # primary/gateway/workstation/voice/edge/storage/""
fleet_primary_host   = "10.0.1.10"              # for non-primary roles
fleet_virtual_ip     = "10.0.1.100"             # edge only
edge_tls_source      = "letsencrypt"            # self-signed/letsencrypt/custom
edge_tls_cert_path   = ""                       # custom only
edge_tls_key_path    = ""                       # custom only
edge_domain          = "ai.corp.example.com"    # edge FQDN
department           = "engineering"            # routing label
fallback_department  = "finance"                # edge failover sibling
```

Empty `vm_role` preserves historical single-VM behavior. No existing
deployment needs any variable changes to keep working.

---

## 8. Relationship to existing features

### Governance Hub sync

Pre-fleet, sync was "local DB → central DB, one direction". With
multiple instances, the same sync machinery aggregates per-instance
telemetry. The capability registry is orthogonal to sync — it's a
faster, lighter channel for "who provides what right now" rather than
"what did this instance do yesterday".

### Humility / OPA

Policies continue to be bundled into each LiteLLM container via the
`humility-guardrail` pip package. There is no fleet-wide OPA; each
node enforces locally. This is intentional — fail-closed is stronger
than fail-open, and it means that a primary outage (§6.1) does not
weaken alignment enforcement.

### DLP

DLP runs at the LiteLLM gateway on each `gateway` VM. Every gateway
configures the same DLP valves from the same tfvars. A department that
wants stricter DLP can run its own gateway with a tightened
`dlp_block_*` set.

### Sidecar

The browser sidecar (InsideLLM Assist) talks to the edge VIP (or
direct gateway in a pre-edge deployment). The sidecar has no awareness
of fleet topology — its config is "base URL + virtual key", the same
as today.

---

## 9. What is shipped vs. what is planned

Checked in as of this document (Streams A + B + this Stream E):

- [x] `FleetCapability` model, table, migration.
- [x] `capability_service.publish_all()` + 60s heartbeat loop.
- [x] `GET /api/v1/fleet/capabilities` (filterable).
- [x] `GET /api/v1/fleet/topology` (aggregated view).
- [x] Admin Hub Fleet tab → Topology matrix with 15s refresh.
- [x] Nine new terraform variables (Stream A).

Shipping in parallel (Stream C):

- [ ] Edge VM cloud-init template.
- [ ] Lua OIDC department map.
- [ ] keepalived VIP role.

Planned (Tier 2+):

- [ ] `fleet.yaml` declarative mode.
- [ ] Control-plane multi-apply.
- [ ] Self-assembly via mDNS/registration tokens.
- [ ] Automatic failover map updates when a gateway flaps.

---

## 10. References

- `configs/governance-hub/src/db/models.py` — `FleetCapability` model.
- `configs/governance-hub/src/services/capability_service.py` —
  publish + heartbeat.
- `configs/governance-hub/src/routers/fleet.py` — capabilities + topology
  endpoints.
- `html/admin.html` — Fleet tab, topology matrix.
- `docs/DefaultDeployment.md` — Fleet / Edge variable reference.
- `docs/sidecar.md` — how the browser sidecar fits into the gateway
  trust chain.

For Humility alignment context (which every role inherits unchanged),
see the canonical [`humility-guardrail`](https://github.com/uniformedi/humility-guardrail)
package.
