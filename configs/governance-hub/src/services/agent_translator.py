"""Manifest → Runtime Translation Layer (P1.2).

Given a published AgentManifest, provision the runtime artifacts that
actually make the agent invokable:

  1. **LiteLLM virtual key** — enforces budget, rpm, model allowlist.
     The key's `metadata` carries the agent identity + guardrail profile
     so the humility / DLP callback chain can compose the correct OPA
     input without a second round-trip to the Governance Hub.
  2. **Open WebUI custom model** — appears in the user's picker when
     their group matches the manifest's visibility scope. System prompt,
     temperature cap, conversation starters, and knowledge collections
     all flow from the manifest.

Design principles
-----------------
* **Fail-soft**: partial success (e.g. LiteLLM OK, OWUI down) is recorded.
  Audit trail + `/sync` endpoint let operators retry without losing state.
* **Dry-run**: every payload builder is a pure function; `build_*_payload`
  can be called from tests or previewed from the Admin UI with no side
  effects. `provision(dry_run=True)` returns the planned calls without
  issuing them.
* **Deterministic resource names**: key alias and OWUI model id are
  derived deterministically from `(tenant_id, agent_id)` so re-provisioning
  always hits the same records — no orphans, no drift.
* **Metadata is the contract**: the LiteLLM key carries everything the
  downstream OPA guardrail needs — reading it means the guardrail chain
  does not have to depend on Governance Hub being reachable.

Exports
-------
* `AgentTranslator` — orchestrator bound to an AsyncSession.
* `ProvisionResult` — structured outcome for router responses + tests.
* `build_litellm_key_payload`, `build_owui_model_payload` — pure builders.
* `litellm_key_alias_for`, `owui_model_id_for` — name helpers.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import settings
from ..db.models import Agent
from ..schemas.agents import AgentManifest

logger = logging.getLogger("governance-hub.agents.translator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# OWUI model id prefix — distinguishes translator-owned models from ones
# operators create by hand or from the skill-sync service.
OWUI_MODEL_PREFIX = "insidellm-agent-"

# LiteLLM key alias prefix — searchable in the LiteLLM UI / spend logs.
LITELLM_KEY_ALIAS_PREFIX = "agent-"

# Models that map to LiteLLM's configured model names. The manifest
# references these by id; LiteLLM resolves them to provider endpoints.
_DEFAULT_MODEL_FALLBACK = "claude-sonnet"

# HTTP timeouts — small because users are waiting on publish.
_HTTP_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ProvisionResult:
    """Structured outcome of a provision / reprovision / deprovision call."""
    ok: bool
    state: str  # one of: provisioned | partial | failed | deprovisioned | skipped
    litellm_key_alias: str | None = None
    litellm_key_last4: str | None = None
    owui_model_id: str | None = None
    litellm_error: str | None = None
    owui_error: str | None = None
    planned_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def error_summary(self) -> str | None:
        parts: list[str] = []
        if self.litellm_error:
            parts.append(f"litellm: {self.litellm_error}")
        if self.owui_error:
            parts.append(f"owui: {self.owui_error}")
        return "; ".join(parts) if parts else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "state": self.state,
            "litellm_key_alias": self.litellm_key_alias,
            "litellm_key_last4": self.litellm_key_last4,
            "owui_model_id": self.owui_model_id,
            "error": self.error_summary,
            "planned_calls": self.planned_calls,
        }


# ---------------------------------------------------------------------------
# Name helpers (pure)
# ---------------------------------------------------------------------------


def litellm_key_alias_for(tenant_id: str, agent_id: str) -> str:
    """Stable alias used for update/delete operations on the virtual key."""
    return f"{LITELLM_KEY_ALIAS_PREFIX}{tenant_id}--{agent_id}"


def owui_model_id_for(tenant_id: str, agent_id: str) -> str:
    """Stable model id for the OWUI custom-model entry."""
    return f"{OWUI_MODEL_PREFIX}{tenant_id}--{agent_id}"


def _last4(key: str) -> str:
    """Return the last 4 chars of an `sk-...` key for audit display."""
    return key[-4:] if len(key) >= 4 else ""


# ---------------------------------------------------------------------------
# Payload builders (pure — no I/O)
# ---------------------------------------------------------------------------


def build_litellm_key_payload(
    manifest: AgentManifest,
    *,
    manifest_hash: str,
    version: int,
) -> dict[str, Any]:
    """Translate manifest → LiteLLM `/key/generate` payload.

    The metadata dict is the contract between this translator and the
    downstream humility / OPA guardrail callback. Fields MUST match what
    `configs/litellm/callbacks/humility_guardrail.py::_build_opa_input`
    expects to read via `/key/info`.
    """
    g = manifest.guardrails
    k = manifest.knowledge
    # Pydantic with use_enum_values=True returns plain strings already.
    allowed_models = list(g.allowed_models) or [_DEFAULT_MODEL_FALLBACK]

    payload: dict[str, Any] = {
        "key_alias": litellm_key_alias_for(manifest.tenant_id, manifest.agent_id),
        "models": allowed_models,
        "rpm_limit": g.rpm_limit,
        "metadata": {
            "source": "insidellm.agent_translator",
            "tenant_id": manifest.tenant_id,
            "agent_id": manifest.agent_id,
            "agent_version": version,
            "manifest_hash": manifest_hash,
            "guardrail_profile": g.profile,
            "visibility_scope": manifest.visibility.scope if manifest.visibility else "private",
            "pii_handling": g.pii_handling,
            "max_actions_per_session": g.max_actions_per_session,
            "token_budget_per_session": g.token_budget_per_session,
            "temperature_cap": g.temperature_cap,
            "dlp_overrides": {
                "allow_pii": g.dlp_overrides.allow_pii,
                "allow_phi": g.dlp_overrides.allow_phi,
                "allow_financials": g.dlp_overrides.allow_financials,
                "allow_credentials": g.dlp_overrides.allow_credentials,
            },
            # Knowledge layer — the OPA rag_scope rule reads these to verify
            # that retrieval targets live inside the manifest's declared set.
            "knowledge_collections": list(k.collections),
            "knowledge_scope": k.scope,
            "team": manifest.team,
        },
    }

    # Only include daily budget when explicitly set — LiteLLM treats 0 as
    # "no budget", but the operator may want a daily cap without clearing it.
    if g.daily_usd_budget is not None and g.daily_usd_budget > 0:
        payload["max_budget"] = float(g.daily_usd_budget)
        payload["budget_duration"] = "1d"

    return payload


def _tag_list(manifest: AgentManifest) -> list[dict[str, str]]:
    tags = [
        manifest.guardrails.profile,
        f"tenant:{manifest.tenant_id}",
        f"visibility:{manifest.visibility.scope if manifest.visibility else 'private'}",
    ]
    if manifest.team:
        tags.append(f"team:{manifest.team}")
    return [{"name": t} for t in tags if t]


def build_owui_model_payload(manifest: AgentManifest) -> dict[str, Any]:
    """Translate manifest → OWUI `/api/v1/models/create` payload."""
    allowed = list(manifest.guardrails.allowed_models) or [_DEFAULT_MODEL_FALLBACK]
    base_model = allowed[0]

    meta: dict[str, Any] = {
        "description": manifest.display.description,
        "tags": _tag_list(manifest),
    }
    if manifest.display.conversation_starters:
        # OWUI accepts a `suggestion_prompts` list; starters fit cleanly.
        meta["suggestion_prompts"] = [
            {"content": s} for s in manifest.display.conversation_starters
        ]
    # Knowledge collections — OWUI stores a list of collection ids under
    # meta.knowledge. The downstream RAG pipeline is P1.4; today we wire
    # the bare list so the UI surfaces it and P1.4 can layer enforcement.
    if manifest.knowledge.collections:
        meta["knowledge"] = [{"id": c} for c in manifest.knowledge.collections]

    params: dict[str, Any] = {
        "system": manifest.instructions,
        # Temperature cap — default 0.7 but pinned at the manifest's cap
        # so operators can't prompt their way above the ceiling.
        "temperature": min(0.7, float(manifest.guardrails.temperature_cap)),
    }

    access_control = _build_access_control(manifest)

    return {
        "id": owui_model_id_for(manifest.tenant_id, manifest.agent_id),
        "name": manifest.display.name,
        "base_model_id": base_model,
        "meta": meta,
        "params": params,
        "access_control": access_control,
        "is_active": True,
    }


def _build_access_control(manifest: AgentManifest) -> dict[str, Any] | None:
    """Map visibility scope → OWUI access_control structure.

    OWUI treats `access_control: null` as fully public. Any non-null
    access_control restricts to the listed user_ids + group_ids.
    """
    vis = manifest.visibility
    if vis is None:
        return None

    scope = vis.scope

    # Public for the tenant → rely on OWUI default (null). Org/fleet users
    # need to be in a matching OWUI group; we send the group names and let
    # OWUI match them against its own group table.
    if scope in ("org", "fleet"):
        return None

    if scope == "team" and manifest.team:
        return {
            "read": {"group_ids": [manifest.team], "user_ids": []},
            "write": {"group_ids": [], "user_ids": []},
        }

    # Private — only the author (manifest.created_by) sees it.
    if scope == "private" and manifest.created_by:
        return {
            "read": {"group_ids": [], "user_ids": [manifest.created_by]},
            "write": {"group_ids": [], "user_ids": []},
        }

    # Fallback: explicit available_to list.
    if vis.available_to:
        return {
            "read": {"group_ids": list(vis.available_to), "user_ids": []},
            "write": {"group_ids": [], "user_ids": []},
        }

    return None


# ---------------------------------------------------------------------------
# HTTP clients (thin wrappers — easy to mock)
# ---------------------------------------------------------------------------


class _LiteLLMClient:
    """Admin-key-scoped LiteLLM HTTP client.

    The translator uses the platform's LITELLM_MASTER_KEY because creating
    virtual keys is an admin-only operation.
    """

    def __init__(self, base_url: str, admin_key: str, timeout: float = _HTTP_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.admin_key}",
            "Content-Type": "application/json",
        }

    async def upsert_key(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create the key if absent, update it in place if the alias exists.

        Returns the parsed JSON response from LiteLLM. Raises on transport
        or HTTP error.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Try to look up the existing key by alias first. LiteLLM's
            # `/key/info` endpoint returns 404 for an unknown alias.
            existing = await client.get(
                f"{self.base_url}/key/info",
                params={"key_alias": payload["key_alias"]},
                headers=self._headers(),
            )
            if existing.status_code == 200:
                # Update in place (LiteLLM requires the token or alias in
                # the update payload; alias suffices).
                update_body = {**payload}
                resp = await client.post(
                    f"{self.base_url}/key/update",
                    headers=self._headers(),
                    json=update_body,
                )
                resp.raise_for_status()
                return resp.json()
            # Create new.
            resp = await client.post(
                f"{self.base_url}/key/generate",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def delete_key_by_alias(self, alias: str) -> bool:
        """Delete a virtual key by alias. Returns True on success, False if
        the key didn't exist (404 is treated as already-deleted)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/key/delete",
                headers=self._headers(),
                json={"key_aliases": [alias]},
            )
            if resp.status_code in (200, 204):
                return True
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            return True


