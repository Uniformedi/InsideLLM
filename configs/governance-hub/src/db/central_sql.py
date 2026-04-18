"""
Dialect-specific SQL for the central fleet database.

All queries that touch the central DB (PostgreSQL, MariaDB, or MSSQL) are
defined here with dialect-specific variants. The active dialect is determined
from settings.central_db_type at import time.

Usage:
    from ..db.central_sql import SQL
    db.execute(text(SQL.upsert_instance), params)
"""

from ..config import settings


def _dialect() -> str:
    return settings.central_db_type  # postgresql, mariadb, mssql


class _PostgreSQL:
    """PostgreSQL dialect."""

    upsert_instance = """
        INSERT INTO governance_instances
            (instance_id, instance_name, industry, governance_tier, data_classification,
             schema_version, platform_version, last_sync_at, status)
        VALUES (:id, :name, :industry, :tier, :classification, :schema_version, :platform_version, NOW(), 'active')
        ON CONFLICT (instance_id) DO UPDATE SET
            instance_name = EXCLUDED.instance_name,
            schema_version = EXCLUDED.schema_version,
            platform_version = EXCLUDED.platform_version,
            last_sync_at = NOW()
    """

    insert_telemetry = """
        INSERT INTO governance_telemetry
            (instance_id, instance_name, schema_version, platform_version, period_start, period_end,
             total_requests, total_spend, unique_users, dlp_blocks, error_count,
             keyword_flags_critical, keyword_flags_high, compliance_score, industry, governance_tier, metrics_json)
        VALUES
            (:instance_id, :instance_name, :schema_version, :platform_version, :period_start, :period_end,
             :total_requests, :total_spend, :unique_users, :dlp_blocks, :error_count,
             :kw_critical, :kw_high, :compliance_score, :industry, :tier, :metrics)
    """

    upsert_snapshot = """
        INSERT INTO governance_config_snapshots
            (id, instance_id, schema_version, config_json, diff_from_previous, snapshot_at, created_by)
        VALUES (:id, :iid, :sv, :config::jsonb, :diff::jsonb, :snap_at, :created_by)
        ON CONFLICT (id, instance_id) DO UPDATE SET
            config_json = EXCLUDED.config_json,
            snapshot_at = EXCLUDED.snapshot_at
    """

    list_instances = """
        SELECT instance_id, instance_name, industry, governance_tier, data_classification,
               schema_version, platform_version, last_sync_at, status, created_at
        FROM governance_instances
        WHERE status = 'active'
        ORDER BY instance_name
    """

    latest_telemetry = """
        SELECT total_requests, total_spend, unique_users,
               compliance_score, keyword_flags_critical, keyword_flags_high
        FROM governance_telemetry
        WHERE instance_id = :iid
        ORDER BY synced_at DESC LIMIT 1
    """

    instance_detail = "SELECT * FROM governance_instances WHERE instance_id = :iid"

    telemetry_history = """
        SELECT period_start, period_end, total_requests, total_spend,
               unique_users, dlp_blocks, error_count,
               keyword_flags_critical, keyword_flags_high,
               compliance_score, synced_at
        FROM governance_telemetry WHERE instance_id = :iid
        ORDER BY synced_at DESC LIMIT 30
    """

    instance_changes = """
        SELECT id, title, category, status, source, proposed_at
        FROM governance_changes WHERE instance_id = :iid
        ORDER BY proposed_at DESC LIMIT 20
    """

    fleet_count = "SELECT COUNT(*) AS cnt FROM governance_instances WHERE status = 'active'"

    fleet_aggregate = """
        SELECT
            COUNT(DISTINCT t.instance_id) AS reporting_instances,
            SUM(t.total_requests) AS fleet_requests,
            SUM(t.total_spend) AS fleet_spend,
            SUM(t.unique_users) AS fleet_users,
            AVG(t.compliance_score) AS avg_compliance_score,
            SUM(t.keyword_flags_critical) AS total_critical_flags
        FROM governance_telemetry t
        INNER JOIN (
            SELECT instance_id, MAX(synced_at) AS max_sync
            FROM governance_telemetry GROUP BY instance_id
        ) latest ON t.instance_id = latest.instance_id AND t.synced_at = latest.max_sync
    """

    fleet_by_industry = """
        SELECT industry, COUNT(*) AS cnt
        FROM governance_instances WHERE status = 'active'
        GROUP BY industry ORDER BY cnt DESC
    """

    fleet_stale = """
        SELECT COUNT(*) AS cnt FROM governance_instances
        WHERE status = 'active' AND (last_sync_at IS NULL OR last_sync_at < NOW() - INTERVAL '24 hours')
    """

    snapshot_by_id = """
        SELECT * FROM governance_config_snapshots
        WHERE instance_id = :iid AND id = :sid
    """

    snapshot_latest = """
        SELECT * FROM governance_config_snapshots
        WHERE instance_id = :iid ORDER BY snapshot_at DESC LIMIT 1
    """

    snapshot_list = """
        SELECT id, instance_id, schema_version, snapshot_at, created_by
        FROM governance_config_snapshots WHERE instance_id = :iid
        ORDER BY snapshot_at DESC LIMIT :lim
    """

    upsert_tfvars = """
        INSERT INTO governance_deployment_tfvars
            (instance_id, platform_version, encrypted_tfvars, encryption_iv, deployed_at, updated_at)
        VALUES (:iid, :ver, :enc, :iv, :deployed_at, :updated_at)
        ON CONFLICT (instance_id) DO UPDATE SET
            encrypted_tfvars = EXCLUDED.encrypted_tfvars,
            encryption_iv = EXCLUDED.encryption_iv,
            platform_version = EXCLUDED.platform_version,
            updated_at = EXCLUDED.updated_at
    """

    get_tfvars = """
        SELECT encrypted_tfvars, encryption_iv, platform_version, deployed_at
        FROM governance_deployment_tfvars WHERE instance_id = :iid
    """

    # Keyword templates
    list_keyword_templates = """
        SELECT t.industry, t.hint, t.default_tier, t.default_classification, t.is_active, t.version, t.updated_at, t.updated_by
        FROM governance_keyword_templates t WHERE t.is_active = true ORDER BY t.industry
    """

    get_keyword_template = """
        SELECT t.industry, t.hint, t.default_tier, t.default_classification, t.is_active, t.version, t.updated_at, t.updated_by
        FROM governance_keyword_templates t WHERE t.industry = :industry
    """

    get_keyword_categories = """
        SELECT category_name, keywords, sort_order
        FROM governance_keyword_categories WHERE industry = :industry ORDER BY sort_order, category_name
    """

    upsert_keyword_template = """
        INSERT INTO governance_keyword_templates (industry, hint, default_tier, default_classification, updated_by)
        VALUES (:industry, :hint, :tier, :classification, :updated_by)
        ON CONFLICT (industry) DO UPDATE SET
            hint = EXCLUDED.hint, default_tier = EXCLUDED.default_tier,
            default_classification = EXCLUDED.default_classification,
            version = governance_keyword_templates.version + 1,
            updated_at = NOW(), updated_by = EXCLUDED.updated_by
    """

    upsert_keyword_category = """
        INSERT INTO governance_keyword_categories (industry, category_name, keywords, sort_order)
        VALUES (:industry, :category, :keywords, :sort_order)
        ON CONFLICT (industry, category_name) DO UPDATE SET
            keywords = EXCLUDED.keywords, sort_order = EXCLUDED.sort_order
    """

    delete_keyword_categories = "DELETE FROM governance_keyword_categories WHERE industry = :industry"

    count_keyword_templates = "SELECT COUNT(*) AS cnt FROM governance_keyword_templates"

    # Registration tokens
    create_registration_token = """
        INSERT INTO governance_registration_tokens (token, created_by, expires_at)
        VALUES (:token, :created_by, :expires_at)
    """

    validate_registration_token = """
        SELECT id, token, created_by, expires_at FROM governance_registration_tokens
        WHERE token = :token AND is_used = false AND expires_at > NOW()
    """

    mark_token_used = """
        UPDATE governance_registration_tokens SET is_used = true, used_by = :used_by, used_at = NOW()
        WHERE token = :token
    """

    deregister_instance = """
        UPDATE governance_instances
        SET status = 'deregistered'
        WHERE instance_id = :iid
    """

    # Framework document storage (fleet-wide source of truth)
    insert_framework_document = """
        INSERT INTO governance_framework_documents
            (version, content, sha256, filename, note, uploaded_by, uploaded_from_instance)
        VALUES
            ((SELECT COALESCE(MAX(version), 0) + 1 FROM governance_framework_documents),
             :content, :sha256, :filename, :note, :uploaded_by, :instance_id)
    """

    get_current_framework_document = """
        SELECT id, version, content, sha256, filename, note,
               uploaded_by, uploaded_at, uploaded_from_instance
        FROM governance_framework_documents
        ORDER BY version DESC LIMIT 1
    """

    list_framework_document_versions = """
        SELECT id, version, sha256, filename, note,
               uploaded_by, uploaded_at, uploaded_from_instance
        FROM governance_framework_documents
        ORDER BY version DESC
    """

    get_instance_overrides = """
        SELECT instance_id, alert_webhook, updated_at, updated_by
        FROM governance_instance_overrides
        WHERE instance_id = :iid
    """

    upsert_instance_overrides = """
        INSERT INTO governance_instance_overrides (instance_id, alert_webhook, updated_at, updated_by)
        VALUES (:iid, :alert_webhook, NOW(), :updated_by)
        ON CONFLICT (instance_id) DO UPDATE SET
            alert_webhook = EXCLUDED.alert_webhook,
            updated_at = NOW(),
            updated_by = EXCLUDED.updated_by
    """

    # --- Keycloak identity replication (Phase 2) -----------------------------

    upsert_identity_realm = """
        INSERT INTO governance_identity_realms
            (instance_id, realm_name, display_name, enabled, realm_json, last_synced_at)
        VALUES (:iid, :realm, :display, :enabled, CAST(:realm_json AS JSONB), NOW())
        ON CONFLICT (instance_id, realm_name) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            enabled = EXCLUDED.enabled,
            realm_json = EXCLUDED.realm_json,
            last_synced_at = NOW()
    """

    upsert_identity_user = """
        INSERT INTO governance_identity_users
            (instance_id, realm_name, keycloak_user_id, username, email, first_name, last_name,
             enabled, email_verified, groups_csv, realm_roles_csv, attributes_json,
             created_at_kc, last_synced_at)
        VALUES (:iid, :realm, :user_id, :username, :email, :first_name, :last_name,
                :enabled, :email_verified, :groups_csv, :roles_csv, CAST(:attributes AS JSONB),
                :created_at_kc, NOW())
        ON CONFLICT (instance_id, realm_name, keycloak_user_id) DO UPDATE SET
            username = EXCLUDED.username,
            email = EXCLUDED.email,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            enabled = EXCLUDED.enabled,
            email_verified = EXCLUDED.email_verified,
            groups_csv = EXCLUDED.groups_csv,
            realm_roles_csv = EXCLUDED.realm_roles_csv,
            attributes_json = EXCLUDED.attributes_json,
            last_synced_at = NOW()
    """

    upsert_identity_group = """
        INSERT INTO governance_identity_groups
            (instance_id, realm_name, keycloak_group_id, name, path, parent_group_id,
             attributes_json, realm_roles_csv, last_synced_at)
        VALUES (:iid, :realm, :group_id, :name, :path, :parent_id,
                CAST(:attributes AS JSONB), :roles_csv, NOW())
        ON CONFLICT (instance_id, realm_name, keycloak_group_id) DO UPDATE SET
            name = EXCLUDED.name,
            path = EXCLUDED.path,
            parent_group_id = EXCLUDED.parent_group_id,
            attributes_json = EXCLUDED.attributes_json,
            realm_roles_csv = EXCLUDED.realm_roles_csv,
            last_synced_at = NOW()
    """

    # Delete rows that weren't refreshed by the current sync cycle. Use the
    # started_at timestamp as a cursor so concurrent syncs don't stomp.
    prune_identity_users = """
        DELETE FROM governance_identity_users
        WHERE instance_id = :iid AND realm_name = :realm AND last_synced_at < :cursor
    """
    prune_identity_groups = """
        DELETE FROM governance_identity_groups
        WHERE instance_id = :iid AND realm_name = :realm AND last_synced_at < :cursor
    """

    insert_identity_sync_log = """
        INSERT INTO governance_identity_sync_log
            (instance_id, realm_name, started_at, ended_at, status,
             users_synced, groups_synced, duration_ms, error_message)
        VALUES (:iid, :realm, :started_at, :ended_at, :status,
                :users, :groups, :duration, :error)
    """

    recent_identity_sync_log = """
        SELECT instance_id, realm_name, started_at, ended_at, status,
               users_synced, groups_synced, duration_ms, error_message
        FROM governance_identity_sync_log
        WHERE (:iid IS NULL OR instance_id = :iid)
        ORDER BY started_at DESC
        LIMIT :lim
    """

    list_identity_users = """
        SELECT instance_id, realm_name, keycloak_user_id, username, email,
               first_name, last_name, enabled, email_verified,
               groups_csv, realm_roles_csv, last_synced_at
        FROM governance_identity_users
        WHERE (:iid IS NULL OR instance_id = :iid)
          AND (:realm IS NULL OR realm_name = :realm)
        ORDER BY instance_id, username
        LIMIT :lim OFFSET :off
    """

    list_identity_groups = """
        SELECT instance_id, realm_name, keycloak_group_id, name, path,
               parent_group_id, realm_roles_csv, last_synced_at
        FROM governance_identity_groups
        WHERE (:iid IS NULL OR instance_id = :iid)
          AND (:realm IS NULL OR realm_name = :realm)
        ORDER BY instance_id, path
        LIMIT :lim OFFSET :off
    """

    # --- Portfolio observability (P4.1) -------------------------------------
    # Aggregates across the fleet for the Parent Organization-style cross-tenant view.
    # All metrics pivot on the *latest* telemetry row per instance so a
    # reporting lag doesn't distort the headline numbers.

    portfolio_per_instance = """
        SELECT
            i.instance_id,
            i.instance_name,
            i.industry,
            i.governance_tier,
            i.platform_version,
            i.last_sync_at,
            i.status,
            COALESCE(t.total_requests, 0)          AS total_requests,
            COALESCE(t.total_spend, 0)             AS total_spend,
            COALESCE(t.unique_users, 0)            AS unique_users,
            COALESCE(t.dlp_blocks, 0)              AS dlp_blocks,
            COALESCE(t.error_count, 0)             AS error_count,
            COALESCE(t.keyword_flags_critical, 0)  AS critical_flags,
            COALESCE(t.keyword_flags_high, 0)      AS high_flags,
            COALESCE(t.compliance_score, 0)        AS compliance_score,
            t.synced_at                            AS last_telemetry_at
        FROM governance_instances i
        LEFT JOIN LATERAL (
            SELECT total_requests, total_spend, unique_users, dlp_blocks,
                   error_count, keyword_flags_critical, keyword_flags_high,
                   compliance_score, synced_at
            FROM governance_telemetry
            WHERE instance_id = i.instance_id
            ORDER BY synced_at DESC LIMIT 1
        ) t ON TRUE
        WHERE i.status = 'active'
        ORDER BY i.instance_name
    """

    portfolio_by_industry = """
        WITH latest AS (
            SELECT DISTINCT ON (instance_id) instance_id, total_requests,
                   total_spend, unique_users, dlp_blocks, error_count,
                   keyword_flags_critical, compliance_score
            FROM governance_telemetry
            ORDER BY instance_id, synced_at DESC
        )
        SELECT
            COALESCE(i.industry, 'unspecified')  AS industry,
            COUNT(*)                             AS instances,
            COALESCE(SUM(l.total_requests), 0)   AS total_requests,
            COALESCE(SUM(l.total_spend), 0)      AS total_spend,
            COALESCE(SUM(l.unique_users), 0)     AS total_users,
            COALESCE(SUM(l.dlp_blocks), 0)       AS dlp_blocks,
            COALESCE(SUM(l.error_count), 0)      AS error_count,
            COALESCE(SUM(l.keyword_flags_critical), 0) AS critical_flags,
            COALESCE(AVG(l.compliance_score), 0) AS avg_compliance
        FROM governance_instances i
        LEFT JOIN latest l ON i.instance_id = l.instance_id
        WHERE i.status = 'active'
        GROUP BY COALESCE(i.industry, 'unspecified')
        ORDER BY instances DESC, industry
    """

    portfolio_time_series = """
        SELECT
            DATE_TRUNC('day', synced_at)         AS day,
            COUNT(DISTINCT instance_id)          AS reporting_instances,
            SUM(total_requests)                  AS total_requests,
            SUM(total_spend)                     AS total_spend,
            SUM(unique_users)                    AS unique_users,
            SUM(dlp_blocks)                      AS dlp_blocks,
            SUM(error_count)                     AS error_count,
            AVG(compliance_score)                AS avg_compliance
        FROM governance_telemetry
        WHERE synced_at >= NOW() - (:days * INTERVAL '1 day')
        GROUP BY DATE_TRUNC('day', synced_at)
        ORDER BY day
    """

    portfolio_at_risk = """
        WITH latest AS (
            SELECT DISTINCT ON (instance_id) instance_id, total_spend,
                   compliance_score, error_count, keyword_flags_critical,
                   dlp_blocks, synced_at
            FROM governance_telemetry
            ORDER BY instance_id, synced_at DESC
        )
        SELECT
            i.instance_id,
            i.instance_name,
            i.industry,
            i.last_sync_at,
            COALESCE(l.compliance_score, 0)     AS compliance_score,
            COALESCE(l.error_count, 0)          AS error_count,
            COALESCE(l.keyword_flags_critical, 0) AS critical_flags,
            COALESCE(l.dlp_blocks, 0)           AS dlp_blocks,
            COALESCE(l.total_spend, 0)          AS total_spend,
            CASE
                WHEN i.last_sync_at IS NULL OR i.last_sync_at < NOW() - INTERVAL '24 hours' THEN 'stale_telemetry'
                WHEN l.compliance_score IS NOT NULL AND l.compliance_score < :compliance_threshold THEN 'low_compliance'
                WHEN l.keyword_flags_critical > :critical_flag_threshold THEN 'critical_flags'
                WHEN l.error_count > :error_threshold THEN 'high_error_rate'
                ELSE 'ok'
            END AS risk_reason
        FROM governance_instances i
        LEFT JOIN latest l ON i.instance_id = l.instance_id
        WHERE i.status = 'active' AND (
              i.last_sync_at IS NULL OR i.last_sync_at < NOW() - INTERVAL '24 hours'
           OR (l.compliance_score IS NOT NULL AND l.compliance_score < :compliance_threshold)
           OR l.keyword_flags_critical > :critical_flag_threshold
           OR l.error_count > :error_threshold
        )
        ORDER BY i.instance_name
    """

    portfolio_identity_totals = """
        SELECT
            COUNT(DISTINCT instance_id || '|' || keycloak_user_id) AS total_users,
            COUNT(DISTINCT instance_id)                            AS instances_with_identity
        FROM governance_identity_users
        WHERE enabled = true
    """


