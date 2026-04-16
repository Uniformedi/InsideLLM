import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..config import settings
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


@router.get("/capabilities")
async def list_capabilities(capability: str | None = None, instance_id: str | None = None):
    """List fleet-wide capabilities. Used for smart module deferral (gateway
    nodes point Promtail at primary's Loki) and edge routing.

    Optional filters: ?capability=litellm, ?instance_id=insidellm-01
    """
    from sqlalchemy import select

    from ..db.local_db import AsyncSessionLocal
    from ..db.models import FleetCapability

    async with AsyncSessionLocal() as db:
        stmt = select(FleetCapability)
        if capability:
            stmt = stmt.where(FleetCapability.capability == capability)
        if instance_id:
            stmt = stmt.where(FleetCapability.instance_id == instance_id)
        stmt = stmt.order_by(FleetCapability.instance_id, FleetCapability.capability)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return {
            "capabilities": [
                {
                    "instance_id": r.instance_id,
                    "capability": r.capability,
                    "endpoint": r.endpoint,
                    "role": r.role,
                    "status": r.status,
                    "metadata": r.capability_metadata or {},
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
            "total": len(rows),
        }


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


# =============================================================================
# Fleet-wide AD-join proxy
# =============================================================================
# Forwards AD-join operations to a remote instance's Governance Hub.
# Authentication: caller must present the LOCAL master key (standard RBAC),
# plus the TARGET instance's master key in X-Fleet-Key header.
# The target key is forwarded as Bearer auth to the remote governance hub.
# =============================================================================

_fleet_log = logging.getLogger("insidellm.fleet.ad-join")
_PROXY_TIMEOUT = 30.0


def _require_master_key(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else ""
    mk = settings.litellm_master_key or ""
    if not mk or token != mk:
        raise HTTPException(status_code=401, detail="LITELLM_MASTER_KEY required")


class FleetAdJoinRequest(BaseModel):
    target_url: str = Field(..., description="Target instance gateway URL (e.g. https://10.0.0.11)")
    target_key: str = Field(..., min_length=1, description="Target instance LITELLM_MASTER_KEY")
    user: str = Field(..., min_length=1, description="AD admin sAMAccountName")
    password: str = Field(..., min_length=1, description="AD admin password")
    ou: str | None = Field(default=None, description="Optional Computer OU DN")
    domain: str | None = Field(default=None, description="Override the target's default realm")


class FleetAdStatusRequest(BaseModel):
    target_url: str = Field(..., description="Target instance gateway URL")
    target_key: str = Field(..., min_length=1, description="Target instance LITELLM_MASTER_KEY")


class FleetAdLeaveRequest(BaseModel):
    target_url: str = Field(..., description="Target instance gateway URL")
    target_key: str = Field(..., min_length=1, description="Target instance LITELLM_MASTER_KEY")


async def _proxy_to_target(target_url: str, target_key: str,
                           method: str, path: str,
                           json_body: dict | None = None) -> dict:
    url = f"{target_url.rstrip('/')}/governance/api/v1/ad-join{path}"
    # Mint a break-glass Basic auth token for the target hub
    import base64
    creds = base64.b64encode(f"insidellm-admin:{target_key}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}"}

    # First get a JWT from the target's /auth/token endpoint
    token_url = f"{target_url.rstrip('/')}/governance/auth/token"
    try:
        async with httpx.AsyncClient(verify=False, timeout=_PROXY_TIMEOUT) as client:
            token_resp = await client.post(token_url, headers=headers)
            if token_resp.status_code != 200:
                return {"success": False, "error": f"target auth failed ({token_resp.status_code}): {token_resp.text}"}
            jwt_token = token_resp.json().get("access_token", "")

            bearer = {"Authorization": f"Bearer {jwt_token}"}
            if method.upper() == "GET":
                resp = await client.get(url, headers=bearer)
            else:
                resp = await client.post(url, headers=bearer, json=json_body)

            return {"success": resp.status_code < 400, "status_code": resp.status_code,
                    "response": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text}
    except httpx.ConnectError as exc:
        return {"success": False, "error": f"cannot reach target: {exc}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.post("/ad-join")
async def fleet_ad_join(payload: FleetAdJoinRequest, request: Request):
    """Trigger AD domain join on a remote fleet instance.

    Requires LITELLM_MASTER_KEY of both the local hub (Bearer auth)
    and the target instance (target_key in body).
    """
    _require_master_key(request)
    _fleet_log.info(f"fleet ad-join → {payload.target_url} (user={payload.user})")
    body = {"user": payload.user, "password": payload.password}
    if payload.ou:
        body["ou"] = payload.ou
    if payload.domain:
        body["domain"] = payload.domain
    result = await _proxy_to_target(payload.target_url, payload.target_key, "POST", "", body)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", result))
    return result["response"]


@router.post("/ad-join/status")
async def fleet_ad_join_status(payload: FleetAdStatusRequest, request: Request):
    """Check AD-join status on a remote fleet instance."""
    _require_master_key(request)
    result = await _proxy_to_target(payload.target_url, payload.target_key, "GET", "/status")
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", result))
    return result["response"]


@router.post("/ad-join/leave")
async def fleet_ad_join_leave(payload: FleetAdLeaveRequest, request: Request):
    """Trigger AD domain leave on a remote fleet instance."""
    _require_master_key(request)
    _fleet_log.warning(f"fleet ad-leave → {payload.target_url}")
    result = await _proxy_to_target(payload.target_url, payload.target_key, "POST", "/leave")
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", result))
    return result["response"]
