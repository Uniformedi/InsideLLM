from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChangeCreate(BaseModel):
    title: str = Field(..., max_length=500)
    description: str
    category: str = Field(..., pattern="^(keyword|policy|budget|model|config|framework)$")
    proposed_changes: dict[str, Any]
    impact_assessment: str | None = None
    proposed_by: str
    source: str = Field(default="human", pattern="^(human|ai_advisor)$")
    ai_rationale: str | None = None


class ApprovalRequest(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected|deferred)$")
    reviewer_name: str
    reviewer_email: str
    comments: str | None = None


class ImplementRequest(BaseModel):
    implemented_by: str
    version_title: str
    version_description: str | None = None


class ChangeResponse(BaseModel):
    id: int
    title: str
    description: str
    category: str
    proposed_changes: dict[str, Any]
    impact_assessment: str | None
    proposed_by: str
    proposed_at: datetime
    status: str
    source: str
    ai_rationale: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    framework_version: int | None
    implemented_at: datetime | None

    model_config = {"from_attributes": True}


class ChangeListFilter(BaseModel):
    status: str | None = None
    category: str | None = None
    source: str | None = None
    limit: int = Field(default=50, le=200)
    offset: int = 0
