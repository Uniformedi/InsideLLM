#!/bin/bash
# =============================================================================
# Post-deployment configuration for Inside LLM
# Runs inside the VM after Docker containers are healthy
# Managed by Terraform — do not edit manually
# =============================================================================

set -euo pipefail

LITELLM_URL="http://localhost:4000"
LITELLM_KEY="${litellm_master_key}"
LOG="/var/log/InsideLLM-deploy.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

wait_for_service() {
  local url="$1"
  local name="$2"
  local max_attempts=30
  local attempt=0

  while [ $attempt -lt $max_attempts ]; do
    if curl -sf "$url" > /dev/null 2>&1; then
      log "$name is healthy"
      return 0
    fi
    attempt=$((attempt + 1))
    log "Waiting for $name... ($attempt/$max_attempts)"
    sleep 5
  done

  log "WARNING: $name did not become healthy within timeout"
  return 1
}

# ---------------------------------------------------------------------------
# Wait for services
# ---------------------------------------------------------------------------
log "=== Starting post-deployment configuration ==="

wait_for_service "$LITELLM_URL/health/liveliness" "LiteLLM"
wait_for_service "http://localhost:8080/health" "Open WebUI"

# ---------------------------------------------------------------------------
# Register DLP pipeline as a global filter in Open WebUI
# ---------------------------------------------------------------------------
log "Registering DLP pipeline as a global filter..."

docker exec insidellm-open-webui python3 -c "
import sys
sys.path.insert(0, '/app/backend')

from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

FUNC_ID = 'dlp_filter'
SYSTEM_USER = '00000000-0000-0000-0000-000000000000'

with open('/app/backend/pipelines/dlp-pipeline.py', 'r') as f:
    code = f.read()

# Update if already registered, otherwise create new
existing = Functions.get_function_by_id(FUNC_ID)
if existing:
    Functions.update_function_by_id(FUNC_ID, {
        'content': code,
        'is_active': True,
        'is_global': True
    })
    print('DLP filter updated and activated')
else:
    form = FunctionForm(
        id=FUNC_ID,
        name='DLP Filter Pipeline',
        content=code,
        meta=FunctionMeta(
            description='Data Loss Prevention filter that scans messages and files for PII, PHI, SSNs, credit cards, API keys, and connection strings.',
            manifest={}
        )
    )
    result = Functions.insert_new_function(SYSTEM_USER, 'filter', form)
    if result:
        Functions.update_function_by_id(result.id, {'is_active': True, 'is_global': True})
        print(f'DLP filter registered and activated (id={result.id})')
    else:
        print('ERROR: Failed to register DLP filter')
        sys.exit(1)
" >> "$LOG" 2>&1 || log "WARNING: DLP pipeline registration failed — register manually via Admin > Functions"

# ---------------------------------------------------------------------------
# Create teams in LiteLLM
# ---------------------------------------------------------------------------
log "Creating teams..."

%{ if length(sso_group_mapping) > 0 ~}
# --- Teams from SSO group mapping ---
%{ for group_name, config in sso_group_mapping ~}
log "Creating team for SSO group '${group_name}'..."
jq -n \
  --arg alias "${group_name}" \
  --argjson budget ${config.budget} \
  --arg duration "${config.budget_duration}" \
  --argjson tpm ${config.tpm_limit} \
  --argjson rpm ${config.rpm_limit} \
  '{"team_alias":$alias,"max_budget":$budget,"budget_duration":$duration,"tpm_limit":$tpm,"rpm_limit":$rpm,"models":${jsonencode(config.models)}}' \
| curl -sf -X POST "$LITELLM_URL/team/new" \
  -H "Authorization: Bearer $LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d @- >> "$LOG" 2>&1 || log "Team '${group_name}' may already exist"

%{ endfor ~}
%{ else ~}
# --- Default teams (no SSO group mapping configured) ---

# Admin team (IT / Development)
curl -sf -X POST "$LITELLM_URL/team/new" \
  -H "Authorization: Bearer $LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "team_alias": "administrators",
    "max_budget": 0,
    "budget_duration": "30d",
    "tpm_limit": 500000,
    "rpm_limit": 100,
    "models": ["claude-sonnet", "claude-haiku", "claude-opus"]
  }' >> "$LOG" 2>&1 || log "Team 'administrators' may already exist"

