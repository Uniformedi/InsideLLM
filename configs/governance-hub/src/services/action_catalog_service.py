"""Action catalog CRUD + idempotent seeding (P1.3).

The catalog is the registry every agent's manifest.actions[] references by
action_id. Rows are scoped by tenant — `tenant_id="core"` entries are
shared across all tenants; per-tenant rows override core for the same
action_id.

Design
------
* **Pydantic is the gate**: every write validates against ActionCatalogEntry.
  Invalid entries never reach the DB.
* **Idempotent seeding**: `seed_entries(entries)` can be called on every
  startup — identical payloads are no-ops, changed payloads bump version
  and re-record audit.
* **Hash-chained audit**: every create/update/delete emits an
  `action_created` / `action_updated` / `action_retired` event.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ActionCatalog
from ..schemas.actions import ActionCatalogEntry
from .audit_chain import append_event

logger = logging.getLogger("governance-hub.actions")

CORE_TENANT = "core"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_to_row(entry: ActionCatalogEntry) -> dict[str, Any]:
    """Flatten a validated entry into kwargs for an ActionCatalog row."""
    dumped = entry.model_dump(mode="json")
    return {
        "action_id": entry.action_id,
        "tenant_id": entry.tenant_id or CORE_TENANT,
        "display_name": entry.display_name,
        "description": entry.description,
        "category": entry.category,
        "entry_json": dumped,
        "schema_version": entry.schema_version,
        "backend_type": dumped["backend"]["type"],
        "minimum_guardrail_tier": entry.guardrail_requirements.minimum_guardrail_tier,
        "requires_approval": entry.guardrail_requirements.requires_approval,
        "deprecated": entry.deprecated,
        "version": entry.version,
        "maintainer": entry.maintainer,
    }


def _same_payload(row: ActionCatalog, fields: dict[str, Any]) -> bool:
    """Semantic equality — only the fields that actually define behavior.
    Ignores updated_at + id + created_at + entry_json ordering."""
    return (
        row.display_name == fields["display_name"]
        and row.description == fields["description"]
        and row.category == fields["category"]
        and row.schema_version == fields["schema_version"]
        and row.backend_type == fields["backend_type"]
        and row.minimum_guardrail_tier == fields["minimum_guardrail_tier"]
        and bool(row.requires_approval) == bool(fields["requires_approval"])
        and bool(row.deprecated) == bool(fields["deprecated"])
        and row.version == fields["version"]
        and row.maintainer == fields["maintainer"]
        # JSONB round-trip can reorder keys; compare canonical form.
        and json.dumps(row.entry_json or {}, sort_keys=True)
        == json.dumps(fields["entry_json"], sort_keys=True)
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_action(
    db: AsyncSession,
    tenant_id: str,
    action_id: str,
) -> ActionCatalog | None:
    stmt = select(ActionCatalog).where(
        ActionCatalog.tenant_id == tenant_id,
        ActionCatalog.action_id == action_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def resolve_action(
    db: AsyncSession,
    tenant_id: str,
    action_id: str,
) -> ActionCatalog | None:
    """Tenant-scoped lookup with core fallback.

    Order of preference:
      1. exact (tenant_id, action_id)
      2. ("core", action_id)
    """
    row = await get_action(db, tenant_id, action_id)
    if row is not None:
        return row
    if tenant_id == CORE_TENANT:
        return None
    return await get_action(db, CORE_TENANT, action_id)


async def list_actions(
    db: AsyncSession,
    tenant_id: str | None = None,
    category: str | None = None,
    include_deprecated: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[ActionCatalog]:
    stmt = select(ActionCatalog).order_by(
        ActionCatalog.tenant_id, ActionCatalog.action_id
    )
    if tenant_id:
        # When asking for a specific tenant, also return core entries
        # unless tenant == core itself.
        if tenant_id == CORE_TENANT:
            stmt = stmt.where(ActionCatalog.tenant_id == CORE_TENANT)
        else:
            stmt = stmt.where(ActionCatalog.tenant_id.in_([tenant_id, CORE_TENANT]))
    if category:
        stmt = stmt.where(ActionCatalog.category == category)
    if not include_deprecated:
        stmt = stmt.where(ActionCatalog.deprecated == False)  # noqa: E712
    stmt = stmt.limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def upsert_action(
    db: AsyncSession,
    entry: ActionCatalogEntry,
    actor_email: str | None = None,
) -> tuple[ActionCatalog, str]:
    """Create or update. Returns (row, op) where op ∈ {created, updated, unchanged}."""
    fields = _entry_to_row(entry)
    existing = await get_action(db, fields["tenant_id"], fields["action_id"])
    actor = actor_email or "system"
    if existing is None:
        row = ActionCatalog(**fields)
        db.add(row)
        await db.flush()
        await append_event(db, "action_created", row.id, {
            "action_id": row.action_id,
            "tenant_id": row.tenant_id,
            "backend_type": row.backend_type,
            "minimum_guardrail_tier": row.minimum_guardrail_tier,
            "version": row.version,
            "actor": actor,
        })
        await db.commit()
        await db.refresh(row)
        logger.info(
            f"action_created: {row.tenant_id}/{row.action_id} v{row.version}"
        )
        return row, "created"

    if _same_payload(existing, fields):
        return existing, "unchanged"

    for k, v in fields.items():
        setattr(existing, k, v)
    existing.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await append_event(db, "action_updated", existing.id, {
        "action_id": existing.action_id,
        "tenant_id": existing.tenant_id,
        "version": existing.version,
        "actor": actor,
    })
    await db.commit()
    await db.refresh(existing)
    logger.info(
        f"action_updated: {existing.tenant_id}/{existing.action_id} v{existing.version}"
    )
    return existing, "updated"


async def retire_action(
    db: AsyncSession,
    tenant_id: str,
    action_id: str,
    actor_email: str | None = None,
) -> ActionCatalog | None:
    """Mark an action as deprecated. Agents referencing it will be denied
    at runtime with `deprecated_action` in the OPA deny reasons."""
    row = await get_action(db, tenant_id, action_id)
    if row is None:
        return None
    if row.deprecated:
        return row
    row.deprecated = True
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await append_event(db, "action_retired", row.id, {
        "action_id": row.action_id,
        "tenant_id": row.tenant_id,
        "actor": actor_email or "system",
    })
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Bulk seeding (bootstrap the core wrappers)
# ---------------------------------------------------------------------------


async def seed_entries(
    db: AsyncSession,
    entries: list[ActionCatalogEntry],
    actor_email: str = "action_seed",
) -> dict[str, int]:
    """Idempotent bulk upsert.

    Returns a counter: {created, updated, unchanged, failed}.
    A failure on one entry does NOT abort the rest.
    """
    counts = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for entry in entries:
        try:
            _, op = await upsert_action(db, entry, actor_email=actor_email)
            counts[op] = counts.get(op, 0) + 1
        except Exception as e:
            counts["failed"] += 1
            logger.warning(
                f"action seed failed for {entry.action_id}: {type(e).__name__}: {e}"
            )
    return counts


def parse_multi_action_document(body: str, content_type: str = "application/yaml") -> list[ActionCatalogEntry]:
    """Accept either a single entry or a document with `actions: [...]`.

    Multi-action YAML file shape:

        schema_version: "1.0"
        actions:
          - action_id: foo
            ...
          - action_id: bar
            ...
    """
    content_type = (content_type or "").lower()
    if "yaml" in content_type or "yml" in content_type:
        import yaml
        data: Any = yaml.safe_load(body)
    else:
        data = json.loads(body)
    if not isinstance(data, (dict, list)):
        raise ValueError("action document must be an object or list")

    if isinstance(data, list):
        # Bare list of entries.
        return [ActionCatalogEntry.model_validate(d) for d in data]

    if "actions" in data and isinstance(data["actions"], list):
        return [ActionCatalogEntry.model_validate(d) for d in data["actions"]]

    # Single entry.
    return [ActionCatalogEntry.model_validate(data)]