class _MSSQL:
    """Microsoft SQL Server dialect."""

    upsert_instance = """
        MERGE governance_instances AS target
        USING (SELECT :id AS instance_id) AS source
        ON target.instance_id = source.instance_id
        WHEN MATCHED THEN UPDATE SET
            instance_name = :name, schema_version = :schema_version,
            platform_version = :platform_version, last_sync_at = GETDATE()
        WHEN NOT MATCHED THEN INSERT
            (instance_id, instance_name, industry, governance_tier, data_classification,
             schema_version, platform_version, last_sync_at, status)
        VALUES (:id, :name, :industry, :tier, :classification, :schema_version, :platform_version, GETDATE(), 'active');
    """

    insert_telemetry = """
        INSERT INTO governance_telemetry
            (instance_id, instance_name, schema_version, platform_version, period_start, period_end,
             total_requests, total_spend, unique_users, dlp_blocks, error_count,
             keyword_flags_critical, keyword_flags_high, compliance_score, industry, governance_tier, metrics_json)
        VALUES
            (:instance_id, :instance_name, :schema_version, :platform_version, :period_start, :period_end,
             :total_requests, :total_spend, :unique_users, :dlp_blocks, :error_count,
             :kw_critical, :kw_high, :compliance_score, :industry, :tier, :metrics)
    """

    upsert_snapshot = """
        MERGE governance_config_snapshots AS target
        USING (SELECT :id AS id, :iid AS instance_id) AS source
        ON target.id = source.id AND target.instance_id = source.instance_id
        WHEN MATCHED THEN UPDATE SET
            config_json = :config, snapshot_at = :snap_at
        WHEN NOT MATCHED THEN INSERT
            (id, instance_id, schema_version, config_json, diff_from_previous, snapshot_at, created_by)
        VALUES (:id, :iid, :sv, :config, :diff, :snap_at, :created_by);
    """

    list_instances = """
        SELECT instance_id, instance_name, industry, governance_tier, data_classification,
               schema_version, platform_version, last_sync_at, status, created_at
        FROM governance_instances
        WHERE status = 'active'
        ORDER BY instance_name
    """

    latest_telemetry = """
        SELECT TOP 1 total_requests, total_spend, unique_users,
               compliance_score, keyword_flags_critical, keyword_flags_high
        FROM governance_telemetry
        WHERE instance_id = :iid
        ORDER BY synced_at DESC
    """

    instance_detail = "SELECT * FROM governance_instances WHERE instance_id = :iid"

    telemetry_history = """
        SELECT TOP 30 period_start, period_end, total_requests, total_spend,
               unique_users, dlp_blocks, error_count,
               keyword_flags_critical, keyword_flags_high,
               compliance_score, synced_at
        FROM governance_telemetry WHERE instance_id = :iid
        ORDER BY synced_at DESC
    """

    instance_changes = """
        SELECT TOP 20 id, title, category, status, source, proposed_at
        FROM governance_changes WHERE instance_id = :iid
        ORDER BY proposed_at DESC
    """

    fleet_count = "SELECT COUNT(*) AS cnt FROM governance_instances WHERE status = 'active'"

    fleet_aggregate = """
        SELECT
            COUNT(DISTINCT t.instance_id) AS reporting_instances,
            SUM(t.total_requests) AS fleet_requests,
            SUM(t.total_spend) AS fleet_spend,
            SUM(t.unique_users) AS fleet_users,
            AVG(t.compliance_score) AS avg_compliance_score,
            SUM(t.keyword_flags_critical) AS total_critical_flags
        FROM governance_telemetry t
        INNER JOIN (
            SELECT instance_id, MAX(synced_at) AS max_sync
            FROM governance_telemetry GROUP BY instance_id
        ) latest ON t.instance_id = latest.instance_id AND t.synced_at = latest.max_sync
    """

    fleet_by_industry = """
        SELECT industry, COUNT(*) AS cnt
        FROM governance_instances WHERE status = 'active'
        GROUP BY industry ORDER BY cnt DESC
    """

    fleet_stale = """
        SELECT COUNT(*) AS cnt FROM governance_instances
        WHERE status = 'active' AND (last_sync_at IS NULL OR last_sync_at < DATEADD(hour, -24, GETDATE()))
    """

    snapshot_by_id = """
        SELECT * FROM governance_config_snapshots
        WHERE instance_id = :iid AND id = :sid
    """

    snapshot_latest = """
        SELECT TOP 1 * FROM governance_config_snapshots
        WHERE instance_id = :iid ORDER BY snapshot_at DESC
    """

    snapshot_list = """
        SELECT TOP (:lim) id, instance_id, schema_version, snapshot_at, created_by
        FROM governance_config_snapshots WHERE instance_id = :iid
        ORDER BY snapshot_at DESC
    """

    upsert_tfvars = """
        MERGE governance_deployment_tfvars AS target
        USING (SELECT :iid AS instance_id) AS source
        ON target.instance_id = source.instance_id
        WHEN MATCHED THEN UPDATE SET
            encrypted_tfvars = :enc, encryption_iv = :iv,
            platform_version = :ver, updated_at = :updated_at
        WHEN NOT MATCHED THEN INSERT
            (instance_id, platform_version, encrypted_tfvars, encryption_iv, deployed_at, updated_at)
        VALUES (:iid, :ver, :enc, :iv, :deployed_at, :updated_at);
    """

    get_tfvars = _PostgreSQL.get_tfvars

    # Keyword templates (MSSQL uses BIT for boolean, GETDATE)
    list_keyword_templates = """
        SELECT industry, hint, default_tier, default_classification, is_active, version, updated_at, updated_by
        FROM governance_keyword_templates WHERE is_active = 1 ORDER BY industry
    """
    get_keyword_template = _PostgreSQL.get_keyword_template
    get_keyword_categories = _PostgreSQL.get_keyword_categories

    upsert_keyword_template = """
        MERGE governance_keyword_templates AS target
        USING (SELECT :industry AS industry) AS source ON target.industry = source.industry
        WHEN MATCHED THEN UPDATE SET
            hint = :hint, default_tier = :tier, default_classification = :classification,
            is_active = 1, version = target.version + 1, updated_at = GETDATE(), updated_by = :updated_by
        WHEN NOT MATCHED THEN INSERT (industry, hint, default_tier, default_classification, is_active, version, updated_by)
        VALUES (:industry, :hint, :tier, :classification, 1, 1, :updated_by);
    """

    upsert_keyword_category = """
        MERGE governance_keyword_categories AS target
        USING (SELECT :industry AS industry, :category AS category_name) AS source
        ON target.industry = source.industry AND target.category_name = source.category_name
        WHEN MATCHED THEN UPDATE SET keywords = :keywords, sort_order = :sort_order
        WHEN NOT MATCHED THEN INSERT (industry, category_name, keywords, sort_order)
        VALUES (:industry, :category, :keywords, :sort_order);
    """

    delete_keyword_categories = _PostgreSQL.delete_keyword_categories
    count_keyword_templates = _PostgreSQL.count_keyword_templates

    create_registration_token = """
        INSERT INTO governance_registration_tokens (token, created_by, expires_at)
        VALUES (:token, :created_by, :expires_at)
    """
    validate_registration_token = """
        SELECT id, token, created_by, expires_at FROM governance_registration_tokens
        WHERE token = :token AND is_used = 0 AND expires_at > GETDATE()
    """
    mark_token_used = """
        UPDATE governance_registration_tokens SET is_used = 1, used_by = :used_by, used_at = GETDATE()
        WHERE token = :token
    """

    deregister_instance = _PostgreSQL.deregister_instance

    get_instance_overrides = _PostgreSQL.get_instance_overrides

    # Framework document queries — MSSQL needs its own insert for the
    # auto-increment pattern (no SERIAL; use IDENTITY column + the
    # subquery-as-default-value pattern still works).
    insert_framework_document = """
        INSERT INTO governance_framework_documents
            (version, content, sha256, filename, note, uploaded_by, uploaded_from_instance)
        VALUES
            ((SELECT ISNULL(MAX(version), 0) + 1 FROM governance_framework_documents),
             :content, :sha256, :filename, :note, :uploaded_by, :instance_id)
    """
    # MSSQL uses TOP, not LIMIT
    get_current_framework_document = """
        SELECT TOP 1 id, version, content, sha256, filename, note,
               uploaded_by, uploaded_at, uploaded_from_instance
        FROM governance_framework_documents
        ORDER BY version DESC
    """
    list_framework_document_versions = """
        SELECT id, version, sha256, filename, note,
               uploaded_by, uploaded_at, uploaded_from_instance
        FROM governance_framework_documents
        ORDER BY version DESC
    """

    upsert_instance_overrides = """
        MERGE governance_instance_overrides AS target
        USING (SELECT :iid AS instance_id) AS source
        ON target.instance_id = source.instance_id
        WHEN MATCHED THEN UPDATE SET
            alert_webhook = :alert_webhook,
            updated_at = GETDATE(),
            updated_by = :updated_by
        WHEN NOT MATCHED THEN INSERT
            (instance_id, alert_webhook, updated_at, updated_by)
        VALUES (:iid, :alert_webhook, GETDATE(), :updated_by);
    """

    # --- Keycloak identity replication (Phase 2) -----------------------------
    # MSSQL stores the JSONB-like payloads in NVARCHAR(MAX); no CAST needed.

    upsert_identity_realm = """
        MERGE governance_identity_realms AS target
        USING (SELECT :iid AS instance_id, :realm AS realm_name) AS source
        ON target.instance_id = source.instance_id AND target.realm_name = source.realm_name
        WHEN MATCHED THEN UPDATE SET
            display_name = :display, enabled = :enabled,
            realm_json = :realm_json, last_synced_at = GETDATE()
        WHEN NOT MATCHED THEN INSERT
            (instance_id, realm_name, display_name, enabled, realm_json, last_synced_at)
        VALUES (:iid, :realm, :display, :enabled, :realm_json, GETDATE());
    """

    upsert_identity_user = """
        MERGE governance_identity_users AS target
        USING (SELECT :iid AS instance_id, :realm AS realm_name,
                      :user_id AS keycloak_user_id) AS source
        ON target.instance_id = source.instance_id
           AND target.realm_name = source.realm_name
           AND target.keycloak_user_id = source.keycloak_user_id
        WHEN MATCHED THEN UPDATE SET
            username = :username, email = :email, first_name = :first_name,
            last_name = :last_name, enabled = :enabled, email_verified = :email_verified,
            groups_csv = :groups_csv, realm_roles_csv = :roles_csv,
            attributes_json = :attributes, last_synced_at = GETDATE()
        WHEN NOT MATCHED THEN INSERT
            (instance_id, realm_name, keycloak_user_id, username, email, first_name,
             last_name, enabled, email_verified, groups_csv, realm_roles_csv,
             attributes_json, created_at_kc, last_synced_at)
        VALUES (:iid, :realm, :user_id, :username, :email, :first_name, :last_name,
                :enabled, :email_verified, :groups_csv, :roles_csv, :attributes,
                :created_at_kc, GETDATE());
    """

    upsert_identity_group = """
        MERGE governance_identity_groups AS target
        USING (SELECT :iid AS instance_id, :realm AS realm_name,
                      :group_id AS keycloak_group_id) AS source
        ON target.instance_id = source.instance_id
           AND target.realm_name = source.realm_name
           AND target.keycloak_group_id = source.keycloak_group_id
        WHEN MATCHED THEN UPDATE SET
            name = :name, path = :path, parent_group_id = :parent_id,
            attributes_json = :attributes, realm_roles_csv = :roles_csv,
            last_synced_at = GETDATE()
        WHEN NOT MATCHED THEN INSERT
            (instance_id, realm_name, keycloak_group_id, name, path, parent_group_id,
             attributes_json, realm_roles_csv, last_synced_at)
        VALUES (:iid, :realm, :group_id, :name, :path, :parent_id,
                :attributes, :roles_csv, GETDATE());
    """

    prune_identity_users = """
        DELETE FROM governance_identity_users
        WHERE instance_id = :iid AND realm_name = :realm AND last_synced_at < :cursor
    """
    prune_identity_groups = """
        DELETE FROM governance_identity_groups
        WHERE instance_id = :iid AND realm_name = :realm AND last_synced_at < :cursor
    """

    insert_identity_sync_log = """
        INSERT INTO governance_identity_sync_log
            (instance_id, realm_name, started_at, ended_at, status,
             users_synced, groups_synced, duration_ms, error_message)
        VALUES (:iid, :realm, :started_at, :ended_at, :status,
                :users, :groups, :duration, :error)
    """

    # MSSQL uses TOP + OFFSET/FETCH. Pagination for list_* is OFFSET/FETCH.
    recent_identity_sync_log = """
        SELECT TOP (:lim) instance_id, realm_name, started_at, ended_at, status,
               users_synced, groups_synced, duration_ms, error_message
        FROM governance_identity_sync_log
        WHERE (:iid IS NULL OR instance_id = :iid)
        ORDER BY started_at DESC
    """

    list_identity_users = """
        SELECT instance_id, realm_name, keycloak_user_id, username, email,
               first_name, last_name, enabled, email_verified,
               groups_csv, realm_roles_csv, last_synced_at
        FROM governance_identity_users
        WHERE (:iid IS NULL OR instance_id = :iid)
          AND (:realm IS NULL OR realm_name = :realm)
        ORDER BY instance_id, username
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """

    list_identity_groups = """
        SELECT instance_id, realm_name, keycloak_group_id, name, path,
               parent_group_id, realm_roles_csv, last_synced_at
        FROM governance_identity_groups
        WHERE (:iid IS NULL OR instance_id = :iid)
          AND (:realm IS NULL OR realm_name = :realm)
        ORDER BY instance_id, path
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """

    # --- Portfolio observability (P4.1) -------------------------------------
    # MSSQL: CROSS APPLY replaces LATERAL; DATEADD replaces INTERVAL.

    portfolio_per_instance = """
        SELECT
            i.instance_id, i.instance_name, i.industry, i.governance_tier,
            i.platform_version, i.last_sync_at, i.status,
            COALESCE(t.total_requests, 0)         AS total_requests,
            COALESCE(t.total_spend, 0)            AS total_spend,
            COALESCE(t.unique_users, 0)           AS unique_users,
            COALESCE(t.dlp_blocks, 0)             AS dlp_blocks,
            COALESCE(t.error_count, 0)            AS error_count,
            COALESCE(t.keyword_flags_critical, 0) AS critical_flags,
            COALESCE(t.keyword_flags_high, 0)     AS high_flags,
            COALESCE(t.compliance_score, 0)       AS compliance_score,
            t.synced_at                           AS last_telemetry_at
        FROM governance_instances i
        OUTER APPLY (
            SELECT TOP 1 total_requests, total_spend, unique_users, dlp_blocks,
                   error_count, keyword_flags_critical, keyword_flags_high,
                   compliance_score, synced_at
            FROM governance_telemetry
            WHERE instance_id = i.instance_id
            ORDER BY synced_at DESC
        ) t
        WHERE i.status = 'active'
        ORDER BY i.instance_name
    """

    portfolio_by_industry = """
        WITH latest AS (
            SELECT instance_id, total_requests, total_spend, unique_users,
                   dlp_blocks, error_count, keyword_flags_critical, compliance_score,
                   ROW_NUMBER() OVER (PARTITION BY instance_id ORDER BY synced_at DESC) rn
            FROM governance_telemetry
        )
        SELECT
            COALESCE(i.industry, 'unspecified') AS industry,
            COUNT(*)                            AS instances,
            COALESCE(SUM(l.total_requests), 0)  AS total_requests,
            COALESCE(SUM(l.total_spend), 0)     AS total_spend,
            COALESCE(SUM(l.unique_users), 0)    AS total_users,
            COALESCE(SUM(l.dlp_blocks), 0)      AS dlp_blocks,
            COALESCE(SUM(l.error_count), 0)     AS error_count,
            COALESCE(SUM(l.keyword_flags_critical), 0) AS critical_flags,
            COALESCE(AVG(l.compliance_score), 0) AS avg_compliance
        FROM governance_instances i
        LEFT JOIN latest l ON i.instance_id = l.instance_id AND l.rn = 1
        WHERE i.status = 'active'
        GROUP BY COALESCE(i.industry, 'unspecified')
        ORDER BY COUNT(*) DESC, COALESCE(i.industry, 'unspecified')
    """

    portfolio_time_series = """
        SELECT
            CAST(synced_at AS DATE)           AS day,
            COUNT(DISTINCT instance_id)       AS reporting_instances,
            SUM(total_requests)               AS total_requests,
            SUM(total_spend)                  AS total_spend,
            SUM(unique_users)                 AS unique_users,
            SUM(dlp_blocks)                   AS dlp_blocks,
            SUM(error_count)                  AS error_count,
            AVG(compliance_score)             AS avg_compliance
        FROM governance_telemetry
        WHERE synced_at >= DATEADD(day, -:days, GETDATE())
        GROUP BY CAST(synced_at AS DATE)
        ORDER BY day
    """

    portfolio_at_risk = """
        WITH latest AS (
            SELECT instance_id, total_spend, compliance_score, error_count,
                   keyword_flags_critical, dlp_blocks, synced_at,
                   ROW_NUMBER() OVER (PARTITION BY instance_id ORDER BY synced_at DESC) rn
            FROM governance_telemetry
        )
        SELECT
            i.instance_id, i.instance_name, i.industry, i.last_sync_at,
            COALESCE(l.compliance_score, 0)       AS compliance_score,
            COALESCE(l.error_count, 0)            AS error_count,
            COALESCE(l.keyword_flags_critical, 0) AS critical_flags,
            COALESCE(l.dlp_blocks, 0)             AS dlp_blocks,
            COALESCE(l.total_spend, 0)            AS total_spend,
            CASE
                WHEN i.last_sync_at IS NULL OR i.last_sync_at < DATEADD(hour, -24, GETDATE()) THEN 'stale_telemetry'
                WHEN l.compliance_score IS NOT NULL AND l.compliance_score < :compliance_threshold THEN 'low_compliance'
                WHEN l.keyword_flags_critical > :critical_flag_threshold THEN 'critical_flags'
                WHEN l.error_count > :error_threshold THEN 'high_error_rate'
                ELSE 'ok'
            END AS risk_reason
        FROM governance_instances i
        LEFT JOIN latest l ON i.instance_id = l.instance_id AND l.rn = 1
        WHERE i.status = 'active' AND (
              i.last_sync_at IS NULL OR i.last_sync_at < DATEADD(hour, -24, GETDATE())
           OR (l.compliance_score IS NOT NULL AND l.compliance_score < :compliance_threshold)
           OR l.keyword_flags_critical > :critical_flag_threshold
           OR l.error_count > :error_threshold
        )
        ORDER BY i.instance_name
    """

    portfolio_identity_totals = """
        SELECT
            COUNT(DISTINCT CONCAT(instance_id, '|', keycloak_user_id)) AS total_users,
            COUNT(DISTINCT instance_id)                                AS instances_with_identity
        FROM governance_identity_users
        WHERE enabled = 1
    """


