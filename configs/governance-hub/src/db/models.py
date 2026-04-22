from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "governance_schema_versions"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False, unique=True)
    description = Column(Text, nullable=False)
    applied_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    applied_by = Column(String(255), default="system")


class ChangeProposal(Base):
    __tablename__ = "governance_changes"

    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)  # keyword, policy, budget, model, config, framework
    proposed_changes = Column(JSONB, nullable=False)
    impact_assessment = Column(Text)
    proposed_by = Column(String(255), nullable=False)
    proposed_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    status = Column(String(50), default="pending")  # pending, approved, rejected, implemented
    source = Column(String(50), default="human")  # human, ai_advisor
    ai_rationale = Column(Text)
    reviewed_by = Column(String(255))
    reviewed_at = Column(DateTime(timezone=True))
    review_notes = Column(Text)
    framework_version = Column(Integer)
    implemented_at = Column(DateTime(timezone=True))


class ConfigSnapshot(Base):
    __tablename__ = "governance_config_snapshots"

    id = Column(Integer, primary_key=True)
    instance_id = Column(String(255), nullable=False)
    schema_version = Column(Integer, nullable=False)
    config_json = Column(JSONB, nullable=False)
    diff_from_previous = Column(JSONB)
    snapshot_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    created_by = Column(String(255), default="system")


class FrameworkVersion(Base):
    __tablename__ = "governance_framework_versions"

    version = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    changes_summary = Column(Text)
    effective_date = Column(DateTime(timezone=True), nullable=False)
    approved_by = Column(String(255))
    config_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class SyncLog(Base):
    __tablename__ = "governance_sync_log"

    id = Column(Integer, primary_key=True)
    sync_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    status = Column(String(50), nullable=False)  # success, error
    records_exported = Column(Integer, default=0)
    central_db_type = Column(String(50))
    error_message = Column(Text)
    duration_ms = Column(Integer)


class TelemetryExport(Base):
    """Stored in the CENTRAL database."""
    __tablename__ = "governance_telemetry"

    id = Column(Integer, primary_key=True)
    instance_id = Column(String(255), nullable=False)
    instance_name = Column(String(255))
    schema_version = Column(Integer, nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    total_requests = Column(Integer)
    total_spend = Column(Numeric(12, 4))
    unique_users = Column(Integer)
    dlp_blocks = Column(Integer)
    error_count = Column(Integer)
    keyword_flags_critical = Column(Integer)
    keyword_flags_high = Column(Integer)
    compliance_score = Column(Numeric(5, 2))
    industry = Column(String(100))
    governance_tier = Column(String(50))
    metrics_json = Column(JSONB)
    synced_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class InstanceRegistry(Base):
    """Stored in the CENTRAL database."""
    __tablename__ = "governance_instances"

    instance_id = Column(String(255), primary_key=True)
    instance_name = Column(String(255), nullable=False)
    industry = Column(String(100))
    governance_tier = Column(String(50))
    data_classification = Column(String(50))
    schema_version = Column(Integer)
    config_version = Column(Integer)
    last_sync_at = Column(DateTime(timezone=True))
    status = Column(String(50), default="active")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class AuditChainEntry(Base):
    """Hash-chained audit trail — each entry links to the previous via SHA-256."""
    __tablename__ = "governance_audit_chain"

    id = Column(Integer, primary_key=True)
    sequence = Column(Integer, nullable=False, unique=True)
    event_type = Column(String(100), nullable=False)  # sync_export, change_proposed, change_approved, etc.
    event_id = Column(Integer)  # FK to source record
    payload_hash = Column(String(64), nullable=False)  # SHA-256 of the event payload
    previous_hash = Column(String(64), nullable=False)  # chain_hash of the previous entry
    chain_hash = Column(String(64), nullable=False)  # SHA-256(sequence + event_type + payload_hash + previous_hash)
    instance_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class AuditChainCheckpoint(Base):
    """Periodic root hash checkpoints for efficient verification."""
    __tablename__ = "governance_audit_checkpoints"

    id = Column(Integer, primary_key=True)
    sequence_from = Column(Integer, nullable=False)
    sequence_to = Column(Integer, nullable=False)
    root_hash = Column(String(64), nullable=False)
    entry_count = Column(Integer, nullable=False)
    verified = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class PolicyAuditLog(Base):
    """Audit log for OPA policy decisions and obligation execution."""
    __tablename__ = "governance_policy_audit_log"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(100), nullable=False)
    severity = Column(String(50), default="info")
    user_id = Column(String(255))
    details = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class BreakGlassLog(Base):
    """Emergency break-glass access records."""
    __tablename__ = "governance_break_glass_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    reason = Column(Text, nullable=False)
    data_classification = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class UserAttestation(Base):
    """User attestation records for policy obligations."""
    __tablename__ = "governance_user_attestations"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    action_type = Column(String(255), nullable=False)
    attestation_text = Column(Text)
    attested_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))


