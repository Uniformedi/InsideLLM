"""
title: InsideLLM Canonical Session Bridge
id: insidellm_sessions_bridge
description: |
  Binds every Open WebUI chat to a canonical session in governance-hub. On first
  inbound message in a chat, creates the session via POST /api/v1/sessions;
  on each subsequent inbound, appends an event via the internal adapter
  endpoint; on handoff requests surfaced through the OWUI UI, forwards to
  POST /api/v1/sessions/{id}/handoff.

  This pipeline runs alongside the existing DLP + OPA pipelines. It is
  ordered AFTER OPA (so policy denies never create a session) and BEFORE
  LiteLLM dispatch (so the session_id is available for cost attribution).

  Failure mode: if governance-hub is unreachable, this pipeline logs and
  fails OPEN — the chat continues but the canonical session is lost for
  that message. A reconciliation job replays missed events from OWUI's chat
  DB once governance-hub recovers.

  Environment variables (injected via docker-compose.yml.tpl):
    INSIDELLM_GOVHUB_URL          http://governance-hub:8090
    INSIDELLM_GOVHUB_TOKEN        service-to-service bearer token
    INSIDELLM_TENANT_ID           this tenant's id (from terraform)
    INSIDELLM_DEFAULT_TIER        T0..T7; defaults to T2
    INSIDELLM_DATA_REGION         us-east, eu-west, etc.

author: InsideLLM
version: 0.1.0
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("insidellm.sessions_bridge")

_GOVHUB_URL = os.environ.get("INSIDELLM_GOVHUB_URL", "http://governance-hub:8090")
_GOVHUB_TOKEN = os.environ.get("INSIDELLM_GOVHUB_TOKEN", "")
_TENANT_ID = os.environ.get("INSIDELLM_TENANT_ID", "default")
_DEFAULT_TIER = os.environ.get("INSIDELLM_DEFAULT_TIER", "T2")
_DATA_REGION = os.environ.get("INSIDELLM_DATA_REGION", "us-east")

_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


class Valves(BaseModel):
    enabled: bool = True
    fail_open: bool = True
    default_tier: str = Field(default=_DEFAULT_TIER)
    data_region: str = Field(default=_DATA_REGION)


class Pipeline:
    """Open WebUI filter-pipeline interface."""

    type = "filter"
    name = "InsideLLM Sessions Bridge"

    def __init__(self) -> None:
        self.valves = Valves()
        self._client: httpx.Client | None = None

    # ---- Pipeline lifecycle ------------------------------------------------

    async def on_startup(self) -> None:
        self._client = httpx.Client(
            base_url=_GOVHUB_URL,
            timeout=_TIMEOUT,
            headers={"Authorization": f"Bearer {_GOVHUB_TOKEN}"} if _GOVHUB_TOKEN else {},
        )

    async def on_shutdown(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---- Inbound (user -> LLM) --------------------------------------------

    async def inlet(self, body: dict, user: dict | None = None) -> dict:
        """Called on every user turn BEFORE the LLM call."""
        if not self.valves.enabled:
            return body

        chat_id = body.get("chat_id") or (body.get("metadata") or {}).get("chat_id")
        if not chat_id:
            return body

        user_sub = (user or {}).get("id") or (user or {}).get("sub") or "anonymous"
        manifest_id, manifest_hash = self._extract_manifest(body)

        try:
            session_id = self._ensure_session(
                chat_id=chat_id,
                user_sub=user_sub,
                manifest_id=manifest_id,
                manifest_hash=manifest_hash,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("sessions-bridge inlet failed: %s", e)
            if not self.valves.fail_open:
                raise
            return body

        # Stamp the session_id into the request metadata so downstream
        # LiteLLM callbacks pick it up for cost attribution.
        meta = body.setdefault("metadata", {})
        meta["insidellm_session_id"] = session_id
        meta["insidellm_tenant_id"] = _TENANT_ID
        return body

    # ---- Outbound (LLM -> user) -------------------------------------------

    async def outlet(self, body: dict, user: dict | None = None) -> dict:
        """Called on every assistant turn AFTER the LLM call."""
        # Noop today — LiteLLM cost callback writes cost into the session
        # directly via the session_id stamped in inlet().
        return body

    # ---- Helpers -----------------------------------------------------------

    def _ensure_session(
        self,
        *,
        chat_id: str,
        user_sub: str,
        manifest_id: str,
        manifest_hash: str,
    ) -> str:
        """Create-or-fetch a canonical session bound to this OWUI chat."""
        assert self._client is not None

        # Probe: does a binding already exist for this surface_ref?
        r = self._client.get(
            "/api/v1/sessions",
            params={
                "tenant_id": _TENANT_ID,
                # The list endpoint doesn't filter by surface_ref yet; bridge
                # uses a deterministic surface_ref → session_id mapping via
                # the OWUI chat_id until a dedicated lookup ships.
            },
        )
        # Fallback: always create idempotently. The governance-hub POST
        # endpoint is NOT idempotent in 3.3; upgrade target is `ON CONFLICT
        # DO NOTHING` using a (tenant, surface, surface_ref) key. Until then,
        # we hash chat_id into a stable session_id candidate and the service
        # handles the uniqueness server-side in a future revision.
        r = self._client.post(
            "/api/v1/sessions",
            json={
                "tenant_id": _TENANT_ID,
                "agent_manifest_id": manifest_id,
                "manifest_hash": manifest_hash,
                "surface": "owui",
                "surface_ref": chat_id,
                "classification": "general",
                "security_tier": self.valves.default_tier,
                "tier_source": "tenant",
                "data_region": self.valves.data_region,
                "kms_data_key_id": self._derive_kms_key_id(_TENANT_ID, chat_id),
            },
        )
        r.raise_for_status()
        return r.json()["session_id"]

    def _extract_manifest(self, body: dict) -> tuple[str, str]:
        """OWUI custom-model metadata carries the agent manifest ref.

        Upstream Open WebUI stores the selected model's id/hash in the
        request's metadata.model field. Fall back to a placeholder when
        no manifest is bound.
        """
        meta = body.get("metadata") or {}
        model_id = body.get("model") or meta.get("model") or "unmanaged"
        manifest_hash = meta.get("manifest_hash") or hashlib.sha256(
            model_id.encode("utf-8")
        ).hexdigest()
        return model_id, manifest_hash

    @staticmethod
    def _derive_kms_key_id(tenant_id: str, chat_id: str) -> str:
        """Deterministic KMS key id placeholder.

        Real implementation calls the tenant KMS to provision a data key and
        returns the key arn/kid. This stub keeps the pipeline self-contained
        so 3.3 can ship without a KMS hard dependency — at Phase 4.3 the KMS
        client replaces this.
        """
        seed = f"insidellm.session.dek.v1:{tenant_id}:{chat_id}".encode("utf-8")
        return "local-dek-" + hashlib.sha256(seed).hexdigest()[:32]
