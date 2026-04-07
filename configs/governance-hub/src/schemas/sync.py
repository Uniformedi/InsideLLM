from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TelemetrySummary(BaseModel):
    total_requests: int = 0
    total_spend: float = 0.0
    unique_users: int = 0
    dlp_blocks: int = 0
    error_count: int = 0
    keyword_flags_critical: int = 0
    keyword_flags_high: int = 0
    compliance_score: float = 0.0
    top_models: dict[str, int] = {}
    top_keywords: dict[str, int] = {}
    team_spend: dict[str, float] = {}


class SyncExportEnvelope(BaseModel):
    instance_id: str
    instance_name: str
    schema_version: int
    industry: str
    governance_tier: str
    exported_at: datetime
    period_start: datetime
    period_end: datetime
    telemetry: TelemetrySummary
    config_snapshot: dict[str, Any] | None = None


class SyncStatus(BaseModel):
    last_sync_at: datetime | None
    last_status: str | None
    records_exported: int = 0
    central_db_connected: bool = False
    next_sync_at: datetime | None = None


class SyncHistoryEntry(BaseModel):
    id: int
    sync_at: datetime
    status: str
    records_exported: int
    duration_ms: int | None
    error_message: str | None

    model_config = {"from_attributes": True}