class ReviewQueueItem(Base):
    """Requests queued for supervisor review by policy obligations."""
    __tablename__ = "governance_review_queue"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    review_type = Column(String(100))
    regulation = Column(String(100))
    request_summary = Column(Text)
    status = Column(String(50), default="pending")  # pending, approved, rejected
    reviewer_id = Column(String(255))
    reviewed_at = Column(DateTime(timezone=True))
    review_notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class DataConnector(Base):
    """Registered external data source for cross-referencing."""
    __tablename__ = "governance_data_connectors"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    connector_type = Column(String(50), nullable=False)  # postgresql, mysql, mssql, rest_api, s3, smb, sharepoint
    description = Column(Text)
    connection_config = Column(JSONB, nullable=False)  # encrypted at rest via app layer
    data_classification = Column(String(50), default="internal")  # public, internal, confidential, restricted
    enabled = Column(Boolean, default=True)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    last_tested_at = Column(DateTime(timezone=True))
    last_test_status = Column(String(50))  # success, error


class ConnectorAccessRule(Base):
    """Team/user-based access control for data connectors."""
    __tablename__ = "governance_connector_access"

    id = Column(Integer, primary_key=True)
    connector_id = Column(Integer, nullable=False)
    grant_type = Column(String(50), nullable=False)  # team, user, role
    grant_value = Column(String(255), nullable=False)  # team name, username, or role
    permission = Column(String(50), nullable=False, default="read")  # read, write, admin
    row_filter = Column(Text)  # optional SQL WHERE clause or API filter expression
    field_mask = Column(JSONB)  # optional list of allowed/denied fields
    granted_by = Column(String(255), nullable=False)
    granted_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True))  # optional TTL


class ConnectorQueryLog(Base):
    """Audit log for all data connector queries."""
    __tablename__ = "governance_connector_queries"

    id = Column(Integer, primary_key=True)
    connector_id = Column(Integer, nullable=False)
    connector_name = Column(String(255))
    queried_by = Column(String(255), nullable=False)
    query_type = Column(String(50))  # sql, api_call, file_list, search
    query_text = Column(Text)  # the actual query (redacted if sensitive)
    row_count = Column(Integer)
    duration_ms = Column(Integer)
    status = Column(String(50))  # success, denied, error
    error_message = Column(Text)
    queried_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# =========================================================================
# Settings Overrides — DB-backed config (replaces .env file approach)
# =========================================================================

class SettingsOverride(Base):
    """Runtime configuration overrides stored in DB instead of .env files."""
    __tablename__ = "governance_settings_overrides"

    id = Column(Integer, primary_key=True)
    key = Column(String(255), nullable=False, unique=True)  # e.g., "central_db_host"
    value = Column(Text, nullable=False)
    updated_by = Column(String(255), default="system")
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# =========================================================================
# Framework Sections & Compliance Tracking
# =========================================================================

class FrameworkSection(Base):
    """Parsed sections from the AI Governance Framework document."""
    __tablename__ = "governance_framework_sections"

    id = Column(Integer, primary_key=True)
    section_number = Column(String(30), nullable=False)  # "1", "4.2", "12.3"
    title = Column(String(500), nullable=False)
    parent_section = Column(String(30))  # null for top-level
    content_markdown = Column(Text, nullable=False)
    compliance_type = Column(String(50), nullable=False)  # automated, manual_attestation, informational
    automated_check_key = Column(String(100))  # maps to a check function
    framework_version = Column(Integer, default=1)
    sort_order = Column(Integer, default=0)


class ComplianceStatus(Base):
    """Per-section compliance status from automated checks or attestations."""
    __tablename__ = "governance_compliance_status"

    id = Column(Integer, primary_key=True)
    section_id = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False)  # compliant, non_compliant, partial, not_assessed, check_failed
    evidence_type = Column(String(50))  # automated_check, manual_attestation, external_audit
    evidence_details = Column(JSONB)
    assessed_by = Column(String(255), default="system")
    assessed_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True))  # attestations expire
    notes = Column(Text)


