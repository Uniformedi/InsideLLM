"""
Fleet management service — cross-instance visibility via the central database.

All central DB operations use synchronous SQLAlchemy sessions run in a thread
pool via run_central_query(). This supports all database types (PostgreSQL,
MariaDB, MSSQL/pymssql) without requiring async drivers.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

from ..config import settings
from ..db.central_db import run_central_query, get_central_session_factory


async def list_instances() -> list[dict]:
    """List all registered InsideLLM instances from the central DB."""
    from ..db.central_sql import SQL

    def _query(db):
        result = db.execute(text(SQL.list_instances))
        instances = []
        for row in result.mappings():
            tel = db.execute(text(SQL.latest_telemetry), {"iid": row["instance_id"]})
            tel_row = tel.mappings().first()
            instances.append({
                **dict(row),
                "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "latest_telemetry": dict(tel_row) if tel_row else None,
            })
        return instances

    result = await run_central_query(_query)
    return result if result is not None else []


async def get_instance_detail(instance_id: str) -> dict | None:
    """Get detailed info for a specific instance including telemetry history."""
    from ..db.central_sql import SQL

    def _query(db):
        result = db.execute(text(SQL.instance_detail), {"iid": instance_id})
        instance = result.mappings().first()
        if not instance:
            return None

        tel_result = db.execute(text(SQL.telemetry_history), {"iid": instance_id})
        telemetry = [dict(r) for r in tel_result.mappings()]

        changes = []
        try:
            changes_result = db.execute(text(SQL.instance_changes), {"iid": instance_id})
            changes = [dict(r) for r in changes_result.mappings()]
        except Exception:
            pass

        return {
            "instance": dict(instance),
            "telemetry_history": telemetry,
            "recent_changes": changes,
        }

    return await run_central_query(_query)


async def compare_instances(instance_ids: list[str]) -> dict:
    """Compare configuration and metrics across multiple instances."""
    from ..db.central_sql import SQL

    def _query(db):
        comparisons = []
        for iid in instance_ids:
            inst_result = db.execute(text(SQL.instance_detail), {"iid": iid})
            inst = inst_result.mappings().first()
            if not inst:
                comparisons.append({"instance_id": iid, "error": "not found"})
                continue
            tel = db.execute(text(SQL.latest_telemetry), {"iid": iid})
            tel_row = tel.mappings().first()
            comparisons.append({**dict(inst), "telemetry": dict(tel_row) if tel_row else None})
        return {"instances": comparisons, "compared_at": datetime.now(timezone.utc).isoformat()}

    result = await run_central_query(_query)
    return result if result is not None else {"error": "Central DB not configured"}


async def get_fleet_summary() -> dict:
    """Aggregate fleet-wide metrics."""
    from ..db.central_sql import SQL

    def _query(db):
        count_result = db.execute(text(SQL.fleet_count))
        total = count_result.mappings().first()["cnt"]

        agg_result = db.execute(text(SQL.fleet_aggregate))
        agg = agg_result.mappings().first()

        industry_result = db.execute(text(SQL.fleet_by_industry))
        by_industry = {r["industry"]: r["cnt"] for r in industry_result.mappings()}

        stale_result = db.execute(text(SQL.fleet_stale))
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

    result = await run_central_query(_query)
    return result if result is not None else {"error": "Central DB not configured", "total_instances": 0}


# =========================================================================
# Fleet DB connection test / config
# =========================================================================

def _build_sync_url(config: dict) -> str:
    """Build a synchronous SQLAlchemy URL."""
    db_type = config["db_type"]
    user = config.get("username", "")
    password = config.get("password", "")
    host = config["host"]
    port = config.get("port", 5432)
    db_name = config.get("db_name", "insidellm_central")
    windows_auth = config.get("windows_auth", False)

    if db_type == "postgresql":
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    elif db_type in ("mariadb", "mysql"):
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}"
    elif db_type == "mssql":
        if windows_auth:
            # Windows Integrated Auth — no user/password in URL
            return f"mssql+pymssql://@{host}:{port}/{db_name}"
        return f"mssql+pymssql://{user}:{password}@{host}:{port}/{db_name}"
    raise ValueError(f"Unsupported database type: {db_type}")


async def test_db_connection(config: dict) -> dict:
    """Test a database connection without persisting."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

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
                connect_args = {"login_timeout": 5, "tds_version": "7.3"}

            engine = create_engine(url, pool_size=1, max_overflow=0,
                                   pool_pre_ping=False, connect_args=connect_args)
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

    connected = False
    try:
        connected = get_central_session_factory() is not None
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
    """Save central DB config to the local database (settings overrides table)."""
    from ..db.local_db import SyncSessionLocal
    from ..db.models import SettingsOverride

    mapping = {
        "central_db_type": config["db_type"],
        "central_db_host": config["host"],
        "central_db_port": str(config["port"]),
        "central_db_name": config["db_name"],
        "central_db_user": config.get("username", ""),
        "central_db_password": config.get("password", ""),
        "central_db_windows_auth": str(config.get("windows_auth", False)).lower(),
    }

    try:
        with SyncSessionLocal() as db:
            for key, value in mapping.items():
                existing = db.execute(
                    text("SELECT id FROM governance_settings_overrides WHERE key = :k"),
                    {"k": key},
                ).first()
                if existing:
                    db.execute(
                        text("UPDATE governance_settings_overrides SET value = :v, updated_at = NOW() WHERE key = :k"),
                        {"k": key, "v": value},
                    )
                else:
                    override = SettingsOverride(key=key, value=value)
                    db.add(override)
            db.commit()

        # Hot-reload settings in memory
        _apply_overrides_to_settings(mapping)

        return {"success": True, "message": "Configuration saved to database. Applied immediately (no restart needed)."}
    except Exception as e:
        return {"success": False, "message": str(e)}


