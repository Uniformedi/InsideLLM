# =============================================================================
# Docker Compose: Inside LLM
# Managed by Terraform — do not edit manually
# =============================================================================

services:
  # -------------------------------------------------------------------------
  # PostgreSQL — LiteLLM state, spend tracking, audit logs
  # -------------------------------------------------------------------------
  postgres:
    image: postgres:16-alpine
    container_name: insidellm-postgres
    restart: always
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD: "${postgres_password}"
    volumes:
      - /opt/InsideLLM/data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U litellm"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Redis — Rate limit counters, budget enforcement, LiteLLM state
  # -------------------------------------------------------------------------
  redis:
    image: redis:7-alpine
    container_name: insidellm-redis
    restart: always
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - /opt/InsideLLM/data/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # LiteLLM Proxy — API Gateway, SSO, Budgets, Rate Limiting
  # -------------------------------------------------------------------------
  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: insidellm-litellm
    restart: always
    ports:
      - "4000:4000"
    environment:
      DATABASE_URL: "postgresql://litellm:${postgres_password}@postgres:5432/litellm"
      STORE_MODEL_IN_DB: "True"
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      LITELLM_MASTER_KEY: "${litellm_master_key}"
      ANTHROPIC_API_KEY: "${anthropic_api_key}"
      LITELLM_LOG: "INFO"
      SERVER_ROOT_PATH: "/litellm"
      GOVERNANCE_TIER: "${governance_hub_tier}"
      POLICY_ENGINE_ENABLE: "${policy_engine_enable}"
      POLICY_ENGINE_FAIL_MODE: "${policy_engine_fail_mode}"
%{ if policy_engine_enable ~}
      OPA_URL: "http://opa:8181"
%{ endif ~}
%{ if governance_hub_enable ~}
      GOVERNANCE_HUB_URL: "http://governance-hub:8090"
%{ endif ~}
      # --- DLP Guardrail (Layer 2 — gateway-level, covers all clients) ---
      DLP_ENABLED: "${dlp_enabled}"
      DLP_MODE: "${dlp_mode}"
      DLP_BLOCK_SSN: "${dlp_block_ssn}"
      DLP_BLOCK_CREDIT_CARDS: "${dlp_block_credit_cards}"
      DLP_BLOCK_PHI: "${dlp_block_phi}"
      DLP_BLOCK_CREDENTIALS: "${dlp_block_credentials}"
      DLP_BLOCK_BANK_ACCOUNTS: "${dlp_block_bank_accounts}"
      DLP_BLOCK_STANDALONE_DATES: "${dlp_block_standalone_dates}"
      DLP_SCAN_RESPONSES: "${dlp_scan_responses}"
      DLP_LOG_DETECTIONS: "true"
      DLP_CUSTOM_PATTERNS: '${dlp_custom_patterns}'
      UI_USERNAME: "admin"
      UI_PASSWORD: "${litellm_master_key}"
%{ if sso_provider == "azure_ad" ~}
      # --- Azure AD SSO ---
      MICROSOFT_CLIENT_ID: "${sso_env["MICROSOFT_CLIENT_ID"]}"
      MICROSOFT_CLIENT_SECRET: "${sso_env["MICROSOFT_CLIENT_SECRET"]}"
      MICROSOFT_TENANT: "${sso_env["MICROSOFT_TENANT"]}"
%{ endif ~}
%{ if sso_provider == "okta" ~}
      # --- Okta SSO ---
      GENERIC_CLIENT_ID: "${sso_env["GENERIC_CLIENT_ID"]}"
      GENERIC_CLIENT_SECRET: "${sso_env["GENERIC_CLIENT_SECRET"]}"
      GENERIC_AUTHORIZATION_ENDPOINT: "${sso_env["GENERIC_AUTHORIZATION_ENDPOINT"]}"
      GENERIC_TOKEN_ENDPOINT: "${sso_env["GENERIC_TOKEN_ENDPOINT"]}"
      GENERIC_USERINFO_ENDPOINT: "${sso_env["GENERIC_USERINFO_ENDPOINT"]}"
      GENERIC_USER_ID_ATTRIBUTE: "sub"
      GENERIC_USER_EMAIL_ATTRIBUTE: "email"
      GENERIC_USER_DISPLAY_NAME_ATTRIBUTE: "name"
%{ endif ~}
    volumes:
      - /opt/InsideLLM/litellm-config.yaml:/app/config.yaml
      - /opt/InsideLLM/litellm-callbacks:/app/callbacks:ro
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "3"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
%{ if ollama_enable ~}
      ollama:
        condition: service_healthy
