from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..middleware.auth import verify_api_key
from ..services.fleet_service import (
    compare_instances,
    deregister_instance,
    get_fleet_summary,
    get_instance_detail,
    get_instance_overrides,
    initialize_central_db,
    list_instances,
    set_instance_overrides,
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
    windows_auth: bool = False


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


class InstanceOverrides(BaseModel):
    alert_webhook: str | None = None
    updated_by: str = "admin"


@router.get("/instances/{instance_id}/settings")
async def read_instance_settings(instance_id: str):
    """Get per-instance settings overrides stored in the central fleet DB."""
    data = await get_instance_overrides(instance_id)
    if data is None:
        raise HTTPException(status_code=503, detail="Central DB not configured")
    return data


@router.put("/instances/{instance_id}/settings")
async def write_instance_settings(instance_id: str, overrides: InstanceOverrides):
    """Upsert per-instance settings overrides (e.g. alert_webhook).

    Stored in governance_instance_overrides. Note: this records *intent* only.
    Live propagation to the target instance's running containers is out of
    scope; redeploy or rerun terraform apply on that instance for overrides to
    take effect.
    """
    result = await set_instance_overrides(
        instance_id,
        alert_webhook=overrides.alert_webhook,
        updated_by=overrides.updated_by,
    )
    if not result["success"]:
        raise HTTPException(status_code=503, detail=result["message"])
    return result


@router.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str):
    """Deregister an instance (soft delete — status set to 'deregistered').

    History (telemetry, changes) is preserved for audit. The instance stops
    appearing in active fleet counts and tiles.
    """
    result = await deregister_instance(instance_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


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


class RegistrationTokenRequest(BaseModel):
    hours: int = 24
    created_by: str = "admin"


class RegistrationRequest(BaseModel):
    token: str
    instance_id: str
    instance_name: str = ""


@router.post("/registration-token")
async def create_registration_token(req: RegistrationTokenRequest):
    """Generate a time-limited registration token for new instances to self-register.

    The token is single-use and expires after the specified hours.
    Share it with the new instance's administrator.
    """
    from ..services.registration_service import generate_registration_token, store_token
    from datetime import datetime, timedelta, timezone

    result = generate_registration_token(req.hours, req.created_by)
    stored = await store_token(result["token"], req.created_by,
                               datetime.now(timezone.utc) + timedelta(hours=req.hours))
    if not stored:
        return {"success": False, "message": "Failed to store token in central DB"}

    return {"success": True, **result}


@router.post("/register")
async def register_instance(req: RegistrationRequest):
    """Self-register a new instance using a registration token.

    Returns encrypted fleet DB credentials on success.
    """
    from ..services.registration_service import validate_and_consume_token

    result = await validate_and_consume_token(req.token, req.instance_id)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid, expired, or already-used registration token")

    return {
        "success": True,
        "message": "Instance registered successfully",
        **result,
    }