def _apply_overrides_to_settings(overrides: dict) -> None:
    """Hot-reload config overrides into the running settings singleton."""
    for key, value in overrides.items():
        if hasattr(settings, key):
            field_type = type(getattr(settings, key))
            if field_type == int:
                value = int(value)
            elif field_type == bool:
                value = value.lower() in ("true", "1", "yes")
            object.__setattr__(settings, key, value)

    # Reset central DB engine to pick up new config
    import importlib
    from ..db import central_db
    central_db._central_engine = None
    central_db._CentralSession = None


def load_settings_overrides() -> None:
    """Load settings overrides from the database on startup."""
    from ..db.local_db import SyncSessionLocal

    try:
        with SyncSessionLocal() as db:
            result = db.execute(text("SELECT key, value FROM governance_settings_overrides"))
            overrides = {row[0]: row[1] for row in result}
            if overrides:
                _apply_overrides_to_settings(overrides)
                import logging
                logging.getLogger("governance-hub").info(f"Loaded {len(overrides)} settings overrides from DB")
    except Exception:
        pass  # Table may not exist yet on first startup


# =========================================================================
# Central DB schema initialization
# =========================================================================

# DDL statements use IF NOT EXISTS (PostgreSQL/MariaDB) or
# conditional checks (MSSQL) to be safely re-runnable.