# General users team
curl -sf -X POST "$LITELLM_URL/team/new" \
  -H "Authorization: Bearer $LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "team_alias": "general-users",
    "max_budget": ${default_user_budget},
    "budget_duration": "1d",
    "tpm_limit": 100000,
    "rpm_limit": 30,
    "models": ["claude-sonnet", "claude-haiku"]
  }' >> "$LOG" 2>&1 || log "Team 'general-users' may already exist"

# Power users team (analysts, managers)
curl -sf -X POST "$LITELLM_URL/team/new" \
  -H "Authorization: Bearer $LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "team_alias": "power-users",
    "max_budget": 20,
    "budget_duration": "1d",
    "tpm_limit": 200000,
    "rpm_limit": 60,
    "models": ["claude-sonnet", "claude-haiku", "claude-opus"]
  }' >> "$LOG" 2>&1 || log "Team 'power-users' may already exist"
%{ endif ~}

# ---------------------------------------------------------------------------
# Create a default admin API key
# ---------------------------------------------------------------------------
log "Generating default admin API key..."

ADMIN_KEY_RESPONSE=$(curl -sf -X POST "$LITELLM_URL/key/generate" \
  -H "Authorization: Bearer $LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "key_alias": "admin-default-key",
    "max_budget": 0,
    "models": ["claude-sonnet", "claude-haiku", "claude-opus"],
    "metadata": {"purpose": "admin-api-access"}
  }' 2>/dev/null || echo '{"key":"generation-failed"}')

log "Admin key response saved to log"
echo "$ADMIN_KEY_RESPONSE" >> "$LOG"

# ---------------------------------------------------------------------------
# Verify model availability
# ---------------------------------------------------------------------------
log "Verifying model configuration..."

MODELS=$(curl -sf "$LITELLM_URL/v1/models" \
  -H "Authorization: Bearer $LITELLM_KEY" 2>/dev/null || echo "failed")

if echo "$MODELS" | grep -q "claude-sonnet"; then
  log "✅ claude-sonnet model available"
else
  log "⚠️  claude-sonnet model NOT detected — check API key"
fi

if echo "$MODELS" | grep -q "claude-haiku"; then
  log "✅ claude-haiku model available"
fi

if echo "$MODELS" | grep -q "claude-opus"; then
  log "✅ claude-opus model available"
fi

# ---------------------------------------------------------------------------
# Create PostgreSQL convenience views (lowercase, no quoting needed)
# ---------------------------------------------------------------------------
log "Creating database convenience views..."
docker exec insidellm-postgres psql -U litellm -d litellm -c "
CREATE OR REPLACE VIEW spend_logs AS SELECT
  request_id, call_type, api_key, spend, total_tokens, prompt_tokens,
  completion_tokens, \"startTime\" AS start_time, \"endTime\" AS end_time,
  model, model_group, \"user\" AS username, team_id, end_user,
  requester_ip_address, messages, response, request_tags, cache_hit,
  status, request_duration_ms
FROM \"LiteLLM_SpendLogs\";

CREATE OR REPLACE VIEW audit_log AS SELECT * FROM \"LiteLLM_AuditLog\";
CREATE OR REPLACE VIEW users AS SELECT * FROM \"LiteLLM_UserTable\";
CREATE OR REPLACE VIEW teams AS SELECT * FROM \"LiteLLM_TeamTable\";
CREATE OR REPLACE VIEW api_keys AS SELECT * FROM \"LiteLLM_VerificationToken\";
CREATE OR REPLACE VIEW daily_user_spend AS SELECT * FROM \"LiteLLM_DailyUserSpend\";
CREATE OR REPLACE VIEW daily_team_spend AS SELECT * FROM \"LiteLLM_DailyTeamSpend\";
CREATE OR REPLACE VIEW error_logs AS SELECT * FROM \"LiteLLM_ErrorLogs\";
CREATE OR REPLACE VIEW models AS SELECT * FROM \"LiteLLM_ModelTable\";
CREATE OR REPLACE VIEW budgets AS SELECT * FROM \"LiteLLM_BudgetTable\";
" >> "$LOG" 2>&1 || log "WARNING: Failed to create views"
log "Database views created"

# ---------------------------------------------------------------------------
# Create keyword analysis tables, views, and materialized views
# ---------------------------------------------------------------------------
log "Creating keyword analysis infrastructure..."
docker exec insidellm-postgres psql -U litellm -d litellm -c "
-- ==========================================================================
-- Keyword category dictionary — configurable word-to-category mapping
-- ==========================================================================
CREATE TABLE IF NOT EXISTS keyword_categories (
  id SERIAL PRIMARY KEY,
  category TEXT NOT NULL,
  keyword TEXT NOT NULL,
  severity TEXT DEFAULT 'info',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(category, keyword)
);

