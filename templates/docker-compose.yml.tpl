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
      POSTGRES_PASSWORD: "$${POSTGRES_PASSWORD}"
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
      DATABASE_URL: "postgresql://litellm:$${POSTGRES_PASSWORD}@postgres:5432/litellm"
      STORE_MODEL_IN_DB: "True"
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      LITELLM_MASTER_KEY: "$${LITELLM_MASTER_KEY}"
      LITELLM_SALT_KEY: "$${LITELLM_SALT_KEY}"
      ANTHROPIC_API_KEY: "$${ANTHROPIC_API_KEY}"
      OPENAI_API_KEY: "$${OPENAI_API_KEY}"
      GEMINI_API_KEY: "$${GEMINI_API_KEY}"
      MISTRAL_API_KEY: "$${MISTRAL_API_KEY}"
      COHERE_API_KEY: "$${COHERE_API_KEY}"
      AZURE_OPENAI_API_KEY: "$${AZURE_OPENAI_API_KEY}"
      AZURE_API_BASE: "${azure_openai_endpoint}"
      AZURE_API_VERSION: "${azure_openai_api_version}"
      AWS_ACCESS_KEY_ID: "${aws_bedrock_access_key_id}"
      AWS_SECRET_ACCESS_KEY: "${aws_bedrock_secret_access_key}"
      AWS_REGION_NAME: "${aws_bedrock_region}"
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
      UI_PASSWORD: "$${LITELLM_MASTER_KEY}"
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
    # Install humility-guardrail (canonical SAIVAS implementation) on startup,
    # then hand off to the LiteLLM entrypoint. See
    # https://github.com/uniformedi/humility-guardrail
    entrypoint: ["/bin/sh", "-c"]
    command:
      - "pip install --quiet https://github.com/Uniformedi/humility-guardrail/archive/refs/tags/v0.1.0.tar.gz && exec litellm --config /app/config.yaml --port 4000"
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
      # Route all API calls through LiteLLM. Newer Open WebUI prefers the
      # plural *_URLS / *_KEYS vars; keep the singular forms too for compat
      # with older versions.
      ENABLE_OPENAI_API: "true"
      OPENAI_API_BASE_URL: "http://litellm:4000/v1"
      OPENAI_API_KEY: "$${LITELLM_MASTER_KEY}"
      OPENAI_API_BASE_URLS: "http://litellm:4000/v1"
      OPENAI_API_KEYS: "$${LITELLM_MASTER_KEY}"

      # WebUI settings
      WEBUI_SECRET_KEY: "$${WEBUI_SECRET_KEY}"
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
      # Personal API keys required for the Governance Hub -> Open WebUI
      # model-sync bridge, and useful for users wiring Claude Code / editor
      # plugins at the OWUI /api/ surface. Endpoint restrictions off so
      # the key can create/update models when skills are published.
      ENABLE_API_KEY: "true"
      ENABLE_API_KEY_ENDPOINT_RESTRICTIONS: "false"
%{ if ldap_enable_services ~}
      # LDAP / Active Directory
      ENABLE_LDAP: "true"
      LDAP_SERVER_LABEL: "${ad_domain}"
      LDAP_SERVER_HOST: "${ad_domain}"
      LDAP_SERVER_PORT: "636"
      LDAP_USE_TLS: "true"
      LDAP_VALIDATE_CERT: "false"
      LDAP_CIPHERS: "ALL"
      LDAP_ATTRIBUTE_FOR_MAIL: "mail"
      LDAP_ATTRIBUTE_FOR_USERNAME: "sAMAccountName"
      LDAP_SEARCH_BASE: "${ldap_user_search_base}"
      # Additional filter ANDed with the hardcoded (sAMAccountName=<input>)
      # search in auths.py. Must NOT contain %(user)s — Open WebUI doesn't
      # substitute it, so the placeholder reaches LDAP literally and is
      # rejected as 'malformed filter'. Keep it as a static constraint
      # (e.g. objectClass=user). Users log in with their sAMAccountName.
      LDAP_SEARCH_FILTERS: "(objectClass=user)"
      LDAP_APP_DN: "${ldap_bind_dn}"
      LDAP_APP_PASSWORD: "$${LDAP_APP_PASSWORD}"
%{ endif ~}
%{ if sso_provider != "none" }
      # SSO / OIDC
      ENABLE_OAUTH_SIGNUP: "true"
      OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"
%{ if sso_provider == "azure_ad" }
      OAUTH_PROVIDER_NAME: "Microsoft"
      OAUTH_CLIENT_ID: "${sso_client_id}"
      OAUTH_CLIENT_SECRET: "$${SSO_CLIENT_SECRET}"
      OPENID_PROVIDER_URL: "https://login.microsoftonline.com/${sso_tenant_id}/v2.0/.well-known/openid-configuration"
      OAUTH_SCOPES: "openid email profile"
