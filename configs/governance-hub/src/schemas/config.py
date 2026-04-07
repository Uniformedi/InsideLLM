from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SnapshotCreate(BaseModel):
    created_by: str = "system"


class SnapshotResponse(BaseModel):
    id: int
    instance_id: str
    schema_version: int
    config_json: dict[str, Any]
    diff_from_previous: dict[str, Any] | None
    snapshot_at: datetime
    created_by: str

    model_config = {"from_attributes": True}


class SnapshotListEntry(BaseModel):
    id: int
    schema_version: int
    snapshot_at: datetime
    created_by: str

    model_config = {"from_attributes": True}


class ConfigDiff(BaseModel):
    snapshot_a_id: int
    snapshot_b_id: int
    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, Any]
