from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..db.models import SyncLog
from ..middleware.auth import verify_api_key
from ..schemas.sync import SyncHistoryEntry, SyncStatus
from ..services.sync_service import collect_telemetry, export_to_central

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/trigger", dependencies=[Depends(verify_api_key)])
async def trigger_sync(db: AsyncSession = Depends(get_local_db)):
    telemetry = await collect_telemetry(db, days=1)
    log = await export_to_central(db, telemetry)
    return {"status": log.status, "records_exported": log.records_exported, "error": log.error_message}


@router.get("/status")
async def sync_status(db: AsyncSession = Depends(get_local_db)) -> SyncStatus:
    result = await db.execute(select(SyncLog).order_by(SyncLog.id.desc()).limit(1))
    last = result.scalar_one_or_none()
    return SyncStatus(
        last_sync_at=last.sync_at if last else None,
        last_status=last.status if last else None,
        records_exported=last.records_exported if last else 0,
        central_db_connected=bool(last and last.status == "success"),
    )


@router.get("/history")
async def sync_history(
    limit: int = 20,
    db: AsyncSession = Depends(get_local_db),
) -> list[SyncHistoryEntry]:
    result = await db.execute(select(SyncLog).order_by(SyncLog.id.desc()).limit(limit))
    return [SyncHistoryEntry.model_validate(r) for r in result.scalars().all()]