%{ endif }
%{ if sso_provider == "okta" }
      OAUTH_PROVIDER_NAME: "Okta"
      OAUTH_CLIENT_ID: "${sso_client_id}"
      OAUTH_CLIENT_SECRET: "$${SSO_CLIENT_SECRET}"
      OPENID_PROVIDER_URL: "https://${sso_okta_domain}/.well-known/openid-configuration"
      OAUTH_SCOPES: "openid email profile"
%{ endif }
%{ endif }
%{ if governance_hub_enable ~}
      # Canonical sessions bridge (Phase 3.3). Consumed by
      # sessions-bridge-pipeline.py to bind every OWUI chat to a
      # canonical session in governance-hub and stamp session_id into
      # request metadata for LiteLLM cost attribution.
      INSIDELLM_GOVHUB_URL: "http://governance-hub:8090"
      INSIDELLM_TENANT_ID: "${governance_hub_instance_id}"
      INSIDELLM_DEFAULT_TIER: "${session_security_tier}"
      INSIDELLM_DATA_REGION: "${session_data_region}"
      # Service-to-service bearer — reuses LITELLM_MASTER_KEY so there's
      # no extra secret to provision. Governance-hub's rbac_middleware
      # accepts this token as admin-equivalent when admin_auth_mode != "none".
      # Phase 4.x: replace with a dedicated OWUI service-account token
      # obtained via Keycloak client_credentials + audience restriction.
      INSIDELLM_GOVHUB_TOKEN: "$${LITELLM_MASTER_KEY}"
%{ endif ~}
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
%{ if cockpit_enable ~}
    # Required so the /cockpit/ proxy can resolve host.docker.internal
    # to the VM's host network (Cockpit listens on the host, not in a
    # container).
    extra_hosts:
      - "host.docker.internal:host-gateway"
%{ endif ~}
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
      PGADMIN_DEFAULT_EMAIL: "admin@insidellm.io"
      PGADMIN_CONFIG_CHECK_EMAIL_DELIVERABILITY: "False"
      PGADMIN_DEFAULT_PASSWORD: "$${LITELLM_MASTER_KEY}"
      PGADMIN_CONFIG_SERVER_MODE: "True"
%{ if ldap_enable_services ~}
      # LDAP / Active Directory. pgAdmin requires values to be wrapped in
      # extra quotes because config.py evaluates them with eval().
      PGADMIN_CONFIG_AUTHENTICATION_SOURCES: "['ldap', 'internal']"
      PGADMIN_CONFIG_LDAP_AUTO_CREATE_USER: "True"
      PGADMIN_CONFIG_LDAP_SERVER_URI: "'ldaps://${ad_domain}:636'"
      PGADMIN_CONFIG_LDAP_USERNAME_ATTRIBUTE: "'sAMAccountName'"
      PGADMIN_CONFIG_LDAP_SEARCH_BASE_DN: "'${ldap_user_search_base}'"
      PGADMIN_CONFIG_LDAP_SEARCH_FILTER: "'(objectClass=user)'"
      PGADMIN_CONFIG_LDAP_SEARCH_SCOPE: "'SUBTREE'"
      PGADMIN_CONFIG_LDAP_BIND_USER: "'${ldap_bind_dn}'"
      PGADMIN_CONFIG_LDAP_BIND_PASSWORD: "'$${LDAP_APP_PASSWORD}'"
      PGADMIN_CONFIG_LDAP_USE_STARTTLS: "False"
%{ endif ~}
    volumes:
      - /opt/InsideLLM/data/pgadmin:/var/lib/pgadmin
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - insidellm-internal

%{ if guacamole_enable ~}
  # -------------------------------------------------------------------------
  # guacd — Guacamole proxy daemon (translates RDP/VNC/SSH <-> guac protocol)
  # -------------------------------------------------------------------------
  guacd:
    image: guacamole/guacd:1.5.5
    container_name: insidellm-guacd
    restart: always
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Guacamole — Browser-based RDP/VNC/SSH gateway (web UI)
  # -------------------------------------------------------------------------
  guacamole:
    image: guacamole/guacamole:1.5.5
    container_name: insidellm-guacamole
    restart: always
    environment:
      GUACD_HOSTNAME: guacd
      GUACD_PORT: "4822"
      # Serve at the container root so nginx can strip /remote/ cleanly.
      WEBAPP_CONTEXT: ROOT
      # --- Postgres auth backend ---
      POSTGRES_HOSTNAME: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_DATABASE: guacamole
      POSTGRES_USER: guacamole
      POSTGRES_PASSWORD: "$${GUACAMOLE_DB_PASSWORD}"
      POSTGRES_AUTO_CREATE_ACCOUNTS: "true"
%{ if ldap_enable_services ~}
      # --- LDAP / Active Directory ---
      LDAP_HOSTNAME: "${ad_domain}"
      LDAP_PORT: "636"
      LDAP_ENCRYPTION_METHOD: ssl
      LDAP_SEARCH_BIND_DN: "${ldap_bind_dn}"
      LDAP_SEARCH_BIND_PASSWORD: "$${LDAP_APP_PASSWORD}"
      LDAP_USER_BASE_DN: "${ldap_user_search_base}"
      LDAP_USERNAME_ATTRIBUTE: sAMAccountName
