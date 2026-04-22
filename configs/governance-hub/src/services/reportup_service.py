"""ReportUp — pack + send + verify governance data up to a named parent org.

Workflow
--------
1. Caller invokes `run_once(db)` (manual trigger or scheduler).
2. We read the single-row ReportUpConfig; bail if disabled.
3. We collect the enabled categories since `last_shipped_sequence`:
   audit chain, telemetry, agents, identity, policies, change proposals.
4. We build a canonical ReportUpEnvelope, compute `envelope_hash` (SHA-256
   over canonicalized JSON), and chain it to `previous_envelope_hash` (the
   last successful run's hash — tamper-evidence across runs).
5. We HMAC-SHA256 the envelope hash with the shared secret from
   `settings_overrides.reportup_hmac_secret`.
6. We POST to `parent_endpoint` with headers:
     X-Insidellm-Tenant, X-Insidellm-Envelope-Hash, X-Insidellm-Signature,
     X-Insidellm-Schema-Version
7. Parent's ACK is recorded. Chain-of-custody watermark advances only on
   successful ACK.

Safety
------
* Dry-run (`pack_envelope(db, dry_run=True)`) builds everything without
  sending and without advancing the watermark. UI uses this for preview.
* The watermark (`last_shipped_sequence` + `last_envelope_hash`) only
  advances after parent ACK — a failed send is re-tried next run.
* Max-records-per-run caps each shipment so an initial backfill on a
  long-running instance doesn't produce a 100 MB POST.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ReportUpConfig, ReportUpLog
from ..schemas.reportup import REPORTUP_SCHEMA_VERSION, ReportUpEnvelope

logger = logging.getLogger("governance-hub.reportup")

_SECRET_OVERRIDE_KEY = "reportup_hmac_secret"
_DEFAULT_SCHEMA_VERSION = REPORTUP_SCHEMA_VERSION
_HTTP_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Structured outcome of a ReportUp run."""
    ok: bool
    status: str                              # success | error | disabled | parent_rejected
    envelope_hash: str | None = None
    previous_envelope_hash: str | None = None
    sequence_from: int | None = None
    sequence_to: int | None = None
    records_by_category: dict[str, int] = field(default_factory=dict)
    parent_ack_status: str | None = None
    parent_http_status: int | None = None
    parent_ack_payload: dict[str, Any] | None = None
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "envelope_hash": self.envelope_hash,
            "previous_envelope_hash": self.previous_envelope_hash,
            "sequence_from": self.sequence_from,
            "sequence_to": self.sequence_to,
            "records_by_category": self.records_by_category,
            "parent_ack_status": self.parent_ack_status,
            "parent_http_status": self.parent_http_status,
            "parent_ack_payload": self.parent_ack_payload,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Canonical hashing + HMAC — must match parent-side verifier bit-exactly
# ---------------------------------------------------------------------------


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON encoding: sorted keys, no whitespace, UTF-8.
    Parent's verifier MUST use the same encoding or the hash mismatches."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_envelope_hash(envelope_dict: dict[str, Any]) -> str:
    """SHA-256 over the canonicalized envelope with `envelope_hash` +
    `hmac_signature` excluded (they're computed from this result)."""
    pruned = {k: v for k, v in envelope_dict.items() if k not in ("envelope_hash", "hmac_signature")}
    return hashlib.sha256(canonical_json(pruned)).hexdigest()


