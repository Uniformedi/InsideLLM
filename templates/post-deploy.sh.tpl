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
# Provision the Open WebUI service account used by Governance Hub's
# skill-sync bridge. Idempotent — script exits 0 if the key is already
# in /opt/InsideLLM/.env.
# ---------------------------------------------------------------------------
if [ -x /opt/InsideLLM/scripts/provision-owui-service-account.sh ]; then
  log "Provisioning Open WebUI service account for governance-hub..."
  # INSTANCE_ID is interpolated from Terraform so the service account's
  # email carries the VM identity — critical for cross-fleet audit.
  # Each instance's governance-hub now attributes as a distinct
  # governance-hub@svc.insidellm-<vm_name>.local in OWUI's logs.
  INSTANCE_ID="${instance_id}" \
    bash /opt/InsideLLM/scripts/provision-owui-service-account.sh || \
    log "WARNING: Open WebUI service-account provisioning failed (non-fatal)"
else
  log "Skipping Open WebUI service-account provisioning (script missing)"
fi

# ---------------------------------------------------------------------------
# Register the legacy Open WebUI DLP pipeline as INACTIVE.
#
# As of platform 3.x, DLP runs at the LiteLLM gateway via
# callbacks/dlp_guardrail.py — that path is faster (one fewer hop), covers
# all clients (CLI/API, not just the WebUI), and avoids double-scanning.
#
# The WebUI pipeline is still installed but registered inactive so admins
# can flip it on for belt-and-suspenders if they want a frontend pre-filter
# (e.g. to block before the message even crosses into LiteLLM's address
# space). Operators can toggle it via Admin > Functions.
# ---------------------------------------------------------------------------
log "Registering legacy WebUI DLP pipeline (inactive — LiteLLM guardrail is the active path)..."

docker exec insidellm-open-webui python3 -c "
import sys
sys.path.insert(0, '/app/backend')

from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

FUNC_ID = 'dlp_filter'
SYSTEM_USER = '00000000-0000-0000-0000-000000000000'

with open('/app/backend/pipelines/dlp-pipeline.py', 'r') as f:
    code = f.read()

existing = Functions.get_function_by_id(FUNC_ID)
if existing:
    # Preserve the operator's current is_active setting on upgrades; only
    # refresh the code so they don't get silently downgraded.
    Functions.update_function_by_id(FUNC_ID, {'content': code})
    print('DLP filter code refreshed (active state preserved)')
else:
    form = FunctionForm(
        id=FUNC_ID,
        name='DLP Filter Pipeline (legacy WebUI-only)',
        content=code,
        meta=FunctionMeta(
            description='Legacy WebUI-only DLP. As of 3.x the active DLP runs in LiteLLM and covers all clients. Enable this only if you want an additional frontend pre-filter.',
            manifest={}
        )
    )
    result = Functions.insert_new_function(SYSTEM_USER, 'filter', form)
    if result:
        Functions.update_function_by_id(result.id, {'is_active': False, 'is_global': False})
        print(f'DLP filter registered as INACTIVE (id={result.id}); LiteLLM guardrail is the active path')
    else:
        print('ERROR: Failed to register DLP filter')
        sys.exit(1)
" >> "$LOG" 2>&1 || log "WARNING: DLP pipeline registration failed — manage manually via Admin > Functions"

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

%{ if policy_engine_enable ~}
# ---------------------------------------------------------------------------
# Wait for OPA and register the policy enforcement pipeline
# ---------------------------------------------------------------------------
log "Waiting for OPA Policy Agent..."
OPA_ATTEMPTS=0
OPA_MAX=20
while [ $OPA_ATTEMPTS -lt $OPA_MAX ]; do
  if docker exec insidellm-opa wget -q --spider http://localhost:8181/health 2>/dev/null; then
    log "OPA is healthy"
    break
  fi
  OPA_ATTEMPTS=$((OPA_ATTEMPTS + 1))
  log "Waiting for OPA... ($OPA_ATTEMPTS/$OPA_MAX)"
  sleep 3
done

log "Registering OPA Policy Pipeline in Open WebUI..."
docker exec insidellm-open-webui python3 -c "
import sys
sys.path.insert(0, '/app/backend')

from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

FUNC_ID = 'opa_policy_filter'
SYSTEM_USER = '00000000-0000-0000-0000-000000000000'

with open('/app/backend/pipelines/opa-policy-pipeline.py', 'r') as f:
    code = f.read()

existing = Functions.get_function_by_id(FUNC_ID)
if existing:
    Functions.update_function_by_id(FUNC_ID, {
        'content': code,
        'is_active': True,
        'is_global': True
    })
    print('OPA Policy Pipeline updated and activated')
else:
    form = FunctionForm(
        id=FUNC_ID,
        name='OPA Policy Enforcement',
        content=code,
        meta=FunctionMeta(
            description='Enforces Humility alignment and industry policies via Open Policy Agent. Fail-closed on errors.',
            manifest={}
        )
    )
    result = Functions.insert_new_function(SYSTEM_USER, 'filter', form)
    if result:
        Functions.update_function_by_id(result.id, {'is_active': True, 'is_global': True})
        print(f'OPA Policy Pipeline registered (id={result.id})')
    else:
        print('ERROR: Failed to register OPA Policy Pipeline')
        sys.exit(1)