%{ endif ~}
    volumes:
      # LDAP auth extension JAR is dropped here by post-deploy on first run.
      - /opt/InsideLLM/guacamole/extensions:/etc/guacamole/extensions:ro
    depends_on:
      guacd:
        condition: service_started
      postgres:
        condition: service_healthy
    networks:
      - insidellm-internal

%{ endif ~}
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
    # Pinned: post-Apple maintainer transition (Styra team -> Apple), monthly
    # release cadence continues but new ownership = bump deliberately, not on
    # every container restart. See docs/architecture/guardrails.md.
    image: openpolicyagent/opa:1.10.0
    container_name: insidellm-opa
    restart: always
    command:
      - "run"
      - "--server"
      - "--addr=:8181"
      - "--log-level=info"
      - "--watch"
      - "/policies"
    volumes:
      # rw so the Governance Hub policy editor can write .rego files here.
      # Writes are admin-gated and audited via governance-hub's hash chain.
      - /opt/InsideLLM/opa/policies:/policies:rw
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
      GOVERNANCE_HUB_DATABASE_URL: "postgresql+asyncpg://litellm:$${POSTGRES_PASSWORD}@postgres:5432/litellm"
      # Central fleet DB is configured via the Admin UI Fleet tab (stored in local DB)
      GOVERNANCE_HUB_PLATFORM_VERSION: "${platform_version}"
      GOVERNANCE_HUB_INSTANCE_ID: "${governance_hub_instance_id}"
      GOVERNANCE_HUB_INSTANCE_NAME: "${governance_hub_instance_name}"
      GOVERNANCE_HUB_SYNC_SCHEDULE: "${governance_hub_sync_schedule}"
      GOVERNANCE_HUB_SUPERVISOR_EMAILS: "${governance_hub_supervisor_emails}"
      GOVERNANCE_HUB_HUB_SECRET: "${governance_hub_secret}"
      GOVERNANCE_HUB_LITELLM_URL: "http://litellm:4000"
      GOVERNANCE_HUB_LITELLM_API_KEY: "$${LITELLM_MASTER_KEY}"
      # Hyper-V WinRM (reuses Terraform's hyperv provider creds) — used by
      # the /governance/hosts page for inventory + start/stop/snapshot.
      HYPERV_HOST: "${hyperv_host}"
      HYPERV_USER: "${hyperv_user}"
      HYPERV_PASSWORD: "$${HYPERV_PASSWORD}"
      HYPERV_PORT: "${hyperv_port}"
      HYPERV_HTTPS: "${hyperv_https}"
      HYPERV_INSECURE: "${hyperv_insecure}"
      GOVERNANCE_HUB_ADVISOR_MODEL: "${governance_hub_advisor_model}"
%{ if governance_hub_registration_token != "" }
      GOVERNANCE_HUB_REGISTRATION_TOKEN: "${governance_hub_registration_token}"
%{ endif }
      GOVERNANCE_HUB_INDUSTRY: "${governance_hub_industry}"
      GOVERNANCE_HUB_GOVERNANCE_TIER: "${governance_hub_tier}"
      GOVERNANCE_HUB_DATA_CLASSIFICATION: "${governance_hub_classification}"
      GOVERNANCE_HUB_ADMIN_AUTH_MODE: "${admin_auth_mode}"
      GOVERNANCE_HUB_AUTH_SECRET: "${governance_hub_secret}"
      GOVERNANCE_HUB_CHAT_ENABLE: "${chat_enable}"
      GOVERNANCE_HUB_CHAT_TEAM_NAME: "${chat_team_name}"
      GOVERNANCE_HUB_CHAT_DEFAULT_CHANNEL: "${chat_default_channel}"
%{ if admin_auth_mode == "ldap" }
      GOVERNANCE_HUB_AD_DOMAIN: "${ad_domain}"
      GOVERNANCE_HUB_AD_ADMIN_GROUPS: "${ad_admin_groups}"
      GOVERNANCE_HUB_AD_VIEW_GROUPS: "${ad_view_groups}"
      GOVERNANCE_HUB_AD_APPROVER_GROUPS: "${ad_approver_groups}"
%{ endif }
%{ if admin_auth_mode == "oidc" }
      GOVERNANCE_HUB_OIDC_ISSUER_URL: "${oidc_issuer_url}"
      GOVERNANCE_HUB_OIDC_CLIENT_ID: "${sso_client_id}"
      GOVERNANCE_HUB_OIDC_CLIENT_SECRET: "$${SSO_CLIENT_SECRET}"
      GOVERNANCE_HUB_OIDC_VIEW_GROUP_IDS: "${oidc_view_group_ids}"
      GOVERNANCE_HUB_OIDC_ADMIN_GROUP_IDS: "${oidc_admin_group_ids}"
      GOVERNANCE_HUB_OIDC_APPROVER_GROUP_IDS: "${oidc_approver_group_ids}"
%{ endif }
      # Break-glass: local insidellm-admin account uses this as the password.
      LITELLM_MASTER_KEY: "$${LITELLM_MASTER_KEY}"
