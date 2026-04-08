from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..middleware.auth import verify_api_key, verify_supervisor
from ..services.obligation_service import (
    approve_review,
    check_attestation,
    create_attestation,
    get_review_queue,
    record_audit_log,
    record_break_glass,
    reject_review,
    submit_for_review,
)

router = APIRouter(prefix="/api/v1/obligations", tags=["obligations"])


class AuditLogRequest(BaseModel):
    event_type: str
    severity: str = "info"
    details: dict = {}


class BreakGlassRequest(BaseModel):
    user_id: str
    reason: str
    data_classification: str = "restricted"


class AttestationCreate(BaseModel):
    user_id: str
    action_type: str
    attestation_text: str
    expires_hours: int = 24


class ReviewSubmit(BaseModel):
    user_id: str
    review_type: str = "general"
    regulation: str = ""
    summary: str = ""


class ReviewDecision(BaseModel):
    reviewer_id: str
    notes: str = ""


@router.post("/audit-log", dependencies=[Depends(verify_api_key)])
async def audit_log(req: AuditLogRequest, db: AsyncSession = Depends(get_local_db)):
    log = await record_audit_log(db, req.event_type, req.severity, req.details)
    return {"id": log.id, "status": "recorded"}


@router.post("/break-glass", dependencies=[Depends(verify_api_key)])
async def break_glass(req: BreakGlassRequest, db: AsyncSession = Depends(get_local_db)):
    log = await record_break_glass(db, req.user_id, req.reason, req.data_classification)
    return {"id": log.id, "status": "recorded"}


@router.get("/attestation/{user_id}/{action_type}")
async def get_attestation(user_id: str, action_type: str, db: AsyncSession = Depends(get_local_db)):
    return await check_attestation(db, user_id, action_type)


@router.post("/attestation", dependencies=[Depends(verify_api_key)])
async def post_attestation(req: AttestationCreate, db: AsyncSession = Depends(get_local_db)):
    att = await create_attestation(db, req.user_id, req.action_type, req.attestation_text, req.expires_hours)
    return {"id": att.id, "expires_at": att.expires_at.isoformat() if att.expires_at else None}


@router.post("/review-queue", dependencies=[Depends(verify_api_key)])
async def post_review(req: ReviewSubmit, db: AsyncSession = Depends(get_local_db)):
    item = await submit_for_review(db, req.user_id, req.review_type, req.regulation, req.summary)
    return {"id": item.id, "status": "queued"}


@router.get("/review-queue")
async def list_reviews(status: str = "pending", limit: int = 50, db: AsyncSession = Depends(get_local_db)):
    items = await get_review_queue(db, status, limit)
    return [{
        "id": i.id, "user_id": i.user_id, "review_type": i.review_type,
        "regulation": i.regulation, "summary": i.request_summary,
        "status": i.status, "created_at": i.created_at,
    } for i in items]


@router.post("/review-queue/{item_id}/approve", dependencies=[Depends(verify_supervisor)])
async def approve(item_id: int, req: ReviewDecision, db: AsyncSession = Depends(get_local_db)):
    item = await approve_review(db, item_id, req.reviewer_id, req.notes)
    if not item:
        raise HTTPException(status_code=400, detail="Item not found or not pending")
    return {"id": item.id, "status": "approved"}


@router.post("/review-queue/{item_id}/reject", dependencies=[Depends(verify_supervisor)])
async def reject(item_id: int, req: ReviewDecision, db: AsyncSession = Depends(get_local_db)):
    item = await reject_review(db, item_id, req.reviewer_id, req.notes)
    if not item:
        raise HTTPException(status_code=400, detail="Item not found or not pending")
    return {"id": item.id, "status": "rejected"}
