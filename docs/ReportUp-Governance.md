# InsideLLM — ReportUp Governance Data Sharing

**ReportUp** is an opt-in feature that lets a tenant organization share its
governance data — audit chain, telemetry, agent inventory, identity groups,
change proposals, and policy summaries — with a named parent company.

Data is packed into a tamper-evident, cryptographically signed envelope and
POSTed to the parent's endpoint on demand or on a schedule. The parent can
independently verify every envelope and detect gaps in the chain.

---

## When to use ReportUp

| Scenario | Use it? |
|---|---|
| Parent company requires audit visibility into subsidiary AI usage | Yes |
| Compliance officer needs proof of policy chain-of-custody | Yes |
| Single-tenant deployment with no parent reporting requirement | No (leave disabled) |
| Temporary ad-hoc data export | Use Preview + copy JSON |

---

## Concepts

### Envelope

Each run produces one **envelope** — a JSON document containing:

| Field | Description |
|---|---|
| `schema_version` | Currently `"1.0"` — lets the parent detect format changes |
| `tenant_id` / `tenant_name` | Sender identity |
| `parent_name` | Display name of the receiving parent |
| `generated_at` | ISO 8601 UTC timestamp |
| `sequence_from` / `sequence_to` | Audit-chain sequence range covered |
| `previous_envelope_hash` | SHA-256 of the prior envelope — chain link |
| `envelope_hash` | SHA-256 of this envelope's canonical JSON (excluding itself) |
| `hmac_signature` | HMAC-SHA256 of `envelope_hash` with the shared secret |
| `audit_chain` | Array of audit events in range |
| `telemetry` | Usage metrics (if share_telemetry enabled) |
| `agents` | Active agent manifests (if share_agents enabled) |
| `identity_users` / `identity_groups` | User/group metadata (if share_identity enabled) |
| `change_proposals` | Proposal history (if share_changes enabled) |

### Chain-of-custody

`previous_envelope_hash` links each envelope to the one before it, forming
a hash chain. A receiver that stores every envelope can detect:

- **Gaps** — a missing envelope (sequence jump with no `previous_envelope_hash` match)
- **Tampering** — any payload modification breaks `envelope_hash`
- **Replay / injection** — an inserted envelope breaks the chain link

### Watermark

`last_shipped_sequence` tracks the highest audit-chain sequence number
successfully acknowledged by the parent. Each run picks up from there. The
watermark **only advances after a parent ACK** — a failed send is retried
next run without data loss.

### Attestation gate

Enabling ReportUp or changing the parent endpoint requires a compliance
officer to record an explicit attestation (name + free-text statement) before
the save will succeed. This creates an auditable consent record and prevents
accidental activation.

---

## Setup (first time)

### 1. Set the HMAC shared secret

Generate a 48-character-minimum secret and share it with the parent out-of-band:

```bash
openssl rand -hex 32   # produces 64 hex chars — use this
```

In the Governance Hub UI navigate to **ReportUp → HMAC Secret** and paste it,
or POST to the API:

```bash
curl -sk -X POST https://<host>/governance/api/v1/reportup/hmac-secret \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"secret": "<your-64-char-hex>"}'
```

Alternatively, set `REPORTUP_HMAC_SECRET` in the environment before startup
(the API value takes precedence if set).

### 2. Record an attestation

Before you can enable the feature, a compliance officer must attest:

```bash
curl -sk -X POST https://<host>/governance/api/v1/reportup/attestation \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "attested_by": "jane.doe@example.com",
    "attestation_text": "I authorize sharing governance data with Clarion Capital Partners per our data sharing agreement dated 2026-04-01."
  }'
```

The response includes a `snapshot_sha` that is tied to the config at the time
of attestation. This SHA must match the current config snapshot when you
subsequently enable ReportUp.

### 3. Configure and enable

```bash
curl -sk -X PUT https://<host>/governance/api/v1/reportup/config \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "parent_name": "Clarion Capital Partners",
    "parent_endpoint": "https://hub.clarion.example.com/insidellm/ingest",
    "share_audit_chain": true,
    "share_telemetry": true,
    "share_agents": true,
    "share_identity": false,
    "share_policies": false,
    "share_changes": true,
    "schedule_cron": "0 2 * * *",
    "max_records_per_run": 5000
  }'
```

If the attestation snapshot matches the current config, you receive `200 OK`.
If it doesn't match (config drifted since attestation), you receive `409` with
`"attestation required"` — re-attest before saving.

---

## UI walkthrough

Navigate to **Governance Hub → ReportUp** (`/governance/reportup`).

| Section | What it does |
|---|---|
| **Status banner** | Green = enabled + last run OK, yellow = disabled, red = last run failed |
| **Configuration** | Edit parent name/endpoint and category toggles. Save is blocked until the attestation hash matches. |
| **Attestation** | Record compliance-officer consent. Shows attested-by and text of most recent attestation. |
| **Preview** | Dry-run: builds the envelope but does not send and does not advance the watermark. Shows full JSON for review. |
| **Send Now** | Immediately triggers a run (same as the scheduler, but on demand). |
| **Recent runs** | Last 50 sync log entries: sequence range, record counts, envelope hash, parent HTTP status. |

