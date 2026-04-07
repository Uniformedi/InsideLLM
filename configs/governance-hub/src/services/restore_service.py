"""
Restore service — generate terraform.tfvars from config snapshots.

Reads config snapshots from the local or central database and produces
a complete terraform.tfvars file that can be used to recreate or
redeploy an InsideLLM instance.
"""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.central_db import get_central_session_factory


def generate_tfvars(config: dict, overrides: dict | None = None) -> str:
    """Generate a terraform.tfvars file from a config snapshot."""
    ov = overrides or {}
    lines = [
        "# =========================================================================",
        f"# InsideLLM - terraform.tfvars (restored from snapshot)",
        f"# Source instance: {config.get('instance_name', config.get('instance_id', 'unknown'))}",
        f"# Schema version: {config.get('schema_version', 'unknown')}",
        f"# Restored at: {datetime.now(timezone.utc).isoformat()}",
        "# =========================================================================",
        "",
    ]

    # Map config fields to terraform variable names
    field_map = {
        "industry": ("industry", "str"),
        "governance_tier": ("governance_tier", "str"),
        "data_classification": ("data_classification", "str"),
        "advisor_model": ("governance_hub_advisor_model", "str"),
    }

    for config_key, (tf_key, vtype) in field_map.items():
        val = ov.get(tf_key, config.get(config_key))
        if val is not None:
            if vtype == "str":
                lines.append(f'{tf_key} = "{val}"')
            else:
                lines.append(f"{tf_key} = {val}")

    # Teams → SSO group mapping
    teams = config.get("teams", [])
    if teams:
        lines.append("")
        lines.append("# Teams (from snapshot)")
        lines.append("# NOTE: These were the teams at snapshot time.")
        lines.append("# If using SSO group mapping, configure sso_group_mapping instead.")
        for team in teams:
            alias = team.get("team_alias", "unknown")
            budget = team.get("max_budget", 0)
            tpm = team.get("tpm_limit", 100000)
            rpm = team.get("rpm_limit", 30)
            lines.append(f"# Team: {alias} (budget={budget}, tpm={tpm}, rpm={rpm})")

    # Keyword categories
    keywords = config.get("keyword_categories", [])
    if keywords:
        # Group by category
        categories: dict[str, list[str]] = {}
        for kw in keywords:
            cat = kw.get("category", "unknown")
            word = kw.get("keyword", "")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(word)

        # Only emit custom categories (not built-in ones)
        builtin = {"collections", "legal", "development", "research", "content", "pii_mention"}
        custom = {k: v for k, v in categories.items() if k not in builtin}
        if custom:
            lines.append("")
            lines.append("keyword_categories = {")
            for cat, words in custom.items():
                word_list = ", ".join(f'"{w}"' for w in words)
                lines.append(f"  {cat} = [{word_list}]")
            lines.append("}")

    # Models
    models = config.get("models", [])
    if models:
        lines.append("")
        lines.append("# Models at snapshot time")
        has_haiku = any("haiku" in m.lower() for m in models)
        has_opus = any("opus" in m.lower() for m in models)
        ollama_models = [m.replace("ollama/", "") for m in models if m.startswith("ollama/")]

        lines.append(f"litellm_enable_haiku = {str(has_haiku).lower()}")
        lines.append(f"litellm_enable_opus  = {str(has_opus).lower()}")
        if ollama_models:
            lines.append(f"ollama_enable = true")
            model_list = ", ".join(f'"{m}"' for m in ollama_models)
            lines.append(f"ollama_models = [{model_list}]")

    # Apply any explicit overrides
    if ov:
        lines.append("")
        lines.append("# Overrides applied during restore")
        for k, v in ov.items():
            if k not in [tf_key for _, (tf_key, _) in field_map.items()]:
                if isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                elif isinstance(v, bool):
                    lines.append(f"{k} = {str(v).lower()}")
                else:
                    lines.append(f"{k} = {v}")

    lines.append("")
    return "\n".join(lines)


async def get_snapshot_from_central(instance_id: str, snapshot_id: int | None = None) -> dict | None:
    """Retrieve a config snapshot from the central database."""
    factory = get_central_session_factory()
    if not factory:
        return None

    async with factory() as db:
        if snapshot_id:
            result = await db.execute(text("""
                SELECT * FROM governance_config_snapshots
                WHERE instance_id = :iid AND id = :sid
            """), {"iid": instance_id, "sid": snapshot_id})
        else:
            # Latest snapshot
            result = await db.execute(text("""
                SELECT * FROM governance_config_snapshots
                WHERE instance_id = :iid
                ORDER BY snapshot_at DESC LIMIT 1
            """), {"iid": instance_id})

        row = result.mappings().first()
        if not row:
            return None
        return dict(row)


async def list_instance_snapshots(instance_id: str, limit: int = 20) -> list[dict]:
    """List config snapshots for an instance from the central database."""
    factory = get_central_session_factory()
    if not factory:
        return []

    async with factory() as db:
        result = await db.execute(text("""
            SELECT id, instance_id, schema_version, snapshot_at, created_by
            FROM governance_config_snapshots
            WHERE instance_id = :iid
            ORDER BY snapshot_at DESC
            LIMIT :lim
        """), {"iid": instance_id, "lim": limit})
        return [dict(r) for r in result.mappings()]
