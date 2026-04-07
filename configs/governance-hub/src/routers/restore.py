from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..db.models import ConfigSnapshot
from ..middleware.auth import verify_api_key
from ..services.restore_service import (
    generate_tfvars,
    get_snapshot_from_central,
    list_instance_snapshots,
)

router = APIRouter(prefix="/api/v1/restore", tags=["restore"])


class RestoreRequest(BaseModel):
    instance_id: str
    snapshot_id: int | None = None  # None = latest
    overrides: dict[str, Any] | None = None


@router.post("/generate-tfvars", dependencies=[Depends(verify_api_key)])
async def restore_tfvars(req: RestoreRequest):
    """
    Generate a terraform.tfvars file from a config snapshot.

    If snapshot_id is omitted, uses the latest snapshot for the instance.
    Overrides allow changing specific values (e.g., new hostname, IP).
    """
    # Try central DB first
    snapshot = await get_snapshot_from_central(req.instance_id, req.snapshot_id)

    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshot found for instance {req.instance_id} in central DB",
        )

    config = snapshot.get("config_json", {})
    if isinstance(config, str):
        import json
        config = json.loads(config)

    tfvars = generate_tfvars(config, req.overrides)
    return PlainTextResponse(
        content=tfvars,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="terraform.tfvars"'},
    )


@router.get("/snapshots/{instance_id}", dependencies=[Depends(verify_api_key)])
async def get_snapshots(instance_id: str, limit: int = 20):
    """List available config snapshots for an instance from the central DB."""
    snapshots = await list_instance_snapshots(instance_id, limit)
    return {"instance_id": instance_id, "snapshots": snapshots, "total": len(snapshots)}


@router.post("/generate-tfvars/local", dependencies=[Depends(verify_api_key)])
async def restore_from_local(
    snapshot_id: int | None = None,
    db: AsyncSession = Depends(get_local_db),
):
    """Generate terraform.tfvars from a LOCAL config snapshot (this instance)."""
    if snapshot_id:
        result = await db.execute(select(ConfigSnapshot).where(ConfigSnapshot.id == snapshot_id))
    else:
        result = await db.execute(
            select(ConfigSnapshot).order_by(ConfigSnapshot.id.desc()).limit(1)
        )
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="No local snapshots found")

    tfvars = generate_tfvars(snapshot.config_json)
    return PlainTextResponse(
        content=tfvars,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="terraform.tfvars"'},
    )
