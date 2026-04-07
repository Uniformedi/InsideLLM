from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..middleware.auth import verify_api_key, verify_supervisor
from ..services.connector_service import (
    check_access,
    create_connector,
    delete_connector,
    execute_query,
    get_connector,
    get_query_log,
    grant_access,
    list_access_rules,
    list_connectors,
    revoke_access,
    test_connector,
)

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


# ================================================================
# Schemas
# ================================================================

class ConnectorCreate(BaseModel):
    name: str = Field(..., max_length=255)
    connector_type: str = Field(..., pattern="^(postgresql|mysql|mssql|rest_api|s3|smb|sharepoint)$")
    description: str = ""
    connection_config: dict[str, Any] = Field(...)
    data_classification: str = Field(default="internal", pattern="^(public|internal|confidential|restricted)$")
    enabled: bool = True


class AccessGrant(BaseModel):
    connector_id: int
    grant_type: str = Field(..., pattern="^(team|user|role)$")
    grant_value: str = Field(..., max_length=255)
    permission: str = Field(default="read", pattern="^(read|write|admin)$")
    row_filter: str | None = None
    field_mask: dict | None = None
    expires_at: str | None = None


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=5000)
    username: str
    teams: list[str] = []
    params: dict[str, Any] | None = None


# ================================================================
# Connector CRUD
# ================================================================

@router.get("/")
async def list_all(db: AsyncSession = Depends(get_local_db)):
    connectors = await list_connectors(db)
    return [{
        "id": c.id, "name": c.name, "type": c.connector_type,
        "description": c.description, "classification": c.data_classification,
        "enabled": c.enabled, "created_by": c.created_by,
        "last_test_status": c.last_test_status,
    } for c in connectors]


@router.post("/", dependencies=[Depends(verify_supervisor)])
async def create(data: ConnectorCreate, db: AsyncSession = Depends(get_local_db)):
    connector = await create_connector(db, data.model_dump(), created_by="admin")
    return {"id": connector.id, "name": connector.name, "status": "created"}


@router.get("/{connector_id}")
async def get_detail(connector_id: int, db: AsyncSession = Depends(get_local_db)):
    connector = await get_connector(db, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    # Mask sensitive fields
    config = dict(connector.connection_config)
    for key in ("password", "secret", "api_key", "token", "access_key", "secret_key"):
        if key in config:
            config[key] = "***"
    return {
        "id": connector.id, "name": connector.name, "type": connector.connector_type,
        "description": connector.description, "connection_config": config,
        "classification": connector.data_classification, "enabled": connector.enabled,
        "created_by": connector.created_by, "created_at": connector.created_at,
        "last_tested_at": connector.last_tested_at, "last_test_status": connector.last_test_status,
    }


@router.delete("/{connector_id}", dependencies=[Depends(verify_supervisor)])
async def delete(connector_id: int, db: AsyncSession = Depends(get_local_db)):
    if await delete_connector(db, connector_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Connector not found")


@router.post("/{connector_id}/test", dependencies=[Depends(verify_api_key)])
async def test(connector_id: int, db: AsyncSession = Depends(get_local_db)):
    return await test_connector(db, connector_id)


# ================================================================
# Access Control
# ================================================================

@router.get("/{connector_id}/access")
async def list_access(connector_id: int, db: AsyncSession = Depends(get_local_db)):
    rules = await list_access_rules(db, connector_id)
    return [{
        "id": r.id, "grant_type": r.grant_type, "grant_value": r.grant_value,
        "permission": r.permission, "row_filter": r.row_filter,
        "field_mask": r.field_mask, "granted_by": r.granted_by,
        "granted_at": r.granted_at, "expires_at": r.expires_at,
    } for r in rules]


@router.post("/access", dependencies=[Depends(verify_supervisor)])
async def grant(data: AccessGrant, db: AsyncSession = Depends(get_local_db)):
    rule = await grant_access(db, {**data.model_dump(), "granted_by": "admin"})
    return {"id": rule.id, "status": "granted"}


@router.delete("/access/{rule_id}", dependencies=[Depends(verify_supervisor)])
async def revoke(rule_id: int, db: AsyncSession = Depends(get_local_db)):
    if await revoke_access(db, rule_id):
        return {"status": "revoked"}
    raise HTTPException(status_code=404, detail="Access rule not found")


# ================================================================
# Query Execution
# ================================================================

@router.post("/{connector_id}/query", dependencies=[Depends(verify_api_key)])
async def query(connector_id: int, req: QueryRequest, db: AsyncSession = Depends(get_local_db)):
    return await execute_query(db, connector_id, req.query, req.username, req.teams, req.params)


# ================================================================
# Query Log
# ================================================================

@router.get("/logs/queries")
async def query_logs(connector_id: int | None = None, limit: int = 50, db: AsyncSession = Depends(get_local_db)):
    logs = await get_query_log(db, connector_id, limit)
    return [{
        "id": l.id, "connector_name": l.connector_name, "queried_by": l.queried_by,
        "query_type": l.query_type, "row_count": l.row_count,
        "duration_ms": l.duration_ms, "status": l.status,
        "queried_at": l.queried_at,
    } for l in logs]