%{ if workers_enable ~}
      # Celery broker + result backend (P3.3). Gov-hub publishes to the
      # insidellm-celery-worker via Redis when dispatching catalog actions
      # whose backend.type == celery_task.
      CELERY_BROKER_URL: "redis://redis:6379/1"
      CELERY_RESULT_BACKEND: "redis://redis:6379/2"
%{ endif ~}
%{ if n8n_enable ~}
      # n8n webhook HMAC — the dispatcher signs outbound calls to n8n
      # workflows with this key; workflows verify via a Code node.
      # Name must match the `hmac_secret_env` value in catalog entries.
      N8N_WEBHOOK_SECRET: "$${N8N_WEBHOOK_SECRET}"
%{ endif ~}
%{ if activepieces_enable ~}
      # Activepieces webhook HMAC — same shape as n8n so flows are portable.
      ACTIVEPIECES_WEBHOOK_SECRET: "$${ACTIVEPIECES_WEBHOOK_SECRET}"
%{ endif ~}
      # P2.1 — Teams/Slack notification webhooks. Empty by default; set in
      # /opt/InsideLLM/.env (and thus docker compose env) or via
      # settings_overrides to activate. DLP sidecar runs in-path regardless.
      TEAMS_WEBHOOK_DEFAULT: "$${TEAMS_WEBHOOK_DEFAULT:-}"
      SLACK_WEBHOOK_DEFAULT: "$${SLACK_WEBHOOK_DEFAULT:-}"
      SMTP_HOST: "$${SMTP_HOST:-}"
%{ if keycloak_enable ~}
      # Keycloak identity sync (Phase 2). Auto-enabled when the local
      # keycloak container is deployed; pushes realm/groups/users to the
      # central governance DB so the fleet-wide identity view is one query.
      GOVERNANCE_HUB_KEYCLOAK_SYNC_ENABLE: "true"
      GOVERNANCE_HUB_KEYCLOAK_URL: "http://keycloak:8080/keycloak"
      GOVERNANCE_HUB_KEYCLOAK_REALM: "${keycloak_realm_name}"
      GOVERNANCE_HUB_KEYCLOAK_ADMIN_USER: "${keycloak_admin_user}"
      # Master-realm admin password == LITELLM_MASTER_KEY (the break-glass
      # pattern every other bundled service shares). Kept as a plain env so
      # config.py reads it via validation_alias="KEYCLOAK_ADMIN_PASSWORD".
      KEYCLOAK_ADMIN_PASSWORD: "$${LITELLM_MASTER_KEY}"
%{ endif ~}
      # Fleet role + capability advertisement. The capability_service reads
      # CAP_* to decide which services to publish to the registry.
      VM_ROLE: "${vm_role}"
      FLEET_EDGE_SECRET: "$${FLEET_EDGE_SECRET}"
%{ if effective_litellm_capability ~}
      CAP_LITELLM_ENDPOINT: "http://litellm:4000/v1"
%{ endif ~}
%{ if effective_open_webui_capability ~}
      CAP_OPEN_WEBUI_ENDPOINT: "http://open-webui:8080"
%{ endif ~}
%{ if effective_ops_grafana_enable ~}
      CAP_GRAFANA_ENDPOINT: "http://grafana:3000"
      CAP_LOKI_ENDPOINT: "http://loki:3100"
%{ endif ~}
%{ if effective_guacamole_enable ~}
      CAP_GUACAMOLE_ENDPOINT: "http://guacamole:8080"
%{ endif ~}
%{ if effective_ops_uptime_kuma_enable ~}
      CAP_UPTIME_KUMA_ENDPOINT: "http://uptime-kuma:3001"
%{ endif ~}
%{ if effective_docforge_enable ~}
      CAP_DOCFORGE_ENDPOINT: "http://docforge:3000"
%{ endif ~}
    volumes:
      - /opt/InsideLLM/data/governance-hub:/app/data
      - /opt/InsideLLM/governance-hub/framework:/app/framework:ro
      # Policy editor writes .rego files here; OPA --watch picks up changes.
      - /opt/InsideLLM/opa/policies:/opa-policies:rw
      # AD-join request/status files; written by Hub, consumed by host
      # systemd path watcher (insidellm-ad-join.path).
      - /opt/InsideLLM/ad-join:/ad-join:rw
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
    # containrrr/watchtower is unmaintained since 2022 and hardcodes Docker API 1.25,
    # which is rejected by Docker Engine >=27 (minimum 1.40). Use the maintained fork.
    image: nickfedor/watchtower:latest
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
    # No healthcheck: grafana/loki image is distroless (no shell, wget, curl)
    # so any exec-based probe fails. Dependents use service_started instead.
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}
%{ if effective_promtail_enable ~}
  # -------------------------------------------------------------------------
  # Promtail — Log Collector (ships Docker logs to Loki)
  # On primary nodes: ships to local loki:3100.
  # On non-primary nodes: ships to fleet primary's Loki over the network.
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
%{ if ops_grafana_enable ~}
    depends_on:
      loki:
        condition: service_started
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
  # Grafana — Compliance Dashboards & Visualization
  # -------------------------------------------------------------------------
  grafana:
    image: grafana/grafana-oss:11.3.0
    container_name: insidellm-grafana
    restart: always
    ports:
      - "3000:3000"
    environment:
      GF_SERVER_ROOT_URL: "https://${server_name}/grafana/"
      GF_SERVER_SERVE_FROM_SUB_PATH: "true"
      GF_SECURITY_ADMIN_PASSWORD: "$${GRAFANA_ADMIN_PASSWORD}"
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_AUTH_ANONYMOUS_ENABLED: "false"
%{ if ldap_enable_services ~}
      # LDAP / Active Directory (ldap.toml mounted at /etc/grafana/ldap.toml)
      GF_AUTH_LDAP_ENABLED: "true"
      GF_AUTH_LDAP_CONFIG_FILE: "/etc/grafana/ldap.toml"
      GF_AUTH_LDAP_ALLOW_SIGN_UP: "true"
