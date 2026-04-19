"""Notification emitter REST router (P2.1).

Operator-facing endpoints for Teams/Slack/email notifications with
DLP sidecar enforcement. Internal callers (e.g. the agent approval
flow) use the service directly via notification_service.send().

Endpoints:
  * POST /api/v1/notifications/send     send a notification (admin)
  * POST /api/v1/notifications/test     smoke test default channels (admin)
  * POST /api/v1/notifications/scan     preview DLP scan on a body (view)
  * GET  /api/v1/notifications/channels list configured bootstrap channels (view)
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel, Field

from ..services.dlp_scan import scan_text, severity_counts
from ..services.notification_service import NotificationRequest, send
from ..services.rbac import require_admin, require_view

logger = logging.getLogger("governance-hub.notifications.router")

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# Request shapes
# ---------------------------------------------------------------------------


class NotificationSendRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=100)
    target: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1, max_length=8000)
    severity: str = Field("info", pattern=r"^(info|warning|critical)$")
    metadata: dict[str, Any] = Field(default_factory=dict)
    dlp_mode: str = Field("redact", pattern=r"^(redact|block|off)$")


class ScanRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=16000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _actor(request: Request) -> str | None:
    return getattr(request.state, "user_email", None) or getattr(
        request.state, "user_id", None
    )


@router.post("/send", dependencies=[require_admin])
async def send_notification(
    request: Request,
    payload: NotificationSendRequest = Body(...),
) -> dict:
    req = NotificationRequest(
        event_type=payload.event_type,
        target=payload.target,
        subject=payload.subject,
        body=payload.body,
        severity=payload.severity,
        metadata={**(payload.metadata or {}), "actor": _actor(request) or "system"},
        dlp_mode=payload.dlp_mode,
    )
    result = await send(req)
    return result.to_dict()


@router.post("/test", dependencies=[require_admin])
async def test_default_channels(
    request: Request,
    target: str = Body(..., embed=True),
) -> dict:
    """Send a canned probe to a target URI to confirm the webhook + DLP
    loop is live. Useful immediately after configuring a channel."""
    req = NotificationRequest(
        event_type="smoke_test",
        target=target,
        subject="InsideLLM smoke test",
        body=(
            "This is a smoke-test notification from the Governance Hub.\n"
            "If you see this message, the provider webhook is working + "
            f"DLP sidecar is inline. Triggered by {_actor(request) or 'system'}."
        ),
        severity="info",
        dlp_mode="redact",
    )
    result = await send(req)
    return result.to_dict()


@router.post("/scan", dependencies=[require_view])
async def scan_dlp_preview(payload: ScanRequest = Body(...)) -> dict:
    """Dry-run DLP scan on a proposed body. Doesn't send anything.
    Admin UI uses this for pre-send preview."""
    hits = scan_text(payload.text)
    return {
        "hit_count": len(hits),
        "hits": [h.to_dict() for h in hits],
        "severity_counts": severity_counts(hits),
        "has_critical": any(h.severity == "critical" for h in hits),
    }


@router.get("/channels", dependencies=[require_view])
async def list_configured_channels() -> dict:
    """Report which default webhooks are configured (doesn't expose URLs)."""
    return {
        "teams_default": bool(os.environ.get("TEAMS_WEBHOOK_DEFAULT")),
        "slack_default": bool(os.environ.get("SLACK_WEBHOOK_DEFAULT")),
        "email_smtp": bool(os.environ.get("SMTP_HOST")),
        "dlp_patterns": sorted(__import__("src.services.dlp_scan", fromlist=["PATTERNS"]).PATTERNS.keys()),
    }
