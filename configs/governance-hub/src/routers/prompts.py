"""
System prompts router — manage governance-controlled meta-prompts
injected into every LLM call via LiteLLM custom callback.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..services.prompt_service import (
    activate_prompt,
    create_prompt,
    get_active_prompt,
    list_prompts,
    push_to_redis,
    seed_defaults,
)

router = APIRouter(prefix="/api/v1/prompts", tags=["system-prompts"])


class PromptCreate(BaseModel):
    tier: str  # tier1, tier2, tier3
    prompt_text: str
    created_by: str = "admin"


@router.get("")
async def get_prompts(tier: str = "", db: AsyncSession = Depends(get_local_db)):
    """List all system prompts, optionally filtered by tier."""
    prompts = await list_prompts(db, tier or None)
    return {
        "prompts": [
            {
                "id": p.id,
                "tier": p.tier,
                "prompt_text": p.prompt_text,
                "is_active": p.is_active,
                "version": p.version,
                "created_by": p.created_by,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "activated_at": p.activated_at.isoformat() if p.activated_at else None,
            }
            for p in prompts
        ],
        "total": len(prompts),
    }


@router.get("/active")
async def get_active(tier: str = "tier3", db: AsyncSession = Depends(get_local_db)):
    """Get the currently active prompt for a governance tier."""
    prompt = await get_active_prompt(db, tier)
    if not prompt:
        raise HTTPException(status_code=404, detail=f"No active prompt for {tier}")
    return {
        "id": prompt.id,
        "tier": prompt.tier,
        "prompt_text": prompt.prompt_text,
        "version": prompt.version,
        "activated_at": prompt.activated_at.isoformat() if prompt.activated_at else None,
    }


@router.post("")
async def create_new_prompt(data: PromptCreate, db: AsyncSession = Depends(get_local_db)):
    """Create a new prompt version (inactive until activated)."""
    if data.tier not in ("tier1", "tier2", "tier3"):
        raise HTTPException(status_code=400, detail="Tier must be tier1, tier2, or tier3")

    prompt = await create_prompt(db, data.tier, data.prompt_text, data.created_by)
    return {
        "id": prompt.id,
        "tier": prompt.tier,
        "version": prompt.version,
        "is_active": prompt.is_active,
        "message": f"Prompt v{prompt.version} created for {data.tier}. Use /activate to make it live.",
    }


@router.post("/{prompt_id}/activate")
async def activate(prompt_id: int, db: AsyncSession = Depends(get_local_db)):
    """Activate a prompt and push it to Redis for LiteLLM to use.

    Deactivates all other prompts for the same tier.
    Creates a governance audit record.
    """
    try:
        prompt = await activate_prompt(db, prompt_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Audit trail
    try:
        from ..db.models import ChangeProposal
        from datetime import datetime, timezone
        change = ChangeProposal(
            title=f"System prompt activated: {prompt.tier} v{prompt.version}",
            description=f"Activated system meta-prompt version {prompt.version} for {prompt.tier}",
            category="system_prompt",
            proposed_changes={"prompt_id": prompt.id, "tier": prompt.tier, "version": prompt.version},
            proposed_by=prompt.created_by,
            source="admin",
            status="implemented",
            implemented_at=datetime.now(timezone.utc),
        )
        db.add(change)
        await db.commit()
    except Exception:
        pass  # Audit is best-effort

    return {
        "id": prompt.id,
        "tier": prompt.tier,
        "version": prompt.version,
        "is_active": True,
        "message": f"Prompt v{prompt.version} is now active for {prompt.tier}. Pushed to Redis.",
    }


@router.post("/seed")
async def seed(db: AsyncSession = Depends(get_local_db)):
    """Seed default prompts if none exist."""
    count = await seed_defaults(db)
    return {"seeded": count, "message": f"Seeded {count} default prompts" if count else "Prompts already exist"}


@router.post("/push-all")
async def push_all_to_redis(db: AsyncSession = Depends(get_local_db)):
    """Push all active prompts to Redis (useful after restart)."""
    pushed = 0
    for tier in ("tier1", "tier2", "tier3"):
        prompt = await get_active_prompt(db, tier)
        if prompt:
            await push_to_redis(tier, prompt.prompt_text)
            pushed += 1
    return {"pushed": pushed}