" >> "$LOG" 2>&1 || log "WARNING: OPA Policy Pipeline registration failed"
%{ endif ~}

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
log "Seeding Open WebUI model visibility (public)..."
# Mark all models surfaced by LiteLLM as public so regular users see them.
# Idempotent — re-running updates the same rows. Safe if OWUI isn't up yet
# (we retry a few times).
docker exec insidellm-open-webui python3 <<'PYEOF' || log "  [warn] model-visibility seed failed (non-fatal)"
import os, sys, time, json
from urllib import request, error

base = "http://litellm:4000/v1"
key = os.environ.get("OPENAI_API_KEY", "")
if not key:
    print("no OPENAI_API_KEY; skipping"); sys.exit(0)

# Fetch models from LiteLLM
def fetch():
    req = request.Request(base + "/models", headers={"Authorization": f"Bearer {key}"})
    with request.urlopen(req, timeout=5) as r:
        return json.load(r).get("data", [])

models = []
for attempt in range(6):
    try:
        models = fetch(); break
    except Exception as e:
        print(f"litellm models fetch retry {attempt}: {e}"); time.sleep(5)

if not models:
    print("no models found"); sys.exit(0)

# Mark each model public via Open WebUI internal DB
sys.path.insert(0, "/app/backend")
try:
    from open_webui.models.models import Models, ModelForm, ModelMeta, ModelParams
except Exception as e:
    print(f"open_webui import failed: {e}"); sys.exit(0)

for m in models:
    mid = m["id"]
    try:
        existing = Models.get_model_by_id(mid)
        if existing:
            Models.update_model_by_id(mid, ModelForm(
                id=mid, name=existing.name or mid,
                meta=existing.meta or ModelMeta(),
                params=existing.params or ModelParams(),
                access_control=None,  # None == public in OWUI
                is_active=True,
            ))
            print(f"updated (public): {mid}")
        else:
            Models.insert_new_model(ModelForm(
                id=mid, name=mid,
                meta=ModelMeta(),
                params=ModelParams(),
                access_control=None,
                is_active=True,
            ), user_id="system")
            print(f"created (public): {mid}")
    except Exception as e:
        print(f"failed {mid}: {e}")
PYEOF
log "  done."

# ---------------------------------------------------------------------------
# Break-glass local admin account
#
# Seeds a single local admin — username `insidellm-admin`, password =
# LITELLM_MASTER_KEY — in every bundled service that has its own local auth
# DB. Idempotent: re-running after a master-key rotation updates passwords
# in place. Each block is fail-soft (non-fatal) so one bad service can't
# abort the deploy. Never echo the password to the log.
# ---------------------------------------------------------------------------
log ""
log "Seeding break-glass admin (insidellm-admin) across bundled services..."

# Load master key from .env without printing it.
BG_USER="insidellm-admin"
BG_PASS="$(grep -E '^LITELLM_MASTER_KEY=' /opt/InsideLLM/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//")"
# Grafana admin password is used to auth into Grafana's admin API.
GF_ADMIN_PASS="$(grep -E '^GRAFANA_ADMIN_PASSWORD=' /opt/InsideLLM/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//")"

if [ -z "$BG_PASS" ]; then
  log "  [warn] LITELLM_MASTER_KEY not found in /opt/InsideLLM/.env; skipping break-glass seed"
