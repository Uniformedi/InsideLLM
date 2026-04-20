"""Canonical session REST router.

Surfaces the minimal API needed to ship Phase 3.3 (OWUI adapter only):

  GET  /api/v1/sessions/{session_id}           fetch one
  GET  /api/v1/sessions                        list (tenant-scoped, by owner)
  POST /api/v1/sessions/{session_id}/handoff   request a handoff
  POST /api/v1/sessions/{session_id}/close     close a session
  GET  /api/v1/sessions/{session_id}/events    walk the hash chain

Cross-tenant forks, mirror promotion, and PWA push subscription management
ship in later routers (federation.py, mirror.py, push.py).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..db.local_db import AsyncSessionLocal
from ..services import sessions_service as svc
from ..services.rbac import require_admin, require_view

logger = logging.getLogger("governance-hub.sessions.router")

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class HandoffTarget(BaseModel):
    type: str = Field(pattern="^(user|group|agent|system)$")
    ref: str
    tenant_id: str | None = None
    status: str = "online"
    roles: list[str] = Field(default_factory=list)


class HandoffRequest(BaseModel):
    target: HandoffTarget
    reason: str = Field(min_length=8, max_length=1000)
    hop_count: int = 0
    idempotency_key: str | None = None


class HandoffResponse(BaseModel):
    allowed: bool
    deny_reasons: list[str] = Field(default_factory=list)
    state: str
    current_owner: dict[str, Any] | None = None


class CloseRequest(BaseModel):
    reason: str = Field(min_length=4, max_length=500)


class SessionSummary(BaseModel):
    session_id: str
    tenant_id: str
    agent_manifest_id: str
    manifest_hash: str
    owner_type: str
    owner_ref: str
    state: str
    current_surface: str
    security_tier: str
    classification: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _actor_from_request(request: Request) -> svc.Actor:
    sub = getattr(request.state, "user_id", None) or getattr(
        request.state, "user_email", None
    )
    if not sub:
        raise HTTPException(status_code=401, detail="unauthenticated")
    roles = tuple(getattr(request.state, "user_roles", ()) or ())
    auth_method = getattr(request.state, "auth_method", "oidc")
    return svc.Actor(sub=sub, roles=roles, auth_method=auth_method)


def _owner_ref_of(row) -> str:
    return (
        row.owner_user_id
        or row.owner_group_id
        or row.owner_agent_id
        or row.owner_system_reason
        or ""
    )


def _parse_session_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid session_id") from e


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    tenant_id: str
    agent_manifest_id: str
    manifest_hash: str
    surface: str = Field(pattern="^(owui|mattermost|teams|slack|api|email|sms|n8n)$")
    surface_ref: str | None = None
    classification: str = Field(default="general", pattern="^(general|confidential|regulated)$")
    security_tier: str = Field(default="T2", pattern="^T[0-7]$")
    tier_source: str = Field(default="tenant", pattern="^(tenant|manifest|classification)$")
    data_region: str = "us-east"
    kms_data_key_id: str
    manifest_min_tier: str | None = Field(default=None, pattern="^T[0-7]$")
    classification_min_tier: str | None = Field(default=None, pattern="^T[0-7]$")
    retention_floor_override: int = Field(default=0, ge=0, le=10000)
    retention_cap_override: int = Field(default=0, ge=0, le=10000)


@router.post("", dependencies=[require_view])
async def create_session(
    body: CreateSessionRequest, request: Request
) -> dict[str, Any]:
    actor = _actor_from_request(request)
    async with AsyncSessionLocal() as db:
        try:
            result = await svc.create_session(
                db,
                tenant_id=body.tenant_id,
                agent_manifest_id=body.agent_manifest_id,
                manifest_hash=body.manifest_hash,
                initiator=actor,
                surface=body.surface,
                surface_ref=body.surface_ref,
                classification=body.classification,
                security_tier=body.security_tier,
                tier_source=body.tier_source,
                data_region=body.data_region,
                kms_data_key_id=body.kms_data_key_id,
                manifest_min_tier=body.manifest_min_tier,
                classification_min_tier=body.classification_min_tier,
                retention_floor_override=body.retention_floor_override,
                retention_cap_override=body.retention_cap_override,
            )
            await db.commit()
        except Exception as e:
            logger.exception("create_session failed")
            raise HTTPException(status_code=500, detail=str(e)) from e
    return result


@router.get("/{session_id}", dependencies=[require_view], response_model=SessionSummary)
async def get_session(session_id: str) -> SessionSummary:
    sid = _parse_session_id(session_id)
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT session_id, tenant_id, agent_manifest_id, manifest_hash,
                           owner_type, owner_user_id, owner_group_id,
                           owner_agent_id, owner_system_reason,
                           state, current_surface, security_tier, classification,
                           created_at, updated_at
                      FROM sessions WHERE session_id = :sid
                    """
                ),
                {"sid": str(sid)},
            )
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionSummary(
        session_id=str(row.session_id),
        tenant_id=row.tenant_id,
        agent_manifest_id=row.agent_manifest_id,
        manifest_hash=row.manifest_hash,
        owner_type=row.owner_type,
        owner_ref=_owner_ref_of(row),
        state=row.state,
        current_surface=row.current_surface,
        security_tier=row.security_tier,
        classification=row.classification,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("", dependencies=[require_view])
async def list_sessions(
    request: Request,
    tenant_id: str = Query(...),
    owner_user_id: str | None = Query(None),
    owner_group_id: str | None = Query(None),
    state: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    clauses = ["tenant_id = :tenant_id"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "lim": limit, "off": offset}
    if owner_user_id:
        clauses.append("owner_user_id = :owner_user_id")
        params["owner_user_id"] = owner_user_id
    if owner_group_id:
        clauses.append("owner_group_id = :owner_group_id")
        params["owner_group_id"] = owner_group_id
    if state:
        clauses.append("state = :state")
        params["state"] = state

    sql = f"""
        SELECT session_id, tenant_id, agent_manifest_id, manifest_hash,
               owner_type, owner_user_id, owner_group_id,
               owner_agent_id, owner_system_reason,
               state, current_surface, security_tier, classification,
               created_at, updated_at
          FROM sessions
         WHERE {' AND '.join(clauses)}
         ORDER BY updated_at DESC
         LIMIT :lim OFFSET :off
    """
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(sql), params)).all()
    return {
        "sessions": [
            SessionSummary(
                session_id=str(r.session_id),
                tenant_id=r.tenant_id,
                agent_manifest_id=r.agent_manifest_id,
                manifest_hash=r.manifest_hash,
                owner_type=r.owner_type,
                owner_ref=_owner_ref_of(r),
                state=r.state,
                current_surface=r.current_surface,
                security_tier=r.security_tier,
                classification=r.classification,
                created_at=r.created_at.isoformat(),
                updated_at=r.updated_at.isoformat(),
            ).model_dump()
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/{session_id}/handoff",
    dependencies=[require_view],
    response_model=HandoffResponse,
)
async def request_handoff(
    session_id: str, body: HandoffRequest, request: Request
) -> HandoffResponse:
    sid = _parse_session_id(session_id)
    actor = _actor_from_request(request)

    target = svc.HandoffTarget(
        type=body.target.type,  # type: ignore[arg-type]
        ref=body.target.ref,
        tenant_id=body.target.tenant_id,
        status=body.target.status,
        roles=tuple(body.target.roles),
    )

    async with AsyncSessionLocal() as db:
        try:
            result = await svc.request_handoff(
                db,
                session_id=sid,
                target=target,
                reason=body.reason,
                actor=actor,
                hop_count=body.hop_count,
            )
            await db.commit()
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    return HandoffResponse(**result)


@router.post("/{session_id}/close", dependencies=[require_view])
async def close_session(
    session_id: str, body: CloseRequest, request: Request
) -> dict[str, str]:
    sid = _parse_session_id(session_id)
    actor = _actor_from_request(request)

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT tenant_id, state, owner_type, owner_user_id "
                    "FROM sessions WHERE session_id = :sid FOR UPDATE"
                ),
                {"sid": str(sid)},
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        if row.state in {"closed", "archived"}:
            raise HTTPException(status_code=409, detail=f"already {row.state}")
        # Only the owner (or an admin) may close.
        if row.owner_type == "user" and row.owner_user_id != actor.sub:
            if "tenant-admin" not in actor.roles:
                raise HTTPException(status_code=403, detail="not owner")

        await db.execute(
            text(
                "UPDATE sessions SET state = 'closed', closed_at = now() "
                "WHERE session_id = :sid"
            ),
            {"sid": str(sid)},
        )
        await svc.append_session_event(
            db,
            session_id=sid,
            tenant_id=row.tenant_id,
            event_type="session.closed",
            actor_type="user",
            actor_sub=actor.sub,
            surface=None,
            payload_metadata={"reason": body.reason},
        )
        await db.commit()

    return {"session_id": str(sid), "state": "closed"}