def hmac_sign(secret: str, envelope_hash: str) -> str:
    """HMAC-SHA256 over the envelope hash, keyed by the shared secret.
    Hex output; matches what receivers recompute to verify."""
    return hmac.new(secret.encode("utf-8"), envelope_hash.encode("utf-8"), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


async def get_config(db: AsyncSession) -> ReportUpConfig:
    """Fetch or create the single-row config. Defaults to disabled."""
    stmt = select(ReportUpConfig).limit(1)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = ReportUpConfig(
            enabled=False,
            share_audit_chain=True,
            share_telemetry=True,
            schedule_cron="0 2 * * *",
            max_records_per_run=10000,
            last_shipped_sequence=0,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _get_hmac_secret(db: AsyncSession) -> str | None:
    """Read the HMAC secret from settings_overrides. Callers that need
    to SET it use update_hmac_secret below."""
    env = os.environ.get("REPORTUP_HMAC_SECRET", "")
    if env:
        return env
    try:
        row = (await db.execute(
            text("SELECT value FROM governance_settings_overrides WHERE key = :k"),
            {"k": _SECRET_OVERRIDE_KEY},
        )).first()
        if row:
            return row[0]
    except Exception:
        pass
    return None


async def update_hmac_secret(db: AsyncSession, secret: str, actor: str) -> None:
    """Write/rotate the HMAC secret. Uses UPSERT against settings_overrides
    so the secret never rides on the normal ReportUpConfig row — that one
    is safe to expose via GET /config (nothing sensitive on it)."""
    await db.execute(
        text("""
            INSERT INTO governance_settings_overrides (key, value, updated_by)
            VALUES (:k, :v, :actor)
            ON CONFLICT (key) DO UPDATE SET
              value = EXCLUDED.value,
              updated_by = EXCLUDED.updated_by,
              updated_at = CURRENT_TIMESTAMP
        """),
        {"k": _SECRET_OVERRIDE_KEY, "v": secret, "actor": actor},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------


async def pack_envelope(
    db: AsyncSession,
    *,
    config: ReportUpConfig | None = None,
    dry_run: bool = False,
) -> tuple[ReportUpEnvelope, dict[str, int]]:
    """Build the envelope for the next run. Returns (envelope, counts).

    The envelope's `envelope_hash` is populated but `hmac_signature` is
    NOT — the caller adds that after reading the secret. Separating this
    keeps `pack_envelope` pure/secretless so `/preview` can show the
    envelope without needing the secret.
    """
    cfg = config or await get_config(db)

    from ..config import settings

    tenant_id = settings.instance_id or "unknown"
    tenant_name = settings.instance_name or tenant_id
    parent_name = cfg.parent_name or ""
    seq_from = int(cfg.last_shipped_sequence or 0) + 1
    max_rec = int(cfg.max_records_per_run or 10000)

    counts = {
        "audit_chain": 0,
        "telemetry": 0,
        "agents": 0,
        "identity_users": 0,
        "identity_groups": 0,
        "change_proposals": 0,
    }

    audit_chain: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    identity_users: list[dict[str, Any]] = []
    identity_groups: list[dict[str, Any]] = []
    change_proposals: list[dict[str, Any]] = []

    seq_to = seq_from - 1

    if cfg.share_audit_chain:
        rows = (await db.execute(
            text(
                "SELECT sequence, event_type, event_id, payload_hash, "
                "previous_hash, chain_hash, created_at "
                "FROM governance_audit_chain "
                "WHERE sequence >= :from_seq "
                "ORDER BY sequence ASC LIMIT :lim"
            ),
            {"from_seq": seq_from, "lim": max_rec},
        )).mappings().all()
        for r in rows:
            audit_chain.append({
                "sequence": r["sequence"],
                "event_type": r["event_type"],
                "event_id": r["event_id"],
                "payload_hash": r["payload_hash"],
                "previous_hash": r["previous_hash"],
                "chain_hash": r["chain_hash"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })
            if r["sequence"] > seq_to:
                seq_to = r["sequence"]
        counts["audit_chain"] = len(audit_chain)

    if cfg.share_telemetry:
        # Last 30 telemetry rows for THIS instance — cheap and bounded.
        rows = (await db.execute(
            text(
                "SELECT period_start, period_end, total_requests, total_spend, "
                "unique_users, dlp_blocks, error_count, compliance_score, synced_at "
                "FROM governance_telemetry ORDER BY synced_at DESC LIMIT 30"
            ),
        )).mappings().all()
        for r in rows:
            telemetry.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()})
        counts["telemetry"] = len(telemetry)

    if cfg.share_agents:
        rows = (await db.execute(
            text(
                "SELECT agent_id, tenant_id, name, team, guardrail_profile, "
                "visibility_scope, status, version, manifest_hash, runtime_sync_state, "
                "created_at, updated_at FROM governance_agents"
            ),
        )).mappings().all()
        for r in rows:
            agents.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()})
        counts["agents"] = len(agents)

    if cfg.share_identity:
        # identity tables created by Phase-2 Keycloak sync — may not exist.
        try:
            rows = (await db.execute(text(
                "SELECT keycloak_user_id, realm_name, username, email, "
                "enabled, groups_csv, last_synced_at FROM governance_identity_users "
                "LIMIT :lim"
            ), {"lim": max_rec})).mappings().all()
            identity_users = [
                {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
                for r in rows
            ]
            counts["identity_users"] = len(identity_users)
        except Exception as e:
            logger.debug(f"identity_users share skipped: {e}")
        try:
            rows = (await db.execute(text(
                "SELECT keycloak_group_id, realm_name, name, path, "
                "realm_roles_csv, last_synced_at FROM governance_identity_groups "
                "LIMIT :lim"
            ), {"lim": max_rec})).mappings().all()
            identity_groups = [
                {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
                for r in rows
            ]
            counts["identity_groups"] = len(identity_groups)
        except Exception as e:
            logger.debug(f"identity_groups share skipped: {e}")

    if cfg.share_change_proposals:
        rows = (await db.execute(
            text(
                "SELECT id, title, category, status, proposed_by, proposed_at, "
                "reviewed_by, reviewed_at FROM governance_changes "
                "ORDER BY proposed_at DESC LIMIT :lim"
            ),
            {"lim": max_rec},
        )).mappings().all()
        for r in rows:
            change_proposals.append(
                {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
            )
        counts["change_proposals"] = len(change_proposals)

    if seq_to < seq_from:
        # No audit_chain rows — still let the envelope ship (telemetry etc).
        seq_to = seq_from - 1

    envelope = ReportUpEnvelope(
        schema_version=_DEFAULT_SCHEMA_VERSION,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        parent_name=parent_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sequence_from=seq_from,
        sequence_to=seq_to,
        previous_envelope_hash=cfg.last_envelope_hash,
        audit_chain=audit_chain,
        telemetry=telemetry,
        agents=agents,
        identity_users=identity_users,
        identity_groups=identity_groups,
        change_proposals=change_proposals,
    )

    # Compute hash over the payload (excluding envelope_hash + hmac_signature).
    envelope_dict = envelope.model_dump(mode="json")
    envelope.envelope_hash = compute_envelope_hash(envelope_dict)
    return envelope, counts


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


async def run_once(
    db: AsyncSession,
    *,
    actor: str = "scheduler",
    http_timeout: float = _HTTP_TIMEOUT_SECONDS,
) -> RunResult:
    """Pack + send + record. Always returns a RunResult; errors captured
    into `result.error`, never raised to the caller."""
    cfg = await get_config(db)
    start_dt = datetime.now(timezone.utc)

    if not cfg.enabled:
        return RunResult(
            ok=False, status="disabled",
            error="ReportUp is disabled (enabled=false in config)",
        )
    if not cfg.parent_endpoint:
        return RunResult(
            ok=False, status="error",
            error="parent_endpoint not configured",
        )

    secret = await _get_hmac_secret(db)
    if not secret:
        return RunResult(
            ok=False, status="error",
            error="HMAC secret not configured (set via PUT /config with hmac_secret field)",
        )

    try:
        envelope, counts = await pack_envelope(db, config=cfg)
    except Exception as e:
        return RunResult(
            ok=False, status="error",
            error=f"pack_envelope failed: {type(e).__name__}: {e}",
        )

    # Open the log row so partial runs are visible in the UI.
    log_row = ReportUpLog(
        started_at=start_dt,
        status="running",
        envelope_hash=envelope.envelope_hash,
        previous_envelope_hash=envelope.previous_envelope_hash,
        sequence_from=envelope.sequence_from,
        sequence_to=envelope.sequence_to,
        audit_entries_shipped=counts["audit_chain"],
        telemetry_rows_shipped=counts["telemetry"],
        agents_shipped=counts["agents"],
        identity_rows_shipped=counts["identity_users"] + counts["identity_groups"],
    )
    db.add(log_row)
    await db.flush()

    # Sign the envelope hash with the shared secret.
    envelope.hmac_signature = hmac_sign(secret, envelope.envelope_hash)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"insidellm-reportup/{_DEFAULT_SCHEMA_VERSION}",
        "X-Insidellm-Tenant": envelope.tenant_id,
        "X-Insidellm-Envelope-Hash": envelope.envelope_hash,
        "X-Insidellm-Signature": envelope.hmac_signature,
        "X-Insidellm-Schema-Version": _DEFAULT_SCHEMA_VERSION,
    }

    try:
        async with httpx.AsyncClient(timeout=http_timeout) as client:
            resp = await client.post(
                cfg.parent_endpoint,
                content=canonical_json(envelope.model_dump(mode="json")),
                headers=headers,
            )
            http_status = resp.status_code
            try:
                ack_payload = resp.json()
            except Exception:
                ack_payload = {"raw": resp.text[:500]}
    except Exception as e:
        log_row.ended_at = datetime.now(timezone.utc)
        log_row.status = "error"
        log_row.error_message = f"{type(e).__name__}: {e}"[:500]
        log_row.duration_ms = int((log_row.ended_at - start_dt).total_seconds() * 1000)
        await db.commit()
        return RunResult(
            ok=False, status="error",
            envelope_hash=envelope.envelope_hash,
            previous_envelope_hash=envelope.previous_envelope_hash,
            sequence_from=envelope.sequence_from,
            sequence_to=envelope.sequence_to,
            records_by_category=counts,
            duration_ms=log_row.duration_ms,
            error=log_row.error_message,
        )

    end_dt = datetime.now(timezone.utc)
    accepted = http_status < 400

    log_row.ended_at = end_dt
    log_row.parent_http_status = http_status
    log_row.parent_ack_status = "accepted" if accepted else "rejected"
    log_row.parent_ack_payload_json = ack_payload
    log_row.status = "success" if accepted else "parent_rejected"
    log_row.duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
    if not accepted:
        log_row.error_message = f"parent HTTP {http_status}: {str(ack_payload)[:300]}"

    # Advance the watermark ONLY on acceptance.
    if accepted:
        cfg.last_envelope_hash = envelope.envelope_hash
        # sequence_to may be < sequence_from when the audit chain is empty;
        # only advance when we actually shipped at least one audit row.
        if counts["audit_chain"] > 0:
            cfg.last_shipped_sequence = envelope.sequence_to
        cfg.updated_at = end_dt
        cfg.updated_by = actor

    await db.commit()

    return RunResult(
        ok=accepted,
        status=log_row.status,
        envelope_hash=envelope.envelope_hash,
        previous_envelope_hash=envelope.previous_envelope_hash,
        sequence_from=envelope.sequence_from,
        sequence_to=envelope.sequence_to,
        records_by_category=counts,
        parent_ack_status=log_row.parent_ack_status,
        parent_http_status=http_status,
        parent_ack_payload=ack_payload,
        duration_ms=log_row.duration_ms,
        error=log_row.error_message,
    )


# ---------------------------------------------------------------------------
# Verifier (parent-side) — exposed here for tests AND for the parent's
# ingest endpoint to import directly. Keeps the one-source-of-truth rule.
# ---------------------------------------------------------------------------


def verify_envelope(
    envelope: dict[str, Any],
    *,
    secret: str,
    expected_previous_hash: str | None = None,
) -> tuple[bool, str | None]:
    """Returns (ok, error). Used by the parent's ingest endpoint.

    Checks:
      1. envelope['envelope_hash'] matches SHA256(canonical(payload-without-hash))
      2. envelope['hmac_signature'] matches HMAC-SHA256(secret, envelope_hash)
      3. If expected_previous_hash given, envelope['previous_envelope_hash'] matches
    """
    submitted_hash = envelope.get("envelope_hash", "")
    submitted_sig = envelope.get("hmac_signature", "")
    recomputed_hash = compute_envelope_hash(envelope)
    if submitted_hash != recomputed_hash:
        return False, "envelope_hash mismatch — payload tampered or encoding mismatch"
    expected_sig = hmac_sign(secret, recomputed_hash)
    if not hmac.compare_digest(submitted_sig, expected_sig):
        return False, "hmac_signature mismatch — wrong secret or tampered envelope"
    if expected_previous_hash is not None:
        got = envelope.get("previous_envelope_hash")
        if got != expected_previous_hash:
            return False, (
                f"previous_envelope_hash mismatch — chain broken "
                f"(got {got!r}, expected {expected_previous_hash!r})"
            )
    return True, None
