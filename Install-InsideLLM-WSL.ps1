#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Deploy InsideLLM on WSL2 Ubuntu 24.04 (no Terraform or Hyper-V required).

.DESCRIPTION
    This script installs and configures the full InsideLLM stack inside WSL2:
      - WSL2 with Ubuntu 24.04
      - Docker Engine inside WSL2
      - PostgreSQL, Redis, LiteLLM, Open WebUI, Nginx, optionally Ollama
      - TLS certificates (self-signed or user-provided)
      - Windows port forwarding for LAN access

    It generates the same configuration files and runs the same containers
    as the Terraform/Hyper-V deployment path.

.PARAMETER AnthropicApiKey
    Anthropic API key (required). Get one at https://console.anthropic.com

.PARAMETER Uninstall
    Remove all InsideLLM containers, configs, port forwarding rules, and firewall rules.

.EXAMPLE
    .\Install-InsideLLM-WSL.ps1 -AnthropicApiKey "sk-ant-api03-..."
.EXAMPLE
    .\Install-InsideLLM-WSL.ps1 -AnthropicApiKey "sk-ant-..." -EnableOllama $false
.EXAMPLE
    .\Install-InsideLLM-WSL.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]$AnthropicApiKey = "",

    [string]$LitellmMasterKey = "",
    [string]$PostgresPassword = "",

    [string]$Hostname = "InsideLLM",
    [string]$Domain   = "local",
    [string]$Owner    = "Your Company Name",

    [bool]$EnableHaiku  = $true,
    [bool]$EnableOpus   = $true,

    [double]$GlobalMaxBudget   = 100,
    [double]$DefaultUserBudget = 5.0,
    [int]$DefaultUserRpm       = 30,
    [int]$DefaultUserTpm       = 100000,

    [bool]$EnableOllama        = $true,
    [string[]]$OllamaModels    = @("qwen2.5-coder:14b", "qwen2.5:14b"),
    [bool]$OllamaGpu           = $false,

    [string]$TlsCertPath = "",
    [string]$TlsKeyPath  = "",

    [string]$SsoProvider         = "none",
    [string]$AzureAdClientId     = "",
    [string]$AzureAdClientSecret = "",
    [string]$AzureAdTenantId     = "",
    [string]$OktaClientId        = "",
    [string]$OktaClientSecret    = "",
    [string]$OktaDomain          = "",

    [string]$WslDistroName = "Ubuntu-24.04",

    [switch]$Uninstall,
    [switch]$SkipPortForwarding
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$InstallPath = "/opt/InsideLLM"
$Fqdn = "$Hostname.$Domain"

# =============================================================================
# Helper functions
# =============================================================================

function Write-Step  { param([string]$M) Write-Host "`n=== $M ===" -ForegroundColor Cyan }
function Write-Ok    { param([string]$M) Write-Host "  [OK] $M" -ForegroundColor Green }
function Write-Warn  { param([string]$M) Write-Host "  [WARN] $M" -ForegroundColor Yellow }
function Write-Fail  { param([string]$M) Write-Host "  [FAIL] $M" -ForegroundColor Red }

function New-RandomPassword {
    param([int]$Length = 32)
    $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    $bytes = [byte[]]::new($Length)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $result = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
    return $result
}

function Invoke-Wsl {
    param([string]$Command)
    $output = wsl -d $WslDistroName -- bash -c $Command 2>&1
    return $output
}

function Write-WslFile {
    param([string]$Path, [string]$Content, [string]$Permissions = "0640")
    $tempFile = [System.IO.Path]::GetTempFileName()
    # Write with LF line endings
    [System.IO.File]::WriteAllText($tempFile, $Content.Replace("`r`n", "`n"))
    $wslTemp = Invoke-Wsl "wslpath '$($tempFile -replace '\\','/')'"
    $wslTemp = ($wslTemp -join "").Trim()
    Invoke-Wsl "sudo cp '$wslTemp' '$Path' && sudo chmod $Permissions '$Path'" | Out-Null
    Remove-Item $tempFile -Force
}

# =============================================================================
# Uninstall
# =============================================================================