else

  # --- Grafana ---------------------------------------------------------------
  if docker ps --format '{{.Names}}' | grep -q '^insidellm-grafana$'; then
    log "  [grafana] seeding break-glass admin..."
    (
      set -e
      GF_URL="http://localhost:3000"
      # Wait briefly for Grafana API
      for i in 1 2 3 4 5 6; do
        if docker exec insidellm-grafana wget -q --spider "$GF_URL/api/health" 2>/dev/null; then break; fi
        sleep 3
      done
      # Look up user by login (auth as admin:GF_ADMIN_PASS)
      USER_JSON=$(docker exec -e U="$BG_USER" -e P="$GF_ADMIN_PASS" insidellm-grafana \
        sh -c 'curl -sf -u "admin:$P" "http://localhost:3000/api/users/lookup?loginOrEmail=$U"' 2>/dev/null || echo "")
      if echo "$USER_JSON" | grep -q '"id"'; then
        UID_GF=$(echo "$USER_JSON" | sed -n 's/.*"id":\([0-9]*\).*/\1/p' | head -n1)
        # Update password
        docker exec -e P="$GF_ADMIN_PASS" -e NEWPW="$BG_PASS" insidellm-grafana \
          sh -c 'curl -sf -u "admin:$P" -H "Content-Type: application/json" -X PUT "http://localhost:3000/api/admin/users/'"$UID_GF"'/password" -d "{\"password\":\"$NEWPW\"}"' >/dev/null
        # Ensure Grafana server-admin flag
        docker exec -e P="$GF_ADMIN_PASS" insidellm-grafana \
          sh -c 'curl -sf -u "admin:$P" -H "Content-Type: application/json" -X PUT "http://localhost:3000/api/admin/users/'"$UID_GF"'/permissions" -d "{\"isGrafanaAdmin\":true}"' >/dev/null
        log "    [grafana] updated break-glass admin password"
      else
        # Create user
        docker exec -e U="$BG_USER" -e P="$GF_ADMIN_PASS" -e NEWPW="$BG_PASS" insidellm-grafana \
          sh -c 'curl -sf -u "admin:$P" -H "Content-Type: application/json" -X POST "http://localhost:3000/api/admin/users" -d "{\"name\":\"InsideLLM Break-Glass\",\"login\":\"$U\",\"email\":\"insidellm-admin@local\",\"password\":\"$NEWPW\"}"' >/dev/null
        NEW_JSON=$(docker exec -e U="$BG_USER" -e P="$GF_ADMIN_PASS" insidellm-grafana \
          sh -c 'curl -sf -u "admin:$P" "http://localhost:3000/api/users/lookup?loginOrEmail=$U"')
        UID_GF=$(echo "$NEW_JSON" | sed -n 's/.*"id":\([0-9]*\).*/\1/p' | head -n1)
        docker exec -e P="$GF_ADMIN_PASS" insidellm-grafana \
          sh -c 'curl -sf -u "admin:$P" -H "Content-Type: application/json" -X PUT "http://localhost:3000/api/admin/users/'"$UID_GF"'/permissions" -d "{\"isGrafanaAdmin\":true}"' >/dev/null
        log "    [grafana] seeded new break-glass admin"
      fi
    ) || log "  [warn] break-glass seed for Grafana failed (non-fatal)"
  fi

  # --- Open WebUI ------------------------------------------------------------
  if docker ps --format '{{.Names}}' | grep -q '^insidellm-open-webui$'; then
    log "  [open-webui] seeding break-glass admin..."
    docker exec -e BG_USER="$BG_USER" -e BG_PASS="$BG_PASS" insidellm-open-webui python3 <<'PYEOF' >> "$LOG" 2>&1 || log "  [warn] break-glass seed for Open WebUI failed (non-fatal)"
import os, sys, traceback, uuid
sys.path.insert(0, "/app/backend")
try:
    from open_webui.models.users import Users
    from open_webui.models.auths import Auths
    from open_webui.utils.auth import get_password_hash

    u = os.environ["BG_USER"]
    p = os.environ["BG_PASS"]
    # OWUI validates emails against a standard regex; "@local" is rejected.
    email = f"{u}@insidellm.local"
    pw_hash = get_password_hash(p)

    existing = Users.get_user_by_email(email)
    if existing:
        Users.update_user_role_by_id(existing.id, "admin")
        try:
            Auths.update_user_password_by_id(existing.id, pw_hash)
        except Exception:
            Auths.update_password_by_id(existing.id, pw_hash)
        print("open-webui: updated break-glass admin")
    else:
        uid = str(uuid.uuid4())
        # insert_new_auth requires an explicit id in recent OWUI versions.
        try:
            Auths.insert_new_auth(
                id=uid, email=email, password=pw_hash,
                name="InsideLLM Break-Glass",
                profile_image_url="/user.png", role="admin",
            )
        except TypeError:
            # Older signature (no id kwarg)
            Auths.insert_new_auth(
                email=email, password=pw_hash,
                name="InsideLLM Break-Glass",
                profile_image_url="/user.png", role="admin",
            )
        print("open-webui: created break-glass admin")