_TABLES_POSTGRESQL = [
    """CREATE TABLE IF NOT EXISTS governance_instances (
        instance_id VARCHAR(100) PRIMARY KEY,
        instance_name VARCHAR(200),
        industry VARCHAR(50),
        governance_tier VARCHAR(20),
        data_classification VARCHAR(30),
        schema_version INTEGER DEFAULT 1,
        platform_version VARCHAR(20) DEFAULT 'unknown',
        last_sync_at TIMESTAMP,
        status VARCHAR(20) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS governance_telemetry (
        id SERIAL PRIMARY KEY,
        instance_id VARCHAR(100) REFERENCES governance_instances(instance_id),
        instance_name VARCHAR(200),
        schema_version INTEGER,
        platform_version VARCHAR(20) DEFAULT 'unknown',
        period_start TIMESTAMP,
        period_end TIMESTAMP,
        total_requests BIGINT DEFAULT 0,
        total_spend NUMERIC(12,4) DEFAULT 0,
        unique_users INTEGER DEFAULT 0,
        dlp_blocks INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        keyword_flags_critical INTEGER DEFAULT 0,
        keyword_flags_high INTEGER DEFAULT 0,
        compliance_score NUMERIC(5,1),
        industry VARCHAR(50),
        governance_tier VARCHAR(20),
        metrics_json TEXT,
        synced_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS governance_config_snapshots (
        id INTEGER,
        instance_id VARCHAR(100),
        schema_version INTEGER,
        config_json JSONB,
        diff_from_previous JSONB,
        snapshot_at TIMESTAMP,
        created_by VARCHAR(100),
        PRIMARY KEY (id, instance_id)
    )""",
    """CREATE TABLE IF NOT EXISTS governance_changes (
        id SERIAL PRIMARY KEY,
        instance_id VARCHAR(100),
        title VARCHAR(300),
        category VARCHAR(50),
        description TEXT,
        source VARCHAR(30),
        proposed_by VARCHAR(100),
        proposed_at TIMESTAMP DEFAULT NOW(),
        status VARCHAR(20) DEFAULT 'pending',
        reviewed_by VARCHAR(100),
        reviewed_at TIMESTAMP,
        reviewer_comments TEXT,
        framework_version INTEGER,
        implemented_at TIMESTAMP
    )""",
]

_TABLES_MSSQL = [
    """IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'governance_instances')
    CREATE TABLE governance_instances (
        instance_id VARCHAR(100) PRIMARY KEY,
        instance_name VARCHAR(200),
        industry VARCHAR(50),
        governance_tier VARCHAR(20),
        data_classification VARCHAR(30),
        schema_version INT DEFAULT 1,
        platform_version VARCHAR(20) DEFAULT 'unknown',
        last_sync_at DATETIME2,
        status VARCHAR(20) DEFAULT 'active',
        created_at DATETIME2 DEFAULT GETDATE()
    )""",
    """IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'governance_telemetry')
    CREATE TABLE governance_telemetry (
        id INT IDENTITY(1,1) PRIMARY KEY,
        instance_id VARCHAR(100),
        instance_name VARCHAR(200),
        schema_version INT,
        platform_version VARCHAR(20) DEFAULT 'unknown',
        period_start DATETIME2,
        period_end DATETIME2,
        total_requests BIGINT DEFAULT 0,
        total_spend DECIMAL(12,4) DEFAULT 0,
        unique_users INT DEFAULT 0,
        dlp_blocks INT DEFAULT 0,
        error_count INT DEFAULT 0,
        keyword_flags_critical INT DEFAULT 0,
        keyword_flags_high INT DEFAULT 0,
        compliance_score DECIMAL(5,1),
        industry VARCHAR(50),
        governance_tier VARCHAR(20),
        metrics_json NVARCHAR(MAX),
        synced_at DATETIME2 DEFAULT GETDATE()
    )""",
    """IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'governance_config_snapshots')
    CREATE TABLE governance_config_snapshots (
        id INT,
        instance_id VARCHAR(100),
        schema_version INT,
        config_json NVARCHAR(MAX),
        diff_from_previous NVARCHAR(MAX),
        snapshot_at DATETIME2,
        created_by VARCHAR(100),
        PRIMARY KEY (id, instance_id)
    )""",
    """IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'governance_changes')
    CREATE TABLE governance_changes (
        id INT IDENTITY(1,1) PRIMARY KEY,
        instance_id VARCHAR(100),
        title VARCHAR(300),
        category VARCHAR(50),
        description NVARCHAR(MAX),
        source VARCHAR(30),
        proposed_by VARCHAR(100),
        proposed_at DATETIME2 DEFAULT GETDATE(),
        status VARCHAR(20) DEFAULT 'pending',
        reviewed_by VARCHAR(100),
        reviewed_at DATETIME2,
        reviewer_comments NVARCHAR(MAX),
        framework_version INT,
        implemented_at DATETIME2
    )""",
]

