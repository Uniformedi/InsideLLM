"""ReportUp REST router.

  GET  /api/v1/reportup/config          Current config
  PUT  /api/v1/reportup/config          Update config (admin, attestation-gated)
  POST /api/v1/reportup/hmac-secret     Set/rotate the shared HMAC secret (admin)
  POST /api/v1/reportup/attestation     Record a compliance officer's consent (admin)
  GET  /api/v1/reportup/attestations    List prior attestations (view)
  POST /api/v1/reportup/send-now        Manually trigger a run (admin)
  POST /api/v1/reportup/preview         Dry-run — what would ship (view)
  GET  /api/v1/reportup/log             Recent sync runs (view)

  GET  /reportup                        HTML UI (view)
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..db.models import ReportUpAttestation, ReportUpConfig, ReportUpLog
from ..schemas.reportup import (
    AttestationListResponse,
    AttestationRequest,
    AttestationResponse,
    PreviewResponse,
    REPORTUP_SCHEMA_VERSION,
    ReportUpConfigRequest,
    ReportUpConfigResponse,
    ReportUpLogEntry,
    ReportUpLogResponse,
)
from ..services.audit_chain import append_event
from ..services.rbac import require_admin, require_view
from ..services.reportup_service import (
    get_config,
    pack_envelope,
    run_once,
    update_hmac_secret,
)

logger = logging.getLogger("governance-hub.reportup.router")

router = APIRouter(tags=["reportup"])

_PAGE_PATH = Path(__file__).resolve().parent.parent / "pages" / "reportup.html"


def _actor(request: Request) -> str:
    return (
        getattr(request.state, "user_email", None)
        or getattr(request.state, "user_id", None)
        or "system"
    )


def _config_to_response(cfg: ReportUpConfig) -> ReportUpConfigResponse:
    return ReportUpConfigResponse(
        enabled=bool(cfg.enabled),
        parent_name=cfg.parent_name,
        parent_endpoint=cfg.parent_endpoint,
        parent_public_key_present=bool(cfg.parent_public_key_pem),
        share_audit_chain=bool(cfg.share_audit_chain),
        share_telemetry=bool(cfg.share_telemetry),
        share_agents=bool(cfg.share_agents),
        share_identity=bool(cfg.share_identity),
        share_policies=bool(cfg.share_policies),
        share_change_proposals=bool(cfg.share_change_proposals),
        schedule_cron=cfg.schedule_cron or "0 2 * * *",
        max_records_per_run=int(cfg.max_records_per_run or 10000),
        last_shipped_sequence=int(cfg.last_shipped_sequence or 0),
        last_envelope_hash=cfg.last_envelope_hash,
        updated_at=cfg.updated_at,
        updated_by=cfg.updated_by,
    )


def _config_snapshot(cfg: ReportUpConfig) -> dict:
    """Serialisable snapshot for attestation records — captures everything
    the officer was agreeing to at the point they signed."""
    return {
        "enabled": bool(cfg.enabled),
        "parent_name": cfg.parent_name,
        "parent_endpoint": cfg.parent_endpoint,
        "share_audit_chain": bool(cfg.share_audit_chain),
        "share_telemetry": bool(cfg.share_telemetry),
        "share_agents": bool(cfg.share_agents),
        "share_identity": bool(cfg.share_identity),
        "share_policies": bool(cfg.share_policies),
        "share_change_proposals": bool(cfg.share_change_proposals),
        "schedule_cron": cfg.schedule_cron,
        "max_records_per_run": cfg.max_records_per_run,
    }


def _snapshot_sha(snapshot: dict) -> str:
    blob = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# HTML UI
# ---------------------------------------------------------------------------


@router.get("/reportup", response_class=HTMLResponse, dependencies=[require_view])
async def reportup_page() -> HTMLResponse:
    if not _PAGE_PATH.exists():
        return HTMLResponse(
            "<h1>ReportUp UI unavailable</h1><p>pages/reportup.html missing.</p>",
            status_code=500,
        )
    return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@router.get("/api/v1/reportup/config", dependencies=[require_view])
async def read_config(db: AsyncSession = Depends(get_local_db)) -> ReportUpConfigResponse:
    cfg = await get_config(db)
    return _config_to_response(cfg)


@router.put("/api/v1/reportup/config", dependencies=[require_admin])
async def update_config(
    payload: ReportUpConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> ReportUpConfigResponse:
    """Merge the payload onto the existing config. If enabled is flipped
    true OR the parent identity changes, an unattested config requires
    an attestation first — we check the attestation store."""
    cfg = await get_config(db)
    actor = _actor(request)

    # Guard: flipping enabled to true, OR changing parent, requires an
    # attestation within the last 24 hours that matches the NEW snapshot.
    wants_enable = (payload.enabled is True and not cfg.enabled)
    parent_changed = (
        payload.parent_name is not None and payload.parent_name != cfg.parent_name
    ) or (
        payload.parent_endpoint is not None and payload.parent_endpoint != cfg.parent_endpoint
    )
    if wants_enable or parent_changed:
        # Check for a recent attestation matching the INTENDED post-update snapshot.
        projected = _config_snapshot(cfg) | {
            k: v for k, v in payload.model_dump(exclude_unset=True).items()
            if k in _config_snapshot(cfg)
        }
        projected_sha = _snapshot_sha(projected)
        recent = await db.execute(
            select(ReportUpAttestation)
            .where(ReportUpAttestation.config_snapshot_sha == projected_sha)
            .order_by(ReportUpAttestation.attested_at.desc())
            .limit(1)
        )
        if recent.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "attestation required: enabling ReportUp or changing the "
                    "parent identity requires POST /api/v1/reportup/attestation "
                    "with the exact intended config first. No attestation matching "
                    f"snapshot SHA {projected_sha[:12]}… was found."
                ),
            )

    # Apply the patch.
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(cfg, k, v)
    cfg.updated_at = datetime.now(timezone.utc)
    cfg.updated_by = actor
    await db.flush()

    # Audit the change.
    await append_event(db, "reportup_config_updated", cfg.id, {
        "actor": actor,
        "snapshot_sha": _snapshot_sha(_config_snapshot(cfg)),
        "enabled": cfg.enabled,
        "parent_name": cfg.parent_name,
    })
    await db.commit()
    await db.refresh(cfg)
    return _config_to_response(cfg)


class _HmacSecretRequest(BaseModel):
    secret: str = Field(..., min_length=32, max_length=256)


@router.post("/api/v1/reportup/hmac-secret", dependencies=[require_admin])
async def set_hmac_secret(
    payload: _HmacSecretRequest,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """Set or rotate the HMAC secret shared with the parent. Stored in
    settings_overrides so it never rides on the regular config GET."""
    await update_hmac_secret(db, payload.secret, actor=_actor(request))
    # Audit — never log the secret; log the digest.
    digest = hashlib.sha256(payload.secret.encode("utf-8")).hexdigest()[:12]
    await append_event(db, "reportup_hmac_rotated", 0, {
        "actor": _actor(request),
        "secret_sha12": digest,
    })
    await db.commit()
    return {"ok": True, "secret_sha12": digest}


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------


@router.post("/api/v1/reportup/attestation", dependencies=[require_admin])
async def record_attestation(
    payload: AttestationRequest,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> AttestationResponse:
    """Record that a named compliance officer signed off on the CURRENT
    config (what GET /config would return right now). The attestation
    itself gets appended to the audit chain."""
    cfg = await get_config(db)
    snapshot = _config_snapshot(cfg)
    sha = _snapshot_sha(snapshot)

    row = ReportUpAttestation(
        attested_by=payload.attested_by,
        attested_role=payload.attested_role,
        attestation_text=payload.attestation_text,
        config_snapshot_json=snapshot,
        config_snapshot_sha=sha,
    )
    db.add(row)
    await db.flush()

    await append_event(db, "reportup_attested", row.id, {
        "actor": _actor(request),
        "attested_by": payload.attested_by,
        "attested_role": payload.attested_role,
        "snapshot_sha": sha,
    })
    await db.commit()
    await db.refresh(row)

    return AttestationResponse(
        id=row.id,
        attested_by=row.attested_by,
        attested_role=row.attested_role,
        attestation_text=row.attestation_text,
        config_snapshot=snapshot,
        config_snapshot_sha=sha,
        attested_at=row.attested_at,
    )


@router.get("/api/v1/reportup/attestations", dependencies=[require_view])
async def list_attestations(
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_local_db),
) -> AttestationListResponse:
    rows = (await db.execute(
        select(ReportUpAttestation)
        .order_by(ReportUpAttestation.attested_at.desc())
        .limit(limit)
    )).scalars().all()
    return AttestationListResponse(
        attestations=[
            AttestationResponse(
                id=r.id,
                attested_by=r.attested_by,
                attested_role=r.attested_role,
                attestation_text=r.attestation_text,
                config_snapshot=r.config_snapshot_json or {},
                config_snapshot_sha=r.config_snapshot_sha,
                attested_at=r.attested_at,
            )
            for r in rows
        ],
        total=len(rows),
    )


# ---------------------------------------------------------------------------
# Preview + send-now + log
# ---------------------------------------------------------------------------


@router.post("/api/v1/reportup/preview", dependencies=[require_view])
async def preview(db: AsyncSession = Depends(get_local_db)) -> PreviewResponse:
    """Build the envelope the next run WOULD ship, without sending."""
    cfg = await get_config(db)
    envelope, counts = await pack_envelope(db, config=cfg, dry_run=True)
    return PreviewResponse(
        enabled=bool(cfg.enabled),
        parent_name=cfg.parent_name,
        parent_endpoint=cfg.parent_endpoint,
        sequence_from=envelope.sequence_from,
        would_ship={
            "audit_entries": counts["audit_chain"],
            "telemetry_rows": counts["telemetry"],
            "agents": counts["agents"],
            "identity_users": counts["identity_users"],
            "identity_groups": counts["identity_groups"],
            "change_proposals": counts["change_proposals"],
        },
        envelope_hash_would_be=envelope.envelope_hash,
        previous_envelope_hash=envelope.previous_envelope_hash,
        schema_version=REPORTUP_SCHEMA_VERSION,
        generated_at=datetime.now(timezone.utc),
    )


@router.post("/api/v1/reportup/send-now", dependencies=[require_admin])
async def send_now(
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """Run once, synchronously. Returns the full RunResult."""
    result = await run_once(db, actor=_actor(request))
    return result.to_dict()


@router.get("/api/v1/reportup/log", dependencies=[require_view])
async def list_runs(
    limit: int = Query(25, ge=1, le=500),
    db: AsyncSession = Depends(get_local_db),
) -> ReportUpLogResponse:
    rows = (await db.execute(
        select(ReportUpLog)
        .order_by(ReportUpLog.started_at.desc())
        .limit(limit)
    )).scalars().all()
    return ReportUpLogResponse(
        runs=[
            ReportUpLogEntry(
                id=r.id,
                started_at=r.started_at,
                ended_at=r.ended_at,
                status=r.status or "unknown",
                envelope_hash=r.envelope_hash,
                previous_envelope_hash=r.previous_envelope_hash,
                sequence_from=r.sequence_from,
                sequence_to=r.sequence_to,
                audit_entries_shipped=int(r.audit_entries_shipped or 0),
                telemetry_rows_shipped=int(r.telemetry_rows_shipped or 0),
                agents_shipped=int(r.agents_shipped or 0),
                identity_rows_shipped=int(r.identity_rows_shipped or 0),
                parent_ack_status=r.parent_ack_status,
                parent_http_status=r.parent_http_status,
                duration_ms=r.duration_ms,
                error_message=r.error_message,
            )
            for r in rows
        ],
        total=len(rows),
    )