-- Seed default categories aligned with AI Governance Framework
INSERT INTO keyword_categories (category, keyword, severity) VALUES
  -- Collections / Material Decisions (Tier 1 flags)
  ('collections', 'debt', 'high'),
  ('collections', 'collection', 'high'),
  ('collections', 'payment plan', 'high'),
  ('collections', 'settlement', 'high'),
  ('collections', 'overdue', 'high'),
  ('collections', 'delinquent', 'high'),
  ('collections', 'garnishment', 'high'),
  ('collections', 'repossession', 'high'),
  ('collections', 'charge-off', 'high'),
  ('collections', 'creditor', 'medium'),
  ('collections', 'debtor', 'medium'),
  -- Legal / Compliance
  ('legal', 'fdcpa', 'critical'),
  ('legal', 'fcra', 'critical'),
  ('legal', 'tcpa', 'critical'),
  ('legal', 'regulation f', 'critical'),
  ('legal', 'cfpb', 'critical'),
  ('legal', 'ecoa', 'critical'),
  ('legal', 'lawsuit', 'high'),
  ('legal', 'litigation', 'high'),
  ('legal', 'subpoena', 'high'),
  ('legal', 'compliance', 'medium'),
  ('legal', 'regulatory', 'medium'),
  ('legal', 'legal', 'medium'),
  ('legal', 'attorney', 'medium'),
  -- Code / Development (Tier 3)
  ('development', 'code', 'info'),
  ('development', 'function', 'info'),
  ('development', 'api', 'info'),
  ('development', 'debug', 'info'),
  ('development', 'refactor', 'info'),
  ('development', 'deploy', 'info'),
  ('development', 'database', 'info'),
  ('development', 'script', 'info'),
  -- Research / Analysis (Tier 2-3)
  ('research', 'analyze', 'info'),
  ('research', 'research', 'info'),
  ('research', 'report', 'info'),
  ('research', 'summarize', 'info'),
  ('research', 'compare', 'info'),
  ('research', 'data', 'info'),
  -- Content / Writing (Tier 3)
  ('content', 'write', 'info'),
  ('content', 'draft', 'info'),
  ('content', 'email', 'info'),
  ('content', 'letter', 'info'),
  ('content', 'template', 'info'),
  ('content', 'document', 'info'),
  -- PII / Sensitive (should be caught by DLP but flag for audit)
  ('pii_mention', 'social security', 'critical'),
  ('pii_mention', 'ssn', 'critical'),
  ('pii_mention', 'credit card', 'critical'),
  ('pii_mention', 'account number', 'high'),
  ('pii_mention', 'date of birth', 'high'),
  ('pii_mention', 'medical record', 'critical'),
  ('pii_mention', 'password', 'high'),
  ('pii_mention', 'api key', 'high')
ON CONFLICT (category, keyword) DO NOTHING;
%{ for cat, keywords in keyword_categories ~}
%{ for kw in keywords ~}
INSERT INTO keyword_categories (category, keyword, severity)
VALUES ('${cat}', '${kw}', 'medium')
ON CONFLICT (category, keyword) DO NOTHING;
%{ endfor ~}
%{ endfor ~}

-- ==========================================================================
-- View: message_content — extracts user message text from JSONB
-- ==========================================================================
CREATE OR REPLACE VIEW message_content AS
SELECT
  s.request_id,
  s.\"startTime\" AS request_time,
  s.\"user\" AS username,
  s.team_id,
  s.model,
  s.spend,
  s.total_tokens,
  msg->>'role' AS message_role,
  msg->>'content' AS message_text,
  to_tsvector('english', COALESCE(msg->>'content', '')) AS search_vector
FROM \"LiteLLM_SpendLogs\" s,
LATERAL jsonb_array_elements(
  CASE
    WHEN s.messages IS NOT NULL AND s.messages::text != 'null' AND s.messages::text != ''
    THEN s.messages::jsonb
    ELSE '[]'::jsonb
  END
) AS msg
WHERE msg->>'role' = 'user';

-- ==========================================================================
-- View: keyword_matches — joins messages against the keyword dictionary
-- ==========================================================================
CREATE OR REPLACE VIEW keyword_matches AS
SELECT
  mc.request_id,
  mc.request_time,
  mc.username,
  mc.team_id,
  mc.model,
  mc.spend,
  kc.category,
  kc.keyword,
  kc.severity