%{ endif ~}
%{ if sso_provider != "none" }
      # SSO / Generic OAuth
      GF_AUTH_GENERIC_OAUTH_ENABLED: "true"
      GF_AUTH_GENERIC_OAUTH_NAME: "InsideLLM SSO"
      GF_AUTH_GENERIC_OAUTH_ALLOW_SIGN_UP: "true"
      GF_AUTH_GENERIC_OAUTH_CLIENT_ID: "${sso_client_id}"
      GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET: "$${SSO_CLIENT_SECRET}"
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
%{ if ldap_enable_services ~}
      - /opt/InsideLLM/grafana/ldap.toml:/etc/grafana/ldap.toml:ro
%{ endif ~}
    depends_on:
      loki:
        condition: service_started
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
%{ if chat_enable ~}
  # -------------------------------------------------------------------------
  # Mattermost DB Init — Creates 'mattermost' database in Postgres (idempotent)
  # -------------------------------------------------------------------------
  mattermost-db-init:
    image: postgres:16-alpine
    container_name: insidellm-mattermost-db-init
    restart: "no"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PGPASSWORD: "$${POSTGRES_PASSWORD}"
    entrypoint:
      - sh
      - -c
      - |
        psql -h postgres -U litellm -d litellm -tc "SELECT 1 FROM pg_database WHERE datname='mattermost'" | grep -q 1 || \
        psql -h postgres -U litellm -d litellm -c "CREATE DATABASE mattermost OWNER litellm"
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Mattermost — Embedded browser chat (FOSS, MIT Team Edition)
  # -------------------------------------------------------------------------
  mattermost:
    image: mattermost/mattermost-team-edition:latest
    container_name: insidellm-mattermost
    restart: always
    depends_on:
      mattermost-db-init:
        condition: service_completed_successfully
    environment:
      MM_SQLSETTINGS_DRIVERNAME: "postgres"
      MM_SQLSETTINGS_DATASOURCE: "postgres://litellm:$${POSTGRES_PASSWORD}@postgres:5432/mattermost?sslmode=disable&connect_timeout=10"
      MM_SERVICESETTINGS_SITEURL: "${chat_site_url}"
      MM_SERVICESETTINGS_LISTENADDRESS: ":8065"
      MM_SERVICESETTINGS_ENABLELOCALMODE: "true"
      MM_SERVICESETTINGS_ENABLEUSERACCESSTOKENS: "true"
      MM_SERVICESETTINGS_ALLOWCORSFROM: "${chat_site_url}"
      MM_SERVICESETTINGS_ALLOWCOOKIESFORSUBDOMAINS: "false"
      MM_SERVICESETTINGS_WEBSOCKETURL: "wss://${server_name}/chat"
      MM_TEAMSETTINGS_SITENAME: "InsideLLM Chat"
      MM_TEAMSETTINGS_ENABLETEAMCREATION: "false"
      MM_TEAMSETTINGS_ENABLEUSERCREATION: "true"
      MM_TEAMSETTINGS_ENABLEOPENSERVER: "false"
      MM_FILESETTINGS_DRIVERNAME: "local"
      MM_FILESETTINGS_DIRECTORY: "/mattermost/data/"
      MM_PLUGINSETTINGS_ENABLE: "true"
      MM_PLUGINSETTINGS_ENABLEUPLOADS: "false"
      MM_LOGSETTINGS_CONSOLELEVEL: "INFO"
      MM_LOGSETTINGS_FILELEVEL: "INFO"
      MM_METRICSSETTINGS_ENABLE: "false"
%{ if admin_auth_mode == "oidc" ~}
      MM_GITLABSETTINGS_ENABLE: "true"
      MM_GITLABSETTINGS_ID: "${sso_client_id}"
      MM_GITLABSETTINGS_SECRET: "$${SSO_CLIENT_SECRET}"
      MM_GITLABSETTINGS_AUTHENDPOINT: "${oidc_issuer_url}/oauth2/v2.0/authorize"
      MM_GITLABSETTINGS_TOKENENDPOINT: "${oidc_issuer_url}/oauth2/v2.0/token"
      MM_GITLABSETTINGS_USERAPIENDPOINT: "https://graph.microsoft.com/oidc/userinfo"
