from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.models import ConfigSnapshot
from ..schemas.config import ConfigDiff
from .audit_chain import append_event


async def capture_snapshot(db: AsyncSession, created_by: str = "system") -> ConfigSnapshot:
    """Capture the current instance configuration as a versioned snapshot."""
    config = await _gather_config(db)

    # Get previous snapshot for diff
    prev = await db.execute(
        select(ConfigSnapshot)
        .where(ConfigSnapshot.instance_id == settings.instance_id)
        .order_by(ConfigSnapshot.id.desc())
        .limit(1)
    )
    prev_snapshot = prev.scalar_one_or_none()
    diff = _compute_diff(prev_snapshot.config_json, config) if prev_snapshot else None

    snapshot = ConfigSnapshot(
        instance_id=settings.instance_id,
        schema_version=settings.schema_version,
        config_json=config,
        diff_from_previous=diff,
        created_by=created_by,
    )
    db.add(snapshot)
    await db.flush()
    await append_event(db, "config_snapshot", snapshot.id, {
        "schema_version": settings.schema_version,
        "created_by": created_by,
        "has_diff": diff is not None,
    })
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_snapshots(db: AsyncSession, limit: int = 20) -> list[ConfigSnapshot]:
    result = await db.execute(
        select(ConfigSnapshot)
        .where(ConfigSnapshot.instance_id == settings.instance_id)
        .order_by(ConfigSnapshot.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_snapshot(db: AsyncSession, snapshot_id: int) -> ConfigSnapshot | None:
    result = await db.execute(select(ConfigSnapshot).where(ConfigSnapshot.id == snapshot_id))
    return result.scalar_one_or_none()


async def diff_snapshots(db: AsyncSession, id_a: int, id_b: int) -> ConfigDiff | None:
    a = await get_snapshot(db, id_a)
    b = await get_snapshot(db, id_b)
    if not a or not b:
        return None

    diff = _compute_diff(a.config_json, b.config_json)
    return ConfigDiff(
        snapshot_a_id=id_a,
        snapshot_b_id=id_b,
        added=diff.get("added", {}),
        removed=diff.get("removed", {}),
        changed=diff.get("changed", {}),
    )


async def _gather_config(db: AsyncSession) -> dict:
    """Gather full instance configuration for snapshot/restore.

    Captures everything needed to recreate an InsideLLM deployment:
    governance settings, models, teams, budgets, DLP, keyword categories,
    operations config, and supervisor contacts.
    """
    import os

    config = {
        # Instance identity
        "instance_id": settings.instance_id,
        "instance_name": settings.instance_name,
        "schema_version": settings.schema_version,
        "platform_version": settings.platform_version,
        "captured_at": datetime.now(timezone.utc).isoformat(),

        # Governance
        "industry": settings.industry,
        "governance_tier": settings.governance_tier,
        "data_classification": settings.data_classification,
        "advisor_model": settings.advisor_model,
        "supervisor_emails": settings.supervisor_emails,
        "sync_schedule": settings.sync_schedule,

        # DLP (from environment — set by Terraform)
        "dlp_enable": os.environ.get("DLP_ENABLE", "true").lower() == "true",
        "dlp_block_ssn": os.environ.get("DLP_BLOCK_SSN", "true").lower() == "true",
        "dlp_block_credit_cards": os.environ.get("DLP_BLOCK_CREDIT_CARDS", "true").lower() == "true",
        "dlp_block_phi": os.environ.get("DLP_BLOCK_PHI", "true").lower() == "true",
        "dlp_block_credentials": os.environ.get("DLP_BLOCK_CREDENTIALS", "true").lower() == "true",
    }

    # LiteLLM settings (from environment)
    config["litellm"] = {
        "default_model": os.environ.get("LITELLM_DEFAULT_MODEL", "claude-sonnet"),
        "global_max_budget": int(os.environ.get("LITELLM_GLOBAL_MAX_BUDGET", "100")),
        "default_user_budget": float(os.environ.get("LITELLM_DEFAULT_USER_BUDGET", "5")),
        "default_user_rpm": int(os.environ.get("LITELLM_DEFAULT_USER_RPM", "30")),
        "default_user_tpm": int(os.environ.get("LITELLM_DEFAULT_USER_TPM", "100000")),
    }

    # Operations config
    config["ops"] = {
        "watchtower_enable": os.environ.get("OPS_WATCHTOWER_ENABLE", "true").lower() == "true",
        "trivy_enable": os.environ.get("OPS_TRIVY_ENABLE", "true").lower() == "true",
        "grafana_enable": os.environ.get("OPS_GRAFANA_ENABLE", "true").lower() == "true",
        "uptime_kuma_enable": os.environ.get("OPS_UPTIME_KUMA_ENABLE", "true").lower() == "true",
        "backup_schedule": os.environ.get("OPS_BACKUP_SCHEDULE", "daily"),
        "alert_webhook": os.environ.get("OPS_ALERT_WEBHOOK", ""),
    }

    # Teams (table may not exist yet — rollback on error to keep transaction clean)
    try:
        result = await db.execute(text(
            'SELECT team_alias, max_budget, budget_duration, tpm_limit, rpm_limit, models FROM "LiteLLM_TeamTable"'
        ))
        config["teams"] = [dict(r._mapping) for r in result]
    except Exception:
        await db.rollback()
        config["teams"] = []

    # Models
    try:
        result = await db.execute(text('SELECT model_name FROM "LiteLLM_ModelTable"'))
        config["models"] = [r[0] for r in result]
    except Exception:
        await db.rollback()
        config["models"] = []

    # Keyword categories
    try:
        result = await db.execute(text("SELECT category, keyword, severity FROM keyword_categories ORDER BY category, keyword"))
        config["keyword_categories"] = [dict(r._mapping) for r in result]
    except Exception:
        await db.rollback()
        config["keyword_categories"] = []

    # Per-user budgets
    try:
        result = await db.execute(text(
            'SELECT user_id, max_budget, tpm_limit, rpm_limit FROM "LiteLLM_UserTable" WHERE max_budget IS NOT NULL LIMIT 50'
        ))
        config["user_budgets"] = [dict(r._mapping) for r in result]
    except Exception:
        await db.rollback()
        config["user_budgets"] = []

    return config


def _compute_diff(old: dict, new: dict) -> dict:
    """Simple top-level diff between two config dictionaries."""
    added = {k: v for k, v in new.items() if k not in old}
    removed = {k: v for k, v in old.items() if k not in new}
    changed = {}
    for k in set(old.keys()) & set(new.keys()):
        if old[k] != new[k]:
            changed[k] = {"before": old[k], "after": new[k]}
    return {"added": added, "removed": removed, "changed": changed}