FROM message_content mc
JOIN keyword_categories kc
  ON mc.search_vector @@ plainto_tsquery('english', kc.keyword);

-- ==========================================================================
-- Materialized view: keyword_daily_summary — refreshed on schedule
-- ==========================================================================
DROP MATERIALIZED VIEW IF EXISTS keyword_daily_summary;
CREATE MATERIALIZED VIEW keyword_daily_summary AS
SELECT
  date_trunc('day', request_time) AS day,
  category,
  keyword,
  severity,
  team_id,
  COUNT(*) AS match_count,
  COUNT(DISTINCT username) AS unique_users,
  ROUND(SUM(spend)::numeric, 4) AS total_spend
FROM keyword_matches
GROUP BY 1, 2, 3, 4, 5;

CREATE UNIQUE INDEX IF NOT EXISTS idx_kds_day_cat_kw_team
  ON keyword_daily_summary (day, category, keyword, severity, team_id);

-- ==========================================================================
-- Materialized view: topic_distribution — category totals for pie chart
-- ==========================================================================
DROP MATERIALIZED VIEW IF EXISTS topic_distribution;
CREATE MATERIALIZED VIEW topic_distribution AS
SELECT
  category,
  COUNT(*) AS total_matches,
  COUNT(DISTINCT request_id) AS unique_requests,
  COUNT(DISTINCT username) AS unique_users
FROM keyword_matches
WHERE request_time > NOW() - INTERVAL '30 days'
GROUP BY category;

-- ==========================================================================
-- View: flagged_requests — high/critical keyword hits for compliance review
-- ==========================================================================
CREATE OR REPLACE VIEW flagged_requests AS
SELECT
  km.request_id,
  km.request_time,
  km.username,
  km.team_id,
  km.model,
  km.category,
  km.keyword,
  km.severity,
  km.spend,
  mc.message_text
FROM keyword_matches km
JOIN message_content mc USING (request_id)
WHERE km.severity IN ('critical', 'high')
ORDER BY km.request_time DESC;

-- ==========================================================================
-- Function to refresh materialized views (called by cron)
-- ==========================================================================
CREATE OR REPLACE FUNCTION refresh_keyword_views() RETURNS void AS \$\$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY keyword_daily_summary;
  REFRESH MATERIALIZED VIEW topic_distribution;
END;
\$\$ LANGUAGE plpgsql;
" >> "$LOG" 2>&1 || log "WARNING: Failed to create keyword analysis views"
log "Keyword analysis infrastructure created"

%{ if governance_hub_enable ~}
# ---------------------------------------------------------------------------
# Wait for Governance Hub and register the advisor tool
# ---------------------------------------------------------------------------
log "Waiting for Governance Hub..."
GOV_ATTEMPTS=0
GOV_MAX=30
while [ $GOV_ATTEMPTS -lt $GOV_MAX ]; do
  if docker exec insidellm-governance-hub curl -sf http://localhost:8090/health > /dev/null 2>&1; then
    log "Governance Hub is healthy"
    break
  fi
  GOV_ATTEMPTS=$((GOV_ATTEMPTS + 1))
  log "Waiting for Governance Hub... ($GOV_ATTEMPTS/$GOV_MAX)"
  sleep 5
done

log "Registering Governance Advisor tool in Open WebUI..."
docker exec insidellm-open-webui python3 -c "
import sys
sys.path.insert(0, '/app/backend')

from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

FUNC_ID = 'governance_advisor'
SYSTEM_USER = '00000000-0000-0000-0000-000000000000'

with open('/app/backend/pipelines/governance-advisor-tool.py', 'r') as f:
    code = f.read()

existing = Functions.get_function_by_id(FUNC_ID)
if existing:
    Functions.update_function_by_id(FUNC_ID, {
        'content': code,
        'is_active': True,
        'is_global': True
    })
    print('Governance Advisor tool updated and activated')
else:
    form = FunctionForm(
        id=FUNC_ID,
        name='AI Governance Advisor',
        content=code,
        meta=FunctionMeta(
            description='Analyze governance data and suggest framework improvements. All suggestions require supervisor approval.',
            manifest={}
        )
    )
    result = Functions.insert_new_function(SYSTEM_USER, 'tool', form)
    if result:
        Functions.update_function_by_id(result.id, {'is_active': True, 'is_global': True})
        print(f'Governance Advisor tool registered (id={result.id})')
    else:
        print('ERROR: Failed to register Governance Advisor tool')
        sys.exit(1)
