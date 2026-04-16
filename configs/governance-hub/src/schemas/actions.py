"""Pydantic models for the InsideLLM action catalog (v1.0).

Polyglot backends: FastAPI HTTP, Celery task, n8n webhook, Activepieces
trigger, MCP tool. An agent manifest names an action_id; this registry
record tells the runtime how to invoke it. Agents never see the backend.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

CATALOG_SCHEMA_VERSION = "1.0"

_ACTION_ID_PATTERN = r"^[a-z][a-z0-9_]{2,63}$"


class ActionCategory(str, Enum):
    LOOKUP    = "lookup"
    DRAFT     = "draft"
    SEND      = "send"
    SCHEDULE  = "schedule"
    CLASSIFY  = "classify"
    TRANSFORM = "transform"
    RETRIEVE  = "retrieve"
    NOTIFY    = "notify"
    WORKFLOW  = "workflow"
    OTHER     = "other"


class DataClass(str, Enum):
    PII         = "pii"
    PHI         = "phi"
    FINANCIAL   = "financial"
    CREDENTIALS = "credentials"
    PUBLIC      = "public"


class MinimumGuardrailTier(str, Enum):
    UNRESTRICTED     = "tier_unrestricted"
    GENERAL_BUSINESS = "tier_general_business"
    FINANCIAL        = "tier_financial_regulated"
    FDCPA            = "tier_fdcpa_regulated"
    HIPAA            = "tier_hipaa_regulated"


class ParamType(str, Enum):
    STRING  = "string"
    INTEGER = "integer"
    NUMBER  = "number"
    BOOLEAN = "boolean"
    OBJECT  = "object"
    ARRAY   = "array"


class InputParam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ParamType
    required: bool = False
    description: str | None = None
    enum: list[str | int | float] | None = None
    pattern: str | None = None
    default: Any = None


class OutputParam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ParamType
    description: str | None = None


# --- Backend discriminated union -------------------------------------------

class FastAPIBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["fastapi_http"]
    url: HttpUrl
    method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
    timeout_ms: int = Field(default=10000, ge=100, le=30000)


class CeleryBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["celery_task"]
    task: str
    queue: str = "default"
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    retries: int = Field(default=0, ge=0, le=5)


class N8nBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["n8n_webhook"]
    webhook_url: HttpUrl
    hmac_secret_env: str | None = None


class ActivepiecesBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["activepieces_trigger"]
    trigger_url: HttpUrl
    hmac_secret_env: str | None = None


class MCPBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["mcp_tool"]
    server: str
    tool_name: str


ActionBackend = Annotated[
    Union[FastAPIBackend, CeleryBackend, N8nBackend, ActivepiecesBackend, MCPBackend],
    Field(discriminator="type"),
]


class GuardrailRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_guardrail_tier: MinimumGuardrailTier
    data_classes: list[DataClass] = Field(default_factory=list)
    requires_approval: bool = False


class AuditPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    log_inputs: bool = True
    log_outputs: bool = True
    redact_fields: list[str] = Field(default_factory=list)


class RateLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    per_minute: int | None = Field(default=None, ge=1)
    per_day: int | None = Field(default=None, ge=1)


class ActionCatalogEntry(BaseModel):
    """Full registration record for one action in the catalog."""
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    schema_version: str = Field(default=CATALOG_SCHEMA_VERSION, pattern=r"^1\.0$")
    action_id: str = Field(pattern=_ACTION_ID_PATTERN)
    tenant_id: str | None = None  # None or "core" = shared across all tenants

    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    category: ActionCategory = ActionCategory.OTHER

    backend: ActionBackend
    inputs: dict[str, InputParam] = Field(default_factory=dict)
    outputs: dict[str, OutputParam] = Field(default_factory=dict)

    guardrail_requirements: GuardrailRequirements
    audit: AuditPolicy = Field(default_factory=AuditPolicy)
    rate_limit: RateLimit = Field(default_factory=RateLimit)

    maintainer: str | None = None
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    deprecated: bool = False
