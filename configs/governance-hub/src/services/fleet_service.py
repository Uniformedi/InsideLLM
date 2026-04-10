"""
Fleet management service — cross-instance visibility via the central database.

Reads from the central DB to provide a unified view of all InsideLLM
deployments: status, config versions, compliance scores, telemetry.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ..config import settings
from ..db.central_db import get_central_session_factory


async def list_instances() -> list[dict]:
    """List all registered InsideLLM instances from the central DB."""
    factory = get_central_session_factory()
    if not factory:
        return []

    async with factory() as db:
        result = await db.execute(text("""
            SELECT
                i.instance_id,
                i.instance_name,
                i.industry,
                i.governance_tier,
                i.data_classification,
                i.schema_version,
                i.platform_version,
                i.last_sync_at,
                i.status,
                i.created_at
            FROM governance_instances i
            ORDER BY i.instance_name
        """))
        instances = []
        for row in result.mappings():
            # Get latest telemetry for each instance
            tel = await db.execute(text("""
                SELECT total_requests, total_spend, unique_users,
                       compliance_score, keyword_flags_critical, keyword_flags_high
                FROM governance_telemetry
                WHERE instance_id = :iid
                ORDER BY synced_at DESC LIMIT 1
            """), {"iid": row["instance_id"]})
            tel_row = tel.mappings().first()

            instances.append({
                **dict(row),
                "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "latest_telemetry": dict(tel_row) if tel_row else None,
            })
        return instances


async def get_instance_detail(instance_id: str) -> dict | None:
    """Get detailed info for a specific instance including telemetry history."""
    factory = get_central_session_factory()
    if not factory:
        return None

    async with factory() as db:
        # Instance info
        result = await db.execute(text("""
            SELECT * FROM governance_instances WHERE instance_id = :iid
        """), {"iid": instance_id})
        instance = result.mappings().first()
        if not instance:
            return None

        # Telemetry history (last 30 entries)
        tel_result = await db.execute(text("""
            SELECT period_start, period_end, total_requests, total_spend,
                   unique_users, dlp_blocks, error_count,
                   keyword_flags_critical, keyword_flags_high,
                   compliance_score, synced_at
            FROM governance_telemetry
            WHERE instance_id = :iid
            ORDER BY synced_at DESC LIMIT 30
        """), {"iid": instance_id})
        telemetry = [dict(r) for r in tel_result.mappings()]

        # Change proposals from this instance
        changes_result = await db.execute(text("""
            SELECT id, title, category, status, source, proposed_at
            FROM governance_changes
            WHERE instance_id = :iid
            ORDER BY proposed_at DESC LIMIT 20
        """), {"iid": instance_id})
        # governance_changes may not have instance_id in central — fallback gracefully
        changes = []
        try:
            changes = [dict(r) for r in changes_result.mappings()]
        except Exception:
            pass

        return {
            "instance": dict(instance),
            "telemetry_history": telemetry,
            "recent_changes": changes,
        }


async def compare_instances(instance_ids: list[str]) -> dict:
    """Compare configuration and metrics across multiple instances."""
    factory = get_central_session_factory()
    if not factory:
        return {"error": "Central DB not configured"}

    async with factory() as db:
        comparisons = []
        for iid in instance_ids:
            # Instance info
            inst_result = await db.execute(text("""
                SELECT instance_id, instance_name, industry, governance_tier,
                       data_classification, schema_version, last_sync_at
                FROM governance_instances WHERE instance_id = :iid
            """), {"iid": iid})
            inst = inst_result.mappings().first()
            if not inst:
                comparisons.append({"instance_id": iid, "error": "not found"})
                continue

            # Latest telemetry
            tel = await db.execute(text("""
                SELECT total_requests, total_spend, unique_users,
                       compliance_score, keyword_flags_critical
                FROM governance_telemetry
                WHERE instance_id = :iid
                ORDER BY synced_at DESC LIMIT 1
            """), {"iid": iid})
            tel_row = tel.mappings().first()

            comparisons.append({
                **dict(inst),
                "telemetry": dict(tel_row) if tel_row else None,
            })

        return {"instances": comparisons, "compared_at": datetime.now(timezone.utc).isoformat()}


async def get_fleet_summary() -> dict:
    """Aggregate fleet-wide metrics."""
    factory = get_central_session_factory()
    if not factory:
        return {"error": "Central DB not configured", "total_instances": 0}

    async with factory() as db:
        # Count instances
        count_result = await db.execute(text("SELECT COUNT(*) AS cnt FROM governance_instances WHERE status = 'active'"))
        total = count_result.mappings().first()["cnt"]

        # Aggregate latest telemetry per instance
        agg_result = await db.execute(text("""
            SELECT
                COUNT(DISTINCT t.instance_id) AS reporting_instances,
                SUM(t.total_requests) AS fleet_requests,
                SUM(t.total_spend) AS fleet_spend,
                SUM(t.unique_users) AS fleet_users,
                AVG(t.compliance_score) AS avg_compliance_score,
                SUM(t.keyword_flags_critical) AS total_critical_flags
            FROM governance_telemetry t
            INNER JOIN (
                SELECT instance_id, MAX(synced_at) AS max_sync
                FROM governance_telemetry
                GROUP BY instance_id
            ) latest ON t.instance_id = latest.instance_id AND t.synced_at = latest.max_sync
        """))
        agg = agg_result.mappings().first()

        # Instances by industry
        industry_result = await db.execute(text("""
            SELECT industry, COUNT(*) AS cnt
            FROM governance_instances WHERE status = 'active'
            GROUP BY industry ORDER BY cnt DESC
        """))
        by_industry = {r["industry"]: r["cnt"] for r in industry_result.mappings()}

        # Stale instances (no sync in 24h)
        stale_result = await db.execute(text("""
            SELECT COUNT(*) AS cnt FROM governance_instances
            WHERE status = 'active' AND (last_sync_at IS NULL OR last_sync_at < NOW() - INTERVAL '24 hours')
        """))
        stale = stale_result.mappings().first()["cnt"]

        return {
            "total_instances": total,
            "reporting_instances": agg["reporting_instances"] or 0,
            "stale_instances": stale,
            "fleet_total_requests": agg["fleet_requests"] or 0,
            "fleet_total_spend": float(agg["fleet_spend"] or 0),
            "fleet_total_users": agg["fleet_users"] or 0,
            "avg_compliance_score": float(agg["avg_compliance_score"] or 0),
            "total_critical_flags": agg["total_critical_flags"] or 0,
            "instances_by_industry": by_industry,
        }


def _build_sync_url(config: dict) -> str:
    """Build a synchronous SQLAlchemy URL (works for all drivers)."""
    db_type = config["db_type"]
    user = config.get("username", "")
    password = config.get("password", "")
    host = config["host"]
    port = config.get("port", 5432)
    db_name = config.get("db_name", "insidellm_central")

    if db_type == "postgresql":
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    elif db_type in ("mariadb", "mysql"):
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}"
    elif db_type == "mssql":
        return f"mssql+pymssql://{user}:{password}@{host}:{port}/{db_name}"
    raise ValueError(f"Unsupported database type: {db_type}")


async def test_db_connection(config: dict) -> dict:
    """Test a database connection without persisting. Returns success, message, latency_ms."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine

    try:
        url = _build_sync_url(config)
    except ValueError as e:
        return {"success": False, "message": str(e), "latency_ms": 0}

    def _test_sync() -> dict:
        engine = None
        try:
            connect_args: dict = {}
            if "psycopg2" in url:
                connect_args = {"connect_timeout": 5}
            elif "pymssql" in url:
                connect_args = {
                    "login_timeout": 5,
                    "tds_version": "7.3",
                }
                if config.get("encrypt"):
                    connect_args["conn_properties"] = "Encrypt=yes;"
                if config.get("trust_server_certificate"):
                    connect_args["conn_properties"] = connect_args.get("conn_properties", "") + "TrustServerCertificate=yes;"

            engine = create_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=False,
                                   connect_args=connect_args)
            start = time.monotonic()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            latency = int((time.monotonic() - start) * 1000)
            return {"success": True, "message": "Connection successful", "latency_ms": latency}
        except Exception as e:
            msg = str(e)
            if "No module named" in msg or "ImportError" in msg:
                msg = f"Database driver not installed for {config['db_type']}"
            elif len(msg) > 200:
                msg = msg[:200]
            return {"success": False, "message": msg, "latency_ms": 0}
        finally:
            if engine:
                engine.dispose()

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, _test_sync)


