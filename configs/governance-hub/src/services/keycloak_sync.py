"""Keycloak → central DB identity replication.

Scheduled job that pulls realm, users, and groups from the local Keycloak
via its Admin REST API and upserts them into the central fleet database
(PostgreSQL | MariaDB | MSSQL).

Called from the gov-hub apscheduler at `settings.keycloak_sync_schedule`,
on-demand from `/api/v1/identity/sync`, and once at startup when enabled.

Stale-row pruning: rows whose last_synced_at predates the current sync
cursor are deleted — so Keycloak-side deletes propagate to the central
store without needing a separate tombstone dance.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ..config import settings
from ..db.central_db import run_central_query
from ..db.central_sql import SQL
from .keycloak_client import KeycloakAdminClient

logger = logging.getLogger("governance-hub.keycloak.sync")


@dataclass
class SyncResult:
    ok: bool
    status: str            # running | success | error
    users_synced: int = 0
    groups_synced: int = 0
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "users_synced": self.users_synced,
            "groups_synced": self.groups_synced,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_sync_once(client: KeycloakAdminClient | None = None) -> SyncResult:
    """Run one full identity sync cycle. Safe to call concurrently — the
    database UPSERTs are idempotent; the sync log captures overlap."""
    if not settings.keycloak_sync_enable:
        return SyncResult(ok=False, status="error", error="keycloak_sync_enable=false")
    if not settings.central_db_url:
        return SyncResult(ok=False, status="error", error="central_db_url not configured")

    client = client or _build_client()
    started_at = datetime.now(timezone.utc)

    try:
        realm = await client.get_realm()
        groups_src = await client.list_groups()
        users_src = [u async for u in client.iter_users(page_size=settings.keycloak_sync_page_size)]
    except Exception as e:
        logger.error(f"keycloak_sync fetch failed: {type(e).__name__}: {e}")
        result = SyncResult(ok=False, status="error", error=_short_err(e))
        await _log_sync_run(started_at, datetime.now(timezone.utc), result)
        return result

    # Enrich users with groups + realm roles in parallel-lite (one per user).
    enriched_users: list[dict[str, Any]] = []
    for u in users_src:
        try:
            u_groups = await client.user_groups(u["id"])
            u_roles = await client.user_realm_roles(u["id"])
        except Exception as e:
            # Partial enrichment is better than nothing — continue.
            logger.debug(f"user {u.get('username')} enrichment failed: {e}")
            u_groups, u_roles = [], []
        enriched_users.append({**u, "_groups": u_groups, "_roles": u_roles})

    # Enrich groups with realm roles.
    enriched_groups: list[dict[str, Any]] = []
    for g in groups_src:
        try:
            g_roles = await client.group_realm_roles(g["id"])
        except Exception as e:
            logger.debug(f"group {g.get('path')} enrichment failed: {e}")
            g_roles = []
        enriched_groups.append({**g, "_roles": g_roles})

    cursor = datetime.now(timezone.utc)
    try:
        await run_central_query(
            lambda db: _write_sync(db, realm, enriched_users, enriched_groups, cursor)
        )
    except Exception as e:
        logger.error(f"keycloak_sync write failed: {type(e).__name__}: {e}")
        result = SyncResult(ok=False, status="error", error=_short_err(e))
        await _log_sync_run(started_at, datetime.now(timezone.utc), result)
        return result

    ended_at = datetime.now(timezone.utc)
    result = SyncResult(
        ok=True,
        status="success",
        users_synced=len(enriched_users),
        groups_synced=len(enriched_groups),
        duration_ms=int((ended_at - started_at).total_seconds() * 1000),
    )
    await _log_sync_run(started_at, ended_at, result)
    logger.info(
        f"keycloak_sync ok: users={result.users_synced} groups={result.groups_synced} "
        f"duration_ms={result.duration_ms}"
    )
    return result


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


def _write_sync(
    db,
    realm: dict[str, Any],
    users: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    cursor: datetime,
) -> None:
    """Run all upserts + prune within a single central-DB transaction."""
    iid = settings.instance_id or "unknown"
    realm_name = realm.get("realm") or settings.keycloak_realm

    # Realm.
    db.execute(text(SQL.upsert_identity_realm), {
        "iid": iid,
        "realm": realm_name,
        "display": realm.get("displayName") or realm_name,
        "enabled": bool(realm.get("enabled", True)),
        "realm_json": json.dumps(_strip_realm(realm)),
    })

    # Groups.
    for g in groups:
        db.execute(text(SQL.upsert_identity_group), {
            "iid": iid,
            "realm": realm_name,
            "group_id": g["id"],
            "name": g.get("name") or "",
            "path": g.get("path") or "",
            "parent_id": g.get("parent_group_id"),
            "attributes": json.dumps(g.get("attributes") or {}),
            "roles_csv": _csv([r.get("name", "") for r in (g.get("_roles") or [])]),
        })

    # Users.
    for u in users:
        created_ms = u.get("createdTimestamp")
        created_dt = (
            datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
            if isinstance(created_ms, (int, float)) else None
        )
        db.execute(text(SQL.upsert_identity_user), {
            "iid": iid,
            "realm": realm_name,
            "user_id": u["id"],
            "username": u.get("username") or "",
            "email": u.get("email"),
            "first_name": u.get("firstName"),
            "last_name": u.get("lastName"),
            "enabled": bool(u.get("enabled", True)),
            "email_verified": bool(u.get("emailVerified", False)),
            "groups_csv": _csv([g.get("path", "") for g in (u.get("_groups") or [])]),
            "roles_csv": _csv([r.get("name", "") for r in (u.get("_roles") or [])]),
            "attributes": json.dumps(u.get("attributes") or {}),
            "created_at_kc": created_dt,
        })

    # Prune stale rows — anything not touched by this cycle is gone Keycloak-side.
    db.execute(text(SQL.prune_identity_users), {"iid": iid, "realm": realm_name, "cursor": cursor})
    db.execute(text(SQL.prune_identity_groups), {"iid": iid, "realm": realm_name, "cursor": cursor})

    db.commit()


async def _log_sync_run(
    started_at: datetime,
    ended_at: datetime,
    result: SyncResult,
) -> None:
    if not settings.central_db_url:
        return
    iid = settings.instance_id or "unknown"
    realm_name = settings.keycloak_realm
    duration = int((ended_at - started_at).total_seconds() * 1000)

    def _write(db):
        db.execute(text(SQL.insert_identity_sync_log), {
            "iid": iid,
            "realm": realm_name,
            "started_at": started_at,
            "ended_at": ended_at,
            "status": result.status,
            "users": result.users_synced,
            "groups": result.groups_synced,
            "duration": duration,
            "error": result.error,
        })
        db.commit()

    try:
        await run_central_query(_write)
    except Exception as e:
        logger.warning(f"sync log write failed: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_client() -> KeycloakAdminClient:
    return KeycloakAdminClient(
        base_url=settings.keycloak_url,
        realm=settings.keycloak_realm,
        admin_user=settings.keycloak_admin_user,
        admin_password=settings.keycloak_admin_password or settings.litellm_master_key,
        admin_client_id=settings.keycloak_admin_client_id,
        timeout=settings.keycloak_http_timeout_seconds,
    )


def _csv(items) -> str:
    clean = [i for i in (items or []) if i]
    return ",".join(clean) if clean else ""


def _short_err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:500]


def _strip_realm(realm: dict[str, Any]) -> dict[str, Any]:
    """Keep just the metadata fields worth preserving; drop the blobs we
    already have in dedicated tables (users, clients, roles, groups)."""
    keep = {
        "realm", "displayName", "displayNameHtml", "enabled", "sslRequired",
        "registrationAllowed", "loginWithEmailAllowed", "duplicateEmailsAllowed",
        "rememberMe", "editUsernameAllowed", "bruteForceProtected",
        "accessTokenLifespan", "ssoSessionIdleTimeout", "ssoSessionMaxLifespan",
        "eventsEnabled", "adminEventsEnabled",
    }
    return {k: v for k, v in realm.items() if k in keep}
