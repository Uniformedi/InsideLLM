"""Declarative agent CRUD router.

Exposes the governance_agents table via REST. Manifests are authored in
YAML or JSON (see docs/Agents-Plan.md + docs/Platform-Ultraplan-v3.md).

RBAC (via rbac middleware):
  - list / get / get-audit → view
  - create / update / delete / publish / retire → admin

Visibility scope gating:
  - private / team       → publish goes live immediately
  - org / fleet          → publish creates a governance_changes proposal
                           that must be approved via
                           /api/v1/changes/{id}/approve before the
                           agent becomes is_active.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..schemas.agents import (
    AgentCreateRequest,
    AgentListResponse,
    AgentManifest,
    AgentResponse,
    AgentUpdateRequest,
)
from ..services.agent_service import (
    _row_to_response,
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    parse_manifest_from_text,
    publish_agent,
    retire_agent,
    update_agent,
)
from ..services.rbac import require_admin, require_view

logger = logging.getLogger("governance-hub.agents.router")

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _actor(request: Request) -> str | None:
    """Pull actor email from RBAC-set request state, else None."""
    return getattr(request.state, "user_email", None) or getattr(
        request.state, "user_id", None
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


@router.get("/", dependencies=[require_view])
async def list_all(
    tenant_id: str | None = Query(None),
    status: str | None = Query(None, pattern=r"^(draft|published|retired)$"),
    visibility: str | None = Query(None, pattern=r"^(private|team|org|fleet)$"),
    team: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_local_db),
) -> AgentListResponse:
    rows = await list_agents(db, tenant_id, status, visibility, team, limit, offset)
    return AgentListResponse(
        agents=[_row_to_response(r) for r in rows],
        total=len(rows),
    )


@router.get("/{tenant_id}/{agent_id}", dependencies=[require_view])
async def get_one(
    tenant_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_local_db),
) -> AgentResponse:
    row = await get_agent(db, tenant_id, agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


@router.post("/", dependencies=[require_admin])
async def create(
    request: Request,
    payload: AgentCreateRequest,
    db: AsyncSession = Depends(get_local_db),
) -> AgentResponse:
    """Create a new declarative agent in draft state."""
    try:
        row = await create_agent(db, payload.manifest, actor_email=_actor(request))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _row_to_response(row)


@router.post("/upload", dependencies=[require_admin])
async def create_from_text(
    request: Request,
    body: str = Body(
        ...,
        media_type="application/x-yaml",
        description="Raw YAML or JSON manifest body. Content-Type drives parser choice.",
    ),
    db: AsyncSession = Depends(get_local_db),
) -> AgentResponse:
    """Convenience endpoint: POST raw YAML or JSON directly (no wrapper)."""
    content_type = request.headers.get("content-type", "application/json")
    try:
        manifest = parse_manifest_from_text(body, content_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"manifest parse failed: {e}")
    try:
        row = await create_agent(db, manifest, actor_email=_actor(request))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _row_to_response(row)


@router.put("/{tenant_id}/{agent_id}", dependencies=[require_admin])
async def update(
    tenant_id: str,
    agent_id: str,
    request: Request,
    payload: AgentUpdateRequest,
    db: AsyncSession = Depends(get_local_db),
) -> AgentResponse:
    try:
        row = await update_agent(
            db, tenant_id, agent_id, payload.manifest, actor_email=_actor(request)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return _row_to_response(row)


@router.post("/{tenant_id}/{agent_id}/publish", dependencies=[require_admin])
async def publish(
    tenant_id: str,
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    row, change_id = await publish_agent(
        db, tenant_id, agent_id, actor_email=_actor(request)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return {
        "agent": _row_to_response(row).model_dump(mode="json"),
        "pending_change_id": change_id,
        "published_immediately": change_id is None,
        "message": (
            "agent published" if change_id is None
            else f"approval required; proposal id={change_id} in governance_changes"
        ),
    }


@router.post("/{tenant_id}/{agent_id}/retire", dependencies=[require_admin])
async def retire(
    tenant_id: str,
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> AgentResponse:
    row = await retire_agent(db, tenant_id, agent_id, actor_email=_actor(request))
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return _row_to_response(row)


@router.delete("/{tenant_id}/{agent_id}", dependencies=[require_admin])
async def soft_delete(
    tenant_id: str,
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """Same as retire — soft-delete, history preserved."""
    ok = await delete_agent(db, tenant_id, agent_id, actor_email=_actor(request))
    if not ok:
        raise HTTPException(status_code=404, detail="agent not found")
    return {"deleted": True, "tenant_id": tenant_id, "agent_id": agent_id}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@router.get("/{tenant_id}/{agent_id}/audit", dependencies=[require_view])
async def get_audit_trail(
    tenant_id: str,
    agent_id: str,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """Hash-chained audit entries filtered to this agent (event_id matches
    agent row id). Lightweight — uses the existing audit_chain service."""
    row = await get_agent(db, tenant_id, agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")

    from sqlalchemy import select

    from ..db.models import AuditChainEntry

    stmt = (
        select(AuditChainEntry)
        .where(AuditChainEntry.event_id == row.id)
        .where(AuditChainEntry.event_type.like("agent_%"))
        .order_by(AuditChainEntry.sequence.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "total": len(rows),
        "entries": [
            {
                "sequence": r.sequence,
                "event_type": r.event_type,
                "payload_hash": r.payload_hash,
                "previous_hash": r.previous_hash,
                "chain_hash": r.chain_hash,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
