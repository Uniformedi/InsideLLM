"""Hyper-V management router — thin web equivalent of Windows Admin Center,
scoped to the bits InsideLLM operators actually need."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, Request

from ..services import hyperv_service

logger = logging.getLogger("insidellm.hyperv_router")

router = APIRouter(prefix="/api/v1/hyperv", tags=["hyperv"])


def _require_admin(request: Request) -> None:
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin role required")


def _caller(request: Request) -> str:
    return getattr(request.state, "user_id", "") or "unknown"


def _unwrap(result: dict) -> dict:
    """Translate {ok, data, err} into HTTPException on failure."""
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("err", "Hyper-V unavailable"))
    return {"data": result.get("data")}


# Read endpoints — admin-only since they expose host inventory

@router.get("/host")
async def get_host(request: Request) -> dict:
    _require_admin(request)
    return _unwrap(hyperv_service.host_resources())


@router.get("/vms")
async def list_vms(request: Request) -> dict:
    _require_admin(request)
    return _unwrap(hyperv_service.list_vms())


@router.get("/vms/{name}")
async def get_vm(name: str, request: Request) -> dict:
    _require_admin(request)
    return _unwrap(hyperv_service.get_vm(name))


@router.get("/vms/{name}/snapshots")
async def list_snapshots(name: str, request: Request) -> dict:
    _require_admin(request)
    return _unwrap(hyperv_service.list_snapshots(name))


# Write endpoints — admin-only, log who did what

@router.post("/vms/{name}/start")
async def start_vm(name: str, request: Request) -> dict:
    _require_admin(request)
    logger.info(f"hyperv: {_caller(request)} starting VM '{name}'")
    return _unwrap(hyperv_service.start_vm(name))


@router.post("/vms/{name}/stop")
async def stop_vm(name: str, request: Request, payload: dict = Body(default={})) -> dict:
    _require_admin(request)
    force = bool(payload.get("force", False))
    logger.warning(f"hyperv: {_caller(request)} stopping VM '{name}' (force={force})")
    return _unwrap(hyperv_service.stop_vm(name, force=force))


@router.post("/vms/{name}/snapshot")
async def snapshot_vm(name: str, request: Request, payload: dict = Body(default={})) -> dict:
    _require_admin(request)
    snap_name = payload.get("name", "")
    logger.info(f"hyperv: {_caller(request)} snapshot VM '{name}' as '{snap_name or '(auto)'}'")
    return _unwrap(hyperv_service.snapshot_vm(name, snapshot_name=snap_name))