%{ endif ~}
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:4000/health/liveliness')\""]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 300s
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Open WebUI — Chat Interface, RAG, DLP Pipelines
  # -------------------------------------------------------------------------
  open-webui:
    image: ghcr.io/open-webui/open-webui:latest
    container_name: insidellm-open-webui
    restart: always
    ports:
      - "8080:8080"
    environment:
      # Route all API calls through LiteLLM
      OPENAI_API_BASE_URL: "http://litellm:4000/v1"
      OPENAI_API_KEY: "${litellm_master_key}"

      # WebUI settings
      WEBUI_SECRET_KEY: "${webui_secret}"
      WEBUI_NAME: "InsideLLM"
      ENABLE_SIGNUP: "true"
      DEFAULT_USER_ROLE: "user"
      ENABLE_COMMUNITY_SHARING: "false"

      # RAG settings — use built-in sentence-transformers (no external API needed)
      RAG_EMBEDDING_ENGINE: ""
      RAG_EMBEDDING_MODEL: "sentence-transformers/all-MiniLM-L6-v2"
      CHUNK_SIZE: "1500"
      CHUNK_OVERLAP: "100"
      RAG_FULL_CONTEXT: "true"

      # Security
      WEBUI_AUTH: "true"
%{ if sso_provider != "none" }
      # SSO / OIDC
      ENABLE_OAUTH_SIGNUP: "true"
      OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"
%{ if sso_provider == "azure_ad" }
      OAUTH_PROVIDER_NAME: "Microsoft"
      OAUTH_CLIENT_ID: "${sso_client_id}"
      OAUTH_CLIENT_SECRET: "${sso_client_secret}"
      OPENID_PROVIDER_URL: "https://login.microsoftonline.com/${sso_tenant_id}/v2.0/.well-known/openid-configuration"
      OAUTH_SCOPES: "openid email profile"
%{ endif }
%{ if sso_provider == "okta" }
      OAUTH_PROVIDER_NAME: "Okta"
      OAUTH_CLIENT_ID: "${sso_client_id}"
      OAUTH_CLIENT_SECRET: "${sso_client_secret}"
      OPENID_PROVIDER_URL: "https://${sso_okta_domain}/.well-known/openid-configuration"
      OAUTH_SCOPES: "openid email profile"
%{ endif }
%{ endif }
    volumes:
      - /opt/InsideLLM/data/open-webui:/app/backend/data
      - /opt/InsideLLM/pipelines:/app/backend/pipelines
    depends_on:
      litellm:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 300s
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Nginx — Reverse Proxy + TLS Termination
  # -------------------------------------------------------------------------
  nginx:
    image: nginx:1.27-alpine
    container_name: insidellm-nginx
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /opt/InsideLLM/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - /opt/InsideLLM/nginx/ssl:/etc/nginx/ssl:ro
      - /opt/InsideLLM/admin.html:/opt/InsideLLM/admin.html:ro
      - /opt/InsideLLM/Setup.html:/opt/InsideLLM/Setup.html:ro
    depends_on:
      open-webui:
        condition: service_healthy
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # pgAdmin — Database Administration UI
  # -------------------------------------------------------------------------
  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: insidellm-pgadmin
    restart: always
    ports:
      - "5050:80"
    environment:
      PGADMIN_DEFAULT_EMAIL: "admin@insidellm.local"
      PGADMIN_DEFAULT_PASSWORD: "${litellm_master_key}"
      PGADMIN_CONFIG_SERVER_MODE: "True"
    volumes:
      - /opt/InsideLLM/data/pgadmin:/var/lib/pgadmin
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Netdata — Real-time System Monitoring
  # -------------------------------------------------------------------------
  netdata:
    image: netdata/netdata:stable
    container_name: insidellm-netdata
    restart: always
    pid: host
    cap_add:
      - SYS_PTRACE
      - SYS_ADMIN
    security_opt:
      - apparmor:unconfined
    volumes:
      - /etc/passwd:/host/etc/passwd:ro
      - /etc/group:/host/etc/group:ro
      - /etc/localtime:/etc/localtime:ro
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /opt/InsideLLM/data/netdata:/var/lib/netdata
    environment:
      NETDATA_CLAIM_TOKEN: ""
      NETDATA_EXTRA_DEB_PACKAGES: ""
      DOCKER_HOST: "unix:///var/run/docker.sock"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:19999/api/v1/info"]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ if docforge_enable ~}
  # -------------------------------------------------------------------------
  # DocForge — File Generation & Conversion Service
  # -------------------------------------------------------------------------
  docforge:
    build:
      context: /opt/InsideLLM/docforge
      dockerfile: Dockerfile
    container_name: insidellm-docforge
    restart: always
    volumes:
      - /opt/InsideLLM/data/docforge:/app/data
    environment:
      PORT: "3000"
      TEMP_DIR: "/app/data/temp"
    deploy:
      resources:
        limits:
          memory: 2G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}
