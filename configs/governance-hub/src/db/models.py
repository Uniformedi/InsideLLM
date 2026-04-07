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