if ($Uninstall) {
    Write-Step "Uninstalling InsideLLM from WSL2"

    # Stop containers
    $wslExists = wsl -l -q 2>$null | Where-Object { $_.Trim() -eq $WslDistroName }
    if ($wslExists) {
        Write-Ok "Stopping containers..."
        Invoke-Wsl "cd $InstallPath && sudo docker compose down -v 2>/dev/null; true" | Out-Null
        Invoke-Wsl "sudo rm -rf $InstallPath" | Out-Null
        Write-Ok "Removed $InstallPath"
    }

    # Remove port forwarding
    foreach ($port in @(80, 443, 4000, 11434)) {
        netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
    }
    Write-Ok "Removed port forwarding rules"

    # Remove firewall rules
    Remove-NetFirewallRule -Group "InsideLLM WSL2" -ErrorAction SilentlyContinue
    Write-Ok "Removed firewall rules"

    # Remove scheduled task
    Unregister-ScheduledTask -TaskName "InsideLLM-WSL2-PortForward" -Confirm:$false -ErrorAction SilentlyContinue
    Write-Ok "Removed scheduled task"

    Write-Host ""
    Write-Host "InsideLLM has been removed from WSL2." -ForegroundColor Green
    Write-Host "The WSL2 distro ($WslDistroName) was NOT removed."
    Write-Host "To also remove it: wsl --unregister $WslDistroName"
    exit 0
}

# =============================================================================
# Validate parameters
# =============================================================================

if (-not $AnthropicApiKey) {
    Write-Fail "AnthropicApiKey is required."
    Write-Host "  Usage: .\Install-InsideLLM-WSL.ps1 -AnthropicApiKey 'sk-ant-api03-...'"
    exit 1
}

# Generate secrets if not provided
if (-not $LitellmMasterKey) { $LitellmMasterKey = "sk-$(New-RandomPassword 32)" }
if (-not $PostgresPassword) { $PostgresPassword = New-RandomPassword 24 }
$WebuiSecret = New-RandomPassword 32

# =============================================================================
# Step 1: Install WSL2
# =============================================================================

Write-Step "Checking WSL2"

$wslStatus = wsl --status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warn "WSL is not installed. Installing WSL2..."
    wsl --install --no-distribution
    Write-Fail "WSL2 has been installed. Please REBOOT and re-run this script."
    exit 1
}
Write-Ok "WSL2 is installed"

# Check for the target distro
$distros = wsl -l -q 2>$null
$hasDistro = $distros | Where-Object { $_.Trim().Replace("`0","") -eq $WslDistroName }

if (-not $hasDistro) {
    Write-Warn "Installing $WslDistroName..."
    wsl --install -d Ubuntu-24.04
    Write-Host "  Waiting for distro to initialize (this may take a minute)..."
    Start-Sleep -Seconds 10
}
Write-Ok "$WslDistroName is installed"

# Ensure WSL2 mode
wsl --set-version $WslDistroName 2 2>$null | Out-Null

# Ensure systemd is enabled
$wslConf = Invoke-Wsl "cat /etc/wsl.conf 2>/dev/null || true"
if (-not ($wslConf -match "systemd\s*=\s*true")) {
    Write-Warn "Enabling systemd in WSL2..."
    Invoke-Wsl "echo -e '[boot]\nsystemd=true' | sudo tee /etc/wsl.conf > /dev/null"
    Write-Warn "Restarting WSL2 to enable systemd..."
    wsl --terminate $WslDistroName
    Start-Sleep -Seconds 3
    Invoke-Wsl "echo ready" | Out-Null
}
Write-Ok "systemd is enabled"

# =============================================================================
# Step 2: Install Docker
# =============================================================================

Write-Step "Checking Docker"