class _OWUIClient:
    """Open WebUI admin-API client — mirrors skill_sync_service patterns."""

    def __init__(self, base_url: str, api_key: str, timeout: float = _HTTP_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def upsert_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Update first — OWUI returns 401/404 when the model isn't there.
            resp = await client.post(
                f"{self.base_url}/api/v1/models/model/update",
                params={"id": payload["id"]},
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code in (401, 404):
                resp = await client.post(
                    f"{self.base_url}/api/v1/models/create",
                    headers=self._headers(),
                    json=payload,
                )
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def delete_model(self, model_id: str) -> bool:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/models/model/delete",
                params={"id": model_id},
                headers=self._headers(),
            )
            if resp.status_code in (200, 204):
                return True
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _fp(payload: dict[str, Any]) -> str:
    """Hash a payload for audit logging without exposing secrets."""
    import json as _json
    blob = _json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


class AgentTranslator:
    """Bind-once orchestrator; call provision/deprovision per agent."""

    def __init__(
        self,
        *,
        litellm_client: _LiteLLMClient | None = None,
        owui_client: _OWUIClient | None = None,
    ):
        self._litellm = litellm_client or _build_default_litellm_client()
        self._owui = owui_client or _build_default_owui_client()

    # ---- Provision --------------------------------------------------------

    async def provision(
        self,
        agent: Agent,
        *,
        dry_run: bool = False,
    ) -> ProvisionResult:
        """Create/update runtime artifacts for a published agent row.

        Idempotent: calling twice on the same manifest is safe.
        Returns a ProvisionResult; the caller is responsible for persisting
        the resulting binding state on the Agent row (see `apply_result`).
        """
        manifest = AgentManifest.model_validate(agent.manifest_json)
        key_payload = build_litellm_key_payload(
            manifest,
            manifest_hash=agent.manifest_hash or "",
            version=agent.version or 1,
        )
        owui_payload = build_owui_model_payload(manifest)

        planned = [
            {"target": "litellm", "op": "upsert_key", "fingerprint": _fp(key_payload)},
            {"target": "owui", "op": "upsert_model", "fingerprint": _fp(owui_payload)},
        ]

        if dry_run:
            return ProvisionResult(
                ok=True,
                state="skipped",
                litellm_key_alias=key_payload["key_alias"],
                owui_model_id=owui_payload["id"],
                planned_calls=planned,
            )

        result = ProvisionResult(
            ok=False,
            state="failed",
            litellm_key_alias=key_payload["key_alias"],
            owui_model_id=owui_payload["id"],
            planned_calls=planned,
        )

        # --- LiteLLM ------------------------------------------------------
        litellm_ok = False
        try:
            llm_resp = await self._litellm.upsert_key(key_payload)
            token = llm_resp.get("key") or llm_resp.get("token") or ""
            if token:
                result.litellm_key_last4 = _last4(token)
            litellm_ok = True
            logger.info(
                f"litellm_upsert_key ok: agent={manifest.tenant_id}/{manifest.agent_id} "
                f"alias={key_payload['key_alias']} last4={result.litellm_key_last4 or '-'}"
            )
        except Exception as e:
            result.litellm_error = f"{type(e).__name__}: {e}"[:500]
            logger.warning(
                f"litellm_upsert_key failed: agent={manifest.tenant_id}/{manifest.agent_id} "
                f"err={result.litellm_error}"
            )

        # --- OWUI ---------------------------------------------------------
        owui_ok = False
        try:
            await self._owui.upsert_model(owui_payload)
            owui_ok = True
            logger.info(
                f"owui_upsert_model ok: agent={manifest.tenant_id}/{manifest.agent_id} "
                f"model_id={owui_payload['id']}"
            )
        except Exception as e:
            result.owui_error = f"{type(e).__name__}: {e}"[:500]
            logger.warning(
                f"owui_upsert_model failed: agent={manifest.tenant_id}/{manifest.agent_id} "
                f"err={result.owui_error}"
            )

        if litellm_ok and owui_ok:
            result.ok = True
            result.state = "provisioned"
        elif litellm_ok or owui_ok:
            result.ok = False
            result.state = "partial"
        else:
            result.ok = False
            result.state = "failed"
        return result

    # ---- Deprovision ------------------------------------------------------

    async def deprovision(
        self,
        agent: Agent,
        *,
        dry_run: bool = False,
    ) -> ProvisionResult:
        """Remove runtime artifacts. Safe if they don't exist (treated as
        already-deprovisioned)."""
        # Resolve names from persisted binding if available, else derive.
        alias = agent.litellm_key_alias or litellm_key_alias_for(
            agent.tenant_id, agent.agent_id
        )
        model_id = agent.owui_model_id or owui_model_id_for(
            agent.tenant_id, agent.agent_id
        )
        planned = [
            {"target": "litellm", "op": "delete_key", "alias": alias},
            {"target": "owui", "op": "delete_model", "id": model_id},
        ]

        if dry_run:
            return ProvisionResult(
                ok=True,
                state="skipped",
                litellm_key_alias=alias,
                owui_model_id=model_id,
                planned_calls=planned,
            )

        result = ProvisionResult(
            ok=False,
            state="failed",
            litellm_key_alias=alias,
            owui_model_id=model_id,
            planned_calls=planned,
        )
        litellm_ok = False
        try:
            await self._litellm.delete_key_by_alias(alias)
            litellm_ok = True
        except Exception as e:
            result.litellm_error = f"{type(e).__name__}: {e}"[:500]
            logger.warning(f"litellm_delete_key failed: alias={alias} err={result.litellm_error}")

        owui_ok = False
        try:
            await self._owui.delete_model(model_id)
            owui_ok = True
        except Exception as e:
            result.owui_error = f"{type(e).__name__}: {e}"[:500]
            logger.warning(f"owui_delete_model failed: id={model_id} err={result.owui_error}")

        if litellm_ok and owui_ok:
            result.ok = True
            result.state = "deprovisioned"
        elif litellm_ok or owui_ok:
            result.ok = False
            result.state = "partial"
        else:
            result.ok = False
            result.state = "failed"
        return result

    # ---- State persistence -----------------------------------------------

    @staticmethod
    def apply_result(agent: Agent, result: ProvisionResult) -> None:
        """Mutate the Agent row with runtime binding state.

        Caller is responsible for flushing / committing; keeping this as a
        pure mutator makes it trivial to compose inside existing
        agent_service.py transactional flows.
        """
        now = datetime.now(timezone.utc)
        if result.state == "provisioned":
            agent.litellm_key_alias = result.litellm_key_alias
            agent.litellm_key_last4 = result.litellm_key_last4
            agent.owui_model_id = result.owui_model_id
            agent.runtime_sync_state = "provisioned"
            agent.runtime_sync_error = None
            agent.runtime_synced_at = now
            agent.runtime_manifest_hash = agent.manifest_hash
        elif result.state == "partial":
            # Remember what succeeded so retry can pick up where we left off.
            if result.litellm_key_alias:
                agent.litellm_key_alias = result.litellm_key_alias
            if result.litellm_key_last4:
                agent.litellm_key_last4 = result.litellm_key_last4
            if result.owui_model_id:
                agent.owui_model_id = result.owui_model_id
            agent.runtime_sync_state = "partial"
            agent.runtime_sync_error = result.error_summary
            agent.runtime_synced_at = now
        elif result.state == "failed":
            agent.runtime_sync_state = "failed"
            agent.runtime_sync_error = result.error_summary
            agent.runtime_synced_at = now
        elif result.state == "deprovisioned":
            agent.litellm_key_alias = None
            agent.litellm_key_last4 = None
            agent.owui_model_id = None
            agent.runtime_sync_state = "deprovisioned"
            agent.runtime_sync_error = None
            agent.runtime_synced_at = now
            agent.runtime_manifest_hash = None


# ---------------------------------------------------------------------------
# Default client factories
# ---------------------------------------------------------------------------


def _build_default_litellm_client() -> _LiteLLMClient:
    """Build the platform LiteLLM admin client from runtime env/settings.

    Admin ops require LITELLM_MASTER_KEY. The LiteLLM API key used by
    ordinary traffic lives in settings.litellm_api_key; for admin we
    prefer the explicit master key if present, else fall back.
    """
    admin_key = (
        os.environ.get("LITELLM_MASTER_KEY")
        or settings.litellm_master_key
        or settings.litellm_api_key
    )
    return _LiteLLMClient(base_url=settings.litellm_url, admin_key=admin_key)


def _build_default_owui_client() -> _OWUIClient:
    base = os.environ.get("OPEN_WEBUI_URL", "http://open-webui:8080")
    key = os.environ.get("OPEN_WEBUI_API_KEY", "")
    return _OWUIClient(base_url=base, api_key=key)
