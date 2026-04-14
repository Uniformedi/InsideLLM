"""Active Directory integration router.

Triggers a host-side realm-join via a request file the Governance Hub
container writes into a shared bind mount; a systemd path watcher on the
host picks it up, runs `realm join`, writes back a status file the Hub
polls. The Hub never sees domain credentials in transit beyond the
single POST that sets them.

Endpoints
---------
GET  /api/v1/ad-join/status     current join state + last run result
POST /api/v1/ad-join             { user, password, ou? } - request join
POST /api/v1/ad-join/leave       request leave
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("insidellm.ad_join")
router = APIRouter(prefix="/api/v1/ad-join", tags=["ad-join"])

REQUEST_FILE = Path(os.environ.get("AD_JOIN_REQUEST_FILE", "/ad-join/ad-join-request.json"))
STATUS_FILE = Path(os.environ.get("AD_JOIN_STATUS_FILE", "/ad-join/ad-join-status.json"))


def _require_admin(request: Request) -> None:
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin role required")


def _caller(request: Request) -> str:
    return getattr(request.state, "user_id", "") or "unknown"


class JoinIn(BaseModel):
    user: str = Field(..., min_length=1, description="Domain admin sAMAccountName")
    password: str = Field(..., min_length=1, description="Domain admin password")
    ou: str | None = Field(default=None, description="Optional Computer OU DN")
    domain: str | None = Field(default=None, description="Override the krb5.conf default_realm")


def _read_status() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return {"joined": False, "last_run": None}
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        # Strip the password if it was somehow recorded (defense-in-depth)
        data.pop("password", None)
        return {"joined": bool(data.get("joined")), "domain": data.get("domain", ""),
                "last_run": data}
    except Exception as exc:
        return {"joined": False, "last_run": None, "error": f"status parse failed: {exc}"}


def _write_request(payload: dict[str, Any]) -> None:
    if REQUEST_FILE.exists():
        raise HTTPException(status_code=409, detail="A previous request is still pending")
    REQUEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically + restrict perms so the password isn't world-readable.
    tmp = REQUEST_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.rename(REQUEST_FILE)


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    _require_admin(request)
    pending = REQUEST_FILE.exists()
    return {**_read_status(), "request_pending": pending}


@router.post("")
async def join(payload: JoinIn, request: Request) -> dict[str, Any]:
    _require_admin(request)
    body = payload.model_dump(exclude_none=True)
    body["action"] = "join"
    _write_request(body)
    logger.info(f"ad-join request submitted by {_caller(request)} (user={payload.user})")

    # Best-effort: poll the status file briefly so the UI can show an
    # immediate result on a fast join.
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if not REQUEST_FILE.exists() and STATUS_FILE.exists():
            break
        time.sleep(0.5)
    return {"submitted": True, **_read_status()}


@router.post("/leave")
async def leave(request: Request) -> dict[str, Any]:
    _require_admin(request)
    _write_request({"action": "leave"})
    logger.warning(f"ad-leave request submitted by {_caller(request)}")
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if not REQUEST_FILE.exists() and STATUS_FILE.exists():
            break
        time.sleep(0.5)
    return {"submitted": True, **_read_status()}
