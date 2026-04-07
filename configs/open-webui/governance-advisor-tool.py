"""
title: AI Governance Advisor
author: InsideLLM
version: 1.0.0
description: Analyze governance data and suggest framework improvements. All suggestions require supervisor approval.
"""

import json
from typing import Any

import requests
from pydantic import BaseModel, Field


class Valves(BaseModel):
    """Configuration for the Governance Advisor tool."""

    governance_hub_url: str = Field(
        default="http://governance-hub:8090",
        description="Governance Hub API URL (internal Docker network)",
    )
    api_key: str = Field(
        default="",
        description="Governance Hub API key",
    )
    enabled: bool = Field(
        default=True,
        description="Enable or disable the governance advisor",
    )


class Tools:
    def __init__(self):
        self.valves = Valves()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.valves.api_key:
            h["X-API-Key"] = self.valves.api_key
        return h

    def analyze_governance(
        self,
        analysis_type: str = "comprehensive",
        time_range_days: int = 30,
        focus_areas: str = "",
        __user__: dict = {},
    ) -> str:
        """
        Run an AI-powered analysis of governance data and generate improvement suggestions.
        All suggestions are created as pending change proposals requiring supervisor approval.

        Analysis types: comprehensive, cost_optimization, compliance_gaps, keyword_trends, team_utilization

        :param analysis_type: Type of analysis (comprehensive, cost_optimization, compliance_gaps, keyword_trends, team_utilization)
        :param time_range_days: Number of days of data to analyze (1-365)
        :param focus_areas: Comma-separated focus areas (optional)
        :return: Analysis summary with improvement suggestions
        """
        if not self.valves.enabled:
            return "Governance Advisor is currently disabled."

        payload: dict[str, Any] = {
            "analysis_type": analysis_type,
            "time_range_days": time_range_days,
        }
        if focus_areas:
            payload["focus_areas"] = [a.strip() for a in focus_areas.split(",")]

        try:
            resp = requests.post(
                f"{self.valves.governance_hub_url}/api/v1/advisor/analyze",
                headers=self._headers(),
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Error calling Governance Hub: {e}"

        # Format response
        lines = [f"## Governance Analysis ({analysis_type}, {time_range_days}d)\n"]
        lines.append(data.get("analysis_summary", "No summary available."))
        lines.append(f"\n**Proposals created:** {data.get('proposals_created', 0)}")
        lines.append("\n> All suggestions have been added as **pending change proposals** requiring supervisor approval.\n")

        for i, s in enumerate(data.get("suggestions", []), 1):
            lines.append(f"### {i}. {s['title']}")
            lines.append(f"**Category:** {s['category']} | **Priority:** {s['priority']}")
            lines.append(s["description"])
            if s.get("estimated_savings"):
                lines.append(f"**Estimated savings:** {s['estimated_savings']}")
            if s.get("compliance_impact"):
                lines.append(f"**Compliance impact:** {s['compliance_impact']}")
            lines.append("")

        return "\n".join(lines)

    def list_pending_changes(self, __user__: dict = {}) -> str:
        """
        List all pending governance change proposals awaiting supervisor approval.

        :return: Formatted list of pending change proposals
        """
        if not self.valves.enabled:
            return "Governance Advisor is currently disabled."

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/changes",
                headers=self._headers(),
                params={"status": "pending"},
                timeout=30,
            )
            resp.raise_for_status()
            changes = resp.json()
        except Exception as e:
            return f"Error: {e}"

        if not changes:
            return "No pending change proposals."

        lines = ["## Pending Change Proposals\n"]
        for c in changes:
            source_tag = " (AI)" if c["source"] == "ai_advisor" else ""
            lines.append(f"- **#{c['id']}** [{c['category']}] {c['title']}{source_tag}")
            lines.append(f"  Proposed by: {c['proposed_by']} on {c['proposed_at'][:10]}")
            if c.get("impact_assessment"):
                lines.append(f"  Impact: {c['impact_assessment'][:200]}")
            lines.append("")

        lines.append(f"\n**Total pending:** {len(changes)}")
        lines.append("\nSupervisors can approve/reject proposals via the Governance Hub API at `/governance/api/v1/changes/<id>/approve`")
        return "\n".join(lines)

    def get_compliance_summary(self, __user__: dict = {}) -> str:
        """
        Get a compliance summary including sync status, telemetry metrics, and governance scores.

        :return: Formatted compliance summary
        """
        if not self.valves.enabled:
            return "Governance Advisor is currently disabled."

        try:
            sync_resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/sync/status",
                headers=self._headers(),
                timeout=15,
            )
            sync_data = sync_resp.json() if sync_resp.ok else {}

            schema_resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/schema/current",
                headers=self._headers(),
                timeout=15,
            )
            schema_data = schema_resp.json() if schema_resp.ok else {}

            changes_resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/changes",
                headers=self._headers(),
                params={"status": "pending"},
                timeout=15,
            )
            pending = changes_resp.json() if changes_resp.ok else []
        except Exception as e:
            return f"Error: {e}"

        lines = ["## Governance Compliance Summary\n"]
        lines.append(f"**Instance:** {schema_data.get('instance_id', 'unknown')}")
        lines.append(f"**Schema Version:** {schema_data.get('schema_version', 'unknown')}")
        lines.append(f"**Last Sync:** {sync_data.get('last_sync_at', 'never')}")
        lines.append(f"**Sync Status:** {sync_data.get('last_status', 'unknown')}")
        lines.append(f"**Central DB Connected:** {'Yes' if sync_data.get('central_db_connected') else 'No'}")
        lines.append(f"**Pending Changes:** {len(pending)}")
        lines.append("")

        if pending:
            ai_count = sum(1 for c in pending if c.get("source") == "ai_advisor")
            human_count = len(pending) - ai_count
            lines.append(f"  - AI-suggested: {ai_count}")
            lines.append(f"  - Human-proposed: {human_count}")

        return "\n".join(lines)
