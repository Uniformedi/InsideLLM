"""Obligation execution service — backend for OPA policy enforcement obligations."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BreakGlassLog, PolicyAuditLog, ReviewQueueItem, UserAttestation
from .audit_chain import append_event


async def record_audit_log(db: AsyncSession, event_type: str, severity: str, details: dict) -> PolicyAuditLog:
    log = PolicyAuditLog(
        event_type=event_type,
        severity=severity,
        user_id=details.get("user", ""),
        details=details,
    )
    db.add(log)
    await db.flush()
    await append_event(db, "policy_audit", log.id, {
        "event_type": event_type,
        "severity": severity,
        "user": details.get("user", ""),
    })
    await db.commit()
    return log


async def record_break_glass(db: AsyncSession, user_id: str, reason: str, classification: str) -> BreakGlassLog:
    log = BreakGlassLog(
        user_id=user_id,
        reason=reason,
        data_classification=classification,
    )
    db.add(log)
    await db.flush()
    await append_event(db, "break_glass_access", log.id, {
        "user_id": user_id,
        "reason": reason,
        "classification": classification,
    })
    await db.commit()
    return log


async def check_attestation(db: AsyncSession, user_id: str, action_type: str) -> dict:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(UserAttestation)
        .where(UserAttestation.user_id == user_id)
        .where(UserAttestation.action_type == action_type)
        .where(UserAttestation.revoked_at.is_(None))
        .where(
            (UserAttestation.expires_at.is_(None)) | (UserAttestation.expires_at > now)
        )
        .order_by(UserAttestation.attested_at.desc())
        .limit(1)
    )
    attestation = result.scalar_one_or_none()
    if attestation:
        return {"valid": True, "attested_at": attestation.attested_at.isoformat(), "user_id": user_id}
    return {"valid": False, "user_id": user_id, "action_type": action_type}


async def create_attestation(
    db: AsyncSession, user_id: str, action_type: str, attestation_text: str, expires_hours: int = 24
) -> UserAttestation:
    att = UserAttestation(
        user_id=user_id,
        action_type=action_type,
        attestation_text=attestation_text,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=expires_hours),
    )
    db.add(att)
    await db.flush()
    await append_event(db, "attestation_created", att.id, {
        "user_id": user_id,
        "action_type": action_type,
    })
    await db.commit()
    await db.refresh(att)
    return att


async def submit_for_review(db: AsyncSession, user_id: str, review_type: str, regulation: str, summary: str) -> ReviewQueueItem:
    item = ReviewQueueItem(
        user_id=user_id,
        review_type=review_type,
        regulation=regulation,
        request_summary=summary,
    )
    db.add(item)
    await db.flush()
    await append_event(db, "review_queued", item.id, {
        "user_id": user_id,
        "review_type": review_type,
        "regulation": regulation,
    })
    await db.commit()
    await db.refresh(item)
    return item


async def get_review_queue(db: AsyncSession, status: str = "pending", limit: int = 50) -> list[ReviewQueueItem]:
    result = await db.execute(
        select(ReviewQueueItem)
        .where(ReviewQueueItem.status == status)
        .order_by(ReviewQueueItem.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def approve_review(db: AsyncSession, item_id: int, reviewer_id: str, notes: str = "") -> ReviewQueueItem | None:
    result = await db.execute(select(ReviewQueueItem).where(ReviewQueueItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item or item.status != "pending":
        return None
    item.status = "approved"
    item.reviewer_id = reviewer_id
    item.reviewed_at = datetime.now(timezone.utc)
    item.review_notes = notes
    await db.flush()
    await append_event(db, "review_approved", item.id, {"reviewer": reviewer_id})
    await db.commit()
    await db.refresh(item)
    return item


async def reject_review(db: AsyncSession, item_id: int, reviewer_id: str, notes: str = "") -> ReviewQueueItem | None:
    result = await db.execute(select(ReviewQueueItem).where(ReviewQueueItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item or item.status != "pending":
        return None
    item.status = "rejected"
    item.reviewer_id = reviewer_id
    item.reviewed_at = datetime.now(timezone.utc)
    item.review_notes = notes
    await db.flush()
    await append_event(db, "review_rejected", item.id, {"reviewer": reviewer_id})
    await db.commit()
    await db.refresh(item)
    return item
