"""Thin async client for the Keycloak Admin REST API.

Handles:
  * Admin access-token acquisition via password grant on the `admin-cli`
    client (Keycloak ships this client in every master realm).
  * Realm metadata + users + groups with pagination.
  * Per-user group membership lookup + per-user/group realm role lookup.

Kept intentionally narrow — only the endpoints keycloak_sync needs.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("governance-hub.keycloak.client")

# Keycloak default page size; respected across /users and /groups.
_PAGE_SIZE = 100
_TOKEN_REFRESH_SAFETY_SECONDS = 30.0


@dataclass
class _Token:
    access_token: str
    expires_at: float  # monotonic time

    def is_stale(self) -> bool:
        return time.monotonic() + _TOKEN_REFRESH_SAFETY_SECONDS >= self.expires_at


class KeycloakAdminClient:
    """Password-grant admin client against Keycloak's master realm.

    Using the master realm + admin-cli means we don't need a dedicated
    OIDC service account just for sync — the break-glass admin we
    already seed on every VM is sufficient. A hardening pass can swap
    this for a scoped client-credentials grant later.
    """

    def __init__(
        self,
        *,
        base_url: str,
        realm: str,
        admin_user: str,
        admin_password: str,
        admin_client_id: str = "admin-cli",
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.admin_client_id = admin_client_id
        self.timeout = timeout
        self._token: _Token | None = None

    # ---- Auth --------------------------------------------------------------

    async def _get_token(self) -> str:
        if self._token is not None and not self._token.is_stale():
            return self._token.access_token
        url = f"{self.base_url}/realms/master/protocol/openid-connect/token"
        data = {
            "grant_type": "password",
            "client_id": self.admin_client_id,
            "username": self.admin_user,
            "password": self.admin_password,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            body = resp.json()
        access = body["access_token"]
        ttl = float(body.get("expires_in", 60))
        self._token = _Token(access_token=access, expires_at=time.monotonic() + ttl)
        return access

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._get_token()}",
            "Accept": "application/json",
        }

    # ---- Realm -------------------------------------------------------------

    async def get_realm(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/admin/realms/{self.realm}",
                headers=await self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    # ---- Users -------------------------------------------------------------

    async def iter_users(self, page_size: int = _PAGE_SIZE):
        """Yield every user in the realm, paginated."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            first = 0
            while True:
                resp = await client.get(
                    f"{self.base_url}/admin/realms/{self.realm}/users",
                    params={"first": first, "max": page_size, "briefRepresentation": "false"},
                    headers=await self._headers(),
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    return
                for user in batch:
                    yield user
                if len(batch) < page_size:
                    return
                first += page_size

    async def user_groups(self, user_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}/groups",
                headers=await self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def user_realm_roles(self, user_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm",
                headers=await self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    # ---- Groups ------------------------------------------------------------

    async def list_groups(self) -> list[dict[str, Any]]:
        """Return the full group tree, flattened."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/admin/realms/{self.realm}/groups",
                params={"briefRepresentation": "false"},
                headers=await self._headers(),
            )
            resp.raise_for_status()
            groups = resp.json()
        return list(_flatten_groups(groups))

    async def group_realm_roles(self, group_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/admin/realms/{self.realm}/groups/{group_id}/role-mappings/realm",
                headers=await self._headers(),
            )
            resp.raise_for_status()
            return resp.json()


def _flatten_groups(nodes, parent_id: str | None = None):
    for g in nodes:
        row = dict(g)
        row["parent_group_id"] = parent_id
        yield row
        for child in g.get("subGroups", []) or []:
            yield from _flatten_groups([child], parent_id=g["id"])
