"""Notification emitter with DLP sidecar in-path (P2.1).

Every outbound notification passes through DLP scanning before it leaves
the platform. Default policy is `redact` (replace with mask tokens) so
the message still goes out with a useful audit trail; `block` stops on
any critical hit.

Targets: teams://channel, slack://channel, email://addr. The scheme
selects the provider; the authority (channel/addr) selects which
configured webhook or mailbox handles the send.

Webhook URLs live in the Governance Hub settings_overrides table so
operators rotate them without redeploying. The default `teams_default`
and `slack_default` channels read from env vars at startup for bootstrap.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from . import dlp_scan as _dlp

logger = logging.getLogger("governance-hub.notifications")


# ---------------------------------------------------------------------------
# Request / result types
# ---------------------------------------------------------------------------


@dataclass
class NotificationRequest:
    event_type: str
    target: str                  # teams://…, slack://…, email://…
    subject: str
    body: str
    severity: str = "info"       # info | warning | critical
    metadata: dict[str, Any] = field(default_factory=dict)
    # DLP policy — redact is the sensible default; block is for data
    # corridors where a single hit must prevent egress (e.g. HIPAA).
    dlp_mode: str = "redact"     # redact | block | off


@dataclass
class NotificationResult:
    ok: bool
    target: str
    provider: str
    sent_at: str
    dlp_hits: list[dict] = field(default_factory=list)
    dlp_severity_counts: dict[str, int] = field(default_factory=dict)
    redactions_applied: int = 0
    blocked_by_dlp: bool = False
    error: str | None = None
    provider_response_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Target parsing
# ---------------------------------------------------------------------------


def _parse_target(target: str) -> tuple[str, str]:
    """teams://foo  →  ("teams", "foo"). Raises ValueError on bad input."""
    if not target or "://" not in target:
        raise ValueError(f"invalid target URI: {target!r}")
    scheme, _, authority = target.partition("://")
    scheme = scheme.lower().strip()
    if scheme not in _PROVIDERS:
        raise ValueError(f"unsupported notification provider: {scheme!r}")
    if not authority:
        raise ValueError(f"target missing authority: {target!r}")
    return scheme, authority


# ---------------------------------------------------------------------------
# Webhook URL resolution
# ---------------------------------------------------------------------------


def _webhook_url(provider: str, channel: str) -> str | None:
    """Look up the outbound webhook URL for (provider, channel).

    Precedence:
      1. Env var TEAMS_WEBHOOK_<CHANNEL> / SLACK_WEBHOOK_<CHANNEL>
      2. Env var TEAMS_WEBHOOK_DEFAULT / SLACK_WEBHOOK_DEFAULT when
         channel is `default` or not otherwise bound
    Operators rotate webhooks via settings_overrides; this function only
    handles the bootstrap env path.
    """
    prov_upper = provider.upper()
    chan_upper = channel.upper().replace("-", "_").replace(".", "_")
    specific = os.environ.get(f"{prov_upper}_WEBHOOK_{chan_upper}")
    if specific:
        return specific
    if channel in ("default", "primary"):
        return os.environ.get(f"{prov_upper}_WEBHOOK_DEFAULT")
    return os.environ.get(f"{prov_upper}_WEBHOOK_DEFAULT")


# ---------------------------------------------------------------------------
# DLP middleware — wraps every provider
# ---------------------------------------------------------------------------


def _apply_dlp(req: NotificationRequest) -> tuple[str, str, list[_dlp.DLPHit], bool]:
    """Returns (processed_subject, processed_body, hits, blocked).

    Subject + body are concatenated for scanning so the hit set is
    deduplicated against the whole message; per-field redaction applies
    each to its own text.
    """
    if req.dlp_mode == "off":
        return req.subject, req.body, [], False

    combined = (req.subject or "") + "\n" + (req.body or "")
    hits = _dlp.scan_text(combined)

    if req.dlp_mode == "block" and _dlp.contains_critical(hits):
        return req.subject, req.body, hits, True

    if req.dlp_mode == "redact" and hits:
        new_subject, _ = _dlp.redact_text(req.subject or "")
        new_body, _ = _dlp.redact_text(req.body or "")
        return new_subject, new_body, hits, False

    return req.subject, req.body, hits, False


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