_TABLES_MARIADB = [
    """CREATE TABLE IF NOT EXISTS governance_instances (
        instance_id VARCHAR(100) PRIMARY KEY,
        instance_name VARCHAR(200),
        industry VARCHAR(50),
        governance_tier VARCHAR(20),
        data_classification VARCHAR(30),
        schema_version INT DEFAULT 1,
        platform_version VARCHAR(20) DEFAULT 'unknown',
        last_sync_at DATETIME,
        status VARCHAR(20) DEFAULT 'active',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS governance_telemetry (
        id INT AUTO_INCREMENT PRIMARY KEY,
        instance_id VARCHAR(100),
        instance_name VARCHAR(200),
        schema_version INT,
        platform_version VARCHAR(20) DEFAULT 'unknown',
        period_start DATETIME,
        period_end DATETIME,
        total_requests BIGINT DEFAULT 0,
        total_spend DECIMAL(12,4) DEFAULT 0,
        unique_users INT DEFAULT 0,
        dlp_blocks INT DEFAULT 0,
        error_count INT DEFAULT 0,
        keyword_flags_critical INT DEFAULT 0,
        keyword_flags_high INT DEFAULT 0,
        compliance_score DECIMAL(5,1),
        industry VARCHAR(50),
        governance_tier VARCHAR(20),
        metrics_json LONGTEXT,
        synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS governance_config_snapshots (
        id INT,
        instance_id VARCHAR(100),
        schema_version INT,
        config_json LONGTEXT,
        diff_from_previous LONGTEXT,
        snapshot_at DATETIME,
        created_by VARCHAR(100),
        PRIMARY KEY (id, instance_id)
    )""",
    """CREATE TABLE IF NOT EXISTS governance_changes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        instance_id VARCHAR(100),
        title VARCHAR(300),
        category VARCHAR(50),
        description TEXT,
        source VARCHAR(30),
        proposed_by VARCHAR(100),
        proposed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(20) DEFAULT 'pending',
        reviewed_by VARCHAR(100),
        reviewed_at DATETIME,
        reviewer_comments TEXT,
        framework_version INT,
        implemented_at DATETIME
    )""",
]


async def initialize_central_db(config: dict) -> dict:
    """Create governance tables in the central database if they don't exist."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    try:
        url = _build_sync_url(config)
    except ValueError as e:
        return {"success": False, "message": str(e), "tables_created": []}

    db_type = config["db_type"]
    if db_type == "mssql":
        ddl_list = _TABLES_MSSQL
    elif db_type in ("mariadb", "mysql"):
        ddl_list = _TABLES_MARIADB
    else:
        ddl_list = _TABLES_POSTGRESQL

    def _init_sync() -> dict:
        engine = None
        try:
            connect_args: dict = {}
            if "psycopg2" in url:
                connect_args = {"connect_timeout": 10}
            elif "pymssql" in url:
                connect_args = {"login_timeout": 10, "tds_version": "7.3"}

            engine = create_engine(url, pool_size=1, max_overflow=0, connect_args=connect_args)
            created = []
            skipped = []
            with engine.connect() as conn:
                for ddl in ddl_list:
                    # Extract table name for reporting
                    table_name = "unknown"
                    for word in ddl.split():
                        if word.startswith("governance_"):
                            table_name = word.rstrip("(")
                            break
                    try:
                        conn.execute(text(ddl))
                        created.append(table_name)
                    except Exception as e:
                        err = str(e)
                        if "already exists" in err.lower():
                            skipped.append(table_name)
                        else:
                            return {"success": False, "message": f"Failed on {table_name}: {err[:200]}",
                                    "tables_created": created, "tables_skipped": skipped}
                conn.commit()
            return {
                "success": True,
                "message": f"Initialized {len(created)} tables ({len(skipped)} already existed)",
                "tables_created": created,
                "tables_skipped": skipped,
            }
        except Exception as e:
            msg = str(e)[:200]
            return {"success": False, "message": msg, "tables_created": [], "tables_skipped": []}
        finally:
            if engine:
                engine.dispose()

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, _init_sync)