---

## API reference

All endpoints require a valid Bearer token. Admin-scope endpoints (`PUT config`,
`POST hmac-secret`, `POST attestation`, `POST send-now`) require the `admin` role.
View-scope endpoints (`GET config`, `GET attestations`, `GET log`, `POST preview`)
require only the `view` role.

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET` | `/api/v1/reportup/config` | view | Current configuration |
| `PUT` | `/api/v1/reportup/config` | admin | Update config (attestation-gated) |
| `POST` | `/api/v1/reportup/hmac-secret` | admin | Set or rotate the shared secret |
| `POST` | `/api/v1/reportup/attestation` | admin | Record a compliance attestation |
| `GET` | `/api/v1/reportup/attestations` | view | List all attestations |
| `POST` | `/api/v1/reportup/preview` | view | Dry-run — returns envelope without sending |
| `POST` | `/api/v1/reportup/send-now` | admin | Trigger an immediate run |
| `GET` | `/api/v1/reportup/log` | view | Recent run log (default 50 entries) |
| `GET` | `/reportup` | view | HTML UI |

---

## Parent-side receiver

The parent endpoint receives a `POST` with:

**Headers**

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `X-Insidellm-Tenant` | `<tenant_id>` |
| `X-Insidellm-Envelope-Hash` | SHA-256 hex of the envelope |
| `X-Insidellm-Signature` | HMAC-SHA256 of the envelope hash |
| `X-Insidellm-Schema-Version` | `1.0` |

**Body:** the full `ReportUpEnvelope` JSON.

### Verification (pseudocode)

```python
import hashlib, hmac, json

def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",",":"),
                      ensure_ascii=False).encode("utf-8")

def verify(envelope: dict, secret: str, expected_previous_hash: str | None) -> tuple[bool, str | None]:
    # 1. Recompute hash — must exclude the hash and signature fields themselves
    pruned = {k: v for k, v in envelope.items()
              if k not in ("envelope_hash", "hmac_signature")}
    expected_hash = hashlib.sha256(canonical_json(pruned)).hexdigest()
    if envelope.get("envelope_hash") != expected_hash:
        return False, "envelope_hash mismatch — payload tampered"

    # 2. Verify HMAC signature
    sig = hmac.new(secret.encode(), expected_hash.encode(),
                   hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, envelope.get("hmac_signature", "")):
        return False, "hmac_signature mismatch — wrong secret or tampered"

    # 3. Verify chain link (if expecting a specific predecessor)
    if expected_previous_hash is not None:
        if envelope.get("previous_envelope_hash") != expected_previous_hash:
            return False, "previous_envelope_hash mismatch — chain broken"

    return True, None
```

This same logic is also available in the `reportup_service` module for
internal use:

```python
from src.services.reportup_service import verify_envelope
ok, err = verify_envelope(envelope, secret=secret, expected_previous_hash=prev)
```

### ACK response

Return `200 OK` with any JSON body to acknowledge the envelope. Any non-2xx
response is treated as a rejection — the watermark does not advance and the
run is logged as `parent_rejected`. ReportUp retries on the next scheduled run.

---

## Scheduled runs

Set `schedule_cron` to a standard cron expression (UTC). The governance-hub
scheduler invokes `run_once` at each scheduled time using the system actor.
To disable scheduled runs while keeping the feature enabled, clear the
`schedule_cron` field (empty string).

Example values:

| Expression | Meaning |
|---|---|
| `0 2 * * *` | Daily at 02:00 UTC |
| `0 */6 * * *` | Every 6 hours |
| `0 8 * * 1` | Every Monday at 08:00 UTC |
| _(empty)_ | Manual only |

---

## Security notes

- The HMAC secret is stored in `governance_settings_overrides` (encrypted at
  rest by PostgreSQL TDE if enabled) and never returned via the API — only
  the last 4 characters are shown for identification.
- All ReportUp actions — config changes, attestations, secret rotations,
  runs — are written to the hash-chained audit trail.
- Disabling ReportUp does not delete any data. Re-enabling it (with a new
  attestation) resumes from the last successful watermark.
- `max_records_per_run` (default 5 000) caps each shipment. On the first run
  after a long period of inactivity the backlog is drained in multiple
  successive runs, not one giant POST.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `409 Conflict` on config save | No current attestation | POST to `/attestation` first |
| `409 Conflict` after editing config | Config drifted since last attestation | Re-attest with new snapshot |
| Parent returns non-2xx | Wrong endpoint, firewall, or parent not ready | Check `parent_endpoint`; review log for HTTP status |
| `hmac_signature mismatch` in log | Shared secret out of sync | Re-share secret via `/hmac-secret` on both sides |
| Sequence gap in parent log | A run failed and was retried | Normal — watermark re-sends the gap automatically |
| Envelope hash mismatch on parent | Payload was modified in transit | TLS issue or MITM — investigate network path |