$dockerCheck = Invoke-Wsl "docker --version 2>/dev/null && echo DOCKER_OK || echo DOCKER_MISSING"
if (-not ($dockerCheck -match "DOCKER_OK")) {
    Write-Warn "Installing Docker Engine..."
    Invoke-Wsl @"
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg 2>/dev/null
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu noble stable' | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -qq
sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker `$(whoami)
"@ | Out-Null
    Write-Ok "Docker Engine installed"
} else {
    Write-Ok "Docker is already installed"
}

# Ensure Docker is running
Invoke-Wsl "sudo systemctl start docker 2>/dev/null || sudo service docker start 2>/dev/null; true" | Out-Null

# Configure Docker log rotation
Write-WslFile -Path "/etc/docker/daemon.json" -Content @'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
'@ -Permissions "0644"
Invoke-Wsl "sudo systemctl restart docker 2>/dev/null || sudo service docker restart 2>/dev/null; true" | Out-Null
Write-Ok "Docker daemon configured"

# =============================================================================
# Step 3: Generate TLS certificates
# =============================================================================

Write-Step "TLS Certificates"

Invoke-Wsl "sudo mkdir -p $InstallPath/nginx/ssl" | Out-Null

if ($TlsCertPath -and $TlsKeyPath) {
    $certContent = Get-Content $TlsCertPath -Raw
    $keyContent  = Get-Content $TlsKeyPath -Raw
    Write-WslFile -Path "$InstallPath/nginx/ssl/server.crt" -Content $certContent -Permissions "0644"
    Write-WslFile -Path "$InstallPath/nginx/ssl/server.key" -Content $keyContent  -Permissions "0600"
    Write-Ok "User-provided TLS certificate deployed"
} else {
    Invoke-Wsl @"
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout $InstallPath/nginx/ssl/server.key \
  -out $InstallPath/nginx/ssl/server.crt \
  -subj '/CN=$Fqdn/O=$Owner' \
  -addext 'subjectAltName=DNS:$Fqdn,DNS:$Hostname,DNS:localhost,IP:127.0.0.1' \
  2>/dev/null
sudo chmod 0600 $InstallPath/nginx/ssl/server.key
sudo chmod 0644 $InstallPath/nginx/ssl/server.crt
"@ | Out-Null
    Write-Ok "Self-signed TLS certificate generated for $Fqdn"
}

# =============================================================================
# Step 4: Generate configuration files
# =============================================================================

Write-Step "Generating configuration files"

# Create directory structure
Invoke-Wsl "sudo mkdir -p $InstallPath/data/{postgres,redis,open-webui,ollama} $InstallPath/pipelines $InstallPath/nginx/ssl" | Out-Null

# --- LiteLLM config ---
$litellmConfig = @"
model_list:
  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-5-20250929
      api_key: os.environ/ANTHROPIC_API_KEY
"@

if ($EnableHaiku) {
    $litellmConfig += @"

  - model_name: claude-haiku
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY
"@
}

if ($EnableOpus) {
    $litellmConfig += @"

  - model_name: claude-opus
    litellm_params:
      model: anthropic/claude-opus-4-6
      api_key: os.environ/ANTHROPIC_API_KEY
"@
}

if ($EnableOllama) {
    foreach ($model in $OllamaModels) {
        $litellmConfig += @"

  - model_name: "ollama/$model"
    litellm_params:
      model: "ollama/$model"
      api_base: http://ollama:11434
"@
    }
}

$litellmConfig += @"

litellm_settings:
  drop_params: true
  callbacks: ["dynamic_rate_limiter_v3"]
  token_rate_limit_type: "total"
  cache: true
  cache_params:
    type: redis
    host: redis
    port: 6379
  default_internal_user_params:
    max_budget: $DefaultUserBudget
    budget_duration: "1d"
    tpm_limit: $DefaultUserTpm
    rpm_limit: $DefaultUserRpm
  success_callback: ["langfuse"]
  failure_callback: ["langfuse"]

general_settings:
  server_root_path: "/litellm"
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  allow_user_auth: true
  global_max_parallel_requests: 50
  max_budget: $GlobalMaxBudget
  budget_duration: "30d"
  enable_jwt_auth: false
  ui_access_mode: "all"
  alerting:
    - "slack"
  alerting_threshold: 0.8

environment_variables:
  ANTHROPIC_API_KEY: os.environ/ANTHROPIC_API_KEY
  LITELLM_MASTER_KEY: os.environ/LITELLM_MASTER_KEY
  DATABASE_URL: os.environ/DATABASE_URL
"@

Write-WslFile -Path "$InstallPath/litellm-config.yaml" -Content $litellmConfig
Write-Ok "LiteLLM config"

# --- Nginx config ---
$nginxConfig = @"
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    log_format main '\`$remote_addr - \`$remote_user [\`$time_local] '
                    '"\`$request" \`$status \`$body_bytes_sent '
                    '"\`$http_referer" "\`$http_user_agent"';
    access_log /var/log/nginx/access.log main;

    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 50m;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    upstream open-webui {
        server open-webui:8080;
    }

    upstream litellm {
        server litellm:4000;
    }

    server {
        listen 80;
        server_name $Fqdn $Hostname _;

        location /health {
            return 200 'OK';
            add_header Content-Type text/plain;
        }

        location / {
            return 301 https://\`$host\`$request_uri;
        }
    }

    server {
        listen 443 ssl;
        http2 on;
        server_name $Fqdn $Hostname _;

        ssl_certificate     /etc/nginx/ssl/server.crt;
        ssl_certificate_key /etc/nginx/ssl/server.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;
        ssl_session_cache   shared:SSL:10m;
        ssl_session_timeout 1d;

        location / {
            proxy_pass http://open-webui;
            proxy_http_version 1.1;
            proxy_set_header Upgrade \`$http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host \`$host;
            proxy_set_header X-Real-IP \`$remote_addr;
            proxy_set_header X-Forwarded-For \`$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \`$scheme;
            proxy_buffering off;
            proxy_read_timeout 300s;
            proxy_connect_timeout 75s;
        }

        location /litellm/ {
            proxy_pass http://litellm;
            proxy_http_version 1.1;
            proxy_set_header Host \`$host;
            proxy_set_header X-Real-IP \`$remote_addr;
            proxy_set_header X-Forwarded-For \`$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \`$scheme;
            proxy_buffering off;
            proxy_read_timeout 300s;
        }

        location /litellm-asset-prefix/ {
            proxy_pass http://litellm/litellm-asset-prefix/;
            proxy_http_version 1.1;
            proxy_set_header Host \`$host;
            proxy_set_header X-Real-IP \`$remote_addr;
            proxy_set_header X-Forwarded-For \`$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \`$scheme;
        }

        location /v1/ {
            proxy_pass http://litellm/v1/;
            proxy_http_version 1.1;
            proxy_set_header Host \`$host;
            proxy_set_header X-Real-IP \`$remote_addr;
            proxy_set_header X-Forwarded-For \`$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \`$scheme;
            proxy_buffering off;
            proxy_read_timeout 300s;
        }

        location /nginx-health {
            return 200 'OK';
            add_header Content-Type text/plain;
        }
    }
}
"@

Write-WslFile -Path "$InstallPath/nginx/nginx.conf" -Content $nginxConfig -Permissions "0644"
Write-Ok "Nginx config"

# --- Docker Compose ---
$ssoEnvBlock = ""
if ($SsoProvider -eq "azure_ad") {
    $ssoEnvBlock = @"
      MICROSOFT_CLIENT_ID: "$AzureAdClientId"
      MICROSOFT_CLIENT_SECRET: "$AzureAdClientSecret"
      MICROSOFT_TENANT: "$AzureAdTenantId"
"@
} elseif ($SsoProvider -eq "okta") {
    $ssoEnvBlock = @"
      GENERIC_CLIENT_ID: "$OktaClientId"
      GENERIC_CLIENT_SECRET: "$OktaClientSecret"
      GENERIC_AUTHORIZATION_ENDPOINT: "https://$OktaDomain/oauth2/v1/authorize"
      GENERIC_TOKEN_ENDPOINT: "https://$OktaDomain/oauth2/v1/token"
      GENERIC_USERINFO_ENDPOINT: "https://$OktaDomain/oauth2/v1/userinfo"
      GENERIC_USER_ID_ATTRIBUTE: "sub"
      GENERIC_USER_EMAIL_ATTRIBUTE: "email"
      GENERIC_USER_DISPLAY_NAME_ATTRIBUTE: "name"
"@
}

$ollamaDependsOn = ""
if ($EnableOllama) {
    $ollamaDependsOn = @"
      ollama:
        condition: service_healthy
"@
}

$ollamaServices = ""
if ($EnableOllama) {
    $gpuBlock = ""
    if ($OllamaGpu) {
        $gpuBlock = @"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
"@
    }

    $pullCommands = ($OllamaModels | ForEach-Object { "        echo 'Pulling $_...' && ollama pull $_" }) -join "`n"

    $ollamaServices = @"

  ollama:
    image: ollama/ollama:latest
    container_name: claude-ollama
    restart: always
    ports:
      - "11434:11434"
    volumes:
      - $InstallPath/data/ollama:/root/.ollama
$gpuBlock
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:11434/api/tags || exit 1"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "3"
    networks:
      - claude-internal

  ollama-pull:
    image: ollama/ollama:latest
    container_name: claude-ollama-pull
    restart: "no"
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
$pullCommands
        echo "All models pulled."
    environment:
      OLLAMA_HOST: "http://ollama:11434"
    depends_on:
      ollama:
        condition: service_healthy
    networks:
      - claude-internal
"@
}