%{ if ollama_enable ~}
  # -------------------------------------------------------------------------
  # Ollama — Local LLM Inference Engine
  # -------------------------------------------------------------------------
  ollama:
    image: ollama/ollama:latest
    container_name: insidellm-ollama
    restart: always
    ports:
      - "11434:11434"
    volumes:
      - /opt/InsideLLM/data/ollama:/root/.ollama
%{ if ollama_gpu ~}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
%{ endif ~}
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 300s
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}

%{ if policy_engine_enable ~}
  # -------------------------------------------------------------------------
  # OPA — Open Policy Agent (Policy Enforcement)
  # -------------------------------------------------------------------------
  opa:
    image: openpolicyagent/opa:latest
    container_name: insidellm-opa
    restart: always
    command:
      - "run"
      - "--server"
      - "--addr=:8181"
      - "--log-level=info"
      - "/policies"
    volumes:
      - /opt/InsideLLM/opa/policies:/policies:ro
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://localhost:8181/health || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}
%{ if governance_hub_enable ~}
  # -------------------------------------------------------------------------
  # Governance Hub — Central Sync, Change Management, AI Advisor
  # -------------------------------------------------------------------------
  governance-hub:
    build:
      context: /opt/InsideLLM/governance-hub
      dockerfile: Dockerfile
    container_name: insidellm-governance-hub
    restart: always
    environment:
      GOVERNANCE_HUB_DATABASE_URL: "postgresql+asyncpg://litellm:${postgres_password}@postgres:5432/litellm"
      # Central fleet DB is configured via the Admin UI Fleet tab (stored in local DB)
      GOVERNANCE_HUB_PLATFORM_VERSION: "${platform_version}"
      GOVERNANCE_HUB_INSTANCE_ID: "${governance_hub_instance_id}"
      GOVERNANCE_HUB_INSTANCE_NAME: "${governance_hub_instance_name}"
      GOVERNANCE_HUB_SYNC_SCHEDULE: "${governance_hub_sync_schedule}"
      GOVERNANCE_HUB_SUPERVISOR_EMAILS: "${governance_hub_supervisor_emails}"
      GOVERNANCE_HUB_HUB_SECRET: "${governance_hub_secret}"
      GOVERNANCE_HUB_LITELLM_URL: "http://litellm:4000"
      GOVERNANCE_HUB_LITELLM_API_KEY: "${litellm_master_key}"
      GOVERNANCE_HUB_ADVISOR_MODEL: "${governance_hub_advisor_model}"
%{ if governance_hub_registration_token != "" }
      GOVERNANCE_HUB_REGISTRATION_TOKEN: "${governance_hub_registration_token}"
%{ endif }
      GOVERNANCE_HUB_INDUSTRY: "${governance_hub_industry}"
      GOVERNANCE_HUB_GOVERNANCE_TIER: "${governance_hub_tier}"
      GOVERNANCE_HUB_DATA_CLASSIFICATION: "${governance_hub_classification}"
      GOVERNANCE_HUB_ADMIN_AUTH_MODE: "${admin_auth_mode}"
      GOVERNANCE_HUB_AUTH_SECRET: "${governance_hub_secret}"
%{ if admin_auth_mode == "ldap" }
      GOVERNANCE_HUB_AD_DOMAIN: "${ad_domain}"
      GOVERNANCE_HUB_AD_ADMIN_GROUPS: "${ad_admin_groups}"
%{ endif }
%{ if admin_auth_mode == "oidc" }
      GOVERNANCE_HUB_OIDC_ISSUER_URL: "${oidc_issuer_url}"
      GOVERNANCE_HUB_OIDC_CLIENT_ID: "${sso_client_id}"
      GOVERNANCE_HUB_OIDC_CLIENT_SECRET: "${sso_client_secret}"
%{ endif }
    volumes:
      - /opt/InsideLLM/data/governance-hub:/app/data
      - /opt/InsideLLM/governance-hub/framework:/app/framework:ro
    depends_on:
      postgres:
        condition: service_healthy
      litellm:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8090/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}
%{ if ops_watchtower_enable ~}
  # -------------------------------------------------------------------------
  # Watchtower — Automatic Container Image Updates
  # -------------------------------------------------------------------------
  watchtower:
    image: containrrr/watchtower:latest
    container_name: insidellm-watchtower
    restart: always
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_SCHEDULE: "0 0 4 * * *"
      WATCHTOWER_ROLLING_RESTART: "true"
      WATCHTOWER_INCLUDE_STOPPED: "false"
      WATCHTOWER_LABEL_ENABLE: "false"