class DeploymentTfvars(Base):
    """Encrypted deployment terraform.tfvars — stored for clone/restore."""
    __tablename__ = "governance_deployment_tfvars"

    id = Column(Integer, primary_key=True)
    instance_id = Column(String(255), nullable=False)
    platform_version = Column(String(20))
    encrypted_tfvars = Column(Text, nullable=False)  # AES-256-GCM encrypted, base64
    encryption_iv = Column(String(48))  # Base64 IV for AES-GCM
    deployed_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class SystemPrompt(Base):
    """Governance-managed system meta-prompts injected into every LLM call."""
    __tablename__ = "governance_system_prompts"

    id = Column(Integer, primary_key=True)
    tier = Column(String(20), nullable=False)  # tier1, tier2, tier3
    prompt_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    created_by = Column(String(255), default="system")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    activated_at = Column(DateTime(timezone=True))


class ComplianceAttestation(Base):
    """Manual attestation records for non-automated framework sections."""
    __tablename__ = "governance_compliance_attestations"

    id = Column(Integer, primary_key=True)
    section_id = Column(Integer, nullable=False)
    attester_name = Column(String(255), nullable=False)
    attester_email = Column(String(255), nullable=False)
    attester_role = Column(String(100))
    attestation_text = Column(Text, nullable=False)
    status = Column(String(50), default="active")  # active, expired, revoked
    attested_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True))


class SharedSkill(Base):
    """Organizational AI skill — a named prompt/model configuration that
    appears in employee-facing surfaces (Open WebUI, browser extension) as
    a pre-configured persona or workflow. Managed centrally by governance
    admins, gated by AD group membership."""

    __tablename__ = "governance_shared_skills"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), nullable=False, unique=True)  # url-safe id
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    system_prompt = Column(Text, nullable=False)
    base_model = Column(String(100), nullable=False, default="claude-sonnet")
    temperature = Column(Numeric(3, 2), nullable=False, default=0.7)
    # Null/empty = visible to everyone. Otherwise: list of AD CN values —
    # a user with any matching group (case-insensitive) can see this skill.
    group_allowlist = Column(JSONB, nullable=False, default=list)
    tags = Column(JSONB, nullable=False, default=list)  # for filtering in UI
    tool_allowlist = Column(JSONB, nullable=False, default=list)  # OWUI tools
    is_published = Column(Boolean, default=False)  # gate Open WebUI sync
    created_by = Column(String(255), nullable=False, default="system")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


# ----- Vendor Management -------------------------------------------------------
# A curated, values-aligned vendor directory. Default policy: every vendor in
# the catalog must contribute to FOSS and/or recognized standards. Each
# qualifying contribution becomes a ContributionType-tied star on the vendor.
# Users can tag personal favorites, separate from the company-managed list.

class Vendor(Base):
    __tablename__ = "governance_vendors"
    id = Column(Integer, primary_key=True)
    slug = Column(String(100), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    website_url = Column(String(500), nullable=False, default="")
    category = Column(String(100), nullable=False, default="")  # database, model, monitoring, etc.
    is_active = Column(Boolean, default=True)
    # Cached for sort/index performance. Kept in sync via VendorContribution
    # insert/delete; refresh helper in the service layer.
    total_stars = Column(Integer, default=0, nullable=False)
    created_by = Column(String(255), nullable=False, default="system")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class ContributionType(Base):
    """A class of qualifying contribution. Editable by admins so the
    organization can extend or refine the criteria over time without
    code changes."""
    __tablename__ = "governance_contribution_types"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=False, unique=True)  # OSS_PROJECT, STANDARDS_BODY, ...
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    points = Column(Integer, default=1, nullable=False)  # most contributions = 1 star
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=100)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class VendorContribution(Base):
    """One award of a ContributionType to a Vendor. Includes evidence so the
    star isn't a bare assertion — anyone can audit the basis."""
    __tablename__ = "governance_vendor_contributions"
    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, nullable=False, index=True)
    contribution_type_id = Column(Integer, nullable=False)
    evidence_url = Column(String(500), nullable=False, default="")
    evidence_description = Column(Text, nullable=False, default="")
    awarded_by = Column(String(255), nullable=False, default="system")
    awarded_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class VendorFavorite(Base):
    """Per-user favorite. Personal, never affects total_stars or the
    company-curated list."""
    __tablename__ = "governance_vendor_favorites"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    vendor_id = Column(Integer, nullable=False, index=True)
    tag = Column(String(100), default="")  # optional user-applied tag
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class FleetCapability(Base):
    """Fleet capability registry. Each Gov-Hub publishes its own capabilities
    on startup and every 60s. Peers read via /api/v1/fleet/capabilities to
    discover which instance provides which service (used for smart module
    deferral and edge routing)."""
    __tablename__ = "governance_fleet_capabilities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(String(255), nullable=False, index=True)
    capability = Column(String(100), nullable=False)          # litellm | open-webui | grafana | loki | guacamole | governance-hub
    endpoint = Column(String(500), nullable=False)            # http://insidellm-01:4000
    role = Column(String(50), default="")                     # vm_role
    status = Column(String(20), default="live")               # live | degraded | down
    capability_metadata = Column("metadata", JSONB, default=dict)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("instance_id", "capability", name="uq_instance_capability"),
        Index("ix_fleet_capability_status", "status"),
    )


