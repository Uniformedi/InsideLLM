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

%{ if openai_enable ~}
  # --- OpenAI ---
  - model_name: gpt-4o
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY
  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
%{ endif ~}

%{ if gemini_enable ~}
  # --- Google Gemini ---
  - model_name: gemini-1.5-pro
    litellm_params:
      model: gemini/gemini-1.5-pro
      api_key: os.environ/GEMINI_API_KEY
  - model_name: gemini-1.5-flash
    litellm_params:
      model: gemini/gemini-1.5-flash
      api_key: os.environ/GEMINI_API_KEY
%{ endif ~}

%{ if mistral_enable ~}
  # --- Mistral ---
  - model_name: mistral-large
    litellm_params:
      model: mistral/mistral-large-latest
      api_key: os.environ/MISTRAL_API_KEY
%{ endif ~}

%{ if cohere_enable ~}
  # --- Cohere ---
  - model_name: command-r-plus
    litellm_params:
      model: cohere/command-r-plus
      api_key: os.environ/COHERE_API_KEY
%{ endif ~}

%{ if azure_openai_enable ~}
  # --- Azure OpenAI ---
  - model_name: azure-${azure_openai_deployment}
    litellm_params:
      model: azure/${azure_openai_deployment}
      api_key: os.environ/AZURE_OPENAI_API_KEY
      api_base: ${azure_openai_endpoint}
      api_version: "${azure_openai_api_version}"
%{ endif ~}

%{ if bedrock_enable ~}
  # --- AWS Bedrock ---
  - model_name: bedrock-claude
    litellm_params:
      model: bedrock/${bedrock_model}
      aws_region_name: ${bedrock_region}
%{ endif ~}

%{ if ollama_enable ~}
%{ for model in ollama_models ~}
  # --- Local Ollama: ${model} ---
  - model_name: "ollama/${model}"
    litellm_params:
      model: "ollama/${model}"
      api_base: ${ollama_api_base}
%{ endfor ~}
%{ endif ~}

# =============================================================================
# LiteLLM Settings
# =============================================================================
litellm_settings:
  # Drop unsupported params instead of erroring
  drop_params: true

  # Enable dynamic rate limiting + Humility (prompt + guardrail) + DLP guardrail
  callbacks: ["dynamic_rate_limiter_v3", "callbacks.humility_prompt.HumilityPromptCallback", "callbacks.humility_guardrail.HumilityGuardrailCallback", "callbacks.dlp_guardrail.DLPGuardrailCallback"]
  custom_callback_path: "/app/callbacks"

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
  server_root_path: "/litellm"
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  allow_user_auth: true

  # Global budget guard
  global_max_parallel_requests: 50
  max_budget: ${global_max_budget}
  budget_duration: "30d"

  # Admin UI and authentication
  enable_jwt_auth: ${sso_enabled ? "true" : "false"}
  ui_access_mode: "all"
%{ if sso_group_mapping_enabled ~}

  # SSO Group-to-Team mapping via JWT claims
  litellm_jwtauth:
    team_id_jwt_field: "${sso_group_field}"
    team_id_upsert: false
%{ endif ~}

  # Alerting on budget thresholds
  alerting:
    - "slack"
  alerting_threshold: 0.8  # Alert at 80% budget consumption

# =============================================================================
# Environment Variables Reference
# =============================================================================
environment_variables:
  ANTHROPIC_API_KEY: os.environ/ANTHROPIC_API_KEY
  OPENAI_API_KEY: os.environ/OPENAI_API_KEY
  GEMINI_API_KEY: os.environ/GEMINI_API_KEY
  MISTRAL_API_KEY: os.environ/MISTRAL_API_KEY
  COHERE_API_KEY: os.environ/COHERE_API_KEY
  AZURE_OPENAI_API_KEY: os.environ/AZURE_OPENAI_API_KEY
  AWS_ACCESS_KEY_ID: os.environ/AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY: os.environ/AWS_SECRET_ACCESS_KEY
  LITELLM_MASTER_KEY: os.environ/LITELLM_MASTER_KEY
  DATABASE_URL: os.environ/DATABASE_URL
