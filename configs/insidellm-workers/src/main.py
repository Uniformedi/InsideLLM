"""InsideLLM demo workers — stub backends for declarative-agent actions.

Runs as the `insidellm-workers` docker service. Hosts the four endpoints
the example-tenant Dispute Handler agent calls:

  POST /actions/lookup_account       — canned example-tenant account row
  POST /actions/draft_fdcpa_letter   — §1692g(b) letter template
  POST /actions/send_letter          — approval-queue stub (never mails)
  POST /actions/schedule_callback    — callback-record stub

Demo-grade: all responses are deterministic fixtures, no real downstream
systems. Production tenants replace this service with their own — the
action catalog URL is per-tenant, so no platform changes are required.

Health endpoint: /health
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("insidellm-workers")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="InsideLLM Demo Workers",
    version="1.0.0",
    description="Stub action backends for the Dispute Handler showcase agent.",
)


# ---------------------------------------------------------------------------
# Shared models
# ---------------------------------------------------------------------------

_ACCOUNT_PATTERN = re.compile(r"^[A-Z0-9]{6,20}$")


def _validate_account(account_number: str) -> None:
    if not _ACCOUNT_PATTERN.match(account_number or ""):
        raise HTTPException(status_code=400, detail="invalid account_number format")


# ---------------------------------------------------------------------------
# lookup_account
# ---------------------------------------------------------------------------


class LookupAccountRequest(BaseModel):
    account_number: str = Field(..., min_length=6, max_length=20)


class LookupAccountResponse(BaseModel):
    account_summary: dict[str, Any]


# A small fixture set so the demo shows different flows:
#   ORG000001 — in validation window, active
#   ORG000002 — OUT of window, needs remedy-only response
#   ORG000003 — settled; dispute declined
_ACCOUNT_FIXTURES: dict[str, dict[str, Any]] = {
    "ORG000001": {
        "account_number": "ORG000001",
        "status": "active",
        "current_balance_usd": 1247.83,
        "original_creditor": "Midland Credit",
        "debt_acquired_on": "2025-11-20",
        "validation_notice_sent_on": "2026-04-05",
        "in_validation_window": True,
        "last_payment": None,
        "consumer": {
            "last_name_hash": "a4f7…",
            "state": "TX",
            "timezone": "America/Chicago",
            "preferred_contact": "mail",
        },
    },
    "ORG000002": {
        "account_number": "ORG000002",
        "status": "active",
        "current_balance_usd": 623.10,
        "original_creditor": "Navient",
        "debt_acquired_on": "2024-09-02",
        "validation_notice_sent_on": "2025-02-14",
        "in_validation_window": False,
        "last_payment": {"amount_usd": 50.0, "paid_on": "2025-12-10"},
        "consumer": {
            "last_name_hash": "c9b2…",
            "state": "CA",
            "timezone": "America/Los_Angeles",
            "preferred_contact": "phone",
        },
    },
    "ORG000003": {
        "account_number": "ORG000003",
        "status": "settled",
        "current_balance_usd": 0.0,
        "original_creditor": "Capital One",
        "debt_acquired_on": "2023-04-18",
        "validation_notice_sent_on": "2023-05-01",
        "in_validation_window": False,
        "last_payment": {"amount_usd": 1500.0, "paid_on": "2024-01-12"},
        "consumer": {
            "last_name_hash": "f7e1…",
            "state": "NY",
            "timezone": "America/New_York",
            "preferred_contact": "mail",
        },
    },
}


@app.post("/actions/lookup_account", response_model=LookupAccountResponse)
async def lookup_account(req: LookupAccountRequest) -> LookupAccountResponse:
    _validate_account(req.account_number)
    fixture = _ACCOUNT_FIXTURES.get(req.account_number)
    if fixture is None:
        # Return a default in-window shape so unseen demo accounts don't 404.
        fixture = {
            **_ACCOUNT_FIXTURES["ORG000001"],
            "account_number": req.account_number,
        }
    logger.info(f"lookup_account: {req.account_number} status={fixture['status']}")
    return LookupAccountResponse(account_summary=fixture)


# ---------------------------------------------------------------------------
# draft_fdcpa_letter
# ---------------------------------------------------------------------------


class DraftLetterRequest(BaseModel):
    account_number: str
    dispute_reason: str = Field(..., min_length=3, max_length=1000)
    in_validation_window: bool


class DraftLetterResponse(BaseModel):
    letter_markdown: str
    letter_id: str


_LETTER_TEMPLATE = """\
**Example Co., LLC**
*FDCPA Dispute Acknowledgment — §1692g(b)*