class Agent(Base):
    """Declarative agent record. One row per (tenant_id, agent_id). Each
    publish event bumps version + re-hashes the manifest. Audit-chain
    entries emitted on create/update/publish/retire.

    Lifecycle:
      status = draft      — authored, not yet invocable
      status = published  — live; is_active=True governs OWUI visibility
      status = retired    — hidden from picker; history preserved
    """
    __tablename__ = "governance_agents"

    # Composite identity: tenant_id + agent_id is the natural unique key.
    # Row id is an opaque surrogate for FK convenience.
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(128), nullable=False, index=True)
    tenant_id = Column(String(128), nullable=False, index=True)

    # Display
    name = Column(String(255), nullable=False)
    description = Column(Text)
    icon = Column(String(500))
    team = Column(String(128), index=True)
    created_by = Column(String(255))

    # The full manifest, stored verbatim as JSONB for auditability +
    # cheap version diffs. Pydantic validates on write.
    manifest_json = Column("manifest", JSONB, nullable=False, default=dict)
    manifest_schema_version = Column(String(16), default="1.1")

    # Derived / indexable slices of the manifest kept in columns so
    # filtering does not require scanning JSONB blobs.
    guardrail_profile = Column(String(64), index=True)
    visibility_scope = Column(String(32), default="private", index=True)  # private | team | org | fleet
    data_classification = Column(String(32), default="internal")

    # Lifecycle
    status = Column(String(20), default="draft", index=True)  # draft | published | retired
    is_active = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    manifest_hash = Column(String(64))  # SHA-256 of manifest_json — pinned across versions

    # Pending approval lifecycle (set when visibility ≥ org publishes).
    pending_change_id = Column(Integer, index=True)  # FK to governance_changes

    # Runtime binding — populated by the manifest→runtime translator (P1.2)
    # after a successful provision. Deprovision nulls these back out.
    # We never persist the plaintext LiteLLM key; last4 is kept for display.
    litellm_key_alias = Column(String(255))          # deterministic alias used for update/delete
    litellm_key_last4 = Column(String(4))            # UI display only
    owui_model_id = Column(String(255))              # "insidellm-agent-<tenant>-<agent>"
    runtime_sync_state = Column(String(32), default="unprovisioned")
    # unprovisioned | provisioning | provisioned | partial | failed | deprovisioned
    runtime_sync_error = Column(Text)
    runtime_synced_at = Column(DateTime(timezone=True))
    runtime_manifest_hash = Column(String(64))       # hash that was provisioned — diff detector

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", name="uq_agent_tenant_agent_id"),
        Index("ix_agent_tenant_status", "tenant_id", "status"),
    )


class ActionCatalog(Base):
    """Registered catalog action. One row per (tenant_id, action_id).

    Actions are the verbs an agent's manifest can reference by action_id.
    The runtime (P1.2 translator + P2 orchestrator) looks up the row,
    validates guardrail tier + data classes against the calling agent,
    and dispatches to the backend recorded here.

    tenant_id == "core" means shared across every tenant; tenant-scoped
    entries take precedence when both exist with the same action_id.
    """
    __tablename__ = "governance_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(String(64), nullable=False, index=True)
    tenant_id = Column(String(128), nullable=False, default="core", index=True)

    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(32), default="other", index=True)

    # Full v1.0 entry stored verbatim; derived indexable columns below.
    entry_json = Column("entry", JSONB, nullable=False, default=dict)
    schema_version = Column(String(16), default="1.0")

    # Derived columns for fast filtering without scanning JSONB.
    backend_type = Column(String(32), index=True)           # fastapi_http | celery_task | ...
    minimum_guardrail_tier = Column(String(64), index=True)
    requires_approval = Column(Boolean, default=False)
    deprecated = Column(Boolean, default=False, index=True)
    version = Column(String(16), default="1.0.0")
    maintainer = Column(String(128))

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "action_id", name="uq_action_tenant_action_id"),
        Index("ix_action_tenant_backend", "tenant_id", "backend_type"),
    )