$dockerCompose = @"
services:
  postgres:
    image: postgres:16-alpine
    container_name: claude-postgres
    restart: always
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD: "$PostgresPassword"
    volumes:
      - $InstallPath/data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U litellm"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - claude-internal

  redis:
    image: redis:7-alpine
    container_name: claude-redis
    restart: always
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - $InstallPath/data/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - claude-internal

  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: claude-litellm
    restart: always
    ports:
      - "4000:4000"
    environment:
      DATABASE_URL: "postgresql://litellm:${PostgresPassword}@postgres:5432/litellm"
      STORE_MODEL_IN_DB: "True"
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      LITELLM_MASTER_KEY: "$LitellmMasterKey"
      ANTHROPIC_API_KEY: "$AnthropicApiKey"
      LITELLM_LOG: "INFO"
      SERVER_ROOT_PATH: "/litellm"
      UI_USERNAME: "admin"
      UI_PASSWORD: "$LitellmMasterKey"
$ssoEnvBlock
    volumes:
      - $InstallPath/litellm-config.yaml:/app/config.yaml
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
$ollamaDependsOn
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:4000/health/liveliness')\""]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 30s
    networks:
      - claude-internal

  open-webui:
    image: ghcr.io/open-webui/open-webui:latest
    container_name: claude-open-webui
    restart: always
    ports:
      - "8080:8080"
    environment:
      OPENAI_API_BASE_URL: "http://litellm:4000/v1"
      OPENAI_API_KEY: "$LitellmMasterKey"
      WEBUI_SECRET_KEY: "$WebuiSecret"
      WEBUI_NAME: "InsideLLM"
      ENABLE_SIGNUP: "true"
      DEFAULT_USER_ROLE: "user"
      ENABLE_COMMUNITY_SHARING: "false"
      RAG_EMBEDDING_ENGINE: ""
      RAG_EMBEDDING_MODEL: "sentence-transformers/all-MiniLM-L6-v2"
      CHUNK_SIZE: "1500"
      CHUNK_OVERLAP: "100"
      RAG_FULL_CONTEXT: "true"
      WEBUI_AUTH: "true"
    volumes:
      - $InstallPath/data/open-webui:/app/backend/data
      - $InstallPath/pipelines:/app/backend/pipelines
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

  nginx:
    image: nginx:1.27-alpine
    container_name: claude-nginx
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - $InstallPath/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - $InstallPath/nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      open-webui:
        condition: service_healthy
    networks:
      - claude-internal
