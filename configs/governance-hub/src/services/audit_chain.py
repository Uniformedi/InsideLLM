"""
Hash-chained audit integrity service.

Every governance event (sync exports, change proposals, approvals, config
snapshots) is appended to an immutable hash chain. Each entry contains:

  chain_hash = SHA-256(sequence || event_type || payload_hash || previous_hash)

Tampering with any record breaks the chain from that point forward. The
verify endpoint walks the chain and reports the first broken link.

Periodic checkpoints store the root hash at a given sequence number for
efficient partial verification.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.models import AuditChainCheckpoint, AuditChainEntry

GENESIS_HASH = "0" * 64  # The "previous hash" of the very first entry

CHECKPOINT_INTERVAL = 100  # Create a checkpoint every N entries


def hash_payload(payload: Any) -> str:
    """SHA-256 hash of a JSON-serialized payload."""
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_chain_hash(sequence: int, event_type: str, payload_hash: str, previous_hash: str) -> str:
    """Compute the chain hash for an entry."""
    data = f"{sequence}|{event_type}|{payload_hash}|{previous_hash}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


async def get_latest_entry(db: AsyncSession) -> AuditChainEntry | None:
    """Get the most recent chain entry."""
    result = await db.execute(
        select(AuditChainEntry).order_by(AuditChainEntry.sequence.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def append_event(
    db: AsyncSession,
    event_type: str,
    event_id: int | None,
    payload: Any,
) -> AuditChainEntry:
    """Append a new event to the hash chain."""
    latest = await get_latest_entry(db)
    previous_hash = latest.chain_hash if latest else GENESIS_HASH
    next_sequence = (latest.sequence + 1) if latest else 1

    p_hash = hash_payload(payload)
    c_hash = compute_chain_hash(next_sequence, event_type, p_hash, previous_hash)

    entry = AuditChainEntry(
        sequence=next_sequence,
        event_type=event_type,
        event_id=event_id,
        payload_hash=p_hash,
        previous_hash=previous_hash,
        chain_hash=c_hash,
        instance_id=settings.instance_id,
    )
    db.add(entry)

    # Auto-checkpoint
    if next_sequence % CHECKPOINT_INTERVAL == 0:
        checkpoint_from = next_sequence - CHECKPOINT_INTERVAL + 1
        checkpoint = AuditChainCheckpoint(
            sequence_from=checkpoint_from,
            sequence_to=next_sequence,
            root_hash=c_hash,
            entry_count=CHECKPOINT_INTERVAL,
        )
        db.add(checkpoint)

    await db.flush()
    return entry


async def verify_chain(
    db: AsyncSession,
    from_sequence: int | None = None,
    to_sequence: int | None = None,
) -> dict:
    """
    Walk the hash chain and verify integrity.

    Returns:
        {
            "valid": bool,
            "entries_checked": int,
            "first_broken_at": int | None,
            "expected_hash": str | None,
            "actual_hash": str | None,
            "chain_start": int,
            "chain_end": int,
        }
    """
    query = select(AuditChainEntry).order_by(AuditChainEntry.sequence.asc())
    if from_sequence is not None:
        query = query.where(AuditChainEntry.sequence >= from_sequence)
    if to_sequence is not None:
        query = query.where(AuditChainEntry.sequence <= to_sequence)

    result = await db.execute(query)
    entries = list(result.scalars().all())

    if not entries:
        return {
            "valid": True,
            "entries_checked": 0,
            "first_broken_at": None,
            "expected_hash": None,
            "actual_hash": None,
            "chain_start": 0,
            "chain_end": 0,
        }

    # If starting from the middle, get the previous entry's hash
    if from_sequence and from_sequence > 1:
        prev_result = await db.execute(
            select(AuditChainEntry).where(AuditChainEntry.sequence == from_sequence - 1)
        )
        prev_entry = prev_result.scalar_one_or_none()
        expected_previous = prev_entry.chain_hash if prev_entry else GENESIS_HASH
    else:
        expected_previous = GENESIS_HASH

    checked = 0
    for entry in entries:
        expected_chain = compute_chain_hash(
            entry.sequence, entry.event_type, entry.payload_hash, expected_previous
        )

        if entry.chain_hash != expected_chain:
            return {
                "valid": False,
                "entries_checked": checked,
                "first_broken_at": entry.sequence,
                "expected_hash": expected_chain,
                "actual_hash": entry.chain_hash,
                "chain_start": entries[0].sequence,
                "chain_end": entries[-1].sequence,
            }

        if entry.previous_hash != expected_previous:
            return {
                "valid": False,
                "entries_checked": checked,
                "first_broken_at": entry.sequence,
                "expected_hash": expected_previous,
                "actual_hash": entry.previous_hash,
                "chain_start": entries[0].sequence,
                "chain_end": entries[-1].sequence,
            }

        expected_previous = entry.chain_hash
        checked += 1

    return {
        "valid": True,
        "entries_checked": checked,
        "first_broken_at": None,
        "expected_hash": None,
        "actual_hash": None,
        "chain_start": entries[0].sequence,
        "chain_end": entries[-1].sequence,
    }


async def get_chain_stats(db: AsyncSession) -> dict:
    """Get chain statistics."""
    count_result = await db.execute(select(func.count(AuditChainEntry.id)))
    total = count_result.scalar_one()

    latest = await get_latest_entry(db)

    checkpoint_result = await db.execute(
        select(func.count(AuditChainCheckpoint.id))
    )
    checkpoints = checkpoint_result.scalar_one()

    return {
        "total_entries": total,
        "latest_sequence": latest.sequence if latest else 0,
        "latest_hash": latest.chain_hash if latest else GENESIS_HASH,
        "checkpoints": checkpoints,
        "instance_id": settings.instance_id,
    }
