from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ChangeProposal, FrameworkVersion
from ..schemas.changes import ApprovalRequest, ChangeCreate, ChangeResponse, ImplementRequest


async def create_proposal(db: AsyncSession, data: ChangeCreate) -> ChangeProposal:
    proposal = ChangeProposal(
        title=data.title,
        description=data.description,
        category=data.category,
        proposed_changes=data.proposed_changes,
        impact_assessment=data.impact_assessment,
        proposed_by=data.proposed_by,
        source=data.source,
        ai_rationale=data.ai_rationale,
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def list_proposals(
    db: AsyncSession,
    status: str | None = None,
    category: str | None = None,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ChangeProposal]:
    query = select(ChangeProposal).order_by(ChangeProposal.proposed_at.desc())
    if status:
        query = query.where(ChangeProposal.status == status)
    if category:
        query = query.where(ChangeProposal.category == category)
    if source:
        query = query.where(ChangeProposal.source == source)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_proposal(db: AsyncSession, proposal_id: int) -> ChangeProposal | None:
    result = await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))
    return result.scalar_one_or_none()


async def approve_or_reject(db: AsyncSession, proposal_id: int, approval: ApprovalRequest) -> ChangeProposal | None:
    proposal = await get_proposal(db, proposal_id)
    if not proposal or proposal.status != "pending":
        return None

    proposal.status = approval.decision if approval.decision != "deferred" else "pending"
    proposal.reviewed_by = approval.reviewer_name
    proposal.reviewed_at = datetime.now(timezone.utc)
    proposal.review_notes = approval.comments
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def implement_change(db: AsyncSession, proposal_id: int, req: ImplementRequest) -> ChangeProposal | None:
    proposal = await get_proposal(db, proposal_id)
    if not proposal or proposal.status != "approved":
        return None

    # Get next framework version
    result = await db.execute(
        select(FrameworkVersion.version).order_by(FrameworkVersion.version.desc()).limit(1)
    )
    current_version = result.scalar_one_or_none() or 0
    next_version = current_version + 1

    # Create framework version record
    fw = FrameworkVersion(
        version=next_version,
        title=req.version_title,
        description=req.version_description,
        changes_summary=f"Implemented change #{proposal_id}: {proposal.title}",
        effective_date=datetime.now(timezone.utc),
        approved_by=proposal.reviewed_by,
        config_json=proposal.proposed_changes,
    )
    db.add(fw)

    proposal.status = "implemented"
    proposal.framework_version = next_version
    proposal.implemented_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(proposal)
    return proposal
