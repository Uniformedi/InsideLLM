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
        FROM governance_instances ORDER BY instance_name
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
        FROM governance_instances ORDER BY instance_name
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
