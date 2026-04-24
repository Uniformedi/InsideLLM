"""Portfolio observability — cross-tenant aggregate queries (P4.1).

Reads from the central governance DB to produce the fleet-wide view
a portfolio operator (e.g. Parent Portfolio) sees on the /governance/portfolio
page. Every metric pivots on the *latest* telemetry row per instance
so a reporting lag doesn't distort the headline numbers.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from ..db.central_db import run_central_query
from ..db.central_sql import SQL
from .fleet_service import get_fleet_summary

logger = logging.getLogger("governance-hub.portfolio")

# At-risk thresholds — tunable but baked in for now. Operators can
# override via governance_settings_overrides in a later pass.
_DEFAULT_COMPLIANCE_THRESHOLD = 70.0
_DEFAULT_CRITICAL_FLAG_THRESHOLD = 5
_DEFAULT_ERROR_THRESHOLD = 50


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
            # Decimal → float for JSON.
            try:
                out[k] = float(v)
            except Exception:
                out[k] = str(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Public queries
# ---------------------------------------------------------------------------


async def get_overview() -> dict[str, Any]:
    """Headline numbers: total instances, spend, requests, users, compliance.

    Re-uses get_fleet_summary for the per-industry + aggregate block, then
    layers on identity-plane totals (Phase 2 Keycloak sync data).
    """
    summary = await get_fleet_summary()
    identity = await _get_identity_totals()
    return {"fleet": summary, "identity": identity}


async def get_per_instance() -> list[dict[str, Any]]:
    def _query(db):
        rows = db.execute(text(SQL.portfolio_per_instance)).mappings().all()
        return [_row_to_dict(r) for r in rows]

    result = await run_central_query(_query)
    return result or []


async def get_by_industry() -> list[dict[str, Any]]:
    def _query(db):
        rows = db.execute(text(SQL.portfolio_by_industry)).mappings().all()
        return [_row_to_dict(r) for r in rows]

    result = await run_central_query(_query)
    return result or []


async def get_time_series(days: int = 14) -> list[dict[str, Any]]:
    """Daily rollup over the last N days. Drives the trend chart."""
    days = max(1, min(days, 180))

    def _query(db):
        rows = db.execute(text(SQL.portfolio_time_series), {"days": days}).mappings().all()
        return [_row_to_dict(r) for r in rows]

    result = await run_central_query(_query)
    return result or []


async def get_at_risk(
    compliance_threshold: float = _DEFAULT_COMPLIANCE_THRESHOLD,
    critical_flag_threshold: int = _DEFAULT_CRITICAL_FLAG_THRESHOLD,
    error_threshold: int = _DEFAULT_ERROR_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return only instances that hit at least one at-risk predicate.
    Reason string identifies which predicate fired (first match wins in
    the CASE expression — see central_sql.py)."""
    def _query(db):
        rows = db.execute(
            text(SQL.portfolio_at_risk),
            {
                "compliance_threshold": compliance_threshold,
                "critical_flag_threshold": critical_flag_threshold,
                "error_threshold": error_threshold,
            },
        ).mappings().all()
        return [_row_to_dict(r) for r in rows]

    result = await run_central_query(_query)
    return result or []


async def _get_identity_totals() -> dict[str, Any]:
    """Fleet-wide user count from Phase 2's replicated identity tables.
    Returns zeroes when central DB is empty — don't fail the overview."""
    def _query(db):
        try:
            row = db.execute(text(SQL.portfolio_identity_totals)).mappings().first()
            return _row_to_dict(row) if row else {}
        except Exception as e:
            logger.debug(f"identity totals unavailable: {e}")
            return {"total_users": 0, "instances_with_identity": 0}

    result = await run_central_query(_query)
    return result or {"total_users": 0, "instances_with_identity": 0}
