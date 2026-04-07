from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..middleware.auth import verify_api_key
from ..schemas.config import ConfigDiff, SnapshotCreate, SnapshotResponse
from ..services.config_service import capture_snapshot, diff_snapshots, get_snapshot, get_snapshots

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.post("/snapshot", dependencies=[Depends(verify_api_key)])
async def create_snapshot(
    data: SnapshotCreate | None = None,
    db: AsyncSession = Depends(get_local_db),
) -> SnapshotResponse:
    created_by = data.created_by if data else "system"
    snapshot = await capture_snapshot(db, created_by)
    return SnapshotResponse.model_validate(snapshot)


@router.get("/snapshots")
async def list_snapshots(
    limit: int = 20,
    db: AsyncSession = Depends(get_local_db),
) -> list[SnapshotResponse]:
    snapshots = await get_snapshots(db, limit)
    return [SnapshotResponse.model_validate(s) for s in snapshots]


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot_detail(snapshot_id: int, db: AsyncSession = Depends(get_local_db)) -> SnapshotResponse:
    snapshot = await get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return SnapshotResponse.model_validate(snapshot)


@router.get("/diff/{id_a}/{id_b}")
async def get_diff(id_a: int, id_b: int, db: AsyncSession = Depends(get_local_db)) -> ConfigDiff:
    diff = await diff_snapshots(db, id_a, id_b)
    if not diff:
        raise HTTPException(status_code=404, detail="One or both snapshots not found")
    return diff