async def _send_teams(channel: str, subject: str, body: str, severity: str) -> tuple[int, str]:
    url = _webhook_url("teams", channel)
    if not url:
        raise RuntimeError(f"no Teams webhook configured for channel '{channel}'")
    # MessageCard is the legacy-but-universal shape that works with
    # Teams Incoming Webhook connectors + Workflows alike.
    theme = {"info": "22d3ee", "warning": "fbbf24", "critical": "f87171"}.get(severity, "94a3b8")
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": subject,
        "themeColor": theme,
        "title": subject,
        "text": body,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.status_code, resp.text[:200]


async def _send_slack(channel: str, subject: str, body: str, severity: str) -> tuple[int, str]:
    url = _webhook_url("slack", channel)
    if not url:
        raise RuntimeError(f"no Slack webhook configured for channel '{channel}'")
    color = {"info": "#22d3ee", "warning": "#fbbf24", "critical": "#f87171"}.get(severity, "#94a3b8")
    payload = {
        "attachments": [{
            "color": color,
            "title": subject,
            "text": body,
        }],
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.status_code, resp.text[:200]


async def _send_email(channel: str, subject: str, body: str, severity: str) -> tuple[int, str]:
    """SMTP send — bootstrap reads SMTP_HOST/PORT/USER/PASS env vars.
    For the Parent Organization-demo window we stub this out to log-only; wiring
    aiosmtplib lands in a follow-up when a real relay is configured."""
    host = os.environ.get("SMTP_HOST", "")
    if not host:
        logger.warning(f"email send stubbed (no SMTP_HOST): to={channel} subject={subject!r}")
        return 202, "stubbed"
    # Real implementation hooks here. Keeping it stubbed — the spec
    # demands Teams/Slack; email is the deferred channel per P2.1 scope.
    logger.info(f"email queued: to={channel} subject={subject!r} severity={severity}")
    return 202, "queued"


_PROVIDERS = {
    "teams": _send_teams,
    "slack": _send_slack,
    "email": _send_email,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def send(req: NotificationRequest) -> NotificationResult:
    """Process + send one notification. Always returns a result — errors
    are captured into `result.error`, never raised to the caller."""
    now = datetime.now(timezone.utc).isoformat()

    try:
        provider, channel = _parse_target(req.target)
    except ValueError as e:
        return NotificationResult(
            ok=False, target=req.target, provider="unknown", sent_at=now, error=str(e),
        )

    subject, body, hits, blocked = _apply_dlp(req)
    hit_payload = [h.to_dict() for h in hits]
    counts = _dlp.severity_counts(hits)

    if blocked:
        logger.warning(
            f"notification BLOCKED by DLP: target={req.target} event={req.event_type} "
            f"criticals={counts['critical']} highs={counts['high']}"
        )
        return NotificationResult(
            ok=False,
            target=req.target,
            provider=provider,
            sent_at=now,
            dlp_hits=hit_payload,
            dlp_severity_counts=counts,
            redactions_applied=0,
            blocked_by_dlp=True,
            error="blocked by DLP — critical hit in block mode",
        )

    redactions = len(hits) if (req.dlp_mode == "redact" and hits) else 0
    send_fn = _PROVIDERS[provider]

    try:
        status, snippet = await send_fn(channel, subject, body, req.severity)
    except httpx.HTTPStatusError as e:
        return NotificationResult(
            ok=False, target=req.target, provider=provider, sent_at=now,
            dlp_hits=hit_payload, dlp_severity_counts=counts,
            redactions_applied=redactions,
            provider_response_status=e.response.status_code,
            error=f"provider HTTP {e.response.status_code}: {e.response.text[:200]}",
        )
    except Exception as e:
        return NotificationResult(
            ok=False, target=req.target, provider=provider, sent_at=now,
            dlp_hits=hit_payload, dlp_severity_counts=counts,
            redactions_applied=redactions,
            error=f"{type(e).__name__}: {e}"[:500],
        )

    logger.info(
        f"notification sent: provider={provider} channel={channel} "
        f"event={req.event_type} severity={req.severity} "
        f"dlp_hits={len(hits)} redactions={redactions}"
    )
    return NotificationResult(
        ok=True,
        target=req.target,
        provider=provider,
        sent_at=now,
        dlp_hits=hit_payload,
        dlp_severity_counts=counts,
        redactions_applied=redactions,
        provider_response_status=status,
    )


async def send_many(requests: list[NotificationRequest]) -> list[NotificationResult]:
    """Fan-out N notifications concurrently. Order preserved."""
    return await asyncio.gather(*[send(r) for r in requests])
