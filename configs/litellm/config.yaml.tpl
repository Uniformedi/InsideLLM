# =============================================================================
# LiteLLM Proxy Configuration
# Managed by Terraform — do not edit manually
# =============================================================================

model_list:
  # --- Claude Sonnet (default — best cost/performance ratio) ---
  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-5-20250929
      api_key: os.environ/ANTHROPIC_API_KEY

%{ if enable_haiku ~}
  # --- Claude Haiku (cheapest — for simple queries) ---
  - model_name: claude-haiku
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY
%{ endif ~}

%{ if enable_opus ~}
  # --- Claude Opus (most capable — for complex reasoning) ---
  - model_name: claude-opus
    litellm_params:
      model: anthropic/claude-opus-4-6
      api_key: os.environ/ANTHROPIC_API_KEY
%{ endif ~}

# =============================================================================
# LiteLLM Settings
# =============================================================================
litellm_settings:
  # Drop unsupported params instead of erroring
  drop_params: true

  # Enable dynamic rate limiting
  callbacks: ["dynamic_rate_limiter_v3"]

  # Count total tokens for rate limit enforcement
  token_rate_limit_type: "total"

  # Cache settings (in-memory for speed)
  cache: true
  cache_params:
    type: redis
    host: redis
    port: 6379

  # Default budget for new users
  default_internal_user_params:
    max_budget: ${default_user_budget}
    budget_duration: "1d"
    tpm_limit: ${default_user_tpm}
    rpm_limit: ${default_user_rpm}

  # Success and failure callbacks for audit logging
  success_callback: ["langfuse"]
  failure_callback: ["langfuse"]

# =============================================================================
# General Settings
# =============================================================================
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  allow_user_auth: true

  # Global budget guard
  global_max_parallel_requests: 50
  max_budget: ${global_max_budget}
  budget_duration: "30d"

  # Enable the admin UI
  enable_jwt_auth: false
  ui_access_mode: "all"

  # Alerting on budget thresholds
  alerting:
    - "slack"
  alerting_threshold: 0.8  # Alert at 80% budget consumption

# =============================================================================
# Environment Variables Reference
# =============================================================================
environment_variables:
  ANTHROPIC_API_KEY: os.environ/ANTHROPIC_API_KEY
  LITELLM_MASTER_KEY: os.environ/LITELLM_MASTER_KEY
  DATABASE_URL: os.environ/DATABASE_URL