class CostRecord(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    model: str = "unknown"
    latency_ms: int = Field(default=0, ge=0)
    error: bool = False


@router.post("/{session_id}/cost", dependencies=[require_view])
async def record_cost(session_id: str, body: CostRecord) -> dict[str, Any]:
    """Internal endpoint called by LiteLLM's session_cost success callback.

    Trusted service-to-service call (admitted by rbac_middleware via the
    LITELLM_MASTER_KEY bearer token). Idempotency is best-effort — the
    caller does not retry on success.
    """
    sid = _parse_session_id(session_id)
    async with AsyncSessionLocal() as db:
        await svc.record_cost(
            db,
            session_id=sid,
            prompt_tokens=body.prompt_tokens,
            completion_tokens=body.completion_tokens,
            total_tokens=body.total_tokens,
            cost_usd=body.cost_usd,
            model=body.model,
            latency_ms=body.latency_ms,
            error=body.error,
        )
        await db.commit()
    return {"session_id": str(sid), "recorded": True}


@router.get("/{session_id}/events", dependencies=[require_view])
async def get_session_events(
    session_id: str,
    limit: int = Query(100, ge=1, le=1000),
    after_seq: int = Query(0, ge=0),
) -> dict[str, Any]:
    sid = _parse_session_id(session_id)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT event_id, event_seq, event_type, actor_sub, actor_type,
                           surface, prev_hash, self_hash, payload_metadata,
                           created_at
                      FROM session_events
                     WHERE session_id = :sid AND event_seq > :after
                     ORDER BY event_seq ASC
                     LIMIT :lim
                    """
                ),
                {"sid": str(sid), "after": after_seq, "lim": limit},
            )
        ).all()

    return {
        "session_id": str(sid),
        "events": [
            {
                "event_id": str(r.event_id),
                "event_seq": r.event_seq,
                "event_type": r.event_type,
                "actor_sub": r.actor_sub,
                "actor_type": r.actor_type,
                "surface": r.surface,
                "prev_hash": r.prev_hash,
                "self_hash": r.self_hash,
                "payload_metadata": r.payload_metadata,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }
