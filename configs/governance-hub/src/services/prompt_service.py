"""
System prompt service — manages governance-controlled meta-prompts.

Prompts are stored in the local PostgreSQL database. The active prompt
per tier is pushed to Redis so the LiteLLM custom callback can read it
with minimal latency on every request.
"""

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.models import SystemPrompt

logger = logging.getLogger("governance-hub.prompts")

REDIS_KEY_PREFIX = "insidellm:system_prompt:"


async def get_active_prompt(db: AsyncSession, tier: str) -> SystemPrompt | None:
    """Get the currently active prompt for a governance tier."""
    result = await db.execute(
        select(SystemPrompt)
        .where(SystemPrompt.tier == tier, SystemPrompt.is_active == True)
        .order_by(SystemPrompt.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_prompts(db: AsyncSession, tier: str | None = None) -> list[SystemPrompt]:
    """List all prompts, optionally filtered by tier."""
    query = select(SystemPrompt).order_by(SystemPrompt.tier, SystemPrompt.version.desc())
    if tier:
        query = query.where(SystemPrompt.tier == tier)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_prompt(db: AsyncSession, tier: str, prompt_text: str, created_by: str) -> SystemPrompt:
    """Create a new prompt version (inactive by default)."""
    # Get next version number for this tier
    result = await db.execute(
        text("SELECT COALESCE(MAX(version), 0) + 1 FROM governance_system_prompts WHERE tier = :tier"),
        {"tier": tier},
    )
    next_version = result.scalar()

    prompt = SystemPrompt(
        tier=tier,
        prompt_text=prompt_text,
        is_active=False,
        version=next_version,
        created_by=created_by,
    )
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return prompt


async def activate_prompt(db: AsyncSession, prompt_id: int) -> SystemPrompt:
    """Activate a prompt and deactivate all others for the same tier."""
    prompt = await db.get(SystemPrompt, prompt_id)
    if not prompt:
        raise ValueError(f"Prompt {prompt_id} not found")

    # Deactivate all prompts for this tier
    await db.execute(
        text("UPDATE governance_system_prompts SET is_active = false WHERE tier = :tier"),
        {"tier": prompt.tier},
    )

    # Activate the selected one
    prompt.is_active = True
    prompt.activated_at = datetime.now(timezone.utc)
    await db.commit()

    # Push to Redis
    await push_to_redis(prompt.tier, prompt.prompt_text)

    logger.info(f"Activated prompt #{prompt.id} for {prompt.tier} (v{prompt.version})")
    return prompt


async def push_to_redis(tier: str, prompt_text: str) -> bool:
    """Push a prompt to Redis for the LiteLLM callback to read."""
    try:
        import redis
        r = redis.Redis(host="redis", port=6379, decode_responses=True)
        r.set(f"{REDIS_KEY_PREFIX}{tier}", prompt_text)
        r.close()
        logger.info(f"Pushed prompt to Redis: {REDIS_KEY_PREFIX}{tier}")
        return True
    except Exception as e:
        logger.warning(f"Failed to push prompt to Redis: {e}")
        return False


async def seed_defaults(db: AsyncSession) -> int:
    """Seed default prompts if none exist."""
    from .prompt_defaults import TIER1_PROMPT, TIER2_PROMPT, TIER3_PROMPT

    result = await db.execute(text("SELECT COUNT(*) FROM governance_system_prompts"))
    count = result.scalar()
    if count > 0:
        return 0

    seeded = 0
    for tier, text_content in [("tier1", TIER1_PROMPT), ("tier2", TIER2_PROMPT), ("tier3", TIER3_PROMPT)]:
        prompt = SystemPrompt(
            tier=tier,
            prompt_text=text_content.strip(),
            is_active=True,
            version=1,
            created_by="system",
            activated_at=datetime.now(timezone.utc),
        )
        db.add(prompt)
        seeded += 1

    await db.commit()

    # Push all to Redis
    for tier, text_content in [("tier1", TIER1_PROMPT), ("tier2", TIER2_PROMPT), ("tier3", TIER3_PROMPT)]:
        await push_to_redis(tier, text_content.strip())

    logger.info(f"Seeded {seeded} default system prompts")
    return seeded