Date: {date}
Account: {account_number}

Dear Consumer,

We are writing to acknowledge receipt of your dispute concerning the
above-referenced account, received within the thirty (30) day validation
window established by your initial §1692g(a) notice.

Pursuant to 15 U.S.C. §1692g(b), collection activity on this account is
suspended pending our verification of the debt. Until verification is
obtained and mailed to you, we will not pursue further collection.

Summary of dispute as recorded:
> {dispute_reason}

If you wish to add supporting documentation, please reply to the address
above within fifteen (15) business days. You will receive verification
documents by mail; no oral conversation or payment is required during
this period.

Sincerely,
Compliance Operations
Example Co., LLC
"""


@app.post("/actions/draft_fdcpa_letter", response_model=DraftLetterResponse)
async def draft_fdcpa_letter(req: DraftLetterRequest) -> DraftLetterResponse:
    _validate_account(req.account_number)
    if not req.in_validation_window:
        raise HTTPException(
            status_code=409,
            detail="draft_fdcpa_letter is only valid within the 30-day §1692g window; "
                   "consumer should be routed to remedy counseling instead",
        )
    letter_id = str(uuid.uuid4())
    body = _LETTER_TEMPLATE.format(
        date=datetime.now(timezone.utc).strftime("%B %d, %Y"),
        account_number=req.account_number,
        dispute_reason=req.dispute_reason.strip(),
    )
    logger.info(f"draft_fdcpa_letter: account={req.account_number} letter_id={letter_id}")
    return DraftLetterResponse(letter_markdown=body, letter_id=letter_id)


# ---------------------------------------------------------------------------
# send_letter  (NEVER actually sends in demo mode)
# ---------------------------------------------------------------------------


class SendLetterRequest(BaseModel):
    letter_id: str = Field(..., min_length=8, max_length=64)
    account_number: str
    attestation: str = Field(..., min_length=10)


class SendLetterResponse(BaseModel):
    queued_for_approval: bool
    approval_ticket: str


@app.post("/actions/send_letter", response_model=SendLetterResponse)
async def send_letter(req: SendLetterRequest) -> SendLetterResponse:
    _validate_account(req.account_number)
    ticket = f"EXAMPLE-APPROVAL-{uuid.uuid4().hex[:12].upper()}"
    logger.info(
        f"send_letter QUEUED: account={req.account_number} letter_id={req.letter_id} "
        f"ticket={ticket} attestation_len={len(req.attestation)}"
    )
    # In production this would POST to the approval service + mailroom queue.
    # Demo mode: we always queue, never mail.
    return SendLetterResponse(queued_for_approval=True, approval_ticket=ticket)


# ---------------------------------------------------------------------------
# schedule_callback
# ---------------------------------------------------------------------------


class ScheduleCallbackRequest(BaseModel):
    account_number: str
    callback_window_start: str
    callback_window_end: str
    notes: str | None = None


class ScheduleCallbackResponse(BaseModel):
    callback_id: str
    scheduled_at: str


@app.post("/actions/schedule_callback", response_model=ScheduleCallbackResponse)
async def schedule_callback(req: ScheduleCallbackRequest) -> ScheduleCallbackResponse:
    _validate_account(req.account_number)
    cid = f"CB-{uuid.uuid4().hex[:10].upper()}"
    scheduled_at = datetime.now(timezone.utc).isoformat()
    logger.info(
        f"schedule_callback: account={req.account_number} id={cid} "
        f"window={req.callback_window_start}..{req.callback_window_end}"
    )
    return ScheduleCallbackResponse(callback_id=cid, scheduled_at=scheduled_at)


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": "insidellm-workers",
        "actions": [
            "lookup_account",
            "draft_fdcpa_letter",
            "send_letter",
            "schedule_callback",
        ],
    }


@app.get("/")
async def root() -> dict:
    return {
        "service": "insidellm-workers",
        "version": app.version,
        "description": "Stub action backends for the Dispute Handler showcase agent.",
        "endpoints": [
            "POST /actions/lookup_account",
            "POST /actions/draft_fdcpa_letter",
            "POST /actions/send_letter",
            "POST /actions/schedule_callback",
            "GET  /health",
        ],
    }
