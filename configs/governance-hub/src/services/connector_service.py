"""
Data Connector service — manages external data source registration,
access control enforcement, and proxied query execution.

Supported connector types:
- postgresql, mysql, mssql: SQL databases via SQLAlchemy
- rest_api: HTTP endpoints with configurable auth
- s3: AWS S3 / MinIO object listing and retrieval
- smb: Windows file share listing
"""

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ..config import settings
from ..db.models import ConnectorAccessRule, ConnectorQueryLog, DataConnector
from .audit_chain import append_event

# Simple in-memory encryption key derivation from hub secret
# In production, use a proper KMS or Vault integration
def _mask_sensitive(config: dict) -> dict:
    """Redact passwords/keys for display."""
    masked = dict(config)
    for key in ("password", "secret", "api_key", "token", "access_key", "secret_key"):
        if key in masked:
            masked[key] = "***"
    return masked


# ================================================================
# CRUD
# ================================================================

async def create_connector(db: AsyncSession, data: dict, created_by: str) -> DataConnector:
    connector = DataConnector(
        name=data["name"],
        connector_type=data["connector_type"],
        description=data.get("description", ""),
        connection_config=data["connection_config"],
        data_classification=data.get("data_classification", "internal"),
        enabled=data.get("enabled", True),
        created_by=created_by,
    )
    db.add(connector)
    await db.flush()
    await append_event(db, "connector_created", connector.id, {
        "name": connector.name,
        "type": connector.connector_type,
        "classification": connector.data_classification,
        "created_by": created_by,
    })
    await db.commit()
    await db.refresh(connector)
    return connector


async def list_connectors(db: AsyncSession) -> list[DataConnector]:
    result = await db.execute(select(DataConnector).order_by(DataConnector.name))
    return list(result.scalars().all())


async def get_connector(db: AsyncSession, connector_id: int) -> DataConnector | None:
    result = await db.execute(select(DataConnector).where(DataConnector.id == connector_id))
    return result.scalar_one_or_none()


async def delete_connector(db: AsyncSession, connector_id: int) -> bool:
    connector = await get_connector(db, connector_id)
    if not connector:
        return False
    await db.delete(connector)
    await db.commit()
    return True


async def test_connector(db: AsyncSession, connector_id: int) -> dict:
    """Test connectivity to a data source."""
    connector = await get_connector(db, connector_id)
    if not connector:
        return {"status": "error", "message": "Connector not found"}

    try:
        result = await _execute_test(connector)
        connector.last_tested_at = datetime.now(timezone.utc)
        connector.last_test_status = "success"
        await db.commit()
        return {"status": "success", "message": result}
    except Exception as e:
        connector.last_tested_at = datetime.now(timezone.utc)
        connector.last_test_status = "error"
        await db.commit()
        return {"status": "error", "message": str(e)[:500]}


# ================================================================
# Access Control
# ================================================================

async def grant_access(db: AsyncSession, data: dict) -> ConnectorAccessRule:
    rule = ConnectorAccessRule(
        connector_id=data["connector_id"],
        grant_type=data["grant_type"],
        grant_value=data["grant_value"],
        permission=data.get("permission", "read"),
        row_filter=data.get("row_filter"),
        field_mask=data.get("field_mask"),
        granted_by=data["granted_by"],
        expires_at=data.get("expires_at"),
    )
    db.add(rule)
    await db.flush()
    await append_event(db, "connector_access_granted", rule.id, {
        "connector_id": data["connector_id"],
        "grant_type": data["grant_type"],
        "grant_value": data["grant_value"],
        "permission": data.get("permission", "read"),
        "granted_by": data["granted_by"],
    })
    await db.commit()
    await db.refresh(rule)
    return rule