except Exception as e:
    print(f"open-webui seed ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)
PYEOF
  fi

  # --- LiteLLM ---------------------------------------------------------------
  if docker ps --format '{{.Names}}' | grep -q '^insidellm-litellm$'; then
    log "  [litellm] seeding break-glass admin user row..."
    (
      set -e
      EXIST=$(curl -sf -H "Authorization: Bearer $LITELLM_KEY" \
        "$LITELLM_URL/user/info?user_id=$BG_USER" 2>/dev/null || echo "")
      if echo "$EXIST" | grep -q '"user_id"'; then
        curl -sf -X POST "$LITELLM_URL/user/update" \
          -H "Authorization: Bearer $LITELLM_KEY" \
          -H "Content-Type: application/json" \
          -d "{\"user_id\":\"$BG_USER\",\"user_role\":\"proxy_admin\",\"user_email\":\"insidellm-admin@local\"}" >/dev/null
        log "    [litellm] updated break-glass admin user (proxy_admin)"
      else
        curl -sf -X POST "$LITELLM_URL/user/new" \
          -H "Authorization: Bearer $LITELLM_KEY" \
          -H "Content-Type: application/json" \
          -d "{\"user_id\":\"$BG_USER\",\"user_role\":\"proxy_admin\",\"user_email\":\"insidellm-admin@local\",\"auto_create_key\":false}" >/dev/null
        log "    [litellm] created break-glass admin user (proxy_admin)"
      fi
      # Note: the master key itself already grants proxy_admin; no virtual
      # key is minted here to avoid duplicating the secret material.
    ) || log "  [warn] break-glass seed for LiteLLM failed (non-fatal)"
  fi

  # --- Uptime Kuma -----------------------------------------------------------
  if docker ps --format '{{.Names}}' | grep -q '^insidellm-uptime-kuma$'; then
    log "  [uptime-kuma] seeding break-glass admin..."
    (
      set -e
      # Try the first-run setup API first (works only when no user exists).
      SETUP_RESP=$(docker exec -e U="$BG_USER" -e P="$BG_PASS" insidellm-uptime-kuma \
        sh -c 'wget -qO- --header="Content-Type: application/json" --post-data="{\"username\":\"$U\",\"password\":\"$P\"}" http://localhost:3001/api/setup 2>/dev/null || true')
      # If a user already exists, patch sqlite directly. Kuma uses bcryptjs
      # hashes in the `user` table (`password` column).
      COUNT=$(docker exec insidellm-uptime-kuma sh -c 'sqlite3 /app/data/kuma.db "SELECT COUNT(*) FROM user;"' 2>/dev/null || echo "0")
      if [ "$COUNT" -gt 0 ]; then
        # Generate bcrypt hash inside the Kuma container (node + bcryptjs bundled).
        HASH=$(docker exec -e PW="$BG_PASS" insidellm-uptime-kuma \
          node -e 'const b=require("bcryptjs");process.stdout.write(b.hashSync(process.env.PW,10));' 2>/dev/null)
        if [ -n "$HASH" ]; then
          # Upsert: update if exists, else insert. Using parameterized-ish single statement.
          docker exec -e U="$BG_USER" -e H="$HASH" insidellm-uptime-kuma \
            sh -c 'sqlite3 /app/data/kuma.db "INSERT INTO user (username, password, active) VALUES ('"'"'$U'"'"', '"'"'$H'"'"', 1) ON CONFLICT(username) DO UPDATE SET password='"'"'$H'"'"', active=1;"' >/dev/null
          log "    [uptime-kuma] upserted break-glass admin via sqlite"
        else
          log "  [warn] break-glass seed for Uptime Kuma failed (bcrypt hash) (non-fatal)"
        fi
      else
        log "    [uptime-kuma] setup API called for first-run admin"
      fi
    ) || log "  [warn] break-glass seed for Uptime Kuma failed (non-fatal)"
  fi

  # --- pgAdmin ---------------------------------------------------------------
  if docker ps --format '{{.Names}}' | grep -q '^insidellm-pgadmin$'; then
    log "  [pgadmin] seeding break-glass admin..."
    (
      set -e
      PGA_EMAIL="insidellm-admin@insidellm.local"
      # pgAdmin 8.x+ ships /pgadmin4/setup.py using typer subcommands.
      # Older/minor images may lack typer or use argparse — both stderr paths
      # swallowed to keep the log clean; we fall back to a direct SQLAlchemy
      # seed if the CLI path fails entirely.
      if docker exec insidellm-pgadmin sh -c "test -f /pgadmin4/setup.py" 2>/dev/null; then
        if docker exec -e E="$PGA_EMAIL" -e P="$BG_PASS" insidellm-pgadmin \
             sh -c 'python /pgadmin4/setup.py update-user "$E" --password "$P"' >/dev/null 2>&1; then
          log "    [pgadmin] updated break-glass admin password"
        elif docker exec -e E="$PGA_EMAIL" -e P="$BG_PASS" insidellm-pgadmin \
             sh -c 'python /pgadmin4/setup.py add-user "$E" "$P" --admin' >/dev/null 2>&1; then
          log "    [pgadmin] created break-glass admin"
        else
          log "    [pgadmin] setup.py CLI unavailable; attempting direct DB seed..."
          docker exec -e E="$PGA_EMAIL" -e P="$BG_PASS" insidellm-pgadmin python <<'PGAEOF' >> "$LOG" 2>&1 \
            && log "    [pgadmin] seeded via direct DB insert" \
            || log "    [warn] pgAdmin direct DB seed failed (non-fatal)"
import os, sys
sys.path.insert(0, "/pgadmin4")
os.environ.setdefault("SERVER_MODE", "True")
try:
    from pgadmin.model import db, User, Role
    from pgadmin import create_app
    from werkzeug.security import generate_password_hash
    app = create_app()
    with app.app_context():
        email = os.environ["E"]
        pw = os.environ["P"]
        u = User.query.filter_by(email=email).first()
        admin_role = Role.query.filter_by(name="Administrator").first()
        if u:
            u.password = generate_password_hash(pw)
            if admin_role and admin_role not in u.roles:
                u.roles.append(admin_role)
        else:
            u = User(email=email, password=generate_password_hash(pw), active=True)
            if admin_role:
                u.roles.append(admin_role)
            db.session.add(u)
        db.session.commit()
        print("pgadmin direct seed ok")
except Exception as e:
    import traceback; traceback.print_exc()
    sys.exit(1)
PGAEOF
        fi
      else
        log "  [warn] /pgadmin4/setup.py not found; skipping pgAdmin break-glass seed (non-fatal)"
      fi
    ) || log "  [warn] break-glass seed for pgAdmin failed (non-fatal)"
  fi

  unset BG_PASS GF_ADMIN_PASS
  log "Break-glass admin seeding complete."
fi

%{ if guacamole_enable ~}
# ---------------------------------------------------------------------------
# Guacamole — first-run seeding
#
# 1. Drop the LDAP auth extension JAR into /opt/InsideLLM/guacamole/extensions
#    so LDAP logins work (skipped if already present or download fails).
# 2. Initialise the `guacamole` database schema in Postgres (idempotent —
#    detected by presence of the `guacamole_user` table).
# 3. Rotate the default guacadmin/guacadmin account to the master key and
#    seed an `insidellm-admin` break-glass admin with SYSTEM_ADMIN rights.
# 4. Seed an RDP + SSH connection for this VM so operators can connect to
#    themselves immediately via the browser.
#
# All failures are logged but non-fatal — Guacamole can still be driven
# manually if seeding hits a snag.
# ---------------------------------------------------------------------------
log ""
log "Configuring Apache Guacamole (browser RDP/VNC/SSH gateway)..."

GUAC_VER="1.5.5"
GUAC_EXT_DIR="/opt/InsideLLM/guacamole/extensions"
GUAC_API="https://localhost/remote/api"
# Master key doubles as the Guacamole admin + insidellm-admin password.
GUAC_PASS="$(grep -E '^LITELLM_MASTER_KEY=' /opt/InsideLLM/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//")"
GUAC_DB_PASS="$(grep -E '^GUACAMOLE_DB_PASSWORD=' /opt/InsideLLM/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//")"
VM_IP_LOCAL="$(hostname -I | awk '{print $1}')"

