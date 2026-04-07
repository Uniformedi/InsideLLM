"""
title: AI System Designer
author: InsideLLM
version: 1.0.0
description: Design InsideLLM deployments, generate optimized configurations, plan multi-instance architectures, and model cost projections.
"""

import json

import requests
from pydantic import BaseModel, Field


DESIGN_PROMPT = """You are the InsideLLM System Designer. You help organizations plan and configure AI infrastructure deployments.

InsideLLM is a self-hosted enterprise AI platform that deploys on Hyper-V VMs with:
- LiteLLM API gateway (Anthropic Claude models + optional Ollama local models)
- Open WebUI chat interface with DLP pipeline
- PostgreSQL for state/audit, Redis for caching
- Nginx reverse proxy with TLS
- Optional services: DocForge (file conversion), Grafana+Loki (monitoring), Watchtower (patching), Trivy (CVE scanning), Uptime Kuma (health)
- Enterprise Governance Hub with central sync, change management, AI advisor, fleet management

INDUSTRY TEMPLATES AVAILABLE:
- collections: FDCPA/FCRA/TCPA compliance, debt recovery workflows
- healthcare: HIPAA, PHI protection, clinical terminology
- financial: BSA/AML, KYC, lending compliance
- insurance: Claims, underwriting, actuarial
- legal: Litigation, privilege, contracts
- realestate: Fair housing, transactions
- retail: PCI, consumer protection
- education: FERPA, academic integrity
- government: FOIA, FedRAMP, procurement
- manufacturing: OSHA, quality, supply chain
- general: Technology/general purpose

GOVERNANCE TIERS:
- tier1: Material decisions (full controls, bias audits, human oversight, 3-7yr retention)
- tier2: Operational (standard controls, documented purpose, periodic review)
- tier3: Routine tools (lightweight, approved vendors only)

DATA CLASSIFICATION:
- public: Any approved vendor
- internal: Enterprise platforms only
- confidential: On-premise/private cloud only
- restricted: Pre-approved + executive approval

VM SIZING GUIDELINES:
- With Ollama: 8 vCPU, 32GB RAM, 80GB disk
- Without Ollama: 4 vCPU, 8GB RAM, 80GB disk
- Ollama separate VM: 8 vCPU, 32GB RAM, 100GB disk
- Each instance needs: 1 Hyper-V host with Windows Pro/Server

COST FACTORS:
- Anthropic API: ~$3/MTok (Sonnet), ~$0.25/MTok (Haiku), ~$15/MTok (Opus)
- Infrastructure: Hyper-V host hardware + electricity
- Per user: ~$5/day default budget at Sonnet tier
- Ollama: Free inference but requires GPU/high RAM

{context}

Based on the requirements below, provide:
1. Recommended architecture (number of instances, VM sizing, services)
2. Governance configuration (tier, classification, retention)
3. Team structure with budgets
4. Cost projection (monthly)
5. A complete terraform.tfvars snippet

REQUIREMENTS:
{requirements}

Respond with structured markdown including a ```hcl code block for the terraform.tfvars.
"""


class Valves(BaseModel):
    governance_hub_url: str = Field(default="http://governance-hub:8090")
    litellm_url: str = Field(default="http://litellm:4000")
    litellm_api_key: str = Field(default="")
    designer_model: str = Field(default="claude-sonnet")
    enabled: bool = Field(default=True)