$ollamaServices

networks:
  claude-internal:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
"@

Write-WslFile -Path "$InstallPath/docker-compose.yml" -Content $dockerCompose
Write-Ok "Docker Compose"

# --- DLP Pipeline ---
$dlpSource = Join-Path $PSScriptRoot "configs\open-webui\dlp-pipeline.py"
if (Test-Path $dlpSource) {
    $dlpContent = Get-Content $dlpSource -Raw
    Write-WslFile -Path "$InstallPath/pipelines/dlp-pipeline.py" -Content $dlpContent -Permissions "0644"
    Write-Ok "DLP pipeline"
} else {
    Write-Warn "DLP pipeline not found at $dlpSource - skipping (deploy manually later)"
}

# --- Post-deploy script ---
$postDeploy = @"
#!/bin/bash
set -euo pipefail

LITELLM_URL="http://localhost:4000"
LITELLM_KEY="$LitellmMasterKey"
LOG="/var/log/InsideLLM-deploy.log"

log() { echo "[\$(date '+%Y-%m-%d %H:%M:%S')] \$*" | tee -a "\$LOG"; }

wait_for_service() {
  local url="\$1" name="\$2" max=30 attempt=0
  while [ \$attempt -lt \$max ]; do
    if curl -sf "\$url" > /dev/null 2>&1; then
      log "\$name is healthy"; return 0
    fi
    attempt=\$((attempt + 1))
    log "Waiting for \$name... (\$attempt/\$max)"
    sleep 5
  done
  log "WARNING: \$name did not become healthy within timeout"
  return 1
}

