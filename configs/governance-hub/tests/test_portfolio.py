"""Unit tests for P4.1 portfolio observability.

Covers:
  * _row_to_dict serializes datetimes + Decimals to JSON-safe values
  * get_overview merges fleet summary + identity totals
  * get_at_risk passes threshold params through to central_sql
  * get_time_series clamps the `days` arg into the allowed range
  * Router exists and uses the view role
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services import portfolio_service as ps


# ---------------------------------------------------------------------------
# _row_to_dict serialization
# ---------------------------------------------------------------------------


def test_row_to_dict_serializes_datetime():
    now = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    row = {"synced_at": now, "instance_id": "vm-9"}
    out = ps._row_to_dict(row)
    assert out["synced_at"] == now.isoformat()
    assert out["instance_id"] == "vm-9"


def test_row_to_dict_serializes_decimal_as_float():
    row = {"total_spend": Decimal("123.45"), "instance_id": "vm-9"}
    out = ps._row_to_dict(row)
    assert out["total_spend"] == pytest.approx(123.45)
    assert isinstance(out["total_spend"], float)


def test_row_to_dict_leaves_primitives_alone():
    row = {"count": 42, "ok": True, "name": "alice", "score": 3.14}
    out = ps._row_to_dict(row)
    assert out == row


# ---------------------------------------------------------------------------
# get_overview merges fleet + identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_merges_fleet_and_identity():
    fake_fleet = {
        "total_instances": 32,
        "fleet_total_spend": 12345.67,
        "avg_compliance_score": 94.2,
    }
    fake_identity = {"total_users": 480, "instances_with_identity": 28}

    with patch.object(ps, "get_fleet_summary", AsyncMock(return_value=fake_fleet)), \
         patch.object(ps, "_get_identity_totals", AsyncMock(return_value=fake_identity)):
        result = await ps.get_overview()

    assert result["fleet"] == fake_fleet
    assert result["identity"] == fake_identity


# ---------------------------------------------------------------------------
# get_per_instance / by_industry / at_risk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_instance_serializes_rows():
    fake_rows = [
        {
            "instance_id": "vm-9",
            "instance_name": "InsideLLM Primary",
            "industry": "collections",
            "total_spend": Decimal("125.50"),
            "last_sync_at": datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc),
            "compliance_score": Decimal("92.5"),
        },
    ]

    async def _fake_rcq(fn):
        db = MagicMock()
        result = MagicMock()
        result.mappings = MagicMock(return_value=MagicMock(all=MagicMock(return_value=fake_rows)))
        db.execute = MagicMock(return_value=result)
        return fn(db)

    with patch.object(ps, "run_central_query", _fake_rcq):
        rows = await ps.get_per_instance()

    assert len(rows) == 1
    assert rows[0]["total_spend"] == pytest.approx(125.50)
    assert rows[0]["last_sync_at"] == "2026-04-18T10:00:00+00:00"


@pytest.mark.asyncio
async def test_at_risk_passes_thresholds_as_params():
    captured_params: dict = {}

    async def _fake_rcq(fn):
        db = MagicMock()

        def _execute(sql, params=None):
            captured_params.update(params or {})
            result = MagicMock()
            result.mappings = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return result

        db.execute = _execute
        return fn(db)

    with patch.object(ps, "run_central_query", _fake_rcq):
        await ps.get_at_risk(compliance_threshold=80.0, critical_flag_threshold=3, error_threshold=25)

    assert captured_params["compliance_threshold"] == 80.0
    assert captured_params["critical_flag_threshold"] == 3
    assert captured_params["error_threshold"] == 25


@pytest.mark.asyncio
async def test_time_series_clamps_days_range():
    # Capture the `days` param that reaches the DB layer.
    captured_days: list[int] = []

    async def _fake_rcq(fn):
        db = MagicMock()

        def _execute(sql, params=None):
            captured_days.append(params["days"])
            result = MagicMock()
            result.mappings = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return result

        db.execute = _execute
        return fn(db)

    with patch.object(ps, "run_central_query", _fake_rcq):
        await ps.get_time_series(days=1000)    # over max
        await ps.get_time_series(days=-5)      # under min
        await ps.get_time_series(days=14)      # normal

    assert captured_days == [180, 1, 14]


@pytest.mark.asyncio
async def test_identity_totals_returns_zeros_when_central_empty():
    async def _fake_rcq(fn):
        return None

    with patch.object(ps, "run_central_query", _fake_rcq):
        result = await ps._get_identity_totals()

    assert result == {"total_users": 0, "instances_with_identity": 0}


# ---------------------------------------------------------------------------
# Router shape
# ---------------------------------------------------------------------------


def test_router_exposes_expected_paths():
    """Source-level check — avoids importing the full router chain (which
    pulls in RBAC + python-jose etc.)."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1]
        / "src" / "routers" / "portfolio.py"
    ).read_text(encoding="utf-8")
    expected = [
        '"/portfolio"',
        '"/api/v1/portfolio/overview"',
        '"/api/v1/portfolio/instances"',
        '"/api/v1/portfolio/industries"',
        '"/api/v1/portfolio/time-series"',
        '"/api/v1/portfolio/at-risk"',
    ]
    for p in expected:
        assert p in src, f"router missing path {p}"


def test_portfolio_page_file_exists():
    """Regression guard — the HTML landing file must ship with the
    package so `/governance/portfolio` doesn't 500 on render."""
    from pathlib import Path
    page = (
        Path(__file__).resolve().parents[1]
        / "src" / "pages" / "portfolio.html"
    )
    assert page.exists(), f"portfolio.html missing at {page}"
    text = page.read_text(encoding="utf-8")
    # Sanity check key anchors the JS uses.
    for anchor in ("kpi-instances", "trendChart", "industryChart", "instances-body", "atrisk-body"):
        assert anchor in text, f"portfolio.html missing id={anchor}"
