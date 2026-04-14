"""Open WebUI sync for shared skills.

Open WebUI exposes a "Models" admin surface: each entry is a custom
model that chains off a base model with its own system prompt,
temperature, and tool allowlist. Shared skills map cleanly onto that
surface — one skill per Open WebUI model.

Group gating: Open WebUI's per-model "Groups" field limits which users
see the model in the picker. We map the skill's AD group allowlist to
Open WebUI group names 1:1 (e.g. AD group "HR" → Open WebUI group "HR").
Groups must pre-exist in Open WebUI; this sync does not create them.

This service is best-effort. If Open WebUI is unreachable the API
endpoints log and swallow the failure so the governance-hub response
isn't blocked on a slow or down sync target.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..db.models import SharedSkill

logger = logging.getLogger("insidellm.skill_sync")

OWUI_BASE_URL = os.environ.get("OPEN_WEBUI_URL", "http://open-webui:8080")
OWUI_API_KEY = os.environ.get("OPEN_WEBUI_API_KEY", "")

# Prefix we apply to every synced model id so we can tell skill-backed
# entries apart from models operators add manually.
MODEL_ID_PREFIX = "insidellm-skill-"


def _model_id(slug: str) -> str:
    return f"{MODEL_ID_PREFIX}{slug}"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if OWUI_API_KEY:
        headers["Authorization"] = f"Bearer {OWUI_API_KEY}"
    return headers


def _skill_to_owui_payload(skill: SharedSkill) -> dict[str, Any]:
    """Translate a SharedSkill into Open WebUI's model-create payload."""
    return {
        "id": _model_id(skill.slug),
        "name": skill.name,
        "base_model_id": skill.base_model,
        "meta": {
            "description": skill.description,
            "tags": [{"name": t} for t in (skill.tags or [])],
        },
        "params": {
            "system": skill.system_prompt,
            "temperature": float(skill.temperature),
        },
        "access_control": {
            "read": {"group_ids": list(skill.group_allowlist or [])},
            "write": {"group_ids": []},
        },
    }


async def sync_skill_to_openwebui(skill: SharedSkill) -> None:
    """Create or update the Open WebUI model entry for this skill."""
    if not OWUI_API_KEY:
        logger.warning("OPEN_WEBUI_API_KEY not set — skill sync disabled")
        return

    payload = _skill_to_owui_payload(skill)
    model_id = payload["id"]

    async with httpx.AsyncClient(timeout=10) as client:
        # Open WebUI's models API: POST to create, POST to /update for updates.
        # We try update first (idempotent), fall back to create on 404.
        try:
            resp = await client.post(
                f"{OWUI_BASE_URL}/api/v1/models/update",
                params={"id": model_id},
                headers=_headers(),
                json=payload,
            )
            if resp.status_code == 404:
                resp = await client.post(
                    f"{OWUI_BASE_URL}/api/v1/models/create",
                    headers=_headers(),
                    json=payload,
                )
            resp.raise_for_status()
            logger.info(f"Synced skill '{skill.slug}' to Open WebUI model '{model_id}'")
        except httpx.HTTPError as exc:
            logger.error(f"Open WebUI sync failed for '{skill.slug}': {exc}")
            raise


async def remove_skill_from_openwebui(skill: SharedSkill) -> None:
    """Delete the Open WebUI model entry backing this skill."""
    if not OWUI_API_KEY:
        logger.warning("OPEN_WEBUI_API_KEY not set — skill sync disabled")
        return

    model_id = _model_id(skill.slug)
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.delete(
                f"{OWUI_BASE_URL}/api/v1/models/delete",
                params={"id": model_id},
                headers=_headers(),
            )
            # 404 is fine — it may have been deleted out-of-band.
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
            logger.info(f"Removed Open WebUI model '{model_id}' for skill '{skill.slug}'")
        except httpx.HTTPError as exc:
            logger.error(f"Open WebUI delete failed for '{skill.slug}': {exc}")
            raise
