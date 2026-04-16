"""Declarative agent CRUD + lifecycle service.

Responsibilities:
  - Validate incoming manifests against the v1.1 schema (pydantic).
  - Maintain `governance_agents` rows (one per (tenant_id, agent_id)).
  - Compute and pin manifest_hash (SHA-256) on every version.
  - Emit hash-chained audit entries on create / update / publish / retire.
  - For visibility ≥ org, route publish through governance_changes for
    tier-2+ approval (Phase 2 will wire the Teams/Slack approval UI on
    top of this; for now the proposal is created and manual approval
    via the existing /api/v1/changes endpoints unblocks publish).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Agent, ChangeProposal
from ..schemas.agents import (
    AgentManifest,
    AgentResponse,
    VisibilityScope,
)
from .audit_chain import append_event

logger = logging.getLogger("governance-hub.agents")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_manifest_hash(manifest: AgentManifest) -> str:
    """Stable SHA-256 of the manifest JSON. Deterministic: keys sorted,
    no whitespace — so two identical manifests always hash the same."""
    canon = manifest.model_dump(mode="json")
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _requires_approval(visibility: str) -> bool:
    """scope=org routes through tier-2 approval; scope=fleet routes tier-3."""
    return visibility in {VisibilityScope.ORG.value, VisibilityScope.FLEET.value}


def _row_to_response(row: Agent) -> AgentResponse:
    manifest = AgentManifest.model_validate(row.manifest_json)
    return AgentResponse(
        agent_id=row.agent_id,
        tenant_id=row.tenant_id,
        version=row.version,
        is_active=bool(row.is_active),
        status=row.status or "draft",
        manifest=manifest,
        manifest_hash=row.manifest_hash or "",
        created_at=row.created_at or datetime.now(timezone.utc),
        updated_at=row.updated_at or datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_agent(
    db: AsyncSession,
    tenant_id: str,
    agent_id: str,
) -> Agent | None:
    stmt = select(Agent).where(
        Agent.tenant_id == tenant_id,
        Agent.agent_id == agent_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_agents(
    db: AsyncSession,
    tenant_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    team: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Agent]:
    stmt = select(Agent).order_by(Agent.updated_at.desc())
    if tenant_id:
        stmt = stmt.where(Agent.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(Agent.status == status)
    if visibility:
        stmt = stmt.where(Agent.visibility_scope == visibility)
    if team:
        stmt = stmt.where(Agent.team == team)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create_agent(
    db: AsyncSession,
    manifest: AgentManifest,
    actor_email: str | None = None,
) -> Agent:
    """Insert a new agent row. Fails if (tenant_id, agent_id) already exists."""
    existing = await get_agent(db, manifest.tenant_id, manifest.agent_id)
    if existing is not None:
        raise ValueError(
            f"agent '{manifest.agent_id}' already exists in tenant '{manifest.tenant_id}'"
        )

    manifest_json = manifest.model_dump(mode="json")
    manifest_hash = compute_manifest_hash(manifest)

    row = Agent(
        agent_id=manifest.agent_id,
        tenant_id=manifest.tenant_id,
        name=manifest.display.name,
        description=manifest.display.description,
        icon=manifest.display.icon,
        team=manifest.team,
        created_by=manifest.created_by or actor_email,
        manifest_json=manifest_json,
        manifest_schema_version=manifest.schema_version,
        guardrail_profile=manifest.guardrails.profile,
        visibility_scope=manifest.visibility.scope if manifest.visibility else "private",
        data_classification="internal",
        status="draft",
        is_active=False,
        version=1,
        manifest_hash=manifest_hash,
    )
    db.add(row)
    await db.flush()

    await append_event(db, "agent_created", row.id, {
        "agent_id": row.agent_id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "guardrail_profile": row.guardrail_profile,
        "manifest_hash": manifest_hash,
        "actor": actor_email or "system",
    })
    await db.commit()
    await db.refresh(row)
    logger.info(
        f"agent_created: {row.tenant_id}/{row.agent_id} v{row.version} "
        f"hash={manifest_hash[:12]}"
    )
    return row


async def update_agent(
    db: AsyncSession,
    tenant_id: str,
    agent_id: str,
    manifest: AgentManifest,
    actor_email: str | None = None,
) -> Agent | None:
    """Update manifest. Bumps version if manifest_hash changed."""
    if manifest.tenant_id != tenant_id or manifest.agent_id != agent_id:
        raise ValueError("manifest tenant_id/agent_id must match URL path")

    row = await get_agent(db, tenant_id, agent_id)
    if row is None:
        return None

    manifest_json = manifest.model_dump(mode="json")
    new_hash = compute_manifest_hash(manifest)

    if new_hash == row.manifest_hash:
        # No effective change — refresh timestamp only.
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
        return row

    old_hash = row.manifest_hash
    row.manifest_json = manifest_json
    row.manifest_schema_version = manifest.schema_version
    row.name = manifest.display.name
    row.description = manifest.display.description
    row.icon = manifest.display.icon
    row.team = manifest.team
    row.guardrail_profile = manifest.guardrails.profile
    row.visibility_scope = (
        manifest.visibility.scope if manifest.visibility else row.visibility_scope
    )
    row.manifest_hash = new_hash
    row.version = (row.version or 1) + 1
    # A published agent whose manifest changed needs re-approval when
    # visibility ≥ org; downshift to draft and clear active flag.
    if _requires_approval(row.visibility_scope):
        row.status = "draft"
        row.is_active = False
    await db.flush()

    await append_event(db, "agent_updated", row.id, {
        "agent_id": row.agent_id,
        "tenant_id": row.tenant_id,
        "version": row.version,
        "manifest_hash": new_hash,
        "previous_hash": old_hash,
        "actor": actor_email or "system",
    })
    await db.commit()
    await db.refresh(row)
    logger.info(
        f"agent_updated: {row.tenant_id}/{row.agent_id} v{row.version} "
        f"hash={new_hash[:12]} (was {old_hash[:12] if old_hash else '?'})"
    )
    return row


async def delete_agent(
    db: AsyncSession,
    tenant_id: str,
    agent_id: str,
    actor_email: str | None = None,
) -> bool:
    """Soft-delete: mark retired + is_active=false. History preserved."""
    row = await get_agent(db, tenant_id, agent_id)
    if row is None:
        return False
    row.status = "retired"
    row.is_active = False
    await db.flush()

    await append_event(db, "agent_retired", row.id, {
        "agent_id": row.agent_id,
        "tenant_id": row.tenant_id,
        "version": row.version,
        "actor": actor_email or "system",
    })
    await db.commit()
    return True


async def publish_agent(
    db: AsyncSession,
    tenant_id: str,
    agent_id: str,
    actor_email: str | None = None,
) -> tuple[Agent | None, int | None]:
    """Publish an agent so it becomes invokable.

    Returns (row, pending_change_id).
      - If visibility ∈ {private, team}: published immediately, change_id=None.
      - If visibility ∈ {org, fleet}: creates a governance_changes proposal
        and leaves the agent in draft state with pending_change_id set.
        Approval via /api/v1/changes/{id}/approve flips the agent live.
    """
    row = await get_agent(db, tenant_id, agent_id)
    if row is None:
        return None, None

    if _requires_approval(row.visibility_scope):
        # Create governance_changes proposal.
        proposal = ChangeProposal(
            title=f"Publish agent '{row.agent_id}' (tenant={row.tenant_id})",
            description=(
                f"Requested by {actor_email or 'system'}. "
                f"Guardrail profile: {row.guardrail_profile}. "
                f"Visibility scope: {row.visibility_scope}. "
                f"Manifest hash: {row.manifest_hash}."
            ),
            category="agent",
            proposed_changes={
                "operation": "publish_agent",
                "tenant_id": row.tenant_id,
                "agent_id": row.agent_id,
                "version": row.version,
                "manifest_hash": row.manifest_hash,
                "guardrail_profile": row.guardrail_profile,
                "visibility_scope": row.visibility_scope,
            },
            proposed_by=actor_email or "system",
            source="agent_publish",
        )
        db.add(proposal)
        await db.flush()
        row.pending_change_id = proposal.id
        await db.flush()

        await append_event(db, "agent_publish_proposed", row.id, {
            "agent_id": row.agent_id,
            "tenant_id": row.tenant_id,
            "change_id": proposal.id,
            "visibility_scope": row.visibility_scope,
            "actor": actor_email or "system",
        })
        await db.commit()
        await db.refresh(row)
        logger.info(
            f"agent_publish_proposed: {row.tenant_id}/{row.agent_id} "
            f"change_id={proposal.id}"
        )
        return row, proposal.id

    # private / team — publish immediately.
    row.status = "published"
    row.is_active = True
    row.pending_change_id = None
    await db.flush()

    await append_event(db, "agent_published", row.id, {
        "agent_id": row.agent_id,
        "tenant_id": row.tenant_id,
        "version": row.version,
        "manifest_hash": row.manifest_hash,
        "visibility_scope": row.visibility_scope,
        "actor": actor_email or "system",
    })
    await db.commit()
    await db.refresh(row)
    logger.info(
        f"agent_published: {row.tenant_id}/{row.agent_id} v{row.version} "
        f"(visibility={row.visibility_scope})"
    )
    return row, None


async def retire_agent(
    db: AsyncSession,
    tenant_id: str,
    agent_id: str,
    actor_email: str | None = None,
) -> Agent | None:
    """Hide a published agent from the picker without deleting it."""
    row = await get_agent(db, tenant_id, agent_id)
    if row is None:
        return None
    row.status = "retired"
    row.is_active = False
    await db.flush()
    await append_event(db, "agent_retired", row.id, {
        "agent_id": row.agent_id,
        "tenant_id": row.tenant_id,
        "version": row.version,
        "actor": actor_email or "system",
    })
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# YAML authoring helper
# ---------------------------------------------------------------------------


def parse_manifest_from_text(body: str, content_type: str = "application/json") -> AgentManifest:
    """Accept either JSON or YAML; return validated pydantic model."""
    content_type = (content_type or "").lower()
    if "yaml" in content_type or "yml" in content_type:
        import yaml  # PyYAML is already a transitive dep
        data: Any = yaml.safe_load(body)
    else:
        data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("manifest must be an object")
    return AgentManifest.model_validate(data)
