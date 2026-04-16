"""Fleet capability registry.

Each Gov-Hub publishes its own capabilities on startup and every
HEARTBEAT_INTERVAL_SEC seconds. Peers read via /api/v1/fleet/capabilities
to discover 'who provides what' — used for smart module deferral (gateway
nodes point their Promtail at the primary's Loki) and edge routing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..config import settings
from ..db.local_db import AsyncSessionLocal
from ..db.models import FleetCapability

logger = logging.getLogger("governance-hub.capability")

HEARTBEAT_INTERVAL_SEC = 60


def _derive_capabilities() -> list[dict]:
    """Inspect env + settings to list what this instance provides.

    We trust compose-injected CAP_* env vars rather than probing — they are
    set by the Terraform template in line with each service's enablement
    flag, so they are authoritative.
    """
    iid = settings.instance_id or "unknown"
    role = os.environ.get("VM_ROLE", "")
    caps: list[dict] = [
        {
            "capability": "governance-hub",
            "endpoint": f"http://{iid}:8090",
            "role": role,
            "status": "live",
            "metadata": {"version": settings.platform_version},
        }
    ]
    env_map = [
        ("CAP_LITELLM_ENDPOINT", "litellm"),
        ("CAP_OPEN_WEBUI_ENDPOINT", "open-webui"),
        ("CAP_GRAFANA_ENDPOINT", "grafana"),
        ("CAP_LOKI_ENDPOINT", "loki"),
        ("CAP_GUACAMOLE_ENDPOINT", "guacamole"),
        ("CAP_UPTIME_KUMA_ENDPOINT", "uptime-kuma"),
        ("CAP_DOCFORGE_ENDPOINT", "docforge"),
    ]
    for var, name in env_map:
        endpoint = os.environ.get(var, "")
        if endpoint:
            caps.append({
                "capability": name,
                "endpoint": endpoint,
                "role": role,
                "status": "live",
                "metadata": {},
            })
    return caps


async def publish_once() -> int:
    """Upsert this instance's capabilities. Returns count written."""
    caps = _derive_capabilities()
    if not caps:
        return 0
    iid = settings.instance_id or "unknown"
    now = datetime.now(timezone.utc)
    written = 0
    async with AsyncSessionLocal() as db:
        for c in caps:
            stmt = pg_insert(FleetCapability).values(
                instance_id=iid,
                capability=c["capability"],
                endpoint=c["endpoint"],
                role=c["role"],
                status=c["status"],
                capability_metadata=c.get("metadata", {}),
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["instance_id", "capability"],
                set_={
                    "endpoint": c["endpoint"],
                    "role": c["role"],
                    "status": c["status"],
                    # DB column is "metadata" (see FleetCapability model).
                    # set_ takes the underlying column name, not the Python
                    # attribute name capability_metadata.
                    "metadata": c.get("metadata", {}),
                    "updated_at": now,
                },
            )
            await db.execute(stmt)
            written += 1
        await db.commit()
    return written


async def heartbeat_loop() -> None:
    """Long-running task — publish own capabilities every HEARTBEAT_INTERVAL_SEC."""
    while True:
        try:
            n = await publish_once()
            logger.debug(f"capability heartbeat: {n} capabilities published")
        except Exception as exc:
            logger.warning(f"capability heartbeat failed (non-fatal): {exc}")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