%{ endif ~}
    volumes:
      - /opt/InsideLLM/data/mattermost/config:/mattermost/config
      - /opt/InsideLLM/data/mattermost/data:/mattermost/data
      - /opt/InsideLLM/data/mattermost/logs:/mattermost/logs
      - /opt/InsideLLM/data/mattermost/plugins:/mattermost/plugins
      - /opt/InsideLLM/data/mattermost/client-plugins:/mattermost/client/plugins
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8065/api/v4/system/ping"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 90s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - insidellm-internal

%{ endif ~}

%{ if workers_enable ~}
  # -------------------------------------------------------------------------
  # InsideLLM Workers — stub FastAPI service that backs declarative-agent
  # actions for demo / showcase agents (e.g. Dispute Handler's
  # lookup_account, draft_fdcpa_letter, send_letter, schedule_callback).
  #
  # Production tenants replace this with their own service — the action
  # catalog URL is per-tenant so no platform change is required.
  # -------------------------------------------------------------------------
  insidellm-workers:
    build:
      context: /opt/InsideLLM/insidellm-workers
      dockerfile: Dockerfile
    container_name: insidellm-workers
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # InsideLLM Celery Worker — async / queued declarative-agent actions (P3.3)
  #
  # Same image as insidellm-workers; different command. Listens on the
  # `actions` (short) and `bulk` (long-running) queues. Catalog entries
  # with backend.type = celery_task dispatch here via the gov-hub's
  # action_dispatcher.
  # -------------------------------------------------------------------------
  insidellm-celery-worker:
    build:
      context: /opt/InsideLLM/insidellm-workers
      dockerfile: Dockerfile
    container_name: insidellm-celery-worker
    restart: always
    depends_on:
      redis:
        condition: service_healthy
    environment:
      CELERY_BROKER_URL: "redis://redis:6379/1"
      CELERY_RESULT_BACKEND: "redis://redis:6379/2"
    command:
      - "celery"
      - "-A"
      - "src.celery_app"
      - "worker"
      - "--loglevel=info"
      - "--queues=actions,bulk"
      - "--concurrency=2"
    healthcheck:
      # `celery inspect ping` returns non-zero if no worker responds on
      # the control channel within the timeout.
      test: ["CMD-SHELL", "celery -A src.celery_app inspect ping -t 3 >/dev/null 2>&1 || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - insidellm-internal

%{ endif ~}
%{ if activepieces_enable ~}
  # -------------------------------------------------------------------------
  # Activepieces DB init — creates a dedicated `${activepieces_db_name}`
  # database inside the shared insidellm-postgres (same pattern as n8n).
  # -------------------------------------------------------------------------
  activepieces-db-init:
    image: postgres:16-alpine
    container_name: insidellm-activepieces-db-init
    restart: "no"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PGPASSWORD: "$${POSTGRES_PASSWORD}"
    entrypoint:
      - sh
      - -c
      - |
        psql -h postgres -U litellm -d litellm -tc "SELECT 1 FROM pg_database WHERE datname='${activepieces_db_name}'" | grep -q 1 || \
        psql -h postgres -U litellm -d litellm -c "CREATE DATABASE ${activepieces_db_name} OWNER litellm"
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Activepieces — MIT-licensed alternative to n8n (P3.2). Same action-catalog
  # slot, different backend: catalog entries set backend.type=activepieces_trigger
  # and the gov-hub dispatcher posts signed payloads to the flow's webhook.
  #
  # Editor served behind nginx at /activepieces/. AP_FRONTEND_URL mirrors the
  # external path so generated webhook URLs point at the right host.
  # -------------------------------------------------------------------------
  activepieces:
    image: activepieces/activepieces:${activepieces_version}
    container_name: insidellm-activepieces
    restart: always
    depends_on:
      activepieces-db-init:
        condition: service_completed_successfully
      redis:
        condition: service_healthy
    environment:
      AP_ENGINE_EXECUTABLE_PATH: dist/packages/engine/main.js
      AP_ENVIRONMENT: prod
      AP_EXECUTION_MODE: UNSANDBOXED
      AP_POSTGRES_HOST: postgres
      AP_POSTGRES_PORT: "5432"
      AP_POSTGRES_DATABASE: "${activepieces_db_name}"
      AP_POSTGRES_USERNAME: litellm
      AP_POSTGRES_PASSWORD: "$${POSTGRES_PASSWORD}"
      AP_POSTGRES_SSL_CA: ""
      AP_REDIS_HOST: redis
      AP_REDIS_PORT: "6379"
      AP_REDIS_DB: "3"
      AP_QUEUE_MODE: REDIS

      # Encryption + signing — pinned to state-persisted secrets so
      # stored credentials survive restart.
      AP_ENCRYPTION_KEY: "$${AP_ENCRYPTION_KEY}"
      AP_JWT_SECRET: "$${AP_JWT_SECRET}"

      # Outbound webhook HMAC — dispatcher signs with this, flows verify.
      AP_WEBHOOK_SECRET: "$${ACTIVEPIECES_WEBHOOK_SECRET}"

      # External URL — nginx terminates TLS at / and forwards /activepieces/.
      AP_FRONTEND_URL: "https://${server_name}/activepieces"

      # Hardening for single-tenant self-host.
      AP_SIGN_UP_ENABLED: "false"
      AP_TELEMETRY_ENABLED: "false"
      AP_EDITION: ce
      AP_WEBHOOK_TIMEOUT_SECONDS: "30"
      AP_TRIGGER_DEFAULT_POLL_INTERVAL: "5"
    volumes:
      - /opt/InsideLLM/data/activepieces:/var/lib/activepieces/local
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:80/api/v1/flags >/dev/null 2>&1 || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 45s
    networks:
      - insidellm-internal

%{ endif ~}
%{ if n8n_enable ~}
  # -------------------------------------------------------------------------
  # n8n DB init — creates a dedicated `${n8n_db_name}` database inside
  # the shared insidellm-postgres service (same pattern as mattermost/keycloak).
  # -------------------------------------------------------------------------
  n8n-db-init:
    image: postgres:16-alpine
    container_name: insidellm-n8n-db-init
    restart: "no"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PGPASSWORD: "$${POSTGRES_PASSWORD}"
    entrypoint:
      - sh
      - -c
      - |
        psql -h postgres -U litellm -d litellm -tc "SELECT 1 FROM pg_database WHERE datname='${n8n_db_name}'" | grep -q 1 || \
        psql -h postgres -U litellm -d litellm -c "CREATE DATABASE ${n8n_db_name} OWNER litellm"
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # n8n — per-tenant tool factory (P3.1). Low-code workflow builder that
  # declarative agents invoke via the n8n_webhook backend in the action
  # catalog. nginx proxies /n8n/ to this container's port 5678.
  #
  # Auth: break-glass (insidellm-admin + LITELLM_MASTER_KEY) — same pattern
  # every other bundled service uses, so operators sign in once.
  #
  # Webhook HMAC: the gov-hub dispatcher signs outbound calls with
  # X-Insidellm-Signature (hex-HMAC-SHA256 over the raw body) keyed by
  # N8N_WEBHOOK_SECRET. n8n workflows verify via a Crypto node or a small
  # Code node — template workflows ship in configs/n8n/workflows/.
  # -------------------------------------------------------------------------
  n8n:
    image: n8nio/n8n:${n8n_version}
    container_name: insidellm-n8n
    restart: always
    depends_on:
      n8n-db-init:
        condition: service_completed_successfully
      redis:
        condition: service_healthy
    environment:
      # Persistence — shared Postgres, dedicated database.
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: postgres
      DB_POSTGRESDB_PORT: "5432"
      DB_POSTGRESDB_DATABASE: "${n8n_db_name}"
      DB_POSTGRESDB_USER: litellm
      DB_POSTGRESDB_PASSWORD: "$${POSTGRES_PASSWORD}"

      # Queue mode uses Redis for multi-worker scale-out; defer to single-
      # process "regular" mode until a tenant actually needs workers.
      EXECUTIONS_MODE: regular

      # Behind nginx at /n8n/. N8N_HOST is the external hostname; the
      # proxy strips nothing, so N8N_PATH lines up with the nginx route.
      N8N_HOST: "${server_name}"
      N8N_PROTOCOL: https
      N8N_PORT: "5678"
      N8N_PATH: /n8n/
      N8N_EDITOR_BASE_URL: "https://${server_name}/n8n/"
      WEBHOOK_URL: "https://${server_name}/n8n/"
      N8N_PROXY_HOPS: "1"

      # Basic auth fronts the editor until SSO is wired in P1.5 follow-up.
      N8N_BASIC_AUTH_ACTIVE: "true"
      N8N_BASIC_AUTH_USER: "insidellm-admin"
      N8N_BASIC_AUTH_PASSWORD: "$${LITELLM_MASTER_KEY}"

      # Encryption key for credentials stored in the n8n DB. Pinned to the
      # master key so a re-deploy against an existing DB keeps secrets
      # decryptable. Rotate manually via `n8n export/import` if needed.
      N8N_ENCRYPTION_KEY: "$${LITELLM_MASTER_KEY}"

      # Webhook HMAC shared secret — the dispatcher signs, workflows verify.
      N8N_WEBHOOK_SECRET: "$${N8N_WEBHOOK_SECRET}"

      # Logging — emit structured JSON so Promtail tags cleanly.
      N8N_LOG_LEVEL: info
      N8N_LOG_OUTPUT: console
      N8N_LOG_FORMAT: json

      # Limits + hardening.
      N8N_METRICS: "true"
      N8N_DIAGNOSTICS_ENABLED: "false"
      N8N_VERSION_NOTIFICATIONS_ENABLED: "false"
      N8N_PERSONALIZATION_ENABLED: "false"
      N8N_HIRING_BANNER_ENABLED: "false"
    volumes:
      - /opt/InsideLLM/data/n8n:/home/node/.n8n
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:5678/healthz | grep -q ok || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - insidellm-internal

%{ endif ~}
%{ if keycloak_enable ~}
  # -------------------------------------------------------------------------
  # Keycloak DB init — creates a dedicated `${keycloak_db_name}` database
  # inside the shared insidellm-postgres service. Idempotent; completes and
  # exits so the main keycloak container can start against a ready schema.
  # -------------------------------------------------------------------------
  keycloak-db-init:
    image: postgres:16-alpine
    container_name: insidellm-keycloak-db-init
    restart: "no"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PGPASSWORD: "$${POSTGRES_PASSWORD}"
    entrypoint:
      - sh
      - -c
      - |
        psql -h postgres -U litellm -d litellm -tc "SELECT 1 FROM pg_database WHERE datname='${keycloak_db_name}'" | grep -q 1 || \
        psql -h postgres -U litellm -d litellm -c "CREATE DATABASE ${keycloak_db_name} OWNER litellm"
    networks:
      - insidellm-internal

  # -------------------------------------------------------------------------
  # Keycloak — local SSO provider (OIDC). Stores identity in local Postgres;
  # the gov-hub's keycloak_sync service replicates realm + group state to the
  # central MSSQL fleet store so the portfolio view has one identity plane.
  #
  # Served behind nginx at /keycloak/ (KC_HTTP_RELATIVE_PATH=/keycloak). The
  # relative-path trick is what keeps Keycloak's generated URLs consistent
  # when it sits behind a reverse proxy without owning the full hostname.
  # -------------------------------------------------------------------------
  keycloak:
    image: quay.io/keycloak/keycloak:${keycloak_version}
    container_name: insidellm-keycloak
    restart: always
    depends_on:
      keycloak-db-init:
        condition: service_completed_successfully
    command: ["start", "--optimized", "--import-realm"]
    environment:
      # DB — shared local Postgres. Same credentials as LiteLLM/Gov-Hub use.
      KC_DB: postgres
      KC_DB_URL: "jdbc:postgresql://postgres:5432/${keycloak_db_name}"
      KC_DB_USERNAME: litellm
      KC_DB_PASSWORD: "$${POSTGRES_PASSWORD}"

      # Master-realm admin (break-glass via the shared litellm_master_key).
      KEYCLOAK_ADMIN: "${keycloak_admin_user}"
      KEYCLOAK_ADMIN_PASSWORD: "$${LITELLM_MASTER_KEY}"

      # Proxy — TLS is terminated at nginx; Keycloak trusts the X-Forwarded-*
      # headers and serves everything under /keycloak/.
      KC_PROXY: edge
      KC_HOSTNAME_STRICT: "false"
      KC_HOSTNAME_STRICT_HTTPS: "false"
      KC_HTTP_ENABLED: "true"
      KC_HTTP_RELATIVE_PATH: /keycloak
      KC_HEALTH_ENABLED: "true"
      KC_METRICS_ENABLED: "true"

      # Optional production hygiene — tune if needed.
      KC_LOG_LEVEL: INFO
      KC_CACHE: local
    volumes:
      - /opt/InsideLLM/keycloak/import:/opt/keycloak/data/import:ro
    healthcheck:
      # Keycloak 25 exposes readiness at /health/ready; the relative path
      # prefix applies to the app but not the management endpoint.
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/9000; echo -e 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n' >&3; grep -q '\"status\": \"UP\"' <&3"]
      interval: 20s
      timeout: 5s
      retries: 10
      start_period: 60s
    networks:
      - insidellm-internal