log "=== Starting post-deployment configuration ==="
wait_for_service "\$LITELLM_URL/health/liveliness" "LiteLLM"
wait_for_service "http://localhost:8080/health" "Open WebUI"

log "Creating default teams..."

curl -sf -X POST "\$LITELLM_URL/team/new" \
  -H "Authorization: Bearer \$LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"team_alias":"administrators","max_budget":0,"budget_duration":"30d","tpm_limit":500000,"rpm_limit":100,"models":["claude-sonnet","claude-haiku","claude-opus"]}' >> "\$LOG" 2>&1 || log "Team administrators may already exist"

curl -sf -X POST "\$LITELLM_URL/team/new" \
  -H "Authorization: Bearer \$LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"team_alias":"general-users","max_budget":$DefaultUserBudget,"budget_duration":"1d","tpm_limit":100000,"rpm_limit":30,"models":["claude-sonnet","claude-haiku"]}' >> "\$LOG" 2>&1 || log "Team general-users may already exist"

curl -sf -X POST "\$LITELLM_URL/team/new" \
  -H "Authorization: Bearer \$LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"team_alias":"power-users","max_budget":20,"budget_duration":"1d","tpm_limit":200000,"rpm_limit":60,"models":["claude-sonnet","claude-haiku","claude-opus"]}' >> "\$LOG" 2>&1 || log "Team power-users may already exist"

log "Generating admin API key..."
curl -sf -X POST "\$LITELLM_URL/key/generate" \
  -H "Authorization: Bearer \$LITELLM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key_alias":"admin-default-key","max_budget":0,"models":["claude-sonnet","claude-haiku","claude-opus"],"metadata":{"purpose":"admin-api-access"}}' >> "\$LOG" 2>&1 || log "Key generation skipped"

log "Creating systemd service..."
cat > /etc/systemd/system/InsideLLM.service << 'SYSTEMD'
[Unit]
Description=Inside LLM (Docker Compose)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$InstallPath
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable InsideLLM.service

log ""
log "=========================================="
log "  Inside LLM - READY"
log "=========================================="
log ""
log "  Open WebUI:   https://localhost"
log "  LiteLLM UI:   https://localhost/litellm/ui"
log "  Claude Code:"
log '    \$env:ANTHROPIC_BASE_URL = "http://localhost:4000"'
log '    \$env:ANTHROPIC_AUTH_TOKEN = "<your-litellm-key>"'
log ""
log "=========================================="
"@

Write-WslFile -Path "$InstallPath/post-deploy.sh" -Content $postDeploy -Permissions "0750"
Write-Ok "Post-deploy script"

# =============================================================================
# Step 5: Pull images and start the stack
# =============================================================================

Write-Step "Starting InsideLLM stack"

Write-Host "  Pulling container images (this may take several minutes)..."
Invoke-Wsl "cd $InstallPath && sudo docker compose pull 2>&1"
Write-Ok "Images pulled"

