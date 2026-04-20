# InsideLLM runtime secrets — consumed by Docker Compose variable
# substitution. Written by cloud-init to /opt/InsideLLM/.env (0600, root).
#
# Do not commit. Do not bake into images. Do not log.
#
# Docker Compose auto-reads .env from the same directory as the compose
# file, so `$${VAR}` tokens in docker-compose.yml substitute from here at
# `docker compose up` time — the rendered compose on disk never contains
# these values.

# --- Gateway / LLM API keys -------------------------------------------------
LITELLM_MASTER_KEY=${litellm_master_key}
# LITELLM_SALT_KEY encrypts virtual keys in LiteLLM's DB. Stability across
# container recreates is critical — lose this and all previously-issued
# virtual keys become unreadable.
LITELLM_SALT_KEY=${litellm_salt_key}
ANTHROPIC_API_KEY=${anthropic_api_key}
OPENAI_API_KEY=${openai_api_key}
GEMINI_API_KEY=${gemini_api_key}
MISTRAL_API_KEY=${mistral_api_key}
COHERE_API_KEY=${cohere_api_key}
AZURE_OPENAI_API_KEY=${azure_openai_api_key}

# --- Database / cache -------------------------------------------------------
POSTGRES_PASSWORD=${postgres_password}

# --- Frontend secrets -------------------------------------------------------
WEBUI_SECRET_KEY=${webui_secret}
GRAFANA_ADMIN_PASSWORD=${grafana_admin_password}

# --- SSO (OIDC) -------------------------------------------------------------
SSO_CLIENT_SECRET=${sso_client_secret}

# --- LDAP bind (Grafana / Open WebUI / pgAdmin lookup account) -------------
LDAP_APP_PASSWORD=${ldap_bind_password}

# --- Hyper-V management (WinRM creds for /governance/hosts) ----------------
HYPERV_PASSWORD=${hyperv_password}

# --- Guacamole (remote access gateway) auth backend in Postgres -------------
GUACAMOLE_DB_PASSWORD=${guacamole_db_password}

# --- Fleet edge shared secret ----------------------------------------------
# Backends require X-Edge-Secret header match from the edge router before
# trusting forwarded X-User-* claims. Rotate with coordinated restart.
FLEET_EDGE_SECRET=${fleet_edge_secret}

# --- n8n webhook HMAC secret (P3.1) ----------------------------------------
# Gov-hub dispatcher signs outbound webhook calls; n8n workflows verify.
# Empty when n8n_enable=false.
N8N_WEBHOOK_SECRET=${n8n_webhook_secret}

# --- Activepieces secrets (P3.2) -------------------------------------------
# AP_ENCRYPTION_KEY encrypts credentials in Activepieces' DB — stable
# across re-applies or all stored creds become unreadable.
# AP_JWT_SECRET signs editor session tokens.
# ACTIVEPIECES_WEBHOOK_SECRET is the HMAC shared between gov-hub's
# dispatcher and Activepieces Code-step verifiers.
AP_ENCRYPTION_KEY=${activepieces_encryption_key}
AP_JWT_SECRET=${activepieces_jwt_secret}
ACTIVEPIECES_WEBHOOK_SECRET=${activepieces_webhook_secret}

# --- Teams/Slack/email notification webhooks (P2.1) ------------------------
# Empty by default. Paste the Incoming Webhook URL from Teams or Slack
# here (or edit /opt/InsideLLM/.env on the VM) to activate outbound
# notifications for agent publish approvals, at-risk alerts, etc. Every
# send passes through the DLP sidecar scanner before leaving the VM.
TEAMS_WEBHOOK_DEFAULT=
SLACK_WEBHOOK_DEFAULT=
SMTP_HOST=
