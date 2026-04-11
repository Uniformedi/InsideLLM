from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text
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