Write-Host "  Starting containers..."
Invoke-Wsl "cd $InstallPath && sudo docker compose up -d 2>&1"
Write-Ok "Containers started"

Write-Host "  Waiting 60 seconds for services to initialize..."
Start-Sleep -Seconds 60

Write-Host "  Running post-deployment configuration..."
Invoke-Wsl "cd $InstallPath && sudo bash post-deploy.sh 2>&1"
Write-Ok "Post-deploy complete"

# =============================================================================
# Step 6: Port forwarding
# =============================================================================

if (-not $SkipPortForwarding) {
    Write-Step "Configuring port forwarding"

    $wslIp = (Invoke-Wsl "hostname -I" | ForEach-Object { $_.Trim().Split(" ")[0] })
    Write-Ok "WSL2 IP: $wslIp"

    $ports = @(80, 443, 4000)
    if ($EnableOllama) { $ports += 11434 }

    foreach ($port in $ports) {
        $null = netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>&1
        netsh interface portproxy add v4tov4 listenport=$port listenaddress=0.0.0.0 connectport=$port connectaddress=$wslIp | Out-Null

        Remove-NetFirewallRule -DisplayName "InsideLLM WSL2 port $port" -ErrorAction SilentlyContinue
        New-NetFirewallRule `
            -DisplayName "InsideLLM WSL2 port $port" `
            -Group "InsideLLM WSL2" `
            -Direction Inbound `
            -Protocol TCP `
            -LocalPort $port `
            -Action Allow `
            -Profile @("Domain", "Private") `
            -Enabled True | Out-Null

        Write-Ok "Port $port -> ${wslIp}:$port"
    }

    # Create a scheduled task to refresh port forwarding when WSL IP changes
    $refreshScript = @"
`$wslIp = (wsl -d $WslDistroName -- hostname -I).Trim().Split(" ")[0]
if (`$wslIp) {
    foreach (`$port in @($($ports -join ','))) {
        netsh interface portproxy delete v4tov4 listenport=`$port listenaddress=0.0.0.0 2>`$null | Out-Null
        netsh interface portproxy add v4tov4 listenport=`$port listenaddress=0.0.0.0 connectport=`$port connectaddress=`$wslIp | Out-Null
    }
}
"@
    $refreshPath = Join-Path $env:ProgramData "InsideLLM\Refresh-PortForward.ps1"
    $null = New-Item -Path (Split-Path $refreshPath) -ItemType Directory -Force
    [System.IO.File]::WriteAllText($refreshPath, $refreshScript)

    $action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$refreshPath`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Unregister-ScheduledTask -TaskName "InsideLLM-WSL2-PortForward" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName "InsideLLM-WSL2-PortForward" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Description "Refresh InsideLLM WSL2 port forwarding on login" | Out-Null
    Write-Ok "Scheduled task created to refresh port forwarding on login"
}

# =============================================================================
# Summary
# =============================================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  InsideLLM - Deployed on WSL2" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Open WebUI:     https://localhost"
Write-Host "  LiteLLM UI:     https://localhost/litellm/ui"
Write-Host "  LiteLLM API:    http://localhost:4000"
if ($EnableOllama) {
Write-Host "  Ollama API:     http://localhost:11434"
}
Write-Host ""
Write-Host "  Claude Code CLI setup:"
Write-Host '    $env:ANTHROPIC_BASE_URL = "http://localhost:4000"'
Write-Host '    $env:ANTHROPIC_AUTH_TOKEN = "<your-litellm-key>"'
Write-Host ""
Write-Host "  Master Key:     $LitellmMasterKey" -ForegroundColor Yellow
Write-Host "  (save this -- it is your admin password and API key)"
Write-Host ""
Write-Host "  Stop:    wsl -d $WslDistroName -- bash -c 'cd $InstallPath && sudo docker compose stop'"
Write-Host "  Start:   wsl -d $WslDistroName -- bash -c 'cd $InstallPath && sudo docker compose start'"
Write-Host "  Remove:  .\Install-InsideLLM-WSL.ps1 -Uninstall"
Write-Host ""
