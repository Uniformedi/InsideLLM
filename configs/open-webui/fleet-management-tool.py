"""
title: Fleet Management
author: InsideLLM
version: 1.0.0
description: Manage multiple InsideLLM deployments — view instances, compare configs, restore from snapshots, and generate terraform.tfvars for redeployment.
"""

import json

import requests
from pydantic import BaseModel, Field


class Valves(BaseModel):
    """Configuration for the Fleet Management tool."""

    governance_hub_url: str = Field(
        default="http://governance-hub:8090",
        description="Governance Hub API URL",
    )
    api_key: str = Field(
        default="",
        description="Governance Hub API key",
    )
    enabled: bool = Field(
        default=True,
        description="Enable or disable fleet management",
    )


class Tools:
    def __init__(self):
        self.valves = Valves()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.valves.api_key:
            h["X-API-Key"] = self.valves.api_key
        return h

    def list_deployments(self, __user__: dict = {}) -> str:
        """
        List all InsideLLM deployments registered in the central repository.
        Shows instance name, industry, governance tier, last sync, compliance score, and spend.

        :return: Formatted table of all InsideLLM instances across the enterprise
        """
        if not self.valves.enabled:
            return "Fleet management is disabled."

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/fleet/instances",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Error: {e}"

        instances = data.get("instances", [])
        if not instances:
            return "No InsideLLM instances registered in the central repository."

        lines = [f"## InsideLLM Fleet — {len(instances)} Instances\n"]
        lines.append("| Instance | Industry | Tier | Last Sync | Compliance | Spend | Users |")
        lines.append("|----------|----------|------|-----------|------------|-------|-------|")

        for inst in instances:
            name = inst.get("instance_name", "—")
            industry = inst.get("industry", "—")
            tier = inst.get("governance_tier", "—")
            sync = inst.get("last_sync_at", "never")
            if sync and sync != "never":
                sync = sync[:16].replace("T", " ")
            tel = inst.get("latest_telemetry") or {}
            score = tel.get("compliance_score", "—")
            spend = tel.get("total_spend", "—")
            users = tel.get("unique_users", "—")
            if isinstance(spend, (int, float)):
                spend = f"${spend:.2f}"
            if isinstance(score, (int, float)):
                score = f"{score:.1f}%"
            lines.append(f"| {name} | {industry} | {tier} | {sync} | {score} | {spend} | {users} |")

        return "\n".join(lines)

    def get_instance_detail(self, instance_id: str, __user__: dict = {}) -> str:
        """
        Get detailed information about a specific InsideLLM deployment including telemetry history.

        :param instance_id: The instance ID (usually the VM name, e.g., "InsideLLM" or "InsideLLM-East")
        :return: Detailed instance info with telemetry history
        """
        if not self.valves.enabled:
            return "Fleet management is disabled."

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/fleet/instances/{instance_id}",
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code == 404:
                return f"Instance '{instance_id}' not found in the central repository."
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Error: {e}"

        inst = data.get("instance", {})
        lines = [f"## Instance: {inst.get('instance_name', instance_id)}\n"]
        lines.append(f"- **Industry:** {inst.get('industry', '—')}")
        lines.append(f"- **Governance Tier:** {inst.get('governance_tier', '—')}")
        lines.append(f"- **Data Classification:** {inst.get('data_classification', '—')}")
        lines.append(f"- **Schema Version:** {inst.get('schema_version', '—')}")
        lines.append(f"- **Status:** {inst.get('status', '—')}")
        lines.append(f"- **Last Sync:** {inst.get('last_sync_at', 'never')}")

        history = data.get("telemetry_history", [])
        if history:
            lines.append(f"\n### Recent Telemetry ({len(history)} entries)\n")
            lines.append("| Period | Requests | Spend | Users | Compliance | Critical Flags |")
            lines.append("|--------|----------|-------|-------|------------|----------------|")
            for t in history[:10]:
                period = str(t.get("period_end", ""))[:10]
                lines.append(f"| {period} | {t.get('total_requests', 0)} | ${t.get('total_spend', 0):.2f} | {t.get('unique_users', 0)} | {t.get('compliance_score', 0):.1f}% | {t.get('keyword_flags_critical', 0)} |")

        return "\n".join(lines)

    def fleet_summary(self, __user__: dict = {}) -> str:
        """
        Get aggregate metrics across all InsideLLM deployments in the enterprise.

        :return: Fleet-wide summary including total instances, spend, users, compliance
        """
        if not self.valves.enabled:
            return "Fleet management is disabled."

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/fleet/summary",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Error: {e}"

        lines = ["## Fleet Summary\n"]
        lines.append(f"- **Total Instances:** {data.get('total_instances', 0)}")
        lines.append(f"- **Reporting (synced recently):** {data.get('reporting_instances', 0)}")
        lines.append(f"- **Stale (no sync in 24h):** {data.get('stale_instances', 0)}")
        lines.append(f"- **Fleet Total Requests:** {data.get('fleet_total_requests', 0):,}")
        lines.append(f"- **Fleet Total Spend:** ${data.get('fleet_total_spend', 0):,.2f}")
        lines.append(f"- **Fleet Total Users:** {data.get('fleet_total_users', 0):,}")
        lines.append(f"- **Avg Compliance Score:** {data.get('avg_compliance_score', 0):.1f}%")
        lines.append(f"- **Total Critical Keyword Flags:** {data.get('total_critical_flags', 0)}")

        by_industry = data.get("instances_by_industry", {})
        if by_industry:
            lines.append("\n### Instances by Industry")
            for ind, count in by_industry.items():
                lines.append(f"- {ind}: {count}")

        return "\n".join(lines)

    def generate_restore_config(
        self,
        instance_id: str,
        snapshot_id: int = 0,
        overrides: str = "",
        __user__: dict = {},
    ) -> str:
        """
        Generate a terraform.tfvars file to recreate or redeploy an InsideLLM instance from a config snapshot.

        Use snapshot_id=0 for the latest snapshot. Provide overrides as JSON to change specific values
        (e.g., '{"vm_hostname": "NewHost", "vm_static_ip": "192.168.1.60/24"}').

        :param instance_id: The instance ID to restore from
        :param snapshot_id: Specific snapshot ID (0 = latest)
        :param overrides: JSON string of terraform variable overrides (optional)
        :return: Generated terraform.tfvars content ready for deployment
        """
        if not self.valves.enabled:
            return "Fleet management is disabled."

        payload = {"instance_id": instance_id}
        if snapshot_id > 0:
            payload["snapshot_id"] = snapshot_id
        if overrides:
            try:
                payload["overrides"] = json.loads(overrides)
            except json.JSONDecodeError:
                return "Error: overrides must be valid JSON."

        try:
            resp = requests.post(
                f"{self.valves.governance_hub_url}/api/v1/restore/generate-tfvars",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            if resp.status_code == 404:
                return f"No config snapshot found for instance '{instance_id}'. Has it synced to the central DB?"
            resp.raise_for_status()
            tfvars = resp.text
        except Exception as e:
            return f"Error: {e}"

        return (
            f"## Restore Config for `{instance_id}`\n\n"
            f"Generated `terraform.tfvars` — save this and run `terraform apply`:\n\n"
            f"```hcl\n{tfvars}\n```\n\n"
            f"> **Note:** You'll still need to provide secrets (API keys, passwords) that aren't stored in snapshots."
        )

    def list_snapshots(self, instance_id: str, __user__: dict = {}) -> str:
        """
        List available config snapshots for an instance that can be used for restore.

        :param instance_id: The instance ID to list snapshots for
        :return: List of available snapshots with dates and version info
        """
        if not self.valves.enabled:
            return "Fleet management is disabled."

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/restore/snapshots/{instance_id}",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Error: {e}"

        snapshots = data.get("snapshots", [])
        if not snapshots:
            return f"No config snapshots found for instance '{instance_id}'."

        lines = [f"## Config Snapshots for `{instance_id}`\n"]
        lines.append("| ID | Schema Version | Captured At | Created By |")
        lines.append("|----|---------------|-------------|------------|")
        for s in snapshots:
            snap_at = str(s.get("snapshot_at", ""))[:19].replace("T", " ")
            lines.append(f"| {s.get('id')} | v{s.get('schema_version', '?')} | {snap_at} | {s.get('created_by', '—')} |")

        lines.append(f"\nUse `generate_restore_config(instance_id=\"{instance_id}\", snapshot_id=<ID>)` to generate tfvars from a specific snapshot.")
        return "\n".join(lines)