# --- 1. Download the LDAP extension JAR if we don't already have it --------
mkdir -p "$GUAC_EXT_DIR"
if ! ls "$GUAC_EXT_DIR"/guacamole-auth-ldap-*.jar >/dev/null 2>&1; then
  log "  [guacamole] fetching LDAP auth extension v$GUAC_VER..."
  TMPD=$(mktemp -d)
  if curl -sfL "https://archive.apache.org/dist/guacamole/$GUAC_VER/binary/guacamole-auth-ldap-$GUAC_VER.tar.gz" -o "$TMPD/ldap.tgz" 2>>"$LOG"; then
    if tar -xzf "$TMPD/ldap.tgz" -C "$TMPD" 2>>"$LOG"; then
      if cp "$TMPD"/guacamole-auth-ldap-*/guacamole-auth-ldap-*.jar "$GUAC_EXT_DIR"/ 2>>"$LOG"; then
        chmod 0644 "$GUAC_EXT_DIR"/guacamole-auth-ldap-*.jar
        log "    [guacamole] LDAP extension installed"
        # guacamole container already started before we dropped the jar —
        # restart so it picks the extension up.
        docker restart insidellm-guacamole >/dev/null 2>&1 || true
      else
        log "    [warn] LDAP extension: could not copy JAR (non-fatal)"
      fi
    else
      log "    [warn] LDAP extension: tar extract failed (non-fatal)"
    fi
  else
    log "    [warn] LDAP extension: download failed (non-fatal)"
  fi
  rm -rf "$TMPD"
else
  log "  [guacamole] LDAP extension already present — skipping fetch"
fi

# --- 2. Initialise the guacamole database schema ---------------------------
# Create DB + user inside the main postgres container, idempotent.
docker exec -e PGPASSWORD="$(grep -E '^POSTGRES_PASSWORD=' /opt/InsideLLM/.env | head -n1 | cut -d= -f2- | tr -d '\r\n')" \
  insidellm-postgres psql -U litellm -d postgres -v ON_ERROR_STOP=0 <<EOSQL >> "$LOG" 2>&1 || log "  [warn] guacamole db/user bootstrap may have issues (non-fatal)"
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='guacamole') THEN
    CREATE ROLE guacamole LOGIN PASSWORD '$GUAC_DB_PASS';
  ELSE
    ALTER ROLE guacamole WITH LOGIN PASSWORD '$GUAC_DB_PASS';
  END IF;
END\$\$;
SELECT 'CREATE DATABASE guacamole OWNER guacamole'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='guacamole')\gexec
EOSQL

# Has the schema been applied already? guacamole_user is a stable table name.
SCHEMA_READY=$(docker exec -e PGPASSWORD="$GUAC_DB_PASS" insidellm-postgres \
  psql -U guacamole -d guacamole -tAc "SELECT to_regclass('public.guacamole_user') IS NOT NULL" 2>/dev/null || echo "f")