%{ endif ~}
%{ if effective_pkg_mirror_enable ~}
  # -------------------------------------------------------------------------
  # Local package mirrors — only run on the fleet primary. Every other VM's
  # cloud-init points at apt_mirror_host / docker_mirror_host (= primary's IP)
  # so second-and-subsequent deploys skip 1.5 GB of apt traffic and 4 GB of
  # Docker image pulls.
  # -------------------------------------------------------------------------
  apt-cacher-ng:
    image: sameersbn/apt-cacher-ng:3.7.4-20230523
    container_name: insidellm-apt-cacher
    restart: always
    ports:
      - "3142:3142"
    volumes:
      - /opt/InsideLLM/data/apt-cache:/var/cache/apt-cacher-ng
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:3142/acng-report.html"]
      interval: 30s
      timeout: 5s
      retries: 3

  docker-registry-mirror:
    image: registry:2
    container_name: insidellm-registry-mirror
    restart: always
    ports:
      - "5000:5000"
    environment:
      REGISTRY_PROXY_REMOTEURL: "https://registry-1.docker.io"
      REGISTRY_STORAGE_DELETE_ENABLED: "true"
    volumes:
      - /opt/InsideLLM/data/registry:/var/lib/registry
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:5000/v2/"]
      interval: 30s
      timeout: 5s
      retries: 3
%{ endif ~}

networks:
  insidellm-internal:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
