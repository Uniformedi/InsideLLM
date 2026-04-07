from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..db.models import AuditChainEntry
from ..middleware.auth import verify_api_key
from ..services.audit_chain import get_chain_stats, verify_chain

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/chain/stats")
async def chain_stats(db: AsyncSession = Depends(get_local_db)) -> dict:
    """Get audit chain statistics: total entries, latest hash, checkpoints."""
    return await get_chain_stats(db)


@router.post("/chain/verify", dependencies=[Depends(verify_api_key)])
async def verify(
    from_sequence: int | None = None,
    to_sequence: int | None = None,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    """
    Walk the hash chain and verify integrity.

    Returns whether the chain is valid, how many entries were checked,
    and the first broken link if tampering is detected.
    """
    return await verify_chain(db, from_sequence, to_sequence)


@router.get("/chain/entries")
async def list_entries(
    limit: int = 50,
    offset: int = 0,
    event_type: str | None = None,
    db: AsyncSession = Depends(get_local_db),
) -> list[dict]:
    """List recent audit chain entries."""
    query = select(AuditChainEntry).order_by(AuditChainEntry.sequence.desc())
    if event_type:
        query = query.where(AuditChainEntry.event_type == event_type)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return [
        {
            "sequence": e.sequence,
            "event_type": e.event_type,
            "event_id": e.event_id,
            "payload_hash": e.payload_hash,
            "previous_hash": e.previous_hash,
            "chain_hash": e.chain_hash,
            "instance_id": e.instance_id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in result.scalars().all()
    ]


@router.get("/chain/entry/{sequence}")
async def get_entry(sequence: int, db: AsyncSession = Depends(get_local_db)) -> dict:
    """Get a specific chain entry by sequence number."""
    result = await db.execute(
        select(AuditChainEntry).where(AuditChainEntry.sequence == sequence)
    )
    e = result.scalar_one_or_none()
    if not e:
        return {"error": "Entry not found"}
    return {
        "sequence": e.sequence,
        "event_type": e.event_type,
        "event_id": e.event_id,
        "payload_hash": e.payload_hash,
        "previous_hash": e.previous_hash,
        "chain_hash": e.chain_hash,
        "instance_id": e.instance_id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