if [ "$SCHEMA_READY" != "t" ]; then
  log "  [guacamole] applying JDBC auth schema..."
  # Use the schema files bundled inside the guacamole image — avoids GitHub
  # download flakiness and guarantees version alignment with the container.
  # Schema files live under /opt/guacamole/postgresql/schema/.
  (
    set -e
    SCHEMA_OUT=$(docker run --rm --entrypoint "" guacamole/guacamole:"$GUAC_VER" \
      sh -c 'cat /opt/guacamole/postgresql/schema/*.sql' 2>/dev/null)
    if [ -z "$SCHEMA_OUT" ]; then
      # Fallback: pull schema from upstream repo tag.
      SCHEMA_OUT=$( { \
        curl -sfL "https://raw.githubusercontent.com/apache/guacamole-client/$GUAC_VER/extensions/guacamole-auth-jdbc/modules/guacamole-auth-jdbc-postgresql/schema/001-create-schema.sql"; \
        echo; \
        curl -sfL "https://raw.githubusercontent.com/apache/guacamole-client/$GUAC_VER/extensions/guacamole-auth-jdbc/modules/guacamole-auth-jdbc-postgresql/schema/002-create-admin-user.sql"; \
      } )
    fi
    echo "$SCHEMA_OUT" | docker exec -i -e PGPASSWORD="$GUAC_DB_PASS" insidellm-postgres \
      psql -U guacamole -d guacamole -v ON_ERROR_STOP=1 >> "$LOG" 2>&1
    log "    [guacamole] schema applied (default login: guacadmin/guacadmin — rotated below)"
  ) || log "  [warn] guacamole schema init failed (non-fatal — UI will still load but logins will be empty)"
  # Restart guacamole so the JDBC driver sees the fresh schema.
  docker restart insidellm-guacamole >/dev/null 2>&1 || true
else
  log "  [guacamole] schema already present — skipping init"
fi

# Wait for the Guacamole webapp to answer on /remote/ via nginx.
log "  [guacamole] waiting for web UI to come up..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if curl -sk -o /dev/null -w '%%{http_code}' "$GUAC_API/languages" 2>/dev/null | grep -qE '^(200|401|403)$'; then
    break
  fi
  sleep 5
done

# --- 3. Seed break-glass admin via the REST API ----------------------------
# First try default guacadmin creds. If schema had already been rotated in a
# previous run, fall through silently.
if [ -n "$GUAC_PASS" ]; then
  log "  [guacamole] seeding break-glass admin..."
  (
    set -e
    TOKEN_JSON=$(curl -sk -X POST "$GUAC_API/tokens" \
      -d "username=guacadmin&password=guacadmin" 2>/dev/null || echo "")
    if ! echo "$TOKEN_JSON" | grep -q '"authToken"'; then
      # Maybe the password was already rotated to the master key — try that.
      TOKEN_JSON=$(curl -sk -X POST "$GUAC_API/tokens" \
        --data-urlencode "username=guacadmin" \
        --data-urlencode "password=$GUAC_PASS" 2>/dev/null || echo "")
    fi
    TOKEN=$(echo "$TOKEN_JSON" | sed -n 's/.*"authToken"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    if [ -z "$TOKEN" ]; then
      log "    [warn] could not obtain guacadmin session token (non-fatal)"
      exit 0
    fi

    DS="postgresql"
    # Rotate guacadmin password to the master key. Guacamole 1.5.x expects
    # PUT /api/session/data/{ds}/users/{user}/password with old+new body.
    curl -sk -X PUT "$GUAC_API/session/data/$DS/users/guacadmin/password" \
      -H "Guacamole-Token: $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"oldPassword\":\"guacadmin\",\"newPassword\":\"$GUAC_PASS\"}" >/dev/null 2>&1 || true

    # Create (or update) insidellm-admin.
    EXISTS=$(curl -sk -H "Guacamole-Token: $TOKEN" \
      "$GUAC_API/session/data/$DS/users/insidellm-admin" 2>/dev/null || echo "")
    if echo "$EXISTS" | grep -q '"username"'; then
      curl -sk -X PUT "$GUAC_API/session/data/$DS/users/insidellm-admin" \
        -H "Guacamole-Token: $TOKEN" -H "Content-Type: application/json" \
        -d "{\"username\":\"insidellm-admin\",\"password\":\"$GUAC_PASS\",\"attributes\":{\"guac-full-name\":\"InsideLLM Break-Glass\"}}" >/dev/null 2>&1 || true
    else
      curl -sk -X POST "$GUAC_API/session/data/$DS/users" \
        -H "Guacamole-Token: $TOKEN" -H "Content-Type: application/json" \
        -d "{\"username\":\"insidellm-admin\",\"password\":\"$GUAC_PASS\",\"attributes\":{\"guac-full-name\":\"InsideLLM Break-Glass\"}}" >/dev/null 2>&1 || true
    fi

    # Grant SYSTEM_ADMIN + CREATE_CONNECTION etc. via a JSON Patch.
    curl -sk -X PATCH "$GUAC_API/session/data/$DS/users/insidellm-admin/permissions" \
      -H "Guacamole-Token: $TOKEN" -H "Content-Type: application/json" \
      -d '[{"op":"add","path":"/systemPermissions","value":"ADMINISTER"},
            {"op":"add","path":"/systemPermissions","value":"CREATE_CONNECTION"},
            {"op":"add","path":"/systemPermissions","value":"CREATE_CONNECTION_GROUP"},
            {"op":"add","path":"/systemPermissions","value":"CREATE_USER"}]' >/dev/null 2>&1 || true

    log "    [guacamole] seeded break-glass admin (insidellm-admin)"

    # --- 4. Seed RDP + SSH connections for this VM ------------------------
    HN=$(hostname -s)
    for PROTO in rdp ssh; do
      if [ "$PROTO" = "rdp" ]; then
        PORT="3389"
        BODY=$(printf '{"parentIdentifier":"ROOT","name":"RDP: %s","protocol":"rdp","parameters":{"hostname":"%s","port":"3389","ignore-cert":"true","security":"any","resize-method":"display-update"},"attributes":{}}' "$HN" "$VM_IP_LOCAL")
      else
        PORT="22"
        BODY=$(printf '{"parentIdentifier":"ROOT","name":"SSH: %s","protocol":"ssh","parameters":{"hostname":"%s","port":"22"},"attributes":{}}' "$HN" "$VM_IP_LOCAL")
      fi
      # Dedupe by name — list current connections and skip if present.
      EXIST=$(curl -sk -H "Guacamole-Token: $TOKEN" \
        "$GUAC_API/session/data/$DS/connections" 2>/dev/null || echo "")
      if echo "$EXIST" | grep -q "\"$PROTO: $HN\""; then
        log "    [guacamole] connection '$PROTO: $HN' already present"
      else
        curl -sk -X POST "$GUAC_API/session/data/$DS/connections" \
          -H "Guacamole-Token: $TOKEN" -H "Content-Type: application/json" \
          -d "$BODY" >/dev/null 2>&1 \
          && log "    [guacamole] seeded connection '$PROTO: $HN' ($VM_IP_LOCAL:$PORT)" \
          || log "    [warn] failed to seed '$PROTO: $HN' connection (non-fatal)"
      fi
    done

    # Invalidate the token so we don't leak a long-lived admin session.
    curl -sk -X DELETE "$GUAC_API/tokens/$TOKEN" >/dev/null 2>&1 || true
  ) || log "  [warn] guacamole seeding failed (non-fatal)"
