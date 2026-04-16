"""Pydantic models for the InsideLLM declarative agent manifest (v1.1).

Wire format is JSON; YAML authoring is supported by the API via PyYAML
round-trip. The JSON Schema (agent_manifest.schema.json) is the authoritative
spec — these pydantic classes track it.

See docs/Platform-Ultraplan-v3.md §2.2 and docs/Agents-Plan.md for the
full design rationale.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

MANIFEST_VERSION = "1.1"

_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$"


class GuardrailProfile(str, Enum):
    """Named OPA policy bundles. Tenants can only tighten their parent profile."""
    UNRESTRICTED       = "tier_unrestricted"
    GENERAL_BUSINESS   = "tier_general_business"
    FINANCIAL          = "tier_financial_regulated"
    FDCPA              = "tier_fdcpa_regulated"
    HIPAA              = "tier_hipaa_regulated"
    CUSTOM             = "tier_custom"


class VisibilityScope(str, Enum):
    PRIVATE = "private"   # author only
    TEAM    = "team"      # members of manifest.team
    ORG     = "org"       # tenant-wide; tier-2 approval
    FLEET   = "fleet"     # cross-tenant (portfolio); tier-3 approval


class KnowledgeScope(str, Enum):
    STRICT = "strict"
    LOOSE  = "loose"


class ApprovalChannel(str, Enum):
    TEAMS = "teams"
    SLACK = "slack"
    EMAIL = "email"
    NONE  = "none"


class ActionScope(str, Enum):
    READ  = "read"
    WRITE = "write"
    ADMIN = "admin"


class PiiHandling(str, Enum):
    REDACT_IN_LOGS           = "redact_in_logs"
    BLOCK_ON_DETECT          = "block_on_detect"
    PASSTHROUGH_STRICT_AUDIT = "passthrough_strict_audit"


class AgentDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    icon: str | None = None
    conversation_starters: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("conversation_starters")
    @classmethod
    def _starter_lengths(cls, v: list[str]) -> list[str]:
        for s in v:
            if len(s) < 1 or len(s) > 200:
                raise ValueError("each conversation_starter must be 1..200 chars")
        return v


class KnowledgeConnector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector: str
    purpose: str


class AgentKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collections: list[str] = Field(default_factory=list)
    scope: KnowledgeScope = KnowledgeScope.STRICT
    connectors: list[KnowledgeConnector] = Field(default_factory=list)
    urls: list[HttpUrl] = Field(default_factory=list)


class AgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    approval_required: bool = False
    approval_target: str = ""
    approval_channel: ApprovalChannel = ApprovalChannel.NONE
    scope: ActionScope = ActionScope.READ


class DlpOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_pii: bool = False
    allow_phi: bool = False
    allow_financials: bool = False
    allow_credentials: bool = False


class AgentGuardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: GuardrailProfile
    max_actions_per_session: int = Field(default=10, ge=1, le=200)
    token_budget_per_session: int = Field(default=50000, ge=1000, le=2_000_000)
    daily_usd_budget: float | None = Field(default=None, ge=0)
    rpm_limit: int = Field(default=20, ge=1)
    allowed_models: list[str] = Field(default_factory=lambda: ["claude-sonnet-4-6"], min_length=1)
    temperature_cap: float = Field(default=0.7, ge=0, le=2)
    pii_handling: PiiHandling = PiiHandling.REDACT_IN_LOGS
    dlp_overrides: DlpOverrides = Field(default_factory=DlpOverrides)


class AgentVisibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: VisibilityScope = VisibilityScope.PRIVATE
    available_to: list[str] = Field(default_factory=list)
    published: bool = False


class AgentManifest(BaseModel):
    """Canonical declarative-agent manifest (v1.1).

    This is the JSON shape stored in governance_agents.manifest_json and
    exchanged over /api/v1/agents. The translator reads this and produces
    a running Open WebUI Model + LiteLLM virtual key + OPA policy binding.
    """
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    schema_version: str = Field(default=MANIFEST_VERSION, pattern=r"^1\.1$")
    agent_id: str = Field(pattern=_ID_PATTERN)
    tenant_id: str = Field(pattern=_ID_PATTERN)
    created_by: EmailStr | None = None
    team: str | None = None

    display: AgentDisplay
    instructions: str = Field(min_length=20, max_length=8000)
    knowledge: AgentKnowledge = Field(default_factory=AgentKnowledge)
    actions: list[AgentAction] = Field(default_factory=list)
    guardrails: AgentGuardrails
    visibility: AgentVisibility = Field(default_factory=AgentVisibility)
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# API request / response wrappers. CRUD router consumes these.
# ---------------------------------------------------------------------------

class AgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: AgentManifest


class AgentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: AgentManifest


class AgentResponse(BaseModel):
    """Row as returned by the CRUD API. version increments on every publish."""
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    tenant_id: str
    version: int
    is_active: bool
    status: str  # draft | published | retired
    manifest: AgentManifest
    manifest_hash: str  # sha256 of manifest_json — used for version pinning
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agents: list[AgentResponse]
    total: int
