"""Unit tests for the OWUI OPA policy pipeline RAG-scope helpers.

We import the pipeline file directly (it lives in configs/open-webui/,
outside the gov-hub package) and exercise the pure helper methods that
parse model ids and normalize request bodies. Network-backed paths
(_fetch_agent_scope) are covered by mocking requests.get.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Load the pipeline module from source without needing Open WebUI installed.
# parents: [0]=tests, [1]=governance-hub, [2]=configs, [3]=repo root.
_PIPELINE_PATH = (
    Path(__file__).resolve().parents[2]
    / "open-webui"
    / "opa-policy-pipeline.py"
)


@pytest.fixture(scope="module")
def pipeline_module():
    spec = importlib.util.spec_from_file_location(
        "opa_policy_pipeline", str(_PIPELINE_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def pipeline(pipeline_module):
    return pipeline_module.Pipeline()


# -----------------------------------------------------------------------------
# _parse_agent_id_from_model
# -----------------------------------------------------------------------------


def test_parse_agent_id_from_translator_owned_model(pipeline):
    t, a = pipeline._parse_agent_id_from_model(
        "insidellm-agent-example-tenant--dispute-handler"
    )
    assert t == "example-tenant"
    assert a == "dispute-handler"


def test_parse_returns_none_for_plain_model(pipeline):
    assert pipeline._parse_agent_id_from_model("claude-sonnet") is None
    assert pipeline._parse_agent_id_from_model("") is None
    assert pipeline._parse_agent_id_from_model("insidellm-skill-foo") is None


def test_parse_returns_none_for_malformed_agent_model(pipeline):
    # Missing the `--` separator.
    assert pipeline._parse_agent_id_from_model("insidellm-agent-no-separator") is None


# -----------------------------------------------------------------------------
# _extract_requested_collections
# -----------------------------------------------------------------------------


def test_extract_requested_collections_empty(pipeline):
    assert pipeline._extract_requested_collections({}) == []


def test_extract_requested_collections_from_collection_ids(pipeline):
    body = {"collection_ids": ["coll_a", "coll_b"]}
    assert pipeline._extract_requested_collections(body) == ["coll_a", "coll_b"]


def test_extract_requested_collections_from_files(pipeline):
    body = {
        "files": [
            {"collection_name": "coll_a", "name": "policy.pdf"},
            {"collection_id": "coll_b"},
            {},                           # no collection marker — skip
            "not-a-dict",                 # tolerated, skipped
        ],
    }
    assert pipeline._extract_requested_collections(body) == ["coll_a", "coll_b"]


def test_extract_requested_collections_from_metadata(pipeline):
    body = {"metadata": {"collection_id": "legacy-coll"}}
    assert pipeline._extract_requested_collections(body) == ["legacy-coll"]


def test_extract_requested_collections_dedupes_across_sources(pipeline):
    body = {
        "collection_ids": ["coll_a"],
        "files": [{"collection_name": "coll_a"}, {"collection_name": "coll_b"}],
        "metadata": {"collection_id": "coll_b"},
    }
    assert pipeline._extract_requested_collections(body) == ["coll_a", "coll_b"]


# -----------------------------------------------------------------------------
# _fetch_agent_scope (mocked HTTP)
# -----------------------------------------------------------------------------


def test_fetch_agent_scope_returns_manifest_collections(pipeline_module):
    p = pipeline_module.Pipeline()

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "manifest": {
            "knowledge": {
                "collections": ["c1", "c2"],
                "scope": "loose",
            }
        }
    }
    fake_response.raise_for_status = lambda: None

    with patch.object(pipeline_module, "requests") as mreq:
        mreq.get.return_value = fake_response
        scope = p._fetch_agent_scope("t", "a")

    assert scope == {"collections": ["c1", "c2"], "scope": "loose"}


def test_fetch_agent_scope_is_cached(pipeline_module):
    p = pipeline_module.Pipeline()
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "manifest": {"knowledge": {"collections": ["c1"], "scope": "strict"}}
    }
    fake_response.raise_for_status = lambda: None

    with patch.object(pipeline_module, "requests") as mreq:
        mreq.get.return_value = fake_response
        p._fetch_agent_scope("t", "a")
        p._fetch_agent_scope("t", "a")
        p._fetch_agent_scope("t", "a")
        # One fetch → two cache hits. If we re-fetch, the cache is broken.
        assert mreq.get.call_count == 1


def test_fetch_agent_scope_fails_soft(pipeline_module):
    """gov-hub unreachable → return empty scope; OPA rule treats empty
    declared set as 'no scope asserted'."""
    p = pipeline_module.Pipeline()
    with patch.object(pipeline_module, "requests") as mreq:
        mreq.get.side_effect = RuntimeError("gov-hub-down")
        scope = p._fetch_agent_scope("t", "a")
    assert scope == {}


# -----------------------------------------------------------------------------
# _build_input integration — declarative agent path
# -----------------------------------------------------------------------------


def test_build_input_carries_rag_fields_for_agent_model(pipeline_module):
    p = pipeline_module.Pipeline()

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "manifest": {
            "knowledge": {
                "collections": ["organization-fdcpa-letters", "organization-account-policies"],
                "scope": "strict",
            }
        }
    }
    fake_response.raise_for_status = lambda: None

    body = {
        "model": "insidellm-agent-example-tenant--dispute-handler",
        "messages": [{"role": "user", "content": "look up account"}],
        "collection_ids": ["organization-fdcpa-letters"],
    }
    user = {"id": "u1", "name": "alice", "role": "user"}

    with patch.object(pipeline_module, "requests") as mreq:
        mreq.get.return_value = fake_response
        opa_in = p._build_input(body, user)

    assert opa_in["agent_id"] == "dispute-handler"
    assert opa_in["tenant_id"] == "example-tenant"
    assert opa_in["agent_knowledge_collections"] == ["organization-fdcpa-letters", "organization-account-policies"]
    assert opa_in["knowledge_scope"] == "strict"
    assert opa_in["requested_collections"] == ["organization-fdcpa-letters"]


def test_build_input_for_plain_model_has_empty_agent_identity(pipeline_module):
    """Non-agent requests (plain Claude model) carry no agent identity
    and no knowledge scope — the RAG rule sees empty sets and does nothing."""
    p = pipeline_module.Pipeline()
    body = {
        "model": "claude-sonnet",
        "messages": [{"role": "user", "content": "hi"}],
    }
    user = {"id": "u1", "name": "alice", "role": "user"}

    opa_in = p._build_input(body, user)

    assert opa_in["agent_id"] == ""
    assert opa_in["tenant_id"] == ""
    assert opa_in["agent_knowledge_collections"] == []
    assert opa_in["requested_collections"] == []
    # Default scope is still populated so the rule's defaulting logic fires.
    assert opa_in["knowledge_scope"] == "strict"
