from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..middleware.auth import verify_api_key, verify_supervisor
from ..services.rbac import require_approver
from ..schemas.changes import ApprovalRequest, ChangeCreate, ChangeResponse, ImplementRequest
from ..services.change_service import (
    approve_or_reject,
    create_proposal,
    get_proposal,
    implement_change,
    list_proposals,
)

router = APIRouter(prefix="/api/v1/changes", tags=["changes"])


@router.post("/", dependencies=[Depends(verify_api_key)])
async def create_change(data: ChangeCreate, db: AsyncSession = Depends(get_local_db)) -> ChangeResponse:
    proposal = await create_proposal(db, data)
    return ChangeResponse.model_validate(proposal)


@router.get("/")
async def list_changes(
    status: str | None = None,
    category: str | None = None,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_local_db),
) -> list[ChangeResponse]:
    proposals = await list_proposals(db, status, category, source, limit, offset)
    return [ChangeResponse.model_validate(p) for p in proposals]


@router.get("/{proposal_id}")
async def get_change(proposal_id: int, db: AsyncSession = Depends(get_local_db)) -> ChangeResponse:
    proposal = await get_proposal(db, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return ChangeResponse.model_validate(proposal)


@router.post("/{proposal_id}/approve", dependencies=[Depends(verify_supervisor), require_approver])
async def approve_change(
    proposal_id: int,
    approval: ApprovalRequest,
    db: AsyncSession = Depends(get_local_db),
) -> ChangeResponse:
    proposal = await approve_or_reject(db, proposal_id, approval)
    if not proposal:
        raise HTTPException(status_code=400, detail="Proposal not found or not in pending status")
    return ChangeResponse.model_validate(proposal)


@router.post("/{proposal_id}/reject", dependencies=[Depends(verify_supervisor), require_approver])
async def reject_change(
    proposal_id: int,
    approval: ApprovalRequest,
    db: AsyncSession = Depends(get_local_db),
) -> ChangeResponse:
    # Force the action to 'reject' regardless of payload.
    approval = approval.model_copy(update={"action": "reject"}) if hasattr(approval, "model_copy") else approval
    proposal = await approve_or_reject(db, proposal_id, approval)
    if not proposal:
        raise HTTPException(status_code=400, detail="Proposal not found or not in pending status")
    return ChangeResponse.model_validate(proposal)


@router.post("/{proposal_id}/implement", dependencies=[Depends(verify_supervisor)])
async def implement(
    proposal_id: int,
    req: ImplementRequest,
    db: AsyncSession = Depends(get_local_db),
) -> ChangeResponse:
    proposal = await implement_change(db, proposal_id, req)
    if not proposal:
        raise HTTPException(status_code=400, detail="Proposal not found or not approved")
    return ChangeResponse.model_validate(proposal)
