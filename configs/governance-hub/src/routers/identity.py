"""Identity replication REST router.

Surfaces the Keycloak→central-DB sync for operator tooling:

  * GET  /api/v1/identity/sync/status    recent sync runs (central DB)
  * POST /api/v1/identity/sync           run one cycle on-demand
  * GET  /api/v1/identity/users          list central users (all instances)
  * GET  /api/v1/identity/groups         list central groups
  * GET  /api/v1/identity/whoami         quick "Keycloak is reachable + I can auth" probe
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from ..config import settings
from ..db.central_db import run_central_query
from ..db.central_sql import SQL
from ..services.keycloak_sync import run_sync_once
from ..services.rbac import require_admin, require_view

logger = logging.getLogger("governance-hub.identity.router")

router = APIRouter(prefix="/api/v1/identity", tags=["identity"])


def _actor(request: Request) -> str | None:
    return getattr(request.state, "user_email", None) or getattr(
        request.state, "user_id", None
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


@router.get("/sync/status", dependencies=[require_view])
async def sync_status(
    instance_id: str | None = Query(None),
    limit: int = Query(25, ge=1, le=200),
) -> dict:
    """Most recent sync-run log rows. Empty list when central DB unreachable."""
    if not settings.central_db_url:
        return {"runs": [], "central_db_configured": False}

    def _read(db):
        rows = db.execute(
            text(SQL.recent_identity_sync_log),
            {"iid": instance_id, "lim": limit},
        ).mappings().all()
        return [dict(r) for r in rows]

    rows = await run_central_query(_read) or []
    return {
        "runs": _serialize_rows(rows),
        "central_db_configured": True,
        "sync_enabled": settings.keycloak_sync_enable,
    }


@router.get("/users", dependencies=[require_view])
async def list_users(
    instance_id: str | None = Query(None),
    realm: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    if not settings.central_db_url:
        return {"users": [], "total": 0, "central_db_configured": False}

    def _read(db):
        rows = db.execute(
            text(SQL.list_identity_users),
            {"iid": instance_id, "realm": realm, "lim": limit, "off": offset},
        ).mappings().all()
        return [dict(r) for r in rows]

    rows = await run_central_query(_read) or []
    return {"users": _serialize_rows(rows), "total": len(rows), "central_db_configured": True}


@router.get("/groups", dependencies=[require_view])
async def list_groups(
    instance_id: str | None = Query(None),
    realm: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    if not settings.central_db_url:
        return {"groups": [], "total": 0, "central_db_configured": False}

    def _read(db):
        rows = db.execute(
            text(SQL.list_identity_groups),
            {"iid": instance_id, "realm": realm, "lim": limit, "off": offset},
        ).mappings().all()
        return [dict(r) for r in rows]

    rows = await run_central_query(_read) or []
    return {"groups": _serialize_rows(rows), "total": len(rows), "central_db_configured": True}


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


@router.post("/sync", dependencies=[require_admin])
async def sync_now(request: Request) -> dict:
    """Run one identity sync cycle immediately."""
    if not settings.keycloak_sync_enable:
        raise HTTPException(
            status_code=409,
            detail="keycloak_sync_enable is false — enable the local Keycloak first",
        )
    result = await run_sync_once()
    return {"triggered_by": _actor(request) or "system", "result": result.to_dict()}


@router.get("/whoami", dependencies=[require_view])
async def whoami() -> dict:
    """Ping Keycloak to confirm the gov-hub can auth. Short-timeout probe."""
    if not settings.keycloak_sync_enable:
        return {"ok": False, "reason": "keycloak_sync_enable=false"}
    from ..services.keycloak_sync import _build_client
    try:
        client = _build_client()
        realm = await client.get_realm()
        return {
            "ok": True,
            "realm": realm.get("realm"),
            "display_name": realm.get("displayName"),
            "enabled": bool(realm.get("enabled", True)),
            "keycloak_url": settings.keycloak_url,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make datetimes JSON-safe."""
    out = []
    for r in rows:
        row = {}
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
            else:
                row[k] = v
        out.append(row)
    return out
