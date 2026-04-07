"""
title: Data Connector
author: InsideLLM
version: 1.0.0
description: Query external data sources for cross-referencing. Access is controlled by team-based permissions with full audit logging.
"""

import json

import requests
from pydantic import BaseModel, Field


class Valves(BaseModel):
    governance_hub_url: str = Field(default="http://governance-hub:8090")
    api_key: str = Field(default="")
    enabled: bool = Field(default=True)


class Tools:
    def __init__(self):
        self.valves = Valves()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.valves.api_key:
            h["X-API-Key"] = self.valves.api_key
        return h

    def list_data_sources(self, __user__: dict = {}) -> str:
        """
        List all available external data sources you can query.
        Shows the data source name, type, classification level, and connection status.

        :return: Table of registered data connectors
        """
        if not self.valves.enabled:
            return "Data connectors are disabled."

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/connectors/",
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            connectors = resp.json()
        except Exception as e:
            return f"Error: {e}"

        if not connectors:
            return "No data connectors registered. Ask an administrator to add external data sources via the Governance Hub."

        lines = ["## Available Data Sources\n"]
        lines.append("| ID | Name | Type | Classification | Status | Enabled |")
        lines.append("|----|------|------|---------------|--------|---------|")
        for c in connectors:
            status = c.get("last_test_status", "untested")
            enabled = "Yes" if c.get("enabled") else "No"
            lines.append(f"| {c['id']} | **{c['name']}** | {c['type']} | {c['classification']} | {status} | {enabled} |")

        lines.append(f"\nUse `query_data_source` with the connector ID and a query to fetch data.")
        return "\n".join(lines)

    def query_data_source(
        self,
        connector_id: int,
        query: str,
        __user__: dict = {},
    ) -> str:
        """
        Query an external data source. Access is enforced by team-based permissions.

        For SQL databases: provide a SELECT query.
        For REST APIs: provide the endpoint path (e.g., "/users" or "/api/v1/reports").

        :param connector_id: ID of the data connector (from list_data_sources)
        :param query: SQL SELECT query or API endpoint path
        :return: Query results as a formatted table
        """
        if not self.valves.enabled:
            return "Data connectors are disabled."

        username = __user__.get("name", __user__.get("email", "unknown"))
        # Extract team info from user metadata if available
        teams = []
        if __user__.get("role"):
            teams.append(__user__["role"])

        try:
            resp = requests.post(
                f"{self.valves.governance_hub_url}/api/v1/connectors/{connector_id}/query",
                headers=self._headers(),
                json={
                    "query": query,
                    "username": username,
                    "teams": teams,
                },
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            return f"Error: {e}"

        status = result.get("status", "error")
        if status == "denied":
            return f"**Access Denied:** {result.get('message', 'You do not have access to this data source.')} Contact an administrator to request access."

        if status == "error":
            return f"**Query Error:** {result.get('message', 'Unknown error')}"

        data = result.get("data", [])
        if not data:
            return "Query returned no results."

        row_count = result.get("row_count", len(data))
        duration = result.get("duration_ms", "?")

        # Format as markdown table
        columns = list(data[0].keys()) if data else []
        lines = [f"**{row_count} rows** returned in {duration}ms\n"]
        if columns:
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in data[:50]:  # Cap display at 50 rows
                vals = [str(row.get(c, ""))[:100] for c in columns]
                lines.append("| " + " | ".join(vals) + " |")
            if len(data) > 50:
                lines.append(f"\n*Showing 50 of {row_count} rows. Refine your query for the full dataset.*")

        return "\n".join(lines)

    def check_my_access(self, connector_id: int, __user__: dict = {}) -> str:
        """
        Check what access you have to a specific data connector.

        :param connector_id: ID of the data connector
        :return: Your access level and any filters applied
        """
        if not self.valves.enabled:
            return "Data connectors are disabled."

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/connectors/{connector_id}/access",
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            rules = resp.json()
        except Exception as e:
            return f"Error: {e}"

        if not rules:
            return "No access rules configured for this connector. Contact an administrator."

        username = __user__.get("name", __user__.get("email", "unknown"))

        lines = [f"## Access Rules for Connector #{connector_id}\n"]
        lines.append("| Type | Value | Permission | Row Filter | Field Mask | Expires |")
        lines.append("|------|-------|-----------|-----------|-----------|---------|")
        for r in rules:
            expires = r.get("expires_at", "never") or "never"
            row_filter = r.get("row_filter", "--") or "--"
            field_mask = json.dumps(r.get("field_mask")) if r.get("field_mask") else "--"
            lines.append(f"| {r['grant_type']} | {r['grant_value']} | **{r['permission']}** | {row_filter} | {field_mask} | {expires} |")

        return "\n".join(lines)

    def view_query_history(self, connector_id: int = 0, __user__: dict = {}) -> str:
        """
        View recent query audit log for a data connector (or all connectors if ID is 0).

        :param connector_id: Connector ID (0 for all)
        :return: Recent query log with user, status, and timing
        """
        if not self.valves.enabled:
            return "Data connectors are disabled."

        params = {"limit": 20}
        if connector_id > 0:
            params["connector_id"] = connector_id

        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/connectors/logs/queries",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            logs = resp.json()
        except Exception as e:
            return f"Error: {e}"

        if not logs:
            return "No query history found."

        lines = ["## Query Audit Log\n"]
        lines.append("| Time | Connector | User | Status | Rows | Duration |")
        lines.append("|------|-----------|------|--------|------|----------|")
        for l in logs:
            time = str(l.get("queried_at", ""))[:19].replace("T", " ")
            lines.append(f"| {time} | {l.get('connector_name', '?')} | {l.get('queried_by', '?')} | {l.get('status', '?')} | {l.get('row_count', '--')} | {l.get('duration_ms', '--')}ms |")

        return "\n".join(lines)