class Tools:
    def __init__(self):
        self.valves = Valves()

    def _llm_call(self, prompt: str) -> str:
        try:
            resp = requests.post(
                f"{self.valves.litellm_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.valves.litellm_api_key}"},
                json={
                    "model": self.valves.designer_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 8192,
                },
                timeout=180,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error calling LLM: {e}"

    def _get_fleet_context(self) -> str:
        try:
            resp = requests.get(
                f"{self.valves.governance_hub_url}/api/v1/fleet/summary",
                headers={"X-API-Key": ""},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                return f"CURRENT FLEET: {data.get('total_instances', 0)} instances, ${data.get('fleet_total_spend', 0):.2f} total spend, {data.get('fleet_total_users', 0)} users"
        except Exception:
            pass
        return "CURRENT FLEET: No fleet data available (governance hub may not be configured)"

    def design_deployment(
        self,
        requirements: str,
        __user__: dict = {},
    ) -> str:
        """
        Design an InsideLLM deployment based on natural language requirements.

        Provide details like: industry, number of users, compliance needs, budget constraints,
        whether local models are needed, multi-instance requirements, etc.

        Examples:
        - "Healthcare org with 50 users, HIPAA compliant, $500/month budget"
        - "3 branch offices for a collections company, shared central DB, 200 total users"
        - "Developer team of 20, need code assistance and local models, minimal governance"

        :param requirements: Natural language description of what you need
        :return: Architecture recommendation with terraform.tfvars configuration
        """
        if not self.valves.enabled:
            return "System Designer is disabled."

        context = self._get_fleet_context()
        prompt = DESIGN_PROMPT.format(context=context, requirements=requirements)
        return self._llm_call(prompt)

    def estimate_costs(
        self,
        users: int = 10,
        industry: str = "general",
        models: str = "sonnet,haiku",
        local_models: bool = False,
        __user__: dict = {},
    ) -> str:
        """
        Estimate monthly costs for an InsideLLM deployment.

        :param users: Number of users
        :param industry: Industry (collections, healthcare, financial, etc.)
        :param models: Comma-separated Claude models to enable (sonnet, haiku, opus)
        :param local_models: Whether to include Ollama for local LLM inference
        :return: Detailed cost breakdown and optimization suggestions
        """
        if not self.valves.enabled:
            return "System Designer is disabled."

        model_list = [m.strip() for m in models.split(",")]

        prompt = f"""Estimate monthly costs for an InsideLLM deployment:
- Users: {users}
- Industry: {industry}
- Models: {', '.join(model_list)}
- Local models (Ollama): {'Yes' if local_models else 'No'}

Provide:
1. API cost estimate (based on typical usage per user per day)
2. Infrastructure requirements and estimated hardware cost
3. Total monthly projection
4. Cost optimization suggestions
5. Comparison: current config vs optimized config

Use these rates:
- Claude Sonnet: ~$3/MTok input, ~$15/MTok output
- Claude Haiku: ~$0.25/MTok input, ~$1.25/MTok output
- Claude Opus: ~$15/MTok input, ~$75/MTok output
- Average user: ~50 requests/day, ~2000 tokens/request input, ~1000 tokens/request output
- Ollama: Free but requires 32GB RAM VM

Format as a clear markdown table with line items."""
        return self._llm_call(prompt)

    def recommend_config(
        self,
        industry: str,
        users: int = 10,
        budget_per_user_day: float = 5.0,
        needs_local_models: bool = False,
        compliance_level: str = "standard",
        __user__: dict = {},
    ) -> str:
        """
        Get an optimized InsideLLM configuration recommendation.

        :param industry: Industry vertical (collections, healthcare, financial, legal, etc.)
        :param users: Expected number of users
        :param budget_per_user_day: Daily budget per user in USD
        :param needs_local_models: Whether Ollama local models are needed
        :param compliance_level: Compliance level: minimal, standard, strict
        :return: Recommended configuration with terraform.tfvars
        """
        if not self.valves.enabled:
            return "System Designer is disabled."

        tier_map = {"minimal": "tier3", "standard": "tier2", "strict": "tier1"}
        tier = tier_map.get(compliance_level, "tier2")

        context = self._get_fleet_context()
        requirements = f"""Generate an optimized InsideLLM configuration:
- Industry: {industry}
- Users: {users}
- Budget: ${budget_per_user_day}/user/day (${budget_per_user_day * users * 30:.0f}/month total)
- Local models: {'Required' if needs_local_models else 'Not needed'}
- Compliance: {compliance_level} (governance tier: {tier})

Include a complete terraform.tfvars with all recommended settings."""

        prompt = DESIGN_PROMPT.format(context=context, requirements=requirements)
        return self._llm_call(prompt)

    def plan_fleet(
        self,
        requirements: str,
        __user__: dict = {},
    ) -> str:
        """
        Plan a multi-instance InsideLLM fleet architecture.

        Describe your organization's structure, locations, teams, and requirements.
        The designer will recommend how many instances to deploy, where, and how to
        configure the central governance hub for cross-instance management.

        Example: "Law firm with 3 offices (NY, Chicago, LA), 150 attorneys, need
        attorney-client privilege protection, shared billing/audit across offices"

        :param requirements: Description of your multi-instance needs
        :return: Fleet architecture plan with per-instance configurations
        """
        if not self.valves.enabled:
            return "System Designer is disabled."

        context = self._get_fleet_context()
        fleet_prompt = f"""You are planning a multi-instance InsideLLM fleet deployment.

{context}

FLEET PLANNING REQUIREMENTS:
{requirements}

Provide:
1. **Architecture Diagram** (ASCII) showing instances, central DB, and network topology
2. **Instance Inventory** — table with: instance name, location, industry, tier, users, VM sizing
3. **Central Database** — recommended DB type (PostgreSQL/MariaDB/MSSQL), sizing, hosting
4. **Governance Configuration** — per-instance tier, classification, sync schedule
5. **Team Structure** — SSO groups per instance with budgets
6. **Network Requirements** — connectivity between instances and central DB
7. **Cost Projection** — per-instance and fleet total
8. **terraform.tfvars** — for EACH instance (separate code blocks labeled by instance)
9. **Central DB Setup** — SQL to initialize the central repository

Be specific with IP addresses, hostnames, and all terraform variable values."""

        return self._llm_call(fleet_prompt)
