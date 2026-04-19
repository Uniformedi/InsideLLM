"""Agent builder UI — serves the /governance/agents HTML page (P1.5).

The JSON APIs it consumes all live under /governance/api/v1/agents and
/governance/api/v1/actions (see routers/agents.py and routers/actions.py).
This router exists purely to hand the static HTML to the browser.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..services.rbac import require_view

logger = logging.getLogger("governance-hub.agents-ui")

router = APIRouter(tags=["agents-ui"])

_PAGE_PATH = Path(__file__).resolve().parent.parent / "pages" / "agents.html"


@router.get("/agents", response_class=HTMLResponse, dependencies=[require_view])
async def agents_page() -> HTMLResponse:
    if not _PAGE_PATH.exists():
        return HTMLResponse(
            "<h1>Agent Builder unavailable</h1><p>pages/agents.html missing.</p>",
            status_code=500,
        )
    return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))
