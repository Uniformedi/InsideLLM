"""Unit tests for the P1.3 action catalog + core-wrapper seed.

Covers:
  * parse_multi_action_document handles single-entry, list, and
    `actions: [...]` YAML/JSON shapes
  * Every shipped core wrapper YAML parses + validates cleanly
  * The full core set returns a stable count and coverage across
    all 5 tools so a silent deletion gets caught
  * Guardrail tiers are sane (nothing below tier_general_business
    except if intentionally unrestricted)
"""
from __future__ import annotations

import pytest

from src.schemas.actions import ActionCatalogEntry
from src.services.action_catalog_seed import load_core_wrappers
from src.services.action_catalog_service import parse_multi_action_document


# ---------------------------------------------------------------------------
# parse_multi_action_document
# ---------------------------------------------------------------------------


SINGLE_ENTRY_JSON = {
    "schema_version": "1.0",
    "action_id": "ping",
    "tenant_id": "core",
    "display_name": "Ping",
    "description": "Smoke test.",
    "category": "other",
    "backend": {"type": "fastapi_http", "url": "http://x:1/ping"},
    "guardrail_requirements": {
        "minimum_guardrail_tier": "tier_general_business",
    },
}


def test_parse_single_entry_dict():
    import json

    entries = parse_multi_action_document(
        json.dumps(SINGLE_ENTRY_JSON), content_type="application/json"
    )
    assert len(entries) == 1
    assert entries[0].action_id == "ping"


def test_parse_multi_action_yaml():
    import yaml

    doc = {
        "schema_version": "1.0",
        "actions": [SINGLE_ENTRY_JSON, {**SINGLE_ENTRY_JSON, "action_id": "ping2"}],
    }
    entries = parse_multi_action_document(yaml.dump(doc), content_type="application/yaml")
    assert [e.action_id for e in entries] == ["ping", "ping2"]


def test_parse_bare_list_yaml():
    import yaml

    doc = [SINGLE_ENTRY_JSON, {**SINGLE_ENTRY_JSON, "action_id": "ping2"}]
    entries = parse_multi_action_document(yaml.dump(doc), content_type="application/yaml")
    assert len(entries) == 2


def test_parse_rejects_malformed_entry():
    import yaml

    # Missing required `backend` field.
    bad = {**SINGLE_ENTRY_JSON}
    bad.pop("backend")
    with pytest.raises(Exception):
        parse_multi_action_document(yaml.dump(bad), content_type="application/yaml")


# ---------------------------------------------------------------------------
# Core-wrapper shipment
# ---------------------------------------------------------------------------


def test_core_wrappers_load_without_error():
    entries = load_core_wrappers()
    assert isinstance(entries, list)
    assert all(isinstance(e, ActionCatalogEntry) for e in entries)
    # Regression guard — shrinking this silently is almost always a bug.
    assert len(entries) >= 17, (
        f"expected ≥17 core actions across 5 tools, got {len(entries)}"
    )


def test_core_wrappers_cover_all_five_tools():
    entries = load_core_wrappers()
    prefixes = {e.action_id.split("_")[0] for e in entries}
    expected = {
        "docforge",
        "advisor",         # governance-advisor
        "fleet",
        "sysdesigner",
        "dataconnector",
    }
    assert expected.issubset(prefixes), (
        f"missing tool coverage; got prefixes={prefixes}, expected {expected}"
    )


def test_core_wrappers_have_unique_ids():
    entries = load_core_wrappers()
    ids = [(e.tenant_id, e.action_id) for e in entries]
    assert len(ids) == len(set(ids)), f"duplicate action_id in core wrappers: {ids}"


def test_core_wrappers_use_core_tenant():
    entries = load_core_wrappers()
    assert all(e.tenant_id == "core" for e in entries), (
        "shipped wrappers must use tenant_id=core so all tenants inherit them"
    )


def test_core_wrappers_have_reasonable_tiers():
    """Nothing below tier_general_business by default — the ancient
    tier_unrestricted exists for explicit escape hatches, not accidents."""
    entries = load_core_wrappers()
    weak = [
        e.action_id for e in entries
        if e.guardrail_requirements.minimum_guardrail_tier == "tier_unrestricted"
    ]
    assert not weak, f"wrappers must not default to tier_unrestricted: {weak}"


def test_core_wrappers_specify_backend_type():
    """Every action must declare a concrete backend (fastapi_http etc.),
    not rely on runtime guessing."""
    entries = load_core_wrappers()
    for e in entries:
        # pydantic validation already guarantees this; spot-check that the
        # dumped form round-trips with a type discriminator present.
        dumped = e.model_dump(mode="json")
        assert dumped["backend"]["type"], f"{e.action_id} missing backend.type"


def test_dataconnector_query_requires_financial_tier():
    """Regression guard on the sensitive data-connector.query wrapper —
    if someone relaxes this, financial data leaves the platform to any
    tier_general_business agent."""
    entries = {e.action_id: e for e in load_core_wrappers()}
    q = entries.get("dataconnector_query_source")
    assert q is not None, "dataconnector_query_source missing"
    assert q.guardrail_requirements.minimum_guardrail_tier == "tier_financial_regulated"
    assert "financial" in q.guardrail_requirements.data_classes
