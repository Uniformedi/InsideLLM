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


def generate_tfvars(config: dict, overrides: dict | None = None) -> str:
    """Generate a complete, deployment-ready terraform.tfvars from a config snapshot.

    The output includes everything needed to stand up a new InsideLLM instance:
    API keys (placeholder), VM settings (placeholder), models, budgets, rate limits,
    governance settings, DLP, operations, teams, keyword categories, and more.

    Values from the snapshot are used where available. Host-specific values
    (API keys, IPs, passwords) are left as placeholders marked with CHANGE_ME.
    """
    ov = overrides or {}

    def _val(key: str, default=None):
        """Get value from overrides first, then config, then default."""
        return ov.get(key, config.get(key, default))

    litellm = config.get("litellm", {})
    ops = config.get("ops", {})

    lines = [
        "# =========================================================================",
        f"# InsideLLM - terraform.tfvars (cloned from snapshot)",
        f"# Source instance: {config.get('instance_name', config.get('instance_id', 'unknown'))}",
        f"# Platform version: {config.get('platform_version', 'unknown')}",
        f"# Restored at: {datetime.now(timezone.utc).isoformat()}",
        "#",
        "# IMPORTANT: Replace all CHANGE_ME values before deploying.",
        "# =========================================================================",
        "",
        "# =========================================================================",
        "# Hyper-V Host (CHANGE THESE for your environment)",
        "# =========================================================================",
        'hyperv_user     = "CHANGE_ME"',
        'hyperv_password = "CHANGE_ME"',
        'hyperv_host     = "127.0.0.1"',
        "hyperv_port     = 5985",
        "hyperv_https    = false",
        "hyperv_insecure = true",
        "",
        "# =========================================================================",
        "# Anthropic API Key (REQUIRED — get from console.anthropic.com)",
        "# =========================================================================",
        'anthropic_api_key = "CHANGE_ME"',
        "",
        "# =========================================================================",
        "# VM Configuration (adjust for your hardware)",
        "# =========================================================================",
        f'vm_name              = "InsideLLM"',
        "vm_processor_count   = 8",
        "vm_memory_startup_bytes = 34359738368",
        "vm_disk_size_bytes      = 85899345920",
        'vm_path              = "C:\\\\HyperV\\\\VMs"',
        'vm_vhd_path          = "C:\\\\HyperV\\\\VHDs"',
        'vm_hostname          = "InsideLLM"',
        f'vm_domain            = "local"',
        'ubuntu_vhdx_source   = "C:\\\\HyperV\\\\Images\\\\ubuntu-24.04-cloudimg-amd64.vhdx"',
        "",
        "# =========================================================================",
        "# Network (CHANGE THESE for your network)",
        "# =========================================================================",
        'vm_switch_name    = "InsideLLM"',
        'vm_switch_type    = "External"',
        'vm_switch_adapter = "Ethernet"',
        'vm_static_ip      = "CHANGE_ME/24"',
        'vm_gateway        = "CHANGE_ME"',
        'vm_dns_servers    = ["8.8.8.8", "1.1.1.1"]',
        "",
        "# =========================================================================",
        "# SSH Access",
        "# =========================================================================",
        'ssh_admin_user      = "insidellm-admin"',
        'ssh_public_key_path = "~/.ssh/id_rsa.pub"',
    ]

    # LiteLLM
    lines += [
        "",
        "# =========================================================================",
        "# LiteLLM (Models, Budgets, Rate Limits)",
        "# =========================================================================",
        '# litellm_master_key = ""   # Auto-generated if empty',
        f'litellm_default_model      = "{litellm.get("default_model", "claude-sonnet")}"',
    ]

    # Models
    models = config.get("models", [])
    has_haiku = any("haiku" in m.lower() for m in models) if models else True
    has_opus = any("opus" in m.lower() for m in models) if models else True
    ollama_models = [m.replace("ollama/", "") for m in models if m.startswith("ollama/")] if models else []

    lines.append(f"litellm_enable_haiku       = {str(has_haiku).lower()}")
    lines.append(f"litellm_enable_opus        = {str(has_opus).lower()}")
    lines.append(f"litellm_global_max_budget  = {litellm.get('global_max_budget', 100)}")
    lines.append(f"litellm_default_user_budget = {litellm.get('default_user_budget', 5)}")
    lines.append(f"litellm_default_user_rpm   = {litellm.get('default_user_rpm', 30)}")
    lines.append(f"litellm_default_user_tpm   = {litellm.get('default_user_tpm', 100000)}")

    # Database
    lines += [
        "",
        "# =========================================================================",
        "# Database",
        "# =========================================================================",
        '# postgres_password = ""    # Auto-generated if empty',
    ]

    # Ollama
    lines += [
        "",
        "# =========================================================================",
        "# Ollama (Local LLM)",
        "# =========================================================================",
        f"ollama_enable = {str(bool(ollama_models)).lower()}",
    ]
    if ollama_models:
        model_list = ", ".join(f'"{m}"' for m in ollama_models)
        lines.append(f"ollama_models = [{model_list}]")
        lines.append("ollama_gpu    = false")

    # DLP
    lines += [
        "",
        "# =========================================================================",
        "# Data Loss Prevention (DLP)",
        "# =========================================================================",
        f"dlp_enable           = {str(config.get('dlp_enable', True)).lower()}",
        f"dlp_block_ssn        = {str(config.get('dlp_block_ssn', True)).lower()}",
        f"dlp_block_credit_cards = {str(config.get('dlp_block_credit_cards', True)).lower()}",
        f"dlp_block_phi        = {str(config.get('dlp_block_phi', True)).lower()}",
        f"dlp_block_credentials = {str(config.get('dlp_block_credentials', True)).lower()}",
    ]

    # Optional services
    lines += [
        "",
        "# =========================================================================",
        "# Optional Services",
        "# =========================================================================",
        "docforge_enable = true",
    ]

    # AI Governance
    lines += [
        "",
        "# =========================================================================",
        "# AI Governance & Compliance",
        "# =========================================================================",
        f'industry                 = "{_val("industry", "general")}"',
        f'governance_tier          = "{_val("governance_tier", "tier3")}"',
        f'data_classification      = "{_val("data_classification", "internal")}"',
    ]
    if config.get("ai_ethics_officer"):
        lines.append(f'ai_ethics_officer        = "{config["ai_ethics_officer"]}"')
    if config.get("ai_ethics_officer_email"):
        lines.append(f'ai_ethics_officer_email  = "{config["ai_ethics_officer_email"]}"')
    lines.append(f"log_retention_days       = 365")

    # Operations
    lines += [
        "",
        "# =========================================================================",
        "# Automated Operations",
        "# =========================================================================",
        f"ops_watchtower_enable    = {str(ops.get('watchtower_enable', True)).lower()}",
        f"ops_trivy_enable         = {str(ops.get('trivy_enable', True)).lower()}",
        f"ops_grafana_enable       = {str(ops.get('grafana_enable', True)).lower()}",
        f"ops_uptime_kuma_enable   = {str(ops.get('uptime_kuma_enable', True)).lower()}",
        f'ops_backup_schedule      = "{ops.get("backup_schedule", "daily")}"',
    ]
    if ops.get("alert_webhook"):
        lines.append(f'ops_alert_webhook        = "{ops["alert_webhook"]}"')

    # Keyword categories
    keywords = config.get("keyword_categories", [])
    if keywords:
        categories: dict[str, list[str]] = {}
        for kw in keywords:
            cat = kw.get("category", "unknown")
            word = kw.get("keyword", "")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(word)
        if categories:
            lines += ["", "# =========================================================================",
                       "# Keyword Analysis Categories", "# ========================================================================="]
            lines.append("keyword_categories = {")
            for cat, words in categories.items():
                word_list = ", ".join(f'"{w}"' for w in words)
                lines.append(f"  {cat} = [{word_list}]")
            lines.append("}")

    # Governance Hub
    lines += [
        "",
        "# =========================================================================",
        "# Enterprise Governance Hub",
        "# Central fleet database is configured post-deployment via the Admin UI",
        "# =========================================================================",
        "governance_hub_enable              = true",
        f'governance_hub_instance_name       = "{_val("instance_name", "")}"',
        f'governance_hub_sync_schedule       = "{_val("sync_schedule", "0 */6 * * *")}"',
    ]
    if config.get("supervisor_emails"):
        lines.append(f'governance_hub_supervisor_emails  = "{config["supervisor_emails"]}"')
    lines.append(f'governance_hub_advisor_model      = "{_val("advisor_model", "claude-sonnet")}"')

    # Teams
    teams = config.get("teams", [])
    if teams:
        lines += ["", "# =========================================================================",
                   "# Teams (from source instance snapshot)", "# =========================================================================",
                   "# Configure via sso_group_mapping for SSO, or apply manually in LiteLLM UI"]
        for team in teams:
            alias = team.get("team_alias", "unknown")
            budget = team.get("max_budget") or 0
            duration = team.get("budget_duration", "1d")
            tpm = team.get("tpm_limit") or 100000
            rpm = team.get("rpm_limit") or 30
            team_models = team.get("models", [])
            models_str = ", ".join(f'"{m}"' for m in team_models) if team_models else '"claude-sonnet"'
            lines.append(f"# Team: {alias}")
            lines.append(f"#   budget={budget} ({duration}), tpm={tpm}, rpm={rpm}")
            lines.append(f"#   models=[{models_str}]")

    # Environment and ownership
    lines += [
        "",
        "# =========================================================================",
        "# Environment",
        "# =========================================================================",
        'environment = "production"',
        f'owner       = "{_val("owner", "CHANGE_ME")}"',
    ]

    # Apply any explicit overrides
    if ov:
        remaining = {k: v for k, v in ov.items() if not any(
            f'{k} =' in line or f'{k}=' in line for line in lines
        )}
        if remaining:
            lines += ["", "# Overrides applied during restore"]
            for k, v in remaining.items():
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
    from ..db.central_db import run_central_query
    from ..db.central_sql import SQL

    def _query(db):
        if snapshot_id:
            result = db.execute(text(SQL.snapshot_by_id), {"iid": instance_id, "sid": snapshot_id})
        else:
            result = db.execute(text(SQL.snapshot_latest), {"iid": instance_id})
        row = result.mappings().first()
        return dict(row) if row else None

    return await run_central_query(_query)


async def list_instance_snapshots(instance_id: str, limit: int = 20) -> list[dict]:
    """List config snapshots for an instance from the central database."""
    from ..db.central_db import run_central_query
    from ..db.central_sql import SQL

    def _query(db):
        result = db.execute(text(SQL.snapshot_list), {"iid": instance_id, "lim": limit})
        return [dict(r) for r in result.mappings()]

    result = await run_central_query(_query)
    return result if result is not None else []
