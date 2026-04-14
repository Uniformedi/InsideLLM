"""Organizational shared skills router.

A skill is a named prompt + model + temperature + tool allowlist that
employees can pick from in Open WebUI and the browser extension. Skills
are authored by governance admins, gated by AD group, and (when
published) synced to Open WebUI as custom models.

Endpoints
---------
GET    /api/v1/skills              list skills visible to caller
GET    /api/v1/skills/{slug}       fetch one skill
POST   /api/v1/skills              create (admin only)
PATCH  /api/v1/skills/{slug}       update (admin only)
DELETE /api/v1/skills/{slug}       delete (admin only)
POST   /api/v1/skills/{slug}/publish   publish + sync to Open WebUI
POST   /api/v1/skills/{slug}/unpublish unpublish + remove from Open WebUI
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..db.models import SharedSkill

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Pydantic DTOs
# ---------------------------------------------------------------------------

class SkillBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    system_prompt: str = Field(..., min_length=1)
    base_model: str = Field("claude-sonnet", max_length=100)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    group_allowlist: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)


class SkillCreate(SkillBase):
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")


class SkillUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1)
    system_prompt: Optional[str] = Field(None, min_length=1)
    base_model: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    group_allowlist: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    tool_allowlist: Optional[list[str]] = None


class SkillOut(SkillBase):
    slug: str
    is_published: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Auth helpers — caller identity comes from the Governance Hub session cookie
# (set by /auth/login after LDAP bind). We reuse the same pattern used by
# /admin: a subrequest validates the cookie; here we pull the same claims off
# the request state if the auth middleware populated them.
# ---------------------------------------------------------------------------

def _caller_groups(request: Request) -> list[str]:
    """Return AD groups the caller is a member of, lower-cased for matching."""
    groups = getattr(request.state, "ad_groups", None) or []
    return [g.lower() for g in groups]


def _caller_is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def _caller_name(request: Request) -> str:
    return getattr(request.state, "user_id", "") or getattr(request.state, "user_name", "") or "unknown"


def _visible_to(skill: SharedSkill, caller_groups: list[str]) -> bool:
    """A skill with an empty allowlist is visible to everyone. Otherwise the
    caller must be a member of at least one allowed group."""
    allow = skill.group_allowlist or []
    if not allow:
        return True
    allow_lower = {g.lower() for g in allow}
    return any(g in allow_lower for g in caller_groups)


def _require_admin(request: Request) -> None:
    if not _caller_is_admin(request):
        raise HTTPException(status_code=403, detail="Skills administration requires admin role")


def _to_out(skill: SharedSkill) -> SkillOut:
    return SkillOut(
        slug=skill.slug,
        name=skill.name,
        description=skill.description,
        system_prompt=skill.system_prompt,
        base_model=skill.base_model,
        temperature=float(skill.temperature),
        group_allowlist=list(skill.group_allowlist or []),
        tags=list(skill.tags or []),
        tool_allowlist=list(skill.tool_allowlist or []),
        is_published=bool(skill.is_published),
        created_by=skill.created_by,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=dict)
async def list_skills(
    request: Request,
    tag: Optional[str] = None,
    published_only: bool = False,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """List skills visible to the caller. Non-admins only see published
    skills whose group_allowlist matches them."""
    stmt = select(SharedSkill).order_by(SharedSkill.name)
    if published_only or not _caller_is_admin(request):
        stmt = stmt.where(SharedSkill.is_published.is_(True))

    result = await db.execute(stmt)
    skills = result.scalars().all()

    caller_groups = _caller_groups(request)
    is_admin = _caller_is_admin(request)

    out = []
    for s in skills:
        if not is_admin and not _visible_to(s, caller_groups):
            continue
        if tag and tag not in (s.tags or []):
            continue
        out.append(_to_out(s))

    return {"skills": [o.model_dump(mode="json") for o in out], "count": len(out)}


@router.get("/{slug}", response_model=SkillOut)
async def get_skill(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> SkillOut:
    result = await db.execute(select(SharedSkill).where(SharedSkill.slug == slug))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    if not _caller_is_admin(request):
        if not skill.is_published or not _visible_to(skill, _caller_groups(request)):
            raise HTTPException(status_code=404, detail="Skill not found")

    return _to_out(skill)


@router.post("", response_model=SkillOut, status_code=201)
async def create_skill(
    payload: SkillCreate,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> SkillOut:
    _require_admin(request)

    existing = await db.execute(select(SharedSkill).where(SharedSkill.slug == payload.slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Skill '{payload.slug}' already exists")

    skill = SharedSkill(
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        base_model=payload.base_model,
        temperature=payload.temperature,
        group_allowlist=payload.group_allowlist,
        tags=payload.tags,
        tool_allowlist=payload.tool_allowlist,
        is_published=False,
        created_by=_caller_name(request),
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return _to_out(skill)


@router.patch("/{slug}", response_model=SkillOut)
async def update_skill(
    slug: str,
    payload: SkillUpdate,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> SkillOut:
    _require_admin(request)

    result = await db.execute(select(SharedSkill).where(SharedSkill.slug == slug))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(skill, key, value)
    skill.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(skill)

    # Re-sync to Open WebUI if currently published and the changes affect
    # the runtime shape of the model.
    if skill.is_published:
        try:
            from ..services.skill_sync_service import sync_skill_to_openwebui
            await sync_skill_to_openwebui(skill)
        except Exception:
            pass  # sync is best-effort — UI can retry via publish endpoint

    return _to_out(skill)


@router.delete("/{slug}", status_code=204)
async def delete_skill(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> None:
    _require_admin(request)

    result = await db.execute(select(SharedSkill).where(SharedSkill.slug == slug))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Best-effort teardown in Open WebUI before we drop the row.
    if skill.is_published:
        try:
            from ..services.skill_sync_service import remove_skill_from_openwebui
            await remove_skill_from_openwebui(skill)
        except Exception:
            pass

    await db.delete(skill)
    await db.commit()


@router.post("/{slug}/publish", response_model=SkillOut)
async def publish_skill(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> SkillOut:
    _require_admin(request)

    result = await db.execute(select(SharedSkill).where(SharedSkill.slug == slug))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    skill.is_published = True
    skill.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(skill)

    from ..services.skill_sync_service import sync_skill_to_openwebui
    await sync_skill_to_openwebui(skill)
    return _to_out(skill)


@router.post("/{slug}/unpublish", response_model=SkillOut)
async def unpublish_skill(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> SkillOut:
    _require_admin(request)

    result = await db.execute(select(SharedSkill).where(SharedSkill.slug == slug))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    skill.is_published = False
    skill.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(skill)

    from ..services.skill_sync_service import remove_skill_from_openwebui
    await remove_skill_from_openwebui(skill)
    return _to_out(skill)
