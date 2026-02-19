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
    container_name: claude-postgres
    restart: always
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD: "${postgres_password}"
    volumes:
      - /opt/claude-wrapper/data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U litellm"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - claude-internal

  # -------------------------------------------------------------------------
  # Redis — Rate limit counters, session cache
  # -------------------------------------------------------------------------
  redis:
    image: redis:7-alpine
    container_name: claude-redis
    restart: always
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - /opt/claude-wrapper/data/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - claude-internal

  # -------------------------------------------------------------------------
  # LiteLLM Proxy — API Gateway, SSO, Budgets, Rate Limiting
  # -------------------------------------------------------------------------
  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: claude-litellm
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
      LITELLM_LOG: "DEBUG"
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
      - /opt/claude-wrapper/litellm-config.yaml:/app/config.yaml
    command: ["--config", "/app/config.yaml", "--port", "4000", "--detailed_debug"]
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:4000/health/liveliness')\""]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 30s
    networks:
      - claude-internal

  # -------------------------------------------------------------------------
  # Open WebUI — Chat Interface, RAG, DLP Pipelines
  # -------------------------------------------------------------------------
  open-webui:
    image: ghcr.io/open-webui/open-webui:latest
    container_name: claude-open-webui
    restart: always
    ports:
      - "8080:8080"
    environment:
      # Route all API calls through LiteLLM
      OPENAI_API_BASE_URL: "http://litellm:4000/v1"
      OPENAI_API_KEY: "${litellm_master_key}"

      # WebUI settings
      WEBUI_SECRET_KEY: "${webui_secret}"
      WEBUI_NAME: "Claude @ Uniformedi"
      ENABLE_SIGNUP: "true"
      DEFAULT_USER_ROLE: "user"
      ENABLE_COMMUNITY_SHARING: "false"

      # RAG settings — use built-in sentence-transformers (no external API needed)
      RAG_EMBEDDING_ENGINE: ""
      RAG_EMBEDDING_MODEL: "sentence-transformers/all-MiniLM-L6-v2"
      CHUNK_SIZE: "1500"
      CHUNK_OVERLAP: "100"

      # Security
      WEBUI_AUTH: "true"
    volumes:
      - /opt/claude-wrapper/data/open-webui:/app/backend/data
      - /opt/claude-wrapper/pipelines:/app/backend/pipelines
    depends_on:
      litellm:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 30s
    networks:
      - claude-internal

  # -------------------------------------------------------------------------
  # Nginx — Reverse Proxy + TLS Termination
  # -------------------------------------------------------------------------
  nginx:
    image: nginx:1.27-alpine
    container_name: claude-nginx
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /opt/claude-wrapper/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - /opt/claude-wrapper/nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      open-webui:
        condition: service_healthy
    networks:
      - claude-internal

networks:
  claude-internal:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
