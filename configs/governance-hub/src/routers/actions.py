"""Action catalog REST router.

CRUD + multi-action YAML seeding. Agents reference these action_ids in
their manifest; the runtime resolves via tenant → core fallback.

RBAC:
  - list / get / resolve      → view
  - create / update / retire  → admin
  - seed (bulk upload)        → admin
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..schemas.actions import ActionCatalogEntry
from ..services.action_catalog_service import (
    CORE_TENANT,
    get_action,
    list_actions,
    parse_multi_action_document,
    resolve_action,
    retire_action,
    seed_entries,
    upsert_action,
)
from ..services.rbac import require_admin, require_view

logger = logging.getLogger("governance-hub.actions.router")

router = APIRouter(prefix="/api/v1/actions", tags=["actions"])


def _actor(request: Request) -> str | None:
    return getattr(request.state, "user_email", None) or getattr(
        request.state, "user_id", None
    )


def _row_to_response(row) -> dict:
    return {
        "id": row.id,
        "action_id": row.action_id,
        "tenant_id": row.tenant_id,
        "display_name": row.display_name,
        "description": row.description,
        "category": row.category,
        "schema_version": row.schema_version,
        "backend_type": row.backend_type,
        "minimum_guardrail_tier": row.minimum_guardrail_tier,
        "requires_approval": row.requires_approval,
        "version": row.version,
        "maintainer": row.maintainer,
        "deprecated": row.deprecated,
        "entry": row.entry_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


@router.get("/", dependencies=[require_view])
async def list_all(
    tenant_id: str | None = Query(None, description="Tenant (or 'core'). Omitted = all tenants."),
    category: str | None = Query(None),
    include_deprecated: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    rows = await list_actions(db, tenant_id, category, include_deprecated, limit, offset)
    return {"total": len(rows), "actions": [_row_to_response(r) for r in rows]}


@router.get("/{tenant_id}/{action_id}", dependencies=[require_view])
async def get_one(
    tenant_id: str,
    action_id: str,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    row = await get_action(db, tenant_id, action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="action not found")
    return _row_to_response(row)


@router.get("/resolve/{tenant_id}/{action_id}", dependencies=[require_view])
async def resolve_for_tenant(
    tenant_id: str,
    action_id: str,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """Runtime lookup: tenant-scoped row wins; falls back to core."""
    row = await resolve_action(db, tenant_id, action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="action not found (tenant or core)")
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


@router.post("/", dependencies=[require_admin])
async def upsert(
    request: Request,
    payload: ActionCatalogEntry,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    row, op = await upsert_action(db, payload, actor_email=_actor(request))
    return {"operation": op, "action": _row_to_response(row)}


@router.post("/upload", dependencies=[require_admin])
async def upload(
    request: Request,
    body: str = Body(..., media_type="application/x-yaml"),
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """Upload a single entry or a multi-action document (actions: [...])."""
    content_type = request.headers.get("content-type", "application/yaml")
    try:
        entries = parse_multi_action_document(body, content_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"parse failed: {e}")
    counts = await seed_entries(db, entries, actor_email=_actor(request) or "upload")
    return {"counts": counts, "total": len(entries)}


@router.post("/{tenant_id}/{action_id}/retire", dependencies=[require_admin])
async def retire(
    tenant_id: str,
    action_id: str,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    row = await retire_action(db, tenant_id, action_id, actor_email=_actor(request))
    if row is None:
        raise HTTPException(status_code=404, detail="action not found")
    return _row_to_response(row)


@router.post("/seed-core", dependencies=[require_admin])
async def seed_core(
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """Re-seed the shipped `tenant_id=core` catalog (DocForge, GovAdvisor,
    FleetMgmt, SysDesigner, DataConnector). Idempotent — unchanged entries
    are no-ops."""
    from ..services.action_catalog_seed import load_core_wrappers

    entries = load_core_wrappers()
    counts = await seed_entries(db, entries, actor_email=_actor(request) or "seed_core")
    return {"counts": counts, "total": len(entries)}
