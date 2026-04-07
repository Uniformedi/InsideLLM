from fastapi import APIRouter, Depends, HTTPException, Query

from ..middleware.auth import verify_api_key
from ..services.fleet_service import (
    compare_instances,
    get_fleet_summary,
    get_instance_detail,
    list_instances,
)

router = APIRouter(prefix="/api/v1/fleet", tags=["fleet"])


@router.get("/instances")
async def get_instances():
    """List all InsideLLM instances registered in the central repository."""
    instances = await list_instances()
    return {"instances": instances, "total": len(instances)}


@router.get("/instances/{instance_id}")
async def get_instance(instance_id: str):
    """Get detailed info for a specific instance including telemetry history."""
    detail = await get_instance_detail(instance_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Instance not found or central DB not configured")
    return detail


@router.get("/summary")
async def fleet_summary():
    """Get aggregate fleet-wide metrics across all instances."""
    return await get_fleet_summary()


@router.post("/compare")
async def compare(instance_ids: list[str]):
    """Compare configuration and metrics across multiple instances."""
    if len(instance_ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 instance IDs to compare")
    if len(instance_ids) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 instances per comparison")
    return await compare_instances(instance_ids)
