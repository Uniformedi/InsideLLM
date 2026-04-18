-- =============================================================================
-- Central DB Schema for InsideLLM Fleet Management
-- Run this on your central PostgreSQL/MariaDB/MSSQL database before first sync.
-- =============================================================================

-- Instance registry
CREATE TABLE IF NOT EXISTS governance_instances (
    instance_id VARCHAR(255) PRIMARY KEY,
    instance_name VARCHAR(255) NOT NULL,
    industry VARCHAR(100),
    governance_tier VARCHAR(50),
    data_classification VARCHAR(50),
    schema_version INTEGER,
    config_version INTEGER,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Telemetry exports (one per sync per instance)
CREATE TABLE IF NOT EXISTS governance_telemetry (
    id SERIAL PRIMARY KEY,
    instance_id VARCHAR(255) NOT NULL REFERENCES governance_instances(instance_id),
    instance_name VARCHAR(255),
    schema_version INTEGER NOT NULL,
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    total_requests INTEGER,
    total_spend NUMERIC(12, 4),
    unique_users INTEGER,
    dlp_blocks INTEGER,
    error_count INTEGER,
    keyword_flags_critical INTEGER,
    keyword_flags_high INTEGER,
    compliance_score NUMERIC(5, 2),
    industry VARCHAR(100),
    governance_tier VARCHAR(50),
    metrics_json JSONB,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telemetry_instance_sync
    ON governance_telemetry (instance_id, synced_at DESC);

-- Config snapshots (synced from each instance)
CREATE TABLE IF NOT EXISTS governance_config_snapshots (
    id INTEGER NOT NULL,
    instance_id VARCHAR(255) NOT NULL REFERENCES governance_instances(instance_id),
    schema_version INTEGER NOT NULL,
    config_json JSONB NOT NULL,
    diff_from_previous JSONB,
    snapshot_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255) DEFAULT 'system',
    PRIMARY KEY (id, instance_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_instance_time
    ON governance_config_snapshots (instance_id, snapshot_at DESC);

-- Change proposals (optionally synced from instances)
CREATE TABLE IF NOT EXISTS governance_changes (
    id SERIAL PRIMARY KEY,
    instance_id VARCHAR(255) REFERENCES governance_instances(instance_id),
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(100) NOT NULL,
    proposed_changes JSONB NOT NULL,
    impact_assessment TEXT,
    proposed_by VARCHAR(255) NOT NULL,
    proposed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'pending',
    source VARCHAR(50) DEFAULT 'human',
    ai_rationale TEXT,
    reviewed_by VARCHAR(255),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    review_notes TEXT,
    framework_version INTEGER,
    implemented_at TIMESTAMP WITH TIME ZONE
);

-- Audit chain entries (synced from instances for central verification)
CREATE TABLE IF NOT EXISTS governance_audit_chain (
    id SERIAL PRIMARY KEY,
    sequence INTEGER NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_id INTEGER,
    payload_hash VARCHAR(64) NOT NULL,
    previous_hash VARCHAR(64) NOT NULL,
    chain_hash VARCHAR(64) NOT NULL,
    instance_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (instance_id, sequence)
);

-- Governance framework source document (uploaded by an admin via
-- /governance/framework → Upload. One row per version; Governance Hub
-- reads the latest by version DESC on seed. Fleet-wide so every instance
-- sees the same authoritative markdown without local distribution.)
CREATE TABLE IF NOT EXISTS governance_framework_documents (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    content TEXT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    filename VARCHAR(255),
    note TEXT,
    uploaded_by VARCHAR(255) NOT NULL DEFAULT 'admin',
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    uploaded_from_instance VARCHAR(255)
);

-- =============================================================================
-- Keycloak identity replication (Phase 2 of local-Keycloak + central-DB)
--
-- Each InsideLLM VM runs its own Keycloak against local Postgres. This gov-hub
-- sync job pulls realm/groups/users via Keycloak's Admin REST API and mirrors
-- them up here so the fleet-wide identity view stays central while auth stays
-- fast per-VM. Tables are (instance_id, realm_name, keycloak_<entity>_id) —
-- the same username on two VMs correctly produces two rows.
-- =============================================================================

CREATE TABLE IF NOT EXISTS governance_identity_realms (
    instance_id VARCHAR(255) NOT NULL,
    realm_name VARCHAR(128) NOT NULL,
    display_name VARCHAR(255),
    enabled BOOLEAN DEFAULT TRUE,
    realm_json JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (instance_id, realm_name)
);

CREATE TABLE IF NOT EXISTS governance_identity_users (
    instance_id VARCHAR(255) NOT NULL,
    realm_name VARCHAR(128) NOT NULL,
    keycloak_user_id VARCHAR(64) NOT NULL,
    username VARCHAR(255) NOT NULL,
    email VARCHAR(320),
    first_name VARCHAR(128),
    last_name VARCHAR(128),
    enabled BOOLEAN DEFAULT TRUE,
    email_verified BOOLEAN DEFAULT FALSE,
    groups_csv TEXT,                            -- /InsideLLM-Admin,/InsideLLM-View
    realm_roles_csv TEXT,                       -- admin,view,approve
    attributes_json JSONB,
    created_at_kc TIMESTAMP WITH TIME ZONE,     -- Keycloak's createdTimestamp
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (instance_id, realm_name, keycloak_user_id)
);

CREATE INDEX IF NOT EXISTS idx_identity_users_email
    ON governance_identity_users (email);
CREATE INDEX IF NOT EXISTS idx_identity_users_username_instance
    ON governance_identity_users (username, instance_id);

CREATE TABLE IF NOT EXISTS governance_identity_groups (
    instance_id VARCHAR(255) NOT NULL,
    realm_name VARCHAR(128) NOT NULL,
    keycloak_group_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    path VARCHAR(500),                          -- /InsideLLM-Admin
    parent_group_id VARCHAR(64),
    attributes_json JSONB,
    realm_roles_csv TEXT,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (instance_id, realm_name, keycloak_group_id)
);

CREATE INDEX IF NOT EXISTS idx_identity_groups_path
    ON governance_identity_groups (instance_id, realm_name, path);

CREATE TABLE IF NOT EXISTS governance_identity_sync_log (
    id SERIAL PRIMARY KEY,
    instance_id VARCHAR(255) NOT NULL,
    realm_name VARCHAR(128) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(32) DEFAULT 'running',       -- running | success | error
    users_synced INTEGER DEFAULT 0,
    groups_synced INTEGER DEFAULT 0,
    duration_ms INTEGER,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_identity_sync_log_instance_time
    ON governance_identity_sync_log (instance_id, started_at DESC);