def get_db_config() -> dict:
    """Return current central DB configuration with password masked."""
    if not settings.central_db_host:
        return {"configured": False, "connected": False}

    # Check connection status without creating an engine (avoids async driver issues)
    connected = False
    try:
        factory = get_central_session_factory()
        connected = factory is not None
    except Exception:
        pass

    return {
        "configured": True,
        "connected": connected,
        "db_type": settings.central_db_type,
        "host": settings.central_db_host,
        "port": settings.central_db_port,
        "db_name": settings.central_db_name,
        "username": settings.central_db_user,
        "password_set": bool(settings.central_db_password),
    }


def save_db_config(config: dict) -> dict:
    """Save central DB config to an env override file for next restart."""
    env_path = Path("/app/data/.env.central-db")
    try:
        lines = [
            f"GOVERNANCE_HUB_CENTRAL_DB_TYPE={config['db_type']}",
            f"GOVERNANCE_HUB_CENTRAL_DB_HOST={config['host']}",
            f"GOVERNANCE_HUB_CENTRAL_DB_PORT={config['port']}",
            f"GOVERNANCE_HUB_CENTRAL_DB_NAME={config['db_name']}",
            f"GOVERNANCE_HUB_CENTRAL_DB_USER={config['username']}",
            f"GOVERNANCE_HUB_CENTRAL_DB_PASSWORD={config['password']}",
        ]
        env_path.write_text("\n".join(lines) + "\n")
        return {"success": True, "message": f"Saved to {env_path}. Restart the Governance Hub container to apply."}
    except Exception as e:
        return {"success": False, "message": str(e)}