" >> "$LOG" 2>&1 || log "WARNING: Governance Advisor tool registration failed"

log "Registering Fleet Management tool in Open WebUI..."
docker exec insidellm-open-webui python3 -c "
import sys
sys.path.insert(0, '/app/backend')

from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

FUNC_ID = 'fleet_management'
SYSTEM_USER = '00000000-0000-0000-0000-000000000000'

with open('/app/backend/pipelines/fleet-management-tool.py', 'r') as f:
    code = f.read()

existing = Functions.get_function_by_id(FUNC_ID)
if existing:
    Functions.update_function_by_id(FUNC_ID, {
        'content': code,
        'is_active': True,
        'is_global': True
    })
    print('Fleet Management tool updated and activated')
else:
    form = FunctionForm(
        id=FUNC_ID,
        name='Fleet Management',
        content=code,
        meta=FunctionMeta(
            description='Manage multiple InsideLLM deployments - view instances, compare configs, restore from snapshots.',
            manifest={}
        )
    )
    result = Functions.insert_new_function(SYSTEM_USER, 'tool', form)
    if result:
        Functions.update_function_by_id(result.id, {'is_active': True, 'is_global': True})
        print(f'Fleet Management tool registered (id={result.id})')
    else:
        print('ERROR: Failed to register Fleet Management tool')
        sys.exit(1)
" >> "$LOG" 2>&1 || log "WARNING: Fleet Management tool registration failed"

log "Registering AI System Designer tool in Open WebUI..."
docker exec insidellm-open-webui python3 -c "
import sys
sys.path.insert(0, '/app/backend')

from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

FUNC_ID = 'system_designer'
SYSTEM_USER = '00000000-0000-0000-0000-000000000000'

with open('/app/backend/pipelines/system-designer-tool.py', 'r') as f:
    code = f.read()

existing = Functions.get_function_by_id(FUNC_ID)
if existing:
    Functions.update_function_by_id(FUNC_ID, {
        'content': code,
        'is_active': True,
        'is_global': True
    })
    print('AI System Designer tool updated and activated')
else:
    form = FunctionForm(
        id=FUNC_ID,
        name='AI System Designer',
        content=code,
        meta=FunctionMeta(
            description='Design InsideLLM deployments, generate optimized configurations, plan multi-instance architectures, and model cost projections.',
            manifest={}
        )
    )
    result = Functions.insert_new_function(SYSTEM_USER, 'tool', form)
    if result:
        Functions.update_function_by_id(result.id, {'is_active': True, 'is_global': True})
        print(f'AI System Designer tool registered (id={result.id})')
    else:
        print('ERROR: Failed to register AI System Designer tool')
        sys.exit(1)
" >> "$LOG" 2>&1 || log "WARNING: AI System Designer tool registration failed"

log "Registering Data Connector tool in Open WebUI..."
docker exec insidellm-open-webui python3 -c "
import sys
sys.path.insert(0, '/app/backend')

from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

FUNC_ID = 'data_connector'
SYSTEM_USER = '00000000-0000-0000-0000-000000000000'

with open('/app/backend/pipelines/data-connector-tool.py', 'r') as f:
    code = f.read()

existing = Functions.get_function_by_id(FUNC_ID)
if existing:
    Functions.update_function_by_id(FUNC_ID, {
        'content': code,
        'is_active': True,
        'is_global': True
    })
    print('Data Connector tool updated and activated')
else:
    form = FunctionForm(
        id=FUNC_ID,
        name='Data Connector',
        content=code,
        meta=FunctionMeta(
            description='Query external data sources for cross-referencing. Team-based access control with full audit logging.',
            manifest={}
        )
    )
    result = Functions.insert_new_function(SYSTEM_USER, 'tool', form)
    if result:
        Functions.update_function_by_id(result.id, {'is_active': True, 'is_global': True})
        print(f'Data Connector tool registered (id={result.id})')
    else:
        print('ERROR: Failed to register Data Connector tool')
        sys.exit(1)
" >> "$LOG" 2>&1 || log "WARNING: Data Connector tool registration failed"
%{ endif ~}

