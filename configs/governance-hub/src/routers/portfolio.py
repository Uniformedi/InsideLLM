"""Portfolio observability REST endpoints + HTML dashboard (P4.1).

The Parent Portfolio-facing cross-tenant view:

  * GET /governance/portfolio                          HTML dashboard
  * GET /api/v1/portfolio/overview                     headline aggregates
  * GET /api/v1/portfolio/instances                    per-instance breakdown
  * GET /api/v1/portfolio/industries                   per-industry rollup
  * GET /api/v1/portfolio/time-series?days=14          daily trend data
  * GET /api/v1/portfolio/at-risk                      flagged instances

All data views require only the `view` role — a portfolio operator can
browse but not mutate.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from ..services.portfolio_service import (
    get_at_risk,
    get_by_industry,
    get_overview,
    get_per_instance,
    get_time_series,
)
from ..services.rbac import require_view

logger = logging.getLogger("governance-hub.portfolio.router")

router = APIRouter(tags=["portfolio"])

_PAGE_PATH = Path(__file__).resolve().parent.parent / "pages" / "portfolio.html"


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


@router.get("/portfolio", response_class=HTMLResponse, dependencies=[require_view])
async def portfolio_page() -> HTMLResponse:
    """Serve the static portfolio dashboard HTML; JS fetches the JSON
    endpoints below at load time."""
    if not _PAGE_PATH.exists():
        return HTMLResponse(
            "<h1>Portfolio dashboard unavailable</h1><p>pages/portfolio.html missing.</p>",
            status_code=500,
        )
    return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# JSON APIs
# ---------------------------------------------------------------------------


@router.get("/api/v1/portfolio/overview", dependencies=[require_view])
async def overview() -> dict:
    return await get_overview()


@router.get("/api/v1/portfolio/instances", dependencies=[require_view])
async def per_instance() -> dict:
    rows = await get_per_instance()
    return {"instances": rows, "total": len(rows)}


@router.get("/api/v1/portfolio/industries", dependencies=[require_view])
async def by_industry() -> dict:
    rows = await get_by_industry()
    return {"industries": rows, "total": len(rows)}


@router.get("/api/v1/portfolio/time-series", dependencies=[require_view])
async def time_series(days: int = Query(14, ge=1, le=180)) -> dict:
    rows = await get_time_series(days)
    return {"days": days, "points": rows}


@router.get("/api/v1/portfolio/at-risk", dependencies=[require_view])
async def at_risk(
    compliance_threshold: float = Query(70.0, ge=0, le=100),
    critical_flag_threshold: int = Query(5, ge=0),
    error_threshold: int = Query(50, ge=0),
) -> dict:
    rows = await get_at_risk(compliance_threshold, critical_flag_threshold, error_threshold)
    return {"flagged": rows, "total": len(rows)}
