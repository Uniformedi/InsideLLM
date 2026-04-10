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
    """Gather current instance configuration from various sources."""
    config = {
        "instance_id": settings.instance_id,
        "instance_name": settings.instance_name,
        "schema_version": settings.schema_version,
        "industry": settings.industry,
        "governance_tier": settings.governance_tier,
        "data_classification": settings.data_classification,
        "advisor_model": settings.advisor_model,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    # Teams (table may not exist yet — rollback on error to keep transaction clean)
    try:
        result = await db.execute(text('SELECT team_alias, max_budget, tpm_limit, rpm_limit FROM "LiteLLM_TeamTable"'))
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