class _MariaDB:
    """MariaDB / MySQL dialect."""

    upsert_instance = """
        INSERT INTO governance_instances
            (instance_id, instance_name, industry, governance_tier, data_classification,
             schema_version, platform_version, last_sync_at, status)
        VALUES (:id, :name, :industry, :tier, :classification, :schema_version, :platform_version, NOW(), 'active')
        ON DUPLICATE KEY UPDATE
            instance_name = VALUES(instance_name),
            schema_version = VALUES(schema_version),
            platform_version = VALUES(platform_version),
            last_sync_at = NOW()
    """

    insert_telemetry = _PostgreSQL.insert_telemetry  # Standard SQL, works on MariaDB

    upsert_snapshot = """
        INSERT INTO governance_config_snapshots
            (id, instance_id, schema_version, config_json, diff_from_previous, snapshot_at, created_by)
        VALUES (:id, :iid, :sv, :config, :diff, :snap_at, :created_by)
        ON DUPLICATE KEY UPDATE
            config_json = VALUES(config_json),
            snapshot_at = VALUES(snapshot_at)
    """

    list_instances = _PostgreSQL.list_instances
    latest_telemetry = _PostgreSQL.latest_telemetry
    instance_detail = _PostgreSQL.instance_detail
    telemetry_history = _PostgreSQL.telemetry_history
    instance_changes = _PostgreSQL.instance_changes
    fleet_count = _PostgreSQL.fleet_count
    fleet_aggregate = _PostgreSQL.fleet_aggregate
    fleet_by_industry = _PostgreSQL.fleet_by_industry

    fleet_stale = """
        SELECT COUNT(*) AS cnt FROM governance_instances
        WHERE status = 'active' AND (last_sync_at IS NULL OR last_sync_at < NOW() - INTERVAL 24 HOUR)
    """

    snapshot_by_id = _PostgreSQL.snapshot_by_id
    snapshot_latest = _PostgreSQL.snapshot_latest
    snapshot_list = _PostgreSQL.snapshot_list

    # Framework document — PostgreSQL SQL works for MariaDB too (no
    # ON CONFLICT / MERGE needed; we just INSERT a fresh version each upload)
    insert_framework_document = _PostgreSQL.insert_framework_document
    get_current_framework_document = _PostgreSQL.get_current_framework_document
    list_framework_document_versions = _PostgreSQL.list_framework_document_versions

    upsert_tfvars = """
        INSERT INTO governance_deployment_tfvars
            (instance_id, platform_version, encrypted_tfvars, encryption_iv, deployed_at, updated_at)
        VALUES (:iid, :ver, :enc, :iv, :deployed_at, :updated_at)
        ON DUPLICATE KEY UPDATE
            encrypted_tfvars = VALUES(encrypted_tfvars),
            encryption_iv = VALUES(encryption_iv),
            platform_version = VALUES(platform_version),
            updated_at = VALUES(updated_at)
    """

    get_tfvars = _PostgreSQL.get_tfvars

    # Keyword templates (MariaDB uses ON DUPLICATE KEY)
    list_keyword_templates = _PostgreSQL.list_keyword_templates
    get_keyword_template = _PostgreSQL.get_keyword_template
    get_keyword_categories = _PostgreSQL.get_keyword_categories

    upsert_keyword_template = """
        INSERT INTO governance_keyword_templates (industry, hint, default_tier, default_classification, updated_by)
        VALUES (:industry, :hint, :tier, :classification, :updated_by)
        ON DUPLICATE KEY UPDATE
            hint = VALUES(hint), default_tier = VALUES(default_tier),
            default_classification = VALUES(default_classification),
            version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = VALUES(updated_by)
    """

    upsert_keyword_category = """
        INSERT INTO governance_keyword_categories (industry, category_name, keywords, sort_order)
        VALUES (:industry, :category, :keywords, :sort_order)
        ON DUPLICATE KEY UPDATE keywords = VALUES(keywords), sort_order = VALUES(sort_order)
    """

    delete_keyword_categories = _PostgreSQL.delete_keyword_categories
    count_keyword_templates = _PostgreSQL.count_keyword_templates
    create_registration_token = _PostgreSQL.create_registration_token
    validate_registration_token = _PostgreSQL.validate_registration_token
    mark_token_used = _PostgreSQL.mark_token_used
    deregister_instance = _PostgreSQL.deregister_instance
    get_instance_overrides = _PostgreSQL.get_instance_overrides

    upsert_instance_overrides = """
        INSERT INTO governance_instance_overrides (instance_id, alert_webhook, updated_at, updated_by)
        VALUES (:iid, :alert_webhook, NOW(), :updated_by)
        ON DUPLICATE KEY UPDATE
            alert_webhook = VALUES(alert_webhook),
            updated_at = NOW(),
            updated_by = VALUES(updated_by)
    """

    # --- Keycloak identity replication (Phase 2) -----------------------------
    # MariaDB stores the JSON fields as LONGTEXT / JSON; no CAST.

    upsert_identity_realm = """
        INSERT INTO governance_identity_realms
            (instance_id, realm_name, display_name, enabled, realm_json, last_synced_at)
        VALUES (:iid, :realm, :display, :enabled, :realm_json, NOW())
        ON DUPLICATE KEY UPDATE
            display_name = VALUES(display_name),
            enabled = VALUES(enabled),
            realm_json = VALUES(realm_json),
            last_synced_at = NOW()
    """

    upsert_identity_user = """
        INSERT INTO governance_identity_users
            (instance_id, realm_name, keycloak_user_id, username, email, first_name, last_name,
             enabled, email_verified, groups_csv, realm_roles_csv, attributes_json,
             created_at_kc, last_synced_at)
        VALUES (:iid, :realm, :user_id, :username, :email, :first_name, :last_name,
                :enabled, :email_verified, :groups_csv, :roles_csv, :attributes,
                :created_at_kc, NOW())
        ON DUPLICATE KEY UPDATE
            username = VALUES(username),
            email = VALUES(email),
            first_name = VALUES(first_name),
            last_name = VALUES(last_name),
            enabled = VALUES(enabled),
            email_verified = VALUES(email_verified),
            groups_csv = VALUES(groups_csv),
            realm_roles_csv = VALUES(realm_roles_csv),
            attributes_json = VALUES(attributes_json),
            last_synced_at = NOW()
    """

    upsert_identity_group = """
        INSERT INTO governance_identity_groups
            (instance_id, realm_name, keycloak_group_id, name, path, parent_group_id,
             attributes_json, realm_roles_csv, last_synced_at)
        VALUES (:iid, :realm, :group_id, :name, :path, :parent_id,
                :attributes, :roles_csv, NOW())
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            path = VALUES(path),
            parent_group_id = VALUES(parent_group_id),
            attributes_json = VALUES(attributes_json),
            realm_roles_csv = VALUES(realm_roles_csv),
            last_synced_at = NOW()
    """

    prune_identity_users = _PostgreSQL.prune_identity_users
    prune_identity_groups = _PostgreSQL.prune_identity_groups
    insert_identity_sync_log = _PostgreSQL.insert_identity_sync_log

    recent_identity_sync_log = """
        SELECT instance_id, realm_name, started_at, ended_at, status,
               users_synced, groups_synced, duration_ms, error_message
        FROM governance_identity_sync_log
        WHERE (:iid IS NULL OR instance_id = :iid)
        ORDER BY started_at DESC
        LIMIT :lim
    """

    list_identity_users = _PostgreSQL.list_identity_users
    list_identity_groups = _PostgreSQL.list_identity_groups

    # --- Portfolio observability (P4.1) -------------------------------------
    # MariaDB/MySQL: no LATERAL in MySQL <8.0.14; use correlated subqueries.

    portfolio_per_instance = """
        SELECT
            i.instance_id, i.instance_name, i.industry, i.governance_tier,
            i.platform_version, i.last_sync_at, i.status,
            COALESCE((SELECT total_requests FROM governance_telemetry
                      WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1), 0) AS total_requests,
            COALESCE((SELECT total_spend FROM governance_telemetry
                      WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1), 0) AS total_spend,
            COALESCE((SELECT unique_users FROM governance_telemetry
                      WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1), 0) AS unique_users,
            COALESCE((SELECT dlp_blocks FROM governance_telemetry
                      WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1), 0) AS dlp_blocks,
            COALESCE((SELECT error_count FROM governance_telemetry
                      WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1), 0) AS error_count,
            COALESCE((SELECT keyword_flags_critical FROM governance_telemetry
                      WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1), 0) AS critical_flags,
            COALESCE((SELECT keyword_flags_high FROM governance_telemetry
                      WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1), 0) AS high_flags,
            COALESCE((SELECT compliance_score FROM governance_telemetry
                      WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1), 0) AS compliance_score,
            (SELECT synced_at FROM governance_telemetry
             WHERE instance_id = i.instance_id ORDER BY synced_at DESC LIMIT 1) AS last_telemetry_at
        FROM governance_instances i
        WHERE i.status = 'active'
        ORDER BY i.instance_name
    """

    portfolio_by_industry = """
        WITH latest AS (
            SELECT instance_id, total_requests, total_spend, unique_users,
                   dlp_blocks, error_count, keyword_flags_critical, compliance_score,
                   ROW_NUMBER() OVER (PARTITION BY instance_id ORDER BY synced_at DESC) AS rn
            FROM governance_telemetry
        )
        SELECT
            COALESCE(i.industry, 'unspecified') AS industry,
            COUNT(*) AS instances,
            COALESCE(SUM(l.total_requests), 0) AS total_requests,
            COALESCE(SUM(l.total_spend), 0)    AS total_spend,
            COALESCE(SUM(l.unique_users), 0)   AS total_users,
            COALESCE(SUM(l.dlp_blocks), 0)     AS dlp_blocks,
            COALESCE(SUM(l.error_count), 0)    AS error_count,
            COALESCE(SUM(l.keyword_flags_critical), 0) AS critical_flags,
            COALESCE(AVG(l.compliance_score), 0) AS avg_compliance
        FROM governance_instances i
        LEFT JOIN latest l ON i.instance_id = l.instance_id AND l.rn = 1
        WHERE i.status = 'active'
        GROUP BY COALESCE(i.industry, 'unspecified')
        ORDER BY instances DESC, industry
    """

    portfolio_time_series = """
        SELECT
            DATE(synced_at)                  AS day,
            COUNT(DISTINCT instance_id)      AS reporting_instances,
            SUM(total_requests)              AS total_requests,
            SUM(total_spend)                 AS total_spend,
            SUM(unique_users)                AS unique_users,
            SUM(dlp_blocks)                  AS dlp_blocks,
            SUM(error_count)                 AS error_count,
            AVG(compliance_score)            AS avg_compliance
        FROM governance_telemetry
        WHERE synced_at >= NOW() - INTERVAL :days DAY
        GROUP BY DATE(synced_at)
        ORDER BY day
    """

    portfolio_at_risk = """
        WITH latest AS (
            SELECT instance_id, total_spend, compliance_score, error_count,
                   keyword_flags_critical, dlp_blocks, synced_at,
                   ROW_NUMBER() OVER (PARTITION BY instance_id ORDER BY synced_at DESC) AS rn
            FROM governance_telemetry
        )
        SELECT
            i.instance_id, i.instance_name, i.industry, i.last_sync_at,
            COALESCE(l.compliance_score, 0)       AS compliance_score,
            COALESCE(l.error_count, 0)            AS error_count,
            COALESCE(l.keyword_flags_critical, 0) AS critical_flags,
            COALESCE(l.dlp_blocks, 0)             AS dlp_blocks,
            COALESCE(l.total_spend, 0)            AS total_spend,
            CASE
                WHEN i.last_sync_at IS NULL OR i.last_sync_at < NOW() - INTERVAL 24 HOUR THEN 'stale_telemetry'
                WHEN l.compliance_score IS NOT NULL AND l.compliance_score < :compliance_threshold THEN 'low_compliance'
                WHEN l.keyword_flags_critical > :critical_flag_threshold THEN 'critical_flags'
                WHEN l.error_count > :error_threshold THEN 'high_error_rate'
                ELSE 'ok'
            END AS risk_reason
        FROM governance_instances i
        LEFT JOIN latest l ON i.instance_id = l.instance_id AND l.rn = 1
        WHERE i.status = 'active' AND (
              i.last_sync_at IS NULL OR i.last_sync_at < NOW() - INTERVAL 24 HOUR
           OR (l.compliance_score IS NOT NULL AND l.compliance_score < :compliance_threshold)
           OR l.keyword_flags_critical > :critical_flag_threshold
           OR l.error_count > :error_threshold
        )
        ORDER BY i.instance_name
    """

    portfolio_identity_totals = """
        SELECT
            COUNT(DISTINCT CONCAT(instance_id, '|', keycloak_user_id)) AS total_users,
            COUNT(DISTINCT instance_id)                                AS instances_with_identity
        FROM governance_identity_users
        WHERE enabled = 1
    """


def _get_dialect_class():
    d = _dialect()
    if d == "mssql":
        return _MSSQL
    elif d in ("mariadb", "mysql"):
        return _MariaDB
    return _PostgreSQL


class _SQLProxy:
    """Lazy proxy that resolves SQL at access time based on current dialect."""
    def __getattr__(self, name):
        cls = _get_dialect_class()
        return getattr(cls, name)


SQL = _SQLProxy()
