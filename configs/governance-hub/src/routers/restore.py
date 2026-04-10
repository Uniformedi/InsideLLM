from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.local_db import get_local_db
from ..db.models import ConfigSnapshot
from ..services.restore_service import (
    generate_tfvars,
    get_snapshot_from_central,
    list_instance_snapshots,
)

router = APIRouter(prefix="/api/v1/restore", tags=["restore"])


class RestoreRequest(BaseModel):
    instance_id: str
    snapshot_id: int | None = None  # None = latest
    overrides: dict[str, Any] | None = None


class CloneRequest(BaseModel):
    source_instance_id: str
    snapshot_id: int | None = None  # None = latest


@router.post("/generate-tfvars")
async def restore_tfvars(req: RestoreRequest):
    """
    Generate a terraform.tfvars file from a config snapshot.

    Priority: 1) Encrypted original tfvars from vault (decrypted + sanitized + merged)
              2) Reconstructed from config snapshot data
    """
    from ..db.central_db import run_central_query
    from ..db.central_sql import SQL

    # Try to get the encrypted original tfvars from the central DB vault
    vault_row = None
    try:
        def _get_vault(db):
            return db.execute(text(SQL.get_tfvars), {"iid": req.instance_id}).first()
        vault_row = await run_central_query(_get_vault)
    except Exception:
        pass  # Table may not exist yet in central DB

    if vault_row:
        try:
            from ..services.tfvars_vault import (
                decrypt_tfvars, get_current_version_defaults, merge_with_new_variables, sanitize_for_clone,
            )
            original = decrypt_tfvars(vault_row[0], vault_row[1])
            sanitized = sanitize_for_clone(original)
            merged = merge_with_new_variables(sanitized, get_current_version_defaults())

            # Add clone header
            header = (
                f"# =========================================================================\n"
                f"# InsideLLM - terraform.tfvars (cloned from vault)\n"
                f"# Source instance: {req.instance_id}\n"
                f"# Original deployment version: {vault_row[2]}\n"
                f"# Current platform version: {settings.platform_version}\n"
                f"# Cloned at: {datetime.now(timezone.utc).isoformat()}\n"
                f"#\n"
                f"# IMPORTANT: Replace all CHANGE_ME values before deploying.\n"
                f"# =========================================================================\n\n"
            )
            tfvars = header + merged

            return PlainTextResponse(
                content=tfvars,
                media_type="text/plain",
                headers={"Content-Disposition": 'attachment; filename="terraform.tfvars"'},
            )
        except Exception as e:
            # Fall through to snapshot-based generation
            import logging
            logging.getLogger("governance-hub").warning(f"Vault decrypt failed, falling back to snapshot: {e}")

    # Fallback: reconstruct from config snapshot
    snapshot = await get_snapshot_from_central(req.instance_id, req.snapshot_id)
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshot or vault entry found for instance {req.instance_id}",
        )

    config = snapshot.get("config_json", {})
    if isinstance(config, str):
        import json
        config = json.loads(config)

    tfvars = generate_tfvars(config, req.overrides)
    return PlainTextResponse(
        content=tfvars,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="terraform.tfvars"'},
    )


@router.get("/snapshots/{instance_id}")
async def get_snapshots(instance_id: str, limit: int = 20):
    """List available config snapshots for an instance from the central DB."""
    snapshots = await list_instance_snapshots(instance_id, limit)
    return {"instance_id": instance_id, "snapshots": snapshots, "total": len(snapshots)}


@router.post("/generate-tfvars/local")
async def restore_from_local(
    snapshot_id: int | None = None,
    db: AsyncSession = Depends(get_local_db),
):
    """Generate terraform.tfvars from a LOCAL config snapshot (this instance)."""
    if snapshot_id:
        result = await db.execute(select(ConfigSnapshot).where(ConfigSnapshot.id == snapshot_id))
    else:
        result = await db.execute(
            select(ConfigSnapshot).order_by(ConfigSnapshot.id.desc()).limit(1)
        )
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="No local snapshots found")

    tfvars = generate_tfvars(snapshot.config_json)
    return PlainTextResponse(
        content=tfvars,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="terraform.tfvars"'},
    )


@router.post("/clone-from-node")
async def clone_from_node(req: CloneRequest):
    """
    Clone governance configuration from a source instance to this instance.

    Fetches the latest (or specified) snapshot from the central DB and returns
    the config for review. Use generate-tfvars to apply via Terraform, or apply
    governance settings directly via the appropriate API endpoints.
    """
    snapshot = await get_snapshot_from_central(req.source_instance_id, req.snapshot_id)
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshot found for instance {req.source_instance_id}",
        )

    config = snapshot.get("config_json", {})
    if isinstance(config, str):
        import json
        config = json.loads(config)

    return {
        "source_instance_id": req.source_instance_id,
        "snapshot_id": snapshot.get("id"),
        "snapshot_at": snapshot.get("snapshot_at"),
        "config": config,
        "sections": list(config.keys()) if isinstance(config, dict) else [],
    }
