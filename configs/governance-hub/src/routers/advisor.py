from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..middleware.auth import verify_api_key
from ..schemas.advisor import AdvisorResponse, AnalysisRequest
from ..services.advisor_service import run_analysis

router = APIRouter(prefix="/api/v1/advisor", tags=["advisor"])


@router.post("/analyze", dependencies=[Depends(verify_api_key)])
async def analyze_governance(
    request: AnalysisRequest | None = None,
    db: AsyncSession = Depends(get_local_db),
) -> AdvisorResponse:
    req = request or AnalysisRequest()
    return await run_analysis(db, req)
