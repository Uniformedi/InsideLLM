"""P1.6 — Dispute Handler showcase end-to-end checks.

Wires together the pieces the Parent Organization demo depends on:
  * Agent manifest YAML parses under the current pydantic schema
  * Every action_id the manifest references exists in the shipped
    tenant action catalog (organization-collections) or core catalog
  * The manifest's guardrail tier is at least as strict as every
    referenced action's minimum_guardrail_tier
  * Translator payloads reflect the manifest verbatim (no silent drift)
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.schemas.actions import ActionCatalogEntry
from src.schemas.agents import AgentManifest
from src.services.action_catalog_seed import load_core_wrappers
from src.services.action_catalog_service import parse_multi_action_document
from src.services.agent_translator import build_litellm_key_payload, build_owui_model_payload


REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENT_YAML = REPO_ROOT / "examples" / "agents" / "dispute-handler.yaml"
_TENANT_ACTIONS_YAML = (
    REPO_ROOT / "examples" / "actions" / "organization-collections" / "dispute-handler-actions.yaml"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest() -> AgentManifest:
    assert _AGENT_YAML.exists(), f"missing agent manifest: {_AGENT_YAML}"
    data = yaml.safe_load(_AGENT_YAML.read_text(encoding="utf-8"))
    return AgentManifest.model_validate(data)


@pytest.fixture(scope="module")
def tenant_actions() -> list[ActionCatalogEntry]:
    assert _TENANT_ACTIONS_YAML.exists(), (
        f"missing tenant action catalog: {_TENANT_ACTIONS_YAML}"
    )
    body = _TENANT_ACTIONS_YAML.read_text(encoding="utf-8")
    return parse_multi_action_document(body, content_type="application/yaml")


@pytest.fixture(scope="module")
def core_actions() -> list[ActionCatalogEntry]:
    return load_core_wrappers()


# ---------------------------------------------------------------------------
# Manifest validity
# ---------------------------------------------------------------------------


def test_manifest_parses_under_v1_1(manifest):
    assert manifest.schema_version == "1.1"
    assert manifest.agent_id == "dispute-handler"
    assert manifest.tenant_id == "organization-collections"
    assert manifest.guardrails.profile == "tier_fdcpa_regulated"


def test_manifest_knowledge_is_strict_scoped(manifest):
    # strict scope + declared collections → rag_scope rule can enforce.
    assert manifest.knowledge.scope == "strict"
    assert len(manifest.knowledge.collections) >= 1


def test_manifest_has_approval_gated_send_letter(manifest):
    """send_letter is the write path — must require approval."""
    send = next(a for a in manifest.actions if a.action_id == "send_letter")
    assert send.approval_required is True
    assert send.approval_target == "compliance_manager"
    assert send.scope == "write"


# ---------------------------------------------------------------------------
# Action coverage — every referenced action_id is actually registered
# somewhere visible to this tenant.
# ---------------------------------------------------------------------------


def test_every_referenced_action_is_registered(manifest, tenant_actions, core_actions):
    referenced = {a.action_id for a in manifest.actions}

    tenant_ids = {
        a.action_id for a in tenant_actions
        if a.tenant_id in (manifest.tenant_id, None, "core")
    }
    core_ids = {a.action_id for a in core_actions}
    resolvable = tenant_ids | core_ids

    missing = referenced - resolvable
    assert not missing, (
        f"manifest references actions not registered in tenant or core "
        f"catalog: {sorted(missing)}"
    )


def test_tenant_actions_use_correct_tenant_id(tenant_actions):
    assert all(a.tenant_id == "organization-collections" for a in tenant_actions), (
        "dispute-handler actions must be tenant-scoped so they don't bleed "
        "into other portfolio companies"
    )


def test_tenant_actions_require_fdcpa_tier(tenant_actions):
    """Every Organization action runs in collections context — minimum tier must
    be at least financial-regulated, not general-business."""
    relaxed = [
        a.action_id for a in tenant_actions
        if a.guardrail_requirements.minimum_guardrail_tier
        in ("tier_unrestricted", "tier_general_business")
    ]
    assert not relaxed, (
        f"these actions must raise tier to fdcpa/financial/hipaa: {relaxed}"
    )


def test_send_letter_is_approval_gated_at_catalog_layer(tenant_actions):
    """Defense-in-depth — both the agent manifest AND the action catalog
    must demand approval. If either slips, approval disappears."""
    send = next(a for a in tenant_actions if a.action_id == "send_letter")
    assert send.guardrail_requirements.requires_approval is True


# ---------------------------------------------------------------------------
# Translator alignment — the LiteLLM key metadata + OWUI model ship what
# the manifest says, not something inferred or relaxed.
# ---------------------------------------------------------------------------


def test_translator_key_metadata_matches_manifest(manifest):
    payload = build_litellm_key_payload(
        manifest, manifest_hash="d" * 64, version=1
    )
    md = payload["metadata"]
    assert md["tenant_id"] == "organization-collections"
    assert md["agent_id"] == "dispute-handler"
    assert md["guardrail_profile"] == "tier_fdcpa_regulated"
    assert md["knowledge_scope"] == "strict"
    assert set(md["knowledge_collections"]) == set(manifest.knowledge.collections)
    assert md["dlp_overrides"]["allow_pii"] is False
    assert md["dlp_overrides"]["allow_financials"] is False


def test_translator_owui_model_carries_instructions(manifest):
    payload = build_owui_model_payload(manifest)
    # Instructions are the system prompt — the most demo-visible field.
    assert payload["params"]["system"].startswith("You are a dispute resolution")
    # Temperature is capped at the manifest ceiling (0.2 here, lower than default).
    assert payload["params"]["temperature"] == pytest.approx(0.2)
    # Tag surface includes identity + tier so tags can filter in OWUI.
    tags = {t["name"] for t in payload["meta"]["tags"]}
    assert "tier_fdcpa_regulated" in tags
    assert "tenant:organization-collections" in tags


# ---------------------------------------------------------------------------
# Demo runbook present
# ---------------------------------------------------------------------------


def test_demo_runbook_ships():
    """If the runbook disappears, the Parent Organization prep becomes tribal knowledge."""
    runbook = REPO_ROOT / "docs" / "PARENT-ORGANIZATION-DEMO-RUNBOOK.md"
    assert runbook.exists(), f"missing {runbook}"
    text = runbook.read_text(encoding="utf-8")
    for anchor in ("Pre-flight", "seed-dispute-handler.sh", "tier_fdcpa_regulated", "Approval Queue"):
        assert anchor in text, f"runbook missing section anchor: {anchor}"
