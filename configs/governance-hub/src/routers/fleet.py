from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..middleware.auth import verify_api_key
from ..services.fleet_service import (
    compare_instances,
    get_fleet_summary,
    get_instance_detail,
    initialize_central_db,
    list_instances,
    test_db_connection,
    get_db_config,
    save_db_config,
)

router = APIRouter(prefix="/api/v1/fleet", tags=["fleet"])


class FleetDbConfig(BaseModel):
    db_type: str  # mssql, mariadb, postgresql
    host: str
    port: int = 5432
    db_name: str = "insidellm_central"
    username: str = ""
    password: str = ""
    trust_server_certificate: bool = True
    encrypt: bool = True


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


@router.get("/db/config")
async def get_fleet_db_config():
    """Get the current central database configuration (password masked)."""
    return get_db_config()


@router.post("/db/test")
async def test_fleet_db(config: FleetDbConfig):
    """Test a database connection without persisting. Returns success, message, latency_ms."""
    return await test_db_connection(config.model_dump())


@router.put("/db/config")
async def save_fleet_db_config(config: FleetDbConfig):
    """Save central database configuration to env override file."""
    return save_db_config(config.model_dump())


@router.post("/db/initialize")
async def initialize_fleet_db(config: FleetDbConfig):
    """Create governance tables in the central database if they don't exist."""
    return await initialize_central_db(config.model_dump())