async def revoke_access(db: AsyncSession, rule_id: int) -> bool:
    result = await db.execute(select(ConnectorAccessRule).where(ConnectorAccessRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        return False
    await db.delete(rule)
    await append_event(db, "connector_access_revoked", rule_id, {
        "connector_id": rule.connector_id,
        "grant_value": rule.grant_value,
    })
    await db.commit()
    return True


async def list_access_rules(db: AsyncSession, connector_id: int) -> list[ConnectorAccessRule]:
    result = await db.execute(
        select(ConnectorAccessRule)
        .where(ConnectorAccessRule.connector_id == connector_id)
        .order_by(ConnectorAccessRule.granted_at.desc())
    )
    return list(result.scalars().all())


async def check_access(db: AsyncSession, connector_id: int, username: str, teams: list[str]) -> ConnectorAccessRule | None:
    """Check if a user or any of their teams has access to a connector."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(ConnectorAccessRule)
        .where(ConnectorAccessRule.connector_id == connector_id)
        .where(
            (ConnectorAccessRule.expires_at.is_(None)) | (ConnectorAccessRule.expires_at > now)
        )
    )
    rules = result.scalars().all()

    for rule in rules:
        if rule.grant_type == "user" and rule.grant_value == username:
            return rule
        if rule.grant_type == "team" and rule.grant_value in teams:
            return rule
        if rule.grant_type == "role" and rule.grant_value == "*":
            return rule

    return None


# ================================================================
# Query Execution
# ================================================================

async def execute_query(
    db: AsyncSession,
    connector_id: int,
    query: str,
    username: str,
    teams: list[str] | None = None,
    params: dict | None = None,
) -> dict:
    """Execute a query against an external data source with access control."""
    connector = await get_connector(db, connector_id)
    if not connector:
        return {"status": "error", "message": "Connector not found", "data": []}
    if not connector.enabled:
        return {"status": "error", "message": "Connector is disabled", "data": []}

    # Check access
    rule = await check_access(db, connector_id, username, teams or [])
    if not rule:
        log = ConnectorQueryLog(
            connector_id=connector_id,
            connector_name=connector.name,
            queried_by=username,
            query_type="denied",
            query_text=query[:500],
            status="denied",
            error_message=f"Access denied for user {username}",
        )
        db.add(log)
        await db.commit()
        return {"status": "denied", "message": f"Access denied. No access rule for user '{username}' or teams {teams}.", "data": []}

    # Execute
    start = time.time()
    try:
        result = await _execute_query(connector, query, params, rule)
        duration = int((time.time() - start) * 1000)

        log = ConnectorQueryLog(
            connector_id=connector_id,
            connector_name=connector.name,
            queried_by=username,
            query_type=connector.connector_type,
            query_text=query[:500],
            row_count=len(result.get("data", [])),
            duration_ms=duration,
            status="success",
        )
        db.add(log)
        await db.commit()

        return {"status": "success", "data": result.get("data", []), "row_count": log.row_count, "duration_ms": duration}

    except Exception as e:
        duration = int((time.time() - start) * 1000)
        log = ConnectorQueryLog(
            connector_id=connector_id,
            connector_name=connector.name,
            queried_by=username,
            query_type=connector.connector_type,
            query_text=query[:500],
            duration_ms=duration,
            status="error",
            error_message=str(e)[:1000],
        )
        db.add(log)
        await db.commit()
        return {"status": "error", "message": str(e)[:500], "data": []}


async def get_query_log(db: AsyncSession, connector_id: int | None = None, limit: int = 50) -> list[ConnectorQueryLog]:
    query = select(ConnectorQueryLog).order_by(ConnectorQueryLog.queried_at.desc())
    if connector_id:
        query = query.where(ConnectorQueryLog.connector_id == connector_id)
    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


# ================================================================
# Driver-specific execution
# ================================================================

async def _execute_test(connector: DataConnector) -> str:
    config = connector.connection_config
    ctype = connector.connector_type

    if ctype in ("postgresql", "mysql", "mssql"):
        url = _build_db_url(ctype, config)
        engine = create_async_engine(url, pool_size=1)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
        await engine.dispose()
        return f"Connected to {ctype} at {config.get('host', '?')}"

    elif ctype == "rest_api":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(config.get("base_url", ""), headers=_api_headers(config))
            return f"HTTP {resp.status_code} from {config.get('base_url', '?')}"

    return f"Test not implemented for type: {ctype}"


async def _execute_query(connector: DataConnector, query: str, params: dict | None, rule: ConnectorAccessRule) -> dict:
    config = connector.connection_config
    ctype = connector.connector_type

    if ctype in ("postgresql", "mysql", "mssql"):
        return await _query_database(ctype, config, query, params, rule)
    elif ctype == "rest_api":
        return await _query_api(config, query, params)
    else:
        raise ValueError(f"Query not supported for connector type: {ctype}")


async def _query_database(ctype: str, config: dict, query: str, params: dict | None, rule: ConnectorAccessRule) -> dict:
    # Safety: block write operations for read-only access
    if rule.permission == "read":
        upper = query.strip().upper()
        if any(upper.startswith(kw) for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE")):
            raise PermissionError("Write operations not allowed with read-only access")

    url = _build_db_url(ctype, config)
    engine = create_async_engine(url, pool_size=1)
    try:
        async with engine.connect() as conn:
            # Apply row filter if defined
            effective_query = query
            if rule.row_filter:
                effective_query = f"SELECT * FROM ({query}) _q WHERE {rule.row_filter}"

            result = await conn.execute(text(effective_query), params or {})
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            # Apply field mask if defined
            if rule.field_mask:
                allowed = set(rule.field_mask.get("allowed", []))
                denied = set(rule.field_mask.get("denied", []))
                if allowed:
                    rows = [{k: v for k, v in row.items() if k in allowed} for row in rows]
                elif denied:
                    rows = [{k: v for k, v in row.items() if k not in denied} for row in rows]

            return {"data": rows[:1000]}  # Cap at 1000 rows
    finally:
        await engine.dispose()


async def _query_api(config: dict, query: str, params: dict | None) -> dict:
    base_url = config.get("base_url", "")
    endpoint = query.lstrip("/")
    url = f"{base_url}/{endpoint}" if endpoint else base_url

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_api_headers(config), params=params)
        resp.raise_for_status()
        return {"data": [resp.json()] if isinstance(resp.json(), dict) else resp.json()}


def _build_db_url(ctype: str, config: dict) -> str:
    driver_map = {"postgresql": "postgresql+asyncpg", "mysql": "mysql+aiomysql", "mssql": "mssql+pymssql"}
    driver = driver_map.get(ctype, ctype)
    return f"{driver}://{config['user']}:{config['password']}@{config['host']}:{config.get('port', 5432)}/{config['database']}"


def _api_headers(config: dict) -> dict:
    headers = dict(config.get("headers", {}))
    if config.get("api_key"):
        auth_header = config.get("auth_header", "Authorization")
        auth_prefix = config.get("auth_prefix", "Bearer")
        headers[auth_header] = f"{auth_prefix} {config['api_key']}"
    return headers