%{ if docforge_enable ~}
# ---------------------------------------------------------------------------
# Wait for DocForge and register as an Open WebUI Tool
# ---------------------------------------------------------------------------
log "Waiting for DocForge service..."
DOCFORGE_ATTEMPTS=0
DOCFORGE_MAX=20
while [ $DOCFORGE_ATTEMPTS -lt $DOCFORGE_MAX ]; do
  if docker exec insidellm-docforge curl -sf http://localhost:3000/health > /dev/null 2>&1; then
    log "DocForge is healthy"
    break
  fi
  DOCFORGE_ATTEMPTS=$((DOCFORGE_ATTEMPTS + 1))
  log "Waiting for DocForge... ($DOCFORGE_ATTEMPTS/$DOCFORGE_MAX)"
  sleep 5
done
if [ $DOCFORGE_ATTEMPTS -eq $DOCFORGE_MAX ]; then
  log "WARNING: DocForge did not become healthy within timeout"
fi

log "Registering DocForge tool in Open WebUI..."
docker exec insidellm-open-webui python3 -c "
import sys
sys.path.insert(0, '/app/backend')

from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

FUNC_ID = 'docforge_tool'
SYSTEM_USER = '00000000-0000-0000-0000-000000000000'

with open('/app/backend/pipelines/docforge-tool.py', 'r') as f:
    code = f.read()

existing = Functions.get_function_by_id(FUNC_ID)
if existing:
    Functions.update_function_by_id(FUNC_ID, {
        'content': code,
        'is_active': True,
        'is_global': True
    })
    print('DocForge tool updated and activated')
else:
    form = FunctionForm(
        id=FUNC_ID,
        name='DocForge - File Generation & Conversion',
        content=code,
        meta=FunctionMeta(
            description='Generate and convert documents (DOCX, XLSX, PPTX, PDF, CSV, and more) from structured data.',
            manifest={}
        )
    )
    result = Functions.insert_new_function(SYSTEM_USER, 'tool', form)
    if result:
        Functions.update_function_by_id(result.id, {'is_active': True, 'is_global': True})
        print(f'DocForge tool registered and activated (id={result.id})')
    else:
        print('ERROR: Failed to register DocForge tool')
        sys.exit(1)
" >> "$LOG" 2>&1 || log "WARNING: DocForge tool registration failed — register manually via Admin > Functions"
%{ endif ~}

%{ if ollama_enable ~}
# ---------------------------------------------------------------------------
# Pull Ollama models via docker exec (reliable for large downloads)
# ---------------------------------------------------------------------------
log "Pulling Ollama models..."
%{ for model in ollama_models ~}
log "Pulling ${model}..."
docker exec insidellm-ollama ollama pull ${model} >> "$LOG" 2>&1 || log "WARNING: Failed to pull ${model}"
%{ endfor ~}
log "Ollama model pull complete"
%{ endif ~}

# ---------------------------------------------------------------------------
# Create systemd service for auto-start on boot
# ---------------------------------------------------------------------------
log "Creating systemd service for auto-start..."

cat > /etc/systemd/system/InsideLLM.service << 'SYSTEMD'
[Unit]
Description=Inside LLM (Docker Compose)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/InsideLLM
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable InsideLLM.service
log "Systemd service created and enabled"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
VM_IP=$(hostname -I | awk '{print $1}')

log ""
log "=========================================="
log "  Inside LLM — READY"
log "=========================================="
log ""
log "  Admin Portal: https://$VM_IP/admin"
log "  Open WebUI:   https://$VM_IP"
log "  LiteLLM UI:   https://$VM_IP/litellm/ui/chat"
log "  LiteLLM API:  https://$VM_IP/v1"
log "  Netdata:      https://$VM_IP/netdata/"
log "  pgAdmin:      http://$VM_IP:5050"
%{ if docforge_enable ~}
log "  DocForge:     https://$VM_IP/docforge/api/formats"
%{ endif ~}
%{ if governance_hub_enable ~}
log "  Governance:   https://$VM_IP/governance/health"
%{ endif ~}
%{ if ops_grafana_enable ~}
log "  Grafana:      https://$VM_IP/grafana/"
%{ endif ~}
%{ if ops_uptime_kuma_enable ~}
log "  Uptime Kuma:  https://$VM_IP/status/"
%{ endif ~}
log ""
log "  First user to register on Open WebUI"
log "  becomes the admin."
log ""
log "  Claude Code CLI config:"
log "    export ANTHROPIC_BASE_URL=http://${vm_fqdn}:4000"
log "    export ANTHROPIC_AUTH_TOKEN=<your-litellm-key>"
log ""
log "=========================================="
