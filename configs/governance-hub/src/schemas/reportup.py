"""Pydantic request/response models for the ReportUp governance-data
sharing feature.

ReportUp lets a tenant explicitly opt in to forward its governance data
(audit chain, telemetry, agents, identity roster, policy proposals) to a
named parent organization. Every config mutation is attested — the
compliance officer signs the scope + parent identity, and the
attestation itself gets appended to the audit chain.

Canonical spec: docs/ReportUp-Governance.md
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

REPORTUP_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Config — the "who/what/when" of the share
# ---------------------------------------------------------------------------


class ReportUpConfigRequest(BaseModel):
    """Operator-supplied config. All fields optional — PUT merges onto
    the existing single-row config. enabled=false disables sharing
    without losing the rest of the config."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    parent_name: str | None = Field(None, min_length=1, max_length=255)
    # HttpUrl pulls in the `email-validator`/`pydantic-extra-types` extras
    # which aren't in the gov-hub image. Enforce with a plain URL regex.
    parent_endpoint: str | None = Field(None, pattern=r"^https?://")
    parent_public_key_pem: str | None = None

    # What to share — each flag independently toggleable.
    share_audit_chain: bool | None = None
    share_telemetry: bool | None = None
    share_agents: bool | None = None
    share_identity: bool | None = None
    share_policies: bool | None = None
    share_change_proposals: bool | None = None

    # Cadence + size guardrails.
    schedule_cron: str | None = Field(None, min_length=5, max_length=64)
    max_records_per_run: int | None = Field(None, ge=100, le=1_000_000)

    @field_validator("parent_public_key_pem")
    @classmethod
    def _validate_pem(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if "-----BEGIN" not in v or "-----END" not in v:
            raise ValueError("parent_public_key_pem must be a PEM-encoded block")
        return v


class ReportUpConfigResponse(BaseModel):
    """What the API returns — never includes the HMAC secret itself."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    parent_name: str | None
    parent_endpoint: str | None
    parent_public_key_present: bool
    share_audit_chain: bool
    share_telemetry: bool
    share_agents: bool
    share_identity: bool
    share_policies: bool
    share_change_proposals: bool
    schedule_cron: str
    max_records_per_run: int
    last_shipped_sequence: int
    last_envelope_hash: str | None
    updated_at: datetime | None
    updated_by: str | None


# ---------------------------------------------------------------------------
# Attestation — compliance officer's signed consent
# ---------------------------------------------------------------------------


class AttestationRequest(BaseModel):
    """An attestation is required BEFORE enabled flips to true, AND
    whenever the parent identity or scope changes. It's append-only."""
    model_config = ConfigDict(extra="forbid")

    attested_by: str = Field(..., min_length=3, max_length=255)
    attested_role: str = Field("Compliance Officer", max_length=100)
    attestation_text: str = Field(..., min_length=30, max_length=4000)


class AttestationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    attested_by: str
    attested_role: str | None
    attestation_text: str
    config_snapshot: dict[str, Any]
    config_snapshot_sha: str
    attested_at: datetime


class AttestationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attestations: list[AttestationResponse]
    total: int


# ---------------------------------------------------------------------------
# Sync run log
# ---------------------------------------------------------------------------


class ReportUpLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    started_at: datetime
    ended_at: datetime | None
    status: str
    envelope_hash: str | None
    previous_envelope_hash: str | None
    sequence_from: int | None
    sequence_to: int | None
    audit_entries_shipped: int
    telemetry_rows_shipped: int
    agents_shipped: int
    identity_rows_shipped: int
    parent_ack_status: str | None
    parent_http_status: int | None
    duration_ms: int | None
    error_message: str | None


class ReportUpLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[ReportUpLogEntry]
    total: int


# ---------------------------------------------------------------------------
# Dry-run preview
# ---------------------------------------------------------------------------


class PreviewResponse(BaseModel):
    """What the next real send WOULD ship. Never actually posts."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    parent_name: str | None
    parent_endpoint: str | None
    sequence_from: int
    would_ship: dict[str, int]  # {audit_entries: N, telemetry_rows: N, ...}
    envelope_hash_would_be: str
    previous_envelope_hash: str | None
    schema_version: str = REPORTUP_SCHEMA_VERSION
    generated_at: datetime


# ---------------------------------------------------------------------------
# Envelope — the actual wire format sent to the parent
# ---------------------------------------------------------------------------


class ReportUpEnvelope(BaseModel):
    """Canonical shape of what lands on the parent's ingest endpoint.

    Every field included in the HMAC signature computation. Parent
    verifies by recomputing the hash + checking the signature + checking
    that previous_envelope_hash matches the hash of the prior envelope
    they received (chain-of-custody continuity).
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REPORTUP_SCHEMA_VERSION
    tenant_id: str
    tenant_name: str | None
    parent_name: str
    generated_at: str                       # ISO-8601, UTC
    sequence_from: int
    sequence_to: int
    previous_envelope_hash: str | None
    # Payload — one key per category, only present if that category is enabled.
    audit_chain: list[dict[str, Any]] = Field(default_factory=list)
    telemetry: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[dict[str, Any]] = Field(default_factory=list)
    identity_users: list[dict[str, Any]] = Field(default_factory=list)
    identity_groups: list[dict[str, Any]] = Field(default_factory=list)
    change_proposals: list[dict[str, Any]] = Field(default_factory=list)
    # Hash + signature — filled at send time, NOT included in the hash input.
    envelope_hash: str = ""
    hmac_signature: str = ""