# =============================================================================
# ReportUp — opt-in governance-data sharing with a named parent organization.
# Per-tenant configuration + per-run audit log + compliance-officer attestation.
# Canonical spec: docs/ReportUp-Governance.md
# =============================================================================


class ReportUpConfig(Base):
    """Single-row config (one per instance). Holds who we're sharing with,
    how often, and what categories. HMAC secret kept separately in the
    settings_overrides table (never returned from the API)."""
    __tablename__ = "governance_reportup_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    enabled = Column(Boolean, default=False, nullable=False)

    # Identity of the parent organization this instance reports to.
    parent_name = Column(String(255))                    # e.g. "Clarion Capital Partners"
    parent_endpoint = Column(String(500))                # HTTPS ingest URL
    parent_public_key_pem = Column(Text)                 # optional — if set, encrypt payloads

    # What to share — each flag independently toggleable.
    share_audit_chain = Column(Boolean, default=True)
    share_telemetry = Column(Boolean, default=True)
    share_agents = Column(Boolean, default=False)
    share_identity = Column(Boolean, default=False)
    share_policies = Column(Boolean, default=False)
    share_change_proposals = Column(Boolean, default=False)

    # Cadence + size guardrails.
    schedule_cron = Column(String(64), default="0 2 * * *")  # nightly 02:00
    max_records_per_run = Column(Integer, default=10000)

    # Chain-of-custody pointer: highest audit_chain sequence already shipped.
    # Next run resumes at sequence > last_shipped_sequence.
    last_shipped_sequence = Column(Integer, default=0)

    # Hash of the last envelope we sent — parent uses this to verify no
    # envelopes were dropped between runs. Copied into every new envelope
    # as previous_envelope_hash.
    last_envelope_hash = Column(String(64))

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(255))


class ReportUpAttestation(Base):
    """Every config change (enable, change parent, change scope) requires a
    named compliance officer's attestation. Stored append-only; audit chain
    appends an event for every insert so the chain itself records consent."""
    __tablename__ = "governance_reportup_attestations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attested_by = Column(String(255), nullable=False)       # email
    attested_role = Column(String(100))                      # "Compliance Officer", "CTO"
    attestation_text = Column(Text, nullable=False)          # full consent text signed
    config_snapshot_json = Column("config_snapshot", JSONB, nullable=False, default=dict)
    config_snapshot_sha = Column(String(64), nullable=False) # SHA-256 of snapshot
    attested_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_reportup_attestations_attested_at", "attested_at"),
    )


class ReportUpLog(Base):
    """One row per sync run. Records what we shipped, parent's ACK, and any error."""
    __tablename__ = "governance_reportup_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime(timezone=True))
    status = Column(String(32), default="running", index=True)   # running | success | error | parent_rejected

    # Envelope identity.
    envelope_hash = Column(String(64))                   # SHA-256 of this run's payload
    previous_envelope_hash = Column(String(64))          # SHA of the envelope before this — continuity proof
    sequence_from = Column(Integer)                      # audit_chain sequence start
    sequence_to = Column(Integer)                        # audit_chain sequence end inclusive

    # What was shipped (counts per category).
    audit_entries_shipped = Column(Integer, default=0)
    telemetry_rows_shipped = Column(Integer, default=0)
    agents_shipped = Column(Integer, default=0)
    identity_rows_shipped = Column(Integer, default=0)

    # Parent's acknowledgement — we record their response verbatim.
    parent_ack_status = Column(String(32))               # accepted | rejected | no_response
    parent_ack_payload_json = Column("parent_ack_payload", JSONB)
    parent_http_status = Column(Integer)
    duration_ms = Column(Integer)
    error_message = Column(Text)

    __table_args__ = (
        Index("ix_reportup_log_started", "started_at"),
        Index("ix_reportup_log_status", "status"),
    )
