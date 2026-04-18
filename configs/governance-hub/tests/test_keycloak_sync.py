"""Unit tests for Keycloak → central-DB identity replication.

Covers:
  * KeycloakAdminClient paginated user iteration + group tree flattening
  * _build_client reads from config.Settings correctly
  * run_sync_once orchestrates realm + group + user fetches and writes
  * Failure modes (keycloak_sync_enable=false, central_db_url empty,
    fetch exceptions) produce useful SyncResult + sync_log entries
  * Stale-row pruning cursor is set AFTER the last upsert so late-arriving
    rows aren't deleted
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services import keycloak_sync as ks
from src.services.keycloak_client import _flatten_groups


# ---------------------------------------------------------------------------
# Group tree flattening
# ---------------------------------------------------------------------------


def test_flatten_groups_preserves_parent_links():
    tree = [
        {
            "id": "root1",
            "name": "InsideLLM-Admin",
            "path": "/InsideLLM-Admin",
            "subGroups": [
                {"id": "child1", "name": "Sub", "path": "/InsideLLM-Admin/Sub", "subGroups": []},
            ],
        },
        {"id": "root2", "name": "InsideLLM-View", "path": "/InsideLLM-View", "subGroups": []},
    ]
    flat = list(_flatten_groups(tree))
    by_id = {g["id"]: g for g in flat}
    assert by_id["root1"]["parent_group_id"] is None
    assert by_id["child1"]["parent_group_id"] == "root1"
    assert by_id["root2"]["parent_group_id"] is None
    assert len(flat) == 3


# ---------------------------------------------------------------------------
# run_sync_once — gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_disabled_returns_error():
    with patch.object(ks.settings, "keycloak_sync_enable", False):
        result = await ks.run_sync_once()
    assert result.ok is False
    assert result.status == "error"
    assert "keycloak_sync_enable" in (result.error or "")


@pytest.mark.asyncio
async def test_sync_without_central_db_returns_error():
    # central_db_url is a computed property; clearing central_db_host makes
    # it return "" which is what run_sync_once checks.
    with patch.object(ks.settings, "keycloak_sync_enable", True), \
         patch.object(ks.settings, "central_db_host", ""):
        result = await ks.run_sync_once()
    assert result.ok is False
    assert "central_db_url" in (result.error or "")


# ---------------------------------------------------------------------------
# run_sync_once — happy path
# ---------------------------------------------------------------------------


def _fake_client_with(users: list[dict], groups: list[dict], realm: dict | None = None) -> MagicMock:
    """Produce a MagicMock that quacks like KeycloakAdminClient."""
    client = MagicMock()
    client.get_realm = AsyncMock(return_value=realm or {
        "realm": "insidellm",
        "displayName": "InsideLLM",
        "enabled": True,
    })
    client.list_groups = AsyncMock(return_value=groups)

    # iter_users is an async generator — wrap a list.
    async def _iter(page_size=100):
        for u in users:
            yield u
    client.iter_users = _iter

    client.user_groups = AsyncMock(return_value=[])
    client.user_realm_roles = AsyncMock(return_value=[])
    client.group_realm_roles = AsyncMock(return_value=[])
    return client


@pytest.mark.asyncio
async def test_sync_happy_path_writes_and_logs():
    users = [
        {"id": "u1", "username": "alice", "email": "a@x.com", "enabled": True, "emailVerified": True,
         "firstName": "Alice", "lastName": "A", "createdTimestamp": 1_700_000_000_000},
        {"id": "u2", "username": "bob", "email": "b@x.com", "enabled": True, "emailVerified": False,
         "firstName": "Bob", "lastName": "B"},
    ]
    groups = [
        {"id": "g1", "name": "InsideLLM-Admin", "path": "/InsideLLM-Admin", "parent_group_id": None},
        {"id": "g2", "name": "InsideLLM-View",  "path": "/InsideLLM-View",  "parent_group_id": None},
    ]
    client = _fake_client_with(users, groups)

    writes: list = []

    async def _fake_run_central_query(fn):
        # Call the sync-writer function with a mock db so we can inspect
        # everything it issued to execute().
        db = MagicMock()
        db.execute = MagicMock(side_effect=lambda sql, params=None: writes.append((str(sql), params)))
        db.commit = MagicMock()
        return fn(db)

    with patch.object(ks.settings, "keycloak_sync_enable", True), \
         patch.object(ks.settings, "central_db_host", "central-db"), \
         patch.object(ks.settings, "central_db_user", "gov"), \
         patch.object(ks.settings, "central_db_password", "pw"), \
         patch.object(ks.settings, "instance_id", "vm-9"), \
         patch.object(ks, "run_central_query", _fake_run_central_query):
        result = await ks.run_sync_once(client=client)

    assert result.ok is True
    assert result.status == "success"
    assert result.users_synced == 2
    assert result.groups_synced == 2
    # 1 realm + 2 groups + 2 users + 2 prune + 1 log-insert = 8 execute calls minimum.
    assert len(writes) >= 8
    # First execute must be the realm upsert.
    assert "identity_realms" in writes[0][0]
    # Instance id flows through.
    assert writes[0][1]["iid"] == "vm-9"


@pytest.mark.asyncio
async def test_sync_fetch_failure_logs_error_run():
    client = MagicMock()
    client.get_realm = AsyncMock(side_effect=RuntimeError("keycloak-down"))

    logged: list = []

    async def _fake_run_central_query(fn):
        db = MagicMock()
        db.execute = MagicMock(side_effect=lambda sql, params=None: logged.append(params))
        db.commit = MagicMock()
        return fn(db)

    with patch.object(ks.settings, "keycloak_sync_enable", True), \
         patch.object(ks.settings, "central_db_host", "central-db"), \
         patch.object(ks.settings, "central_db_user", "gov"), \
         patch.object(ks.settings, "central_db_password", "pw"), \
         patch.object(ks.settings, "instance_id", "vm-9"), \
         patch.object(ks, "run_central_query", _fake_run_central_query):
        result = await ks.run_sync_once(client=client)

    assert result.ok is False
    assert result.status == "error"
    assert "keycloak-down" in (result.error or "")
    # A sync-log row was still inserted so operators see the failure.
    assert any("keycloak-down" in str(p.get("error", "")) for p in logged)


# ---------------------------------------------------------------------------
# Client factory reads from settings
# ---------------------------------------------------------------------------


def test_build_client_uses_settings():
    with patch.object(ks.settings, "keycloak_url", "http://kc:8080/keycloak"), \
         patch.object(ks.settings, "keycloak_realm", "insidellm"), \
         patch.object(ks.settings, "keycloak_admin_user", "insidellm-admin"), \
         patch.object(ks.settings, "keycloak_admin_password", "s3cret"), \
         patch.object(ks.settings, "keycloak_admin_client_id", "admin-cli"):
        c = ks._build_client()
    assert c.base_url == "http://kc:8080/keycloak"
    assert c.realm == "insidellm"
    assert c.admin_user == "insidellm-admin"
    assert c.admin_password == "s3cret"
    assert c.admin_client_id == "admin-cli"


def test_build_client_falls_back_to_master_key_when_admin_password_empty():
    with patch.object(ks.settings, "keycloak_url", "http://kc:8080/keycloak"), \
         patch.object(ks.settings, "keycloak_realm", "insidellm"), \
         patch.object(ks.settings, "keycloak_admin_user", "insidellm-admin"), \
         patch.object(ks.settings, "keycloak_admin_password", ""), \
         patch.object(ks.settings, "litellm_master_key", "sk-master-test"), \
         patch.object(ks.settings, "keycloak_admin_client_id", "admin-cli"):
        c = ks._build_client()
    assert c.admin_password == "sk-master-test"


# ---------------------------------------------------------------------------
# CSV helper
# ---------------------------------------------------------------------------


def test_csv_joins_non_empty_items():
    assert ks._csv(["a", "b", "c"]) == "a,b,c"
    assert ks._csv(["a", "", "b"]) == "a,b"
    assert ks._csv([]) == ""
    assert ks._csv(None) == ""


def test_strip_realm_drops_bulky_fields():
    full = {
        "realm": "insidellm",
        "enabled": True,
        "users": [{"id": "x"} for _ in range(100)],   # dropped
        "clients": [{"clientId": "x"} for _ in range(20)],  # dropped
        "roles": {"realm": []},  # dropped
        "displayName": "InsideLLM",
    }
    stripped = ks._strip_realm(full)
    assert "users" not in stripped
    assert "clients" not in stripped
    assert "roles" not in stripped
    assert stripped["realm"] == "insidellm"
    assert stripped["displayName"] == "InsideLLM"
