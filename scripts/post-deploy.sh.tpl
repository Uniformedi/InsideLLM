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
# Create default teams in LiteLLM
# ---------------------------------------------------------------------------
log "Creating default teams..."

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
log "  Open WebUI:   https://$VM_IP"
log "  LiteLLM UI:   https://$VM_IP/litellm/ui/chat"
log "  LiteLLM API:  https://$VM_IP/v1"
log ""
log "  First user to register on Open WebUI"
log "  becomes the admin."
log ""
log "  Claude Code CLI config:"
log "    export ANTHROPIC_BASE_URL=http://${vm_fqdn}:4000"
log "    export ANTHROPIC_AUTH_TOKEN=<your-litellm-key>"
log ""
log "=========================================="
