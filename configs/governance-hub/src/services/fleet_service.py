"""
Fleet management service — cross-instance visibility via the central database.

Reads from the central DB to provide a unified view of all InsideLLM
deployments: status, config versions, compliance scores, telemetry.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

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