fi

unset GUAC_PASS GUAC_DB_PASS
log "Guacamole configuration complete."
%{ endif ~}

%{ if claude_code_enable ~}
# =============================================================================
# Claude Code CLI — installed for the admin user so operators can SSH in and
# troubleshoot with an AI assistant scoped to this VM.
#
# Operators must run `claude login` once (interactive OAuth) to activate it.
# Credentials land in ~/.claude/ under the admin account; not system-wide.
# =============================================================================
log ""
log "Installing Claude Code CLI for ${ssh_admin_user}..."
(
  set -e
  ADMIN_HOME=$(getent passwd "${ssh_admin_user}" | cut -d: -f6)
  if [ -z "$ADMIN_HOME" ] || [ ! -d "$ADMIN_HOME" ]; then
    log "  [warn] admin home for ${ssh_admin_user} not found; skipping Claude Code install"
    exit 0
  fi

  if sudo -u "${ssh_admin_user}" bash -lc "command -v claude" >/dev/null 2>&1; then
    log "  Claude Code already installed — skipping."
  else
    # Official installer; lands at ~/.local/bin/claude by default
    sudo -u "${ssh_admin_user}" bash -lc "curl -fsSL https://claude.ai/install.sh | bash" \
      >> "$LOG" 2>&1 || { log "  [warn] Claude Code installer failed (non-fatal)"; exit 0; }
    log "  Claude Code installed."
  fi

  # Pre-seed a per-VM CLAUDE.md so the first session starts with real context.
  # Lives in /opt/InsideLLM — the natural working directory for ops work.
  CLAUDE_MD="/opt/InsideLLM/CLAUDE.md"
  if [ ! -f "$CLAUDE_MD" ]; then
    cat > "$CLAUDE_MD" <<'MDEOF'
# InsideLLM — this VM

This is an InsideLLM platform node. When troubleshooting, use the facts
below first before searching. They were set at deploy time.

## This VM
- Hostname: __HOSTNAME__
- Role:     __ROLE__
- Dept:     __DEPT__
- Fleet primary: __PRIMARY__

## Useful paths
- /opt/InsideLLM/docker-compose.yml — live rendered compose
- /opt/InsideLLM/.env — secrets (chmod 600; sudo to read)
- /var/log/InsideLLM-deploy.log — cloud-init + post-deploy log
- /opt/InsideLLM/data/ — bind-mounted container volumes
- /opt/InsideLLM/governance-hub/framework/ — governance MD

## Routine commands
- sudo docker ps --format '{{.Names}} {{.Status}}'
- sudo docker logs insidellm-<service> --tail 100
- sudo docker exec insidellm-postgres psql -U litellm -d litellm -c '<sql>'
- Health: curl -sk https://localhost/governance/health | jq

## Break-glass account
- insidellm-admin + LITELLM_MASTER_KEY works on Gov-Hub, Grafana, OWUI,
  LiteLLM, Uptime Kuma, pgAdmin, Guacamole (when enabled).

## Scope
Your changes stay on this VM. For cross-fleet work, use the primary's
scripts/Deploy-Fleet.ps1 on the operator's workstation.
MDEOF
    sed -i "s|__HOSTNAME__|$(hostname)|g; s|__ROLE__|${vm_role}|g; s|__DEPT__|${department}|g; s|__PRIMARY__|${fleet_primary_host}|g" "$CLAUDE_MD"
    chown "${ssh_admin_user}":"${ssh_admin_user}" "$CLAUDE_MD" 2>/dev/null || true
    log "  Wrote per-VM context to /opt/InsideLLM/CLAUDE.md"
  fi
) || log "  [warn] Claude Code setup failed (non-fatal)"
%{ endif ~}

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
%{ if chat_enable ~}
log "  Team Chat:    https://$VM_IP/chat/"
log "    (first user to sign up becomes Mattermost sysadmin)"
%{ endif ~}
%{ if pkg_mirror_enable ~}
log ""
log "  Local package mirrors (point future VMs here to skip upstream traffic):"
log "    apt proxy:        http://$VM_IP:3142"
log "    Docker registry:  http://$VM_IP:5000"
log "    Set apt_mirror_host + docker_mirror_host in peer VMs' terraform.tfvars"
log "    (cache on disk: /opt/InsideLLM/data/apt-cache + /opt/InsideLLM/data/registry)"
%{ endif ~}
%{ if apt_mirror_host != "" || docker_mirror_host != "" ~}
log ""
log "  Using upstream mirrors:"
%{ if apt_mirror_host != "" ~}
log "    apt proxy:        http://${apt_mirror_host}:3142"
%{ endif ~}
%{ if docker_mirror_host != "" ~}
log "    Docker registry:  http://${docker_mirror_host}:5000"
%{ endif ~}
%{ endif ~}
%{ if guacamole_enable ~}
log "  Remote (Guacamole): https://$VM_IP/remote/"
log "    (login: insidellm-admin + LITELLM_MASTER_KEY; guacadmin default rotated)"
%{ endif ~}
%{ if keycloak_enable ~}
log "  Keycloak SSO: https://$VM_IP/keycloak/"
log "    Master admin: insidellm-admin + LITELLM_MASTER_KEY"
log "    Realm imported: ${keycloak_realm_name} (groups: InsideLLM-View/Admin/Approve)"
log "    OIDC issuer for downstream services:"
log "      https://$VM_IP/keycloak/realms/${keycloak_realm_name}"
%{ endif ~}
%{ if n8n_enable ~}
log "  n8n Tool Factory: https://$VM_IP/n8n/"
log "    Basic auth: insidellm-admin + LITELLM_MASTER_KEY"
log "    Catalog entries use backend.type=n8n_webhook; dispatcher signs with"
log "    X-Insidellm-Signature (HMAC-SHA256, secret = N8N_WEBHOOK_SECRET)"
log "    Template workflow: configs/n8n/workflows/verify-signature.json"
%{ endif ~}
%{ if activepieces_enable ~}
log "  Activepieces Tool Factory: https://$VM_IP/activepieces/"
log "    First-user signup on the sign-in page — becomes the admin."
log "    Catalog entries use backend.type=activepieces_trigger; same HMAC"
log "    envelope as n8n (secret = ACTIVEPIECES_WEBHOOK_SECRET)"
%{ endif ~}
%{ if desktop_enable ~}
log "  XFCE Desktop (xrdp): rdp://$VM_IP:3389"
log "    Reachable via Guacamole: https://$VM_IP/remote/"
log "    Login: ${ssh_admin_user} + xrdp_password from /opt/InsideLLM/.env"
log "    Theme: Greybird-Dark + Papirus-Dark (session starts xfce4-session)"
%{ endif ~}
%{ if claude_code_enable ~}
log ""
log "  Claude Code CLI installed for ${ssh_admin_user}."
log "    First run: ssh ${ssh_admin_user}@$VM_IP -- cd /opt/InsideLLM && claude login"
log "    Then: cd /opt/InsideLLM && claude"
log "    Per-VM context in /opt/InsideLLM/CLAUDE.md"
%{ endif ~}
log ""
log "  First user to register on Open WebUI"
log "  becomes the admin."
log ""
log "  Break-glass admin: insidellm-admin (pwd=LITELLM_MASTER_KEY — rotate after incident)"
log ""
log "  Claude Code CLI config:"
log "    export ANTHROPIC_BASE_URL=http://${vm_fqdn}:4000"
log "    export ANTHROPIC_AUTH_TOKEN=<your-litellm-key>"
log ""
log "=========================================="
