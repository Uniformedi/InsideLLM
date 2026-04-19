"""Regression tests for the P1.5 Agent Builder UI.

Keeps the HTML page + router shape stable without requiring a live
browser. Anchors the JS looks up must exist; router source must bind
the /agents route to the view role.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PAGE = (
    REPO_ROOT / "configs" / "governance-hub" / "src" / "pages" / "agents.html"
)
ROUTER = (
    REPO_ROOT / "configs" / "governance-hub" / "src" / "routers" / "agents_ui.py"
)


def test_page_exists_and_has_required_anchors():
    assert PAGE.exists(), f"missing {PAGE}"
    text = PAGE.read_text(encoding="utf-8")
    # Every id the JS reads or writes must be present in the DOM.
    required_ids = [
        "agent-list",
        "agent-form",
        "f-tenant-id",
        "f-agent-id",
        "f-display-name",
        "f-display-desc",
        "f-instructions",
        "f-starters",
        "f-collections",
        "f-knowledge-scope",
        "f-actions",
        "f-profile",
        "f-visibility",
        "preview-modal",
        "audit-modal",
    ]
    for rid in required_ids:
        assert f'id="{rid}"' in text, f"page missing element id={rid}"


def test_page_wires_correct_api_paths():
    text = PAGE.read_text(encoding="utf-8")
    # Must use the shared api() helper under /governance/api/v1 so the
    # nginx subpath lines up. Regression guard against someone hand-coding
    # a relative path that breaks in production.
    assert "/api/v1/agents" in text
    assert "/api/v1/actions" in text
    assert "/api/v1/agents/${encodeURIComponent" in text, (
        "CRUD paths must encode tenant/agent to handle hyphens + case"
    )


def test_page_guardrail_profile_options_match_schema():
    text = PAGE.read_text(encoding="utf-8")
    # The six named profiles from the schema — the form must expose all of them.
    for p in [
        "tier_general_business",
        "tier_financial_regulated",
        "tier_fdcpa_regulated",
        "tier_hipaa_regulated",
        "tier_unrestricted",
        "tier_custom",
    ]:
        assert p in text, f"profile option missing: {p}"


def test_router_binds_view_role():
    src = ROUTER.read_text(encoding="utf-8")
    assert "@router.get(\"/agents\"" in src
    assert "require_view" in src
    assert "agents.html" in src


def test_landing_page_links_to_agent_builder():
    main_py = (REPO_ROOT / "configs" / "governance-hub" / "src" / "main.py").read_text(encoding="utf-8")
    assert 'href="/governance/agents"' in main_py
    assert "Agent Builder" in main_py