%{ if ops_alert_webhook != "" ~}
      WATCHTOWER_NOTIFICATION_URL: "${ops_alert_webhook}"
%{ endif ~}
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}
%{ if ops_grafana_enable ~}
  # -------------------------------------------------------------------------
  # Loki — Log Aggregation
  # -------------------------------------------------------------------------
  loki:
    image: grafana/loki:latest
    container_name: insidellm-loki
    restart: always
    volumes:
      - /opt/InsideLLM/loki/loki-config.yml:/etc/loki/local-config.yaml:ro
      - /opt/InsideLLM/data/loki:/loki
    command: -config.file=/etc/loki/local-config.yaml
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:3100/ready || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Promtail — Log Collector (ships Docker logs to Loki)
  # -------------------------------------------------------------------------
  promtail:
    image: grafana/promtail:latest
    container_name: insidellm-promtail
    restart: always
    volumes:
      - /opt/InsideLLM/promtail/promtail-config.yml:/etc/promtail/config.yml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
    command: -config.file=/etc/promtail/config.yml
    depends_on:
      loki:
        condition: service_healthy
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Grafana — Compliance Dashboards & Visualization
  # -------------------------------------------------------------------------
  grafana:
    image: grafana/grafana-oss:latest
    container_name: insidellm-grafana
    restart: always
    ports:
      - "3000:3000"
    environment:
      GF_SERVER_ROOT_URL: "https://${server_name}/grafana/"
      GF_SERVER_SERVE_FROM_SUB_PATH: "true"
      GF_SECURITY_ADMIN_PASSWORD: "${grafana_admin_password}"
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_AUTH_ANONYMOUS_ENABLED: "false"
%{ if sso_provider != "none" }
      # SSO / Generic OAuth
      GF_AUTH_GENERIC_OAUTH_ENABLED: "true"
      GF_AUTH_GENERIC_OAUTH_NAME: "InsideLLM SSO"
      GF_AUTH_GENERIC_OAUTH_ALLOW_SIGN_UP: "true"
      GF_AUTH_GENERIC_OAUTH_CLIENT_ID: "${sso_client_id}"
      GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET: "${sso_client_secret}"
      GF_AUTH_GENERIC_OAUTH_SCOPES: "openid email profile"
%{ if sso_provider == "azure_ad" }
      GF_AUTH_GENERIC_OAUTH_AUTH_URL: "https://login.microsoftonline.com/${sso_tenant_id}/oauth2/v2.0/authorize"
      GF_AUTH_GENERIC_OAUTH_TOKEN_URL: "https://login.microsoftonline.com/${sso_tenant_id}/oauth2/v2.0/token"
      GF_AUTH_GENERIC_OAUTH_API_URL: "https://graph.microsoft.com/oidc/userinfo"
%{ endif }
%{ if sso_provider == "okta" }
      GF_AUTH_GENERIC_OAUTH_AUTH_URL: "https://${sso_okta_domain}/oauth2/default/v1/authorize"
      GF_AUTH_GENERIC_OAUTH_TOKEN_URL: "https://${sso_okta_domain}/oauth2/default/v1/token"
      GF_AUTH_GENERIC_OAUTH_API_URL: "https://${sso_okta_domain}/oauth2/default/v1/userinfo"
%{ endif }
%{ endif }
    volumes:
      - /opt/InsideLLM/data/grafana:/var/lib/grafana
      - /opt/InsideLLM/grafana/provisioning:/etc/grafana/provisioning:ro
      - /opt/InsideLLM/grafana/dashboards:/var/lib/grafana/dashboards:ro
    depends_on:
      loki:
        condition: service_healthy
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}
%{ if ops_uptime_kuma_enable ~}
  # -------------------------------------------------------------------------
  # Uptime Kuma — Service Health Monitoring & Alerting
  # -------------------------------------------------------------------------
  uptime-kuma:
    image: louislam/uptime-kuma:1
    container_name: insidellm-uptime-kuma
    restart: always
    ports:
      - "3001:3001"
    volumes:
      - /opt/InsideLLM/data/uptime-kuma:/app/data
    healthcheck:
      test: ["CMD-SHELL", "node -e \"const http=require('http');const o={hostname:'localhost',port:3001,path:'/api/entry',timeout:2000};http.get(o,r=>{process.exit(r.statusCode===200?0:1)}).on('error',()=>process.exit(1))\""]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}

networks:
  insidellm-internal:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
