import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.central_db import get_central_session_factory
from ..db.models import InstanceRegistry, SyncLog, TelemetryExport
from ..schemas.sync import SyncExportEnvelope, SyncStatus, TelemetrySummary
from .audit_chain import append_event


async def collect_telemetry(db: AsyncSession, days: int = 1) -> TelemetrySummary:
    """Collect governance telemetry from local PostgreSQL."""
    now = datetime.now(timezone.utc)
    # Use naive datetime for LiteLLM queries (its startTime is timestamp without tz)
    since_naive = (now - timedelta(days=days)).replace(tzinfo=None)

    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total_requests,
            COALESCE(SUM(spend), 0) AS total_spend,
            COUNT(DISTINCT "user") AS unique_users,
            COUNT(*) FILTER (WHERE status != 'success') AS error_count
        FROM "LiteLLM_SpendLogs"
        WHERE "startTime" > :since
    """), {"since": since_naive})
    row = result.mappings().first()

    # Keyword flags (table may not exist if keyword analysis not configured)
    flag_row = None
    try:
        flags = await db.execute(text("""
            SELECT
                COALESCE(SUM(CASE WHEN severity = 'critical' THEN match_count ELSE 0 END), 0) AS critical,
                COALESCE(SUM(CASE WHEN severity = 'high' THEN match_count ELSE 0 END), 0) AS high
            FROM keyword_daily_summary
            WHERE day > :since
        """), {"since": since_naive})
        flag_row = flags.mappings().first()
    except Exception:
        await db.rollback()

    # Top models
    models_result = await db.execute(text("""
        SELECT model, COUNT(*) AS cnt
        FROM "LiteLLM_SpendLogs"
        WHERE "startTime" > :since
        GROUP BY model ORDER BY cnt DESC LIMIT 10
    """), {"since": since_naive})
    top_models = {r["model"]: r["cnt"] for r in models_result.mappings()}

    # Compliance score: (1 - error_rate) * 100, capped at 100
    total = row["total_requests"] or 1
    error_rate = (row["error_count"] or 0) / total
    compliance_score = round(min(100.0, (1 - error_rate) * 100), 2)

    return TelemetrySummary(
        total_requests=row["total_requests"] or 0,
        total_spend=float(row["total_spend"] or 0),
        unique_users=row["unique_users"] or 0,
        error_count=row["error_count"] or 0,
        dlp_blocks=0,  # would require Loki query; placeholder
        keyword_flags_critical=flag_row["critical"] if flag_row else 0,
        keyword_flags_high=flag_row["high"] if flag_row else 0,
        compliance_score=compliance_score,
        top_models=top_models,
    )


async def export_to_central(local_db: AsyncSession, telemetry: TelemetrySummary) -> SyncLog:
    """Export telemetry to the central database."""
    start = time.time()
    factory = get_central_session_factory()

    if factory is None:
        log = SyncLog(
            status="skipped",
            records_exported=0,
            central_db_type=settings.central_db_type,
            error_message="Central DB not configured",
            duration_ms=0,
        )
        local_db.add(log)
        await local_db.commit()
        return log

    # Get snapshot from local DB before entering central DB context
    local_snap = await local_db.execute(text("""
        SELECT id, instance_id, schema_version, config_json, diff_from_previous, snapshot_at, created_by
        FROM governance_config_snapshots
        WHERE instance_id = :iid
        ORDER BY id DESC LIMIT 1
    """), {"iid": settings.instance_id})
    snap_row = local_snap.mappings().first()

    try:
        now = datetime.now(timezone.utc)
        tel_params = {
            "instance_id": settings.instance_id,
            "instance_name": settings.instance_name,
            "schema_version": settings.schema_version,
            "platform_version": settings.platform_version,
            "period_start": now - timedelta(days=1),
            "period_end": now,
            "total_requests": telemetry.total_requests,
            "total_spend": telemetry.total_spend,
            "unique_users": telemetry.unique_users,
            "dlp_blocks": telemetry.dlp_blocks,
            "error_count": telemetry.error_count,
            "kw_critical": telemetry.keyword_flags_critical,
            "kw_high": telemetry.keyword_flags_high,
            "compliance_score": telemetry.compliance_score,
            "industry": settings.industry,
            "tier": settings.governance_tier,
            "metrics": "{}",
        }
        snap_params = None
        if snap_row:
            import json as _json
            config_str = _json.dumps(snap_row["config_json"]) if isinstance(snap_row["config_json"], dict) else str(snap_row["config_json"])
            diff_str = _json.dumps(snap_row["diff_from_previous"]) if snap_row["diff_from_previous"] else None
            snap_params = {
                "id": snap_row["id"], "iid": snap_row["instance_id"],
                "sv": snap_row["schema_version"], "config": config_str,
                "diff": diff_str, "snap_at": snap_row["snapshot_at"],
                "created_by": snap_row["created_by"],
            }

        # Run all central DB operations via sync session in thread pool
        from ..db.central_db import run_central_query

        def _sync_export(central_db):
            central_db.execute(text("""
                INSERT INTO governance_instances (instance_id, instance_name, industry, governance_tier, data_classification, schema_version, platform_version, last_sync_at, status)
                VALUES (:id, :name, :industry, :tier, :classification, :schema_version, :platform_version, NOW(), 'active')
                ON CONFLICT (instance_id) DO UPDATE SET
                    instance_name = EXCLUDED.instance_name,
                    schema_version = EXCLUDED.schema_version,
                    platform_version = EXCLUDED.platform_version,
                    last_sync_at = NOW()
            """), {
                "id": settings.instance_id, "name": settings.instance_name,
                "industry": settings.industry, "tier": settings.governance_tier,
                "classification": settings.data_classification,
                "schema_version": settings.schema_version,
                "platform_version": settings.platform_version,
            })

            central_db.execute(text("""
                INSERT INTO governance_telemetry
                    (instance_id, instance_name, schema_version, platform_version, period_start, period_end,
                     total_requests, total_spend, unique_users, dlp_blocks, error_count,
                     keyword_flags_critical, keyword_flags_high, compliance_score, industry, governance_tier, metrics_json)
                VALUES
                    (:instance_id, :instance_name, :schema_version, :platform_version, :period_start, :period_end,
                     :total_requests, :total_spend, :unique_users, :dlp_blocks, :error_count,
                     :kw_critical, :kw_high, :compliance_score, :industry, :tier, :metrics)
            """), tel_params)

            if snap_params:
                central_db.execute(text("""
                    INSERT INTO governance_config_snapshots
                        (id, instance_id, schema_version, config_json, diff_from_previous, snapshot_at, created_by)
                    VALUES (:id, :iid, :sv, :config::jsonb, :diff::jsonb, :snap_at, :created_by)
                    ON CONFLICT (id, instance_id) DO UPDATE SET
                        config_json = EXCLUDED.config_json,
                        snapshot_at = EXCLUDED.snapshot_at
                """), snap_params)

            central_db.commit()
            return True

        await run_central_query(_sync_export)

        duration = int((time.time() - start) * 1000)
        log = SyncLog(status="success", records_exported=2, central_db_type=settings.central_db_type, duration_ms=duration)
        local_db.add(log)
        await local_db.flush()

        # Append to audit hash chain
        await append_event(local_db, "sync_export", log.id, {
            "telemetry": telemetry.model_dump(),
            "central_db_type": settings.central_db_type,
            "records_exported": 1,
        })
        await local_db.commit()
        return log

    except Exception as e:
        duration = int((time.time() - start) * 1000)
        log = SyncLog(status="error", records_exported=0, central_db_type=settings.central_db_type, error_message=str(e)[:1000], duration_ms=duration)
        local_db.add(log)
        await local_db.commit()
        return log
