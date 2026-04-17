"""Unit tests for agent_translator — manifest → runtime translation.

Covers:
  * Pure payload builders — shape + guardrail metadata propagation
  * Name helpers — determinism across calls
  * Dry-run — planned_calls fingerprinted, no HTTP issued
  * Provision happy path — both backends OK → state=provisioned
  * Partial failure — one backend fails → state=partial, retry-safe
  * Deprovision — 404 from backends treated as already-gone

The translator's HTTP clients are mocked via fake implementations that
track calls; httpx itself is never touched so tests run in ~0.01s each.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.db.models import Agent
from src.schemas.agents import (
    AgentDisplay,
    AgentGuardrails,
    AgentKnowledge,
    AgentManifest,
    AgentVisibility,
    DlpOverrides,
    GuardrailProfile,
    KnowledgeScope,
    VisibilityScope,
)
from src.services import agent_translator as at


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mk_manifest(**overrides: Any) -> AgentManifest:
    """Build a minimal-valid manifest; overrides shallow-merge onto defaults."""
    base = dict(
        schema_version="1.1",
        agent_id="dispute-handler",
        tenant_id="organization-collections",
        created_by="dan@uniformedi.com",
        team="collections",
        display=AgentDisplay(
            name="Dispute Handler",
            description="Handles FDCPA consumer disputes",
            conversation_starters=["What's the §1692g status?"],
        ),
        instructions=(
            "You are a compliance-first dispute handler. Always cite the section."
        ),
        guardrails=AgentGuardrails(
            profile=GuardrailProfile.FDCPA,
            max_actions_per_session=5,
            token_budget_per_session=10000,
            daily_usd_budget=25.0,
            rpm_limit=10,
            allowed_models=["claude-sonnet", "claude-haiku"],
            temperature_cap=0.3,
            dlp_overrides=DlpOverrides(allow_financials=True),
        ),
        visibility=AgentVisibility(scope=VisibilityScope.TEAM),
    )
    base.update(overrides)
    return AgentManifest.model_validate(base)


def _mk_agent(manifest: AgentManifest, **overrides: Any) -> Agent:
    """Build a detached (no-DB) Agent row for translator tests."""
    row = Agent(
        agent_id=manifest.agent_id,
        tenant_id=manifest.tenant_id,
        name=manifest.display.name,
        description=manifest.display.description,
        team=manifest.team,
        created_by=manifest.created_by,
        manifest_json=manifest.model_dump(mode="json"),
        manifest_schema_version=manifest.schema_version,
        guardrail_profile=manifest.guardrails.profile,
        visibility_scope=manifest.visibility.scope,
        status="published",
        is_active=True,
        version=overrides.pop("version", 1),
        manifest_hash=overrides.pop("manifest_hash", "a" * 64),
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


class _FakeLiteLLM:
    def __init__(self, *, fail: bool = False, return_token: str = "sk-live-abcd1234"):
        self.fail = fail
        self.return_token = return_token
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[str] = []

    async def upsert_key(self, payload):
        if self.fail:
            raise RuntimeError("litellm-down")
        self.upserts.append(payload)
        return {"key": self.return_token, "key_alias": payload["key_alias"]}

    async def delete_key_by_alias(self, alias):
        if self.fail:
            raise RuntimeError("litellm-down")
        self.deletes.append(alias)
        return True


class _FakeOWUI:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[str] = []

    async def upsert_model(self, payload):
        if self.fail:
            raise RuntimeError("owui-down")
        self.upserts.append(payload)
        return {"id": payload["id"]}

    async def delete_model(self, model_id):
        if self.fail:
            raise RuntimeError("owui-down")
        self.deletes.append(model_id)
        return True


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------


def test_name_helpers_are_deterministic():
    a1 = at.litellm_key_alias_for("acme", "bot")
    a2 = at.litellm_key_alias_for("acme", "bot")
    m1 = at.owui_model_id_for("acme", "bot")
    m2 = at.owui_model_id_for("acme", "bot")
    assert a1 == a2 == "agent-acme--bot"
    assert m1 == m2 == "insidellm-agent-acme--bot"


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def test_litellm_payload_carries_guardrail_metadata():
    manifest = _mk_manifest()
    payload = at.build_litellm_key_payload(
        manifest, manifest_hash="deadbeef" * 8, version=3
    )
    assert payload["key_alias"] == "agent-organization-collections--dispute-handler"
    assert payload["models"] == ["claude-sonnet", "claude-haiku"]
    assert payload["rpm_limit"] == 10
    # Daily budget passthrough.
    assert payload["max_budget"] == 25.0
    assert payload["budget_duration"] == "1d"
    # Metadata is the contract with the downstream OPA guardrail.
    md = payload["metadata"]
    assert md["tenant_id"] == "organization-collections"
    assert md["agent_id"] == "dispute-handler"
    assert md["guardrail_profile"] == "tier_fdcpa_regulated"
    assert md["agent_version"] == 3
    assert md["manifest_hash"] == "deadbeef" * 8
    assert md["dlp_overrides"]["allow_financials"] is True
    assert md["visibility_scope"] == "team"


def test_litellm_payload_omits_budget_when_unset():
    manifest = _mk_manifest(
        guardrails=AgentGuardrails(
            profile=GuardrailProfile.GENERAL_BUSINESS,
            allowed_models=["claude-sonnet"],
        )
    )
    payload = at.build_litellm_key_payload(manifest, manifest_hash="", version=1)
    assert "max_budget" not in payload
    assert "budget_duration" not in payload


def test_owui_payload_system_prompt_and_temperature_cap():
    manifest = _mk_manifest()
    payload = at.build_owui_model_payload(manifest)
    assert payload["id"] == "insidellm-agent-organization-collections--dispute-handler"
    assert payload["base_model_id"] == "claude-sonnet"
    assert payload["params"]["system"].startswith("You are a compliance-first")
    # Cap pins temperature <= 0.3 even though default 0.7 was requested.
    assert payload["params"]["temperature"] == pytest.approx(0.3)
    # Tags carry identity for OWUI-side filtering.
    tag_names = {t["name"] for t in payload["meta"]["tags"]}
    assert "tier_fdcpa_regulated" in tag_names
    assert "tenant:organization-collections" in tag_names
    assert "team:collections" in tag_names


def test_owui_access_control_maps_visibility_team():
    manifest = _mk_manifest()
    payload = at.build_owui_model_payload(manifest)
    ac = payload["access_control"]
    assert ac is not None
    assert ac["read"]["group_ids"] == ["collections"]


def test_owui_access_control_org_scope_is_public():
    manifest = _mk_manifest(
        visibility=AgentVisibility(scope=VisibilityScope.ORG)
    )
    payload = at.build_owui_model_payload(manifest)
    # org-scoped agents are visible to every tenant user — OWUI treats
    # access_control=null as unrestricted within the tenant.
    assert payload["access_control"] is None


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_dry_run_makes_no_calls():
    manifest = _mk_manifest()
    row = _mk_agent(manifest)
    llm = _FakeLiteLLM()
    owui = _FakeOWUI()
    t = at.AgentTranslator(litellm_client=llm, owui_client=owui)

    result = await t.provision(row, dry_run=True)

    assert result.state == "skipped"
    assert result.ok is True
    assert result.litellm_key_alias == "agent-organization-collections--dispute-handler"
    assert result.owui_model_id == "insidellm-agent-organization-collections--dispute-handler"
    assert len(result.planned_calls) == 2
    assert llm.upserts == [] and owui.upserts == []


# ---------------------------------------------------------------------------
# Provision — success and partial-failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_happy_path():
    manifest = _mk_manifest()
    row = _mk_agent(manifest)
    llm = _FakeLiteLLM()
    owui = _FakeOWUI()
    t = at.AgentTranslator(litellm_client=llm, owui_client=owui)

    result = await t.provision(row)

    assert result.ok is True
    assert result.state == "provisioned"
    assert result.litellm_key_last4 == "1234"
    # Payload reached the fake client unchanged.
    assert llm.upserts[0]["metadata"]["agent_id"] == "dispute-handler"
    assert owui.upserts[0]["id"] == "insidellm-agent-organization-collections--dispute-handler"

    # apply_result pins the binding onto the row.
    at.AgentTranslator.apply_result(row, result)
    assert row.runtime_sync_state == "provisioned"
    assert row.litellm_key_alias == "agent-organization-collections--dispute-handler"
    assert row.litellm_key_last4 == "1234"
    assert row.owui_model_id == "insidellm-agent-organization-collections--dispute-handler"
    assert row.runtime_manifest_hash == row.manifest_hash


@pytest.mark.asyncio
async def test_provision_partial_records_what_succeeded():
    manifest = _mk_manifest()
    row = _mk_agent(manifest)
    llm = _FakeLiteLLM()          # ok
    owui = _FakeOWUI(fail=True)   # down
    t = at.AgentTranslator(litellm_client=llm, owui_client=owui)

    result = await t.provision(row)

    assert result.ok is False
    assert result.state == "partial"
    assert result.litellm_key_last4 == "1234"
    assert "owui-down" in (result.owui_error or "")
    # apply_result preserves what worked, so a retry only touches the broken side.
    at.AgentTranslator.apply_result(row, result)
    assert row.runtime_sync_state == "partial"
    assert row.litellm_key_alias == "agent-organization-collections--dispute-handler"
    assert row.runtime_sync_error and "owui-down" in row.runtime_sync_error


@pytest.mark.asyncio
async def test_provision_both_down_marks_failed():
    manifest = _mk_manifest()
    row = _mk_agent(manifest)
    llm = _FakeLiteLLM(fail=True)
    owui = _FakeOWUI(fail=True)
    t = at.AgentTranslator(litellm_client=llm, owui_client=owui)

    result = await t.provision(row)

    assert result.ok is False
    assert result.state == "failed"
    assert "litellm-down" in (result.litellm_error or "")
    assert "owui-down" in (result.owui_error or "")
    at.AgentTranslator.apply_result(row, result)
    assert row.runtime_sync_state == "failed"


# ---------------------------------------------------------------------------
# Deprovision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deprovision_removes_from_both_backends():
    manifest = _mk_manifest()
    row = _mk_agent(
        manifest,
        litellm_key_alias="agent-organization-collections--dispute-handler",
        owui_model_id="insidellm-agent-organization-collections--dispute-handler",
        runtime_sync_state="provisioned",
    )
    llm = _FakeLiteLLM()
    owui = _FakeOWUI()
    t = at.AgentTranslator(litellm_client=llm, owui_client=owui)

    result = await t.deprovision(row)

    assert result.ok is True
    assert result.state == "deprovisioned"
    assert llm.deletes == ["agent-organization-collections--dispute-handler"]
    assert owui.deletes == ["insidellm-agent-organization-collections--dispute-handler"]

    at.AgentTranslator.apply_result(row, result)
    assert row.runtime_sync_state == "deprovisioned"
    assert row.litellm_key_alias is None
    assert row.owui_model_id is None


@pytest.mark.asyncio
async def test_deprovision_without_prior_binding_still_works():
    # If an agent is retired without ever being published, deprovision
    # should still hit the deterministic alias/model_id and succeed
    # (backends treat 404 as already-gone).
    manifest = _mk_manifest()
    row = _mk_agent(manifest, runtime_sync_state="unprovisioned")
    llm = _FakeLiteLLM()
    owui = _FakeOWUI()
    t = at.AgentTranslator(litellm_client=llm, owui_client=owui)

    result = await t.deprovision(row)

    assert result.ok is True
    assert result.litellm_key_alias == "agent-organization-collections--dispute-handler"
    assert llm.deletes and owui.deletes


# ---------------------------------------------------------------------------
# Regression: the metadata shape the humility callback reads MUST include
# the minimum fields the OPA input builder needs.
# ---------------------------------------------------------------------------


def test_litellm_metadata_includes_all_opa_input_keys():
    """The humility_guardrail callback extracts these fields from
    `key/info`. If we drop one, OPA input becomes malformed and the
    fail-closed default denies every request."""
    manifest = _mk_manifest()
    payload = at.build_litellm_key_payload(manifest, manifest_hash="x" * 64, version=1)
    required = {
        "tenant_id", "agent_id", "agent_version", "manifest_hash",
        "guardrail_profile", "visibility_scope", "pii_handling",
        "max_actions_per_session", "token_budget_per_session",
        "temperature_cap", "dlp_overrides",
        # Knowledge layer — consumed by the rag_scope OPA rule.
        "knowledge_collections", "knowledge_scope",
    }
    assert required.issubset(payload["metadata"].keys()), (
        f"missing keys: {required - set(payload['metadata'].keys())}"
    )


def test_litellm_metadata_propagates_knowledge_scope():
    """Translator must surface manifest.knowledge.{collections,scope}
    onto the LiteLLM key metadata so OPA's rag_scope rule has the
    declared allowlist at evaluation time."""
    manifest = _mk_manifest(
        knowledge=AgentKnowledge(
            collections=["organization-fdcpa-letters", "organization-account-policies"],
            scope=KnowledgeScope.STRICT,
        ),
    )
    payload = at.build_litellm_key_payload(manifest, manifest_hash="y" * 64, version=1)
    md = payload["metadata"]
    assert md["knowledge_collections"] == ["organization-fdcpa-letters", "organization-account-policies"]
    assert md["knowledge_scope"] == "strict"


def test_litellm_metadata_empty_knowledge_defaults_strict():
    """Manifest with no declared collections still carries a `strict`
    scope marker so downstream OPA defaults to the safe behaviour."""
    manifest = _mk_manifest(knowledge=AgentKnowledge(collections=[]))
    payload = at.build_litellm_key_payload(manifest, manifest_hash="z" * 64, version=1)
    md = payload["metadata"]
    assert md["knowledge_collections"] == []
    assert md["knowledge_scope"] == "strict"
