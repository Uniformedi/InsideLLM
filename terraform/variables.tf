###############################################################################
# variables.tf — Input variables for the InsideLLM deployment
###############################################################################

# =============================================================================
# HYPER-V HOST CONNECTION
# =============================================================================

variable "hyperv_user" {
  description = "Username for Hyper-V host WinRM connection (e.g., DOMAIN\\Administrator or .\\Administrator)"
  type        = string
  default     = ".\\Administrator"
}

variable "hyperv_password" {
  description = "Password for the Hyper-V host administrator account"
  type        = string
  sensitive   = true
}

variable "hyperv_host" {
  description = "Hyper-V host address (127.0.0.1 for local)"
  type        = string
  default     = "127.0.0.1"
}

variable "hyperv_port" {
  description = "WinRM port (5985 for HTTP, 5986 for HTTPS)"
  type        = number
  default     = 5985
}

variable "hyperv_https" {
  description = "Use HTTPS for WinRM connection"
  type        = bool
  default     = false
}

variable "hyperv_insecure" {
  description = "Skip TLS verification for WinRM (only for local/dev)"
  type        = bool
  default     = true
}

# =============================================================================
# VM CONFIGURATION
# =============================================================================

variable "vm_name" {
  description = "Name for the Hyper-V virtual machine"
  type        = string
  default     = "InsideLLM"
}

variable "vm_processor_count" {
  description = "Number of virtual CPUs for the VM (8 recommended with Ollama, 4 sufficient without)"
  type        = number
  default     = 8
}

variable "vm_memory_startup_bytes" {
  description = "VM startup memory in bytes (32GB default for Ollama; 8GB sufficient without: 8589934592)"
  type        = number
  default     = 34359738368 # 32 GB
}

variable "vm_memory_dynamic" {
  description = "Enable dynamic memory for the VM"
  type        = bool
  default     = false
}

variable "vm_disk_size_bytes" {
  description = "VM boot disk size in bytes (80GB = 85899345920)"
  type        = number
  default     = 85899345920 # 80 GB
}

variable "vm_path" {
  description = "Base path on Hyper-V host for VM files"
  type        = string
  default     = "C:\\HyperV\\VMs"
}

variable "vm_vhd_path" {
  description = "Path for virtual hard disks"
  type        = string
  default     = "C:\\HyperV\\VHDs"
}

variable "vm_switch_name" {
  description = "Name of the Hyper-V virtual switch to use (must have external/internal network access)"
  type        = string
  default     = "InsideLLM"
}

variable "vm_switch_type" {
  description = "Type of virtual switch: Internal or External"
  type        = string
  default     = "External"

  validation {
    condition     = contains(["Internal", "External"], var.vm_switch_type)
    error_message = "Switch type must be Internal or External."
  }
}

variable "vm_switch_adapter" {
  description = "Physical network adapter name for External switch (e.g., 'Ethernet', 'Wi-Fi'). Required when vm_switch_type = External."
  type        = string
  default     = ""
}

variable "base_vhdx_source" {
  description = "Path to the base OS cloud image VHDX on the Hyper-V host (created by SetupInstall.ps1). Default: Debian 12 Bookworm generic cloud image."
  type        = string
  default     = "C:\\HyperV\\Images\\debian-12-genericcloud-amd64.vhdx"
}

# Legacy alias — keeps older terraform.tfvars working. Remove once all
# environments have migrated to `base_vhdx_source`.
variable "ubuntu_vhdx_source" {
  description = "Deprecated alias for base_vhdx_source. Set base_vhdx_source instead."
  type        = string
  default     = ""
}

# =============================================================================
# NETWORK CONFIGURATION
# =============================================================================

variable "vm_static_ip" {
  description = "Static IP address for the VM (CIDR notation, e.g., 192.168.1.100/24). Leave empty for DHCP."
  type        = string
  default     = ""
}

variable "vm_gateway" {
  description = "Default gateway for static IP configuration"
  type        = string
  default     = ""
}

variable "vm_dns_servers" {
  description = "DNS servers for the VM"
  type        = list(string)
  default     = ["8.8.8.8", "8.8.4.4"]
}

variable "vm_hostname" {
  description = "Hostname for the Ubuntu VM"
  type        = string
  default     = "InsideLLM"
}

variable "vm_domain" {
  description = "Domain name for the VM (for FQDN and TLS cert)"
  type        = string
  default     = "local"
}

# =============================================================================
# ACTIVE DIRECTORY DOMAIN JOIN
# =============================================================================

variable "ad_domain_join" {
  description = "Join the Ubuntu VM to the Active Directory domain specified in vm_domain"
  type        = bool
  default     = false
}

variable "ad_join_user" {
  description = "AD username with permission to join computers to the domain (e.g., Administrator or a service account)"
  type        = string
  default     = ""
}

variable "ad_join_password" {
  description = "Password for the AD join account"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ad_join_ou" {
  description = "Organizational Unit for the computer account (e.g., OU=Servers,DC=company,DC=local). Leave empty for default."
  type        = string
  default     = ""
}

variable "ad_dns_register" {
  description = "Register the VM hostname in Active Directory DNS via dynamic update"
  type        = bool
  default     = true
}

variable "ad_admin_groups" {
  description = "Comma-separated AD groups for the Governance Hub 'admin' role (CRUD except approvals)."
  type        = string
  default     = "InsideLLM-Admin"
}

variable "ad_view_groups" {
  description = "Comma-separated AD groups for the Governance Hub 'view' role (GET-only)."
  type        = string
  default     = "InsideLLM-View"
}

variable "ad_approver_groups" {
  description = "Comma-separated AD groups for the Governance Hub 'approver' role (change approve/reject)."
  type        = string
  default     = "InsideLLM-Approve"
}

variable "oidc_view_group_ids" {
  description = "OIDC group object IDs (GUIDs) mapped to the 'view' role."
  type        = list(string)
  default     = []
}

variable "oidc_admin_group_ids" {
  description = "OIDC group object IDs (GUIDs) mapped to the 'admin' role."
  type        = list(string)
  default     = []
}

variable "oidc_approver_group_ids" {
  description = "OIDC group object IDs (GUIDs) mapped to the 'approver' role."
  type        = list(string)
  default     = []
}

variable "dc_dns_servers" {
  description = <<-EOT
    Domain controller IP(s) to use as the VM's DNS resolver. Required if
    admin_auth_mode = "ldap" and the default network DNS doesn't forward
    to your AD DNS (the common case — Ubuntu's systemd-resolved stub
    can't resolve uniformedi.local without this). Leave empty to inherit
    whatever DHCP provides.
  EOT
  type        = list(string)
  default     = []
}

# =============================================================================
# LDAP enablement for component services (Grafana, Open WebUI, pgAdmin, LiteLLM)
# =============================================================================

variable "ldap_enable_services" {
  description = <<-EOT
    When true, turn on LDAP auth in Grafana, Open WebUI, and pgAdmin, and
    gate the LiteLLM admin UI behind the Governance Hub auth subrequest.
    Requires ad_domain_join = true (so the VM resolves the DC) and a valid
    ldap_bind_dn / ldap_bind_password service account.
  EOT
  type        = bool
  default     = false
}

variable "ldap_bind_dn" {
  description = <<-EOT
    Distinguished Name of the read-only service account used by Grafana /
    Open WebUI / pgAdmin to look up a user's DN before binding with the
    user's own credentials. Example:
      CN=svc-insidellm,OU=Service Accounts,DC=uniformedi,DC=local
  EOT
  type        = string
  default     = ""
}

variable "ldap_bind_password" {
  description = "Password for the LDAP bind service account. Treat as secret — do not commit."
  type        = string
  default     = ""
  sensitive   = true
}

variable "cockpit_enable" {
  description = <<-EOT
    Install Cockpit on each VM and expose it at /cockpit/ behind the
    InsideLLM nginx. Cockpit is a Linux web management UI: web shell,
    service control, log viewer, container management. Lightweight
    equivalent of Windows Admin Center for the Linux side.
  EOT
  type        = bool
  default     = true
}

variable "ldap_user_search_base" {
  description = <<-EOT
    Base DN for user lookups. If empty, defaults to the domain's DC= chain
    (e.g. DC=uniformedi,DC=local for ad_domain = uniformedi.local). Narrow
    to an OU if you want to restrict which users can authenticate.
  EOT
  type        = string
  default     = ""
}

# =============================================================================
# SSH ACCESS
# =============================================================================

variable "ssh_public_key_path" {
  description = "Path to SSH public key file on the Windows host for VM access"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "ssh_admin_user" {
  description = "Admin username for the Ubuntu VM"
  type        = string
  default     = "insidellm-admin"
}

# =============================================================================
# ANTHROPIC API
# =============================================================================

variable "anthropic_api_key" {
  description = "Anthropic API key from https://console.anthropic.com"
  type        = string
  sensitive   = true
}

# =============================================================================
# ADDITIONAL VENDOR API KEYS (optional — empty disables that vendor)
# =============================================================================

variable "openai_api_key" {
  description = "OpenAI API key (https://platform.openai.com). Empty = disabled."
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  description = "Google Gemini API key (https://aistudio.google.com). Empty = disabled."
  type        = string
  sensitive   = true
  default     = ""
}

variable "mistral_api_key" {
  description = "Mistral API key (https://console.mistral.ai). Empty = disabled."
  type        = string
  sensitive   = true
  default     = ""
}

variable "cohere_api_key" {
  description = "Cohere API key (https://dashboard.cohere.com). Empty = disabled."
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_openai_api_key" {
  description = "Azure OpenAI API key. Empty = disabled."
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint, e.g. https://my-resource.openai.azure.com"
  type        = string
  default     = ""
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI API version"
  type        = string
  default     = "2024-08-01-preview"
}

variable "azure_openai_deployment" {
  description = "Azure OpenAI deployment name (model)"
  type        = string
  default     = ""
}

variable "aws_bedrock_access_key_id" {
  description = "AWS access key ID for Bedrock. Empty = disabled."
  type        = string
  sensitive   = true
  default     = ""
}

variable "aws_bedrock_secret_access_key" {
  description = "AWS secret access key for Bedrock."
  type        = string
  sensitive   = true
  default     = ""
}

variable "aws_bedrock_region" {
  description = "AWS region for Bedrock (e.g. us-east-1)"
  type        = string
  default     = "us-east-1"
}

variable "aws_bedrock_model" {
  description = "Bedrock model ID, e.g. anthropic.claude-3-5-sonnet-20241022-v2:0"
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20241022-v2:0"
}

# =============================================================================
# LITELLM CONFIGURATION
# =============================================================================

variable "litellm_master_key" {
  description = "Master API key for LiteLLM proxy admin access. Auto-generated if empty."
  type        = string
  sensitive   = true
  default     = ""
}

variable "litellm_salt_key" {
  description = <<-EOT
    LITELLM_SALT_KEY — used by LiteLLM to encrypt virtual API keys in its
    database. Must remain stable across container recreates; if it changes,
    previously issued virtual keys become unreadable. Auto-generated on first
    deploy; for fleet deployments set this explicitly (same value on every VM
    sharing a Postgres) or let each VM generate its own if DBs aren't shared.
  EOT
  type        = string
  sensitive   = true
  default     = ""
}

variable "litellm_default_model" {
  description = "Default model alias for LiteLLM routing"
  type        = string
  default     = "claude-sonnet"
}

variable "litellm_enable_haiku" {
  description = "Enable Claude Haiku (cheapest tier) in model routing"
  type        = bool
  default     = true
}

variable "litellm_enable_opus" {
  description = "Enable Claude Opus (most capable tier) in model routing"
  type        = bool
  default     = true
}

variable "litellm_global_max_budget" {
  description = "Global maximum monthly budget in USD (0 = unlimited)"
  type        = number
  default     = 100
}

variable "litellm_default_user_budget" {
  description = "Default per-user daily budget in USD"
  type        = number
  default     = 5.0
}

variable "litellm_default_user_rpm" {
  description = "Default requests per minute per user"
  type        = number
  default     = 30
}

variable "litellm_default_user_tpm" {
  description = "Default tokens per minute per user"
  type        = number
  default     = 100000
}

# =============================================================================
# LOCAL LLM (OLLAMA)
# =============================================================================

variable "ollama_enable" {
  description = "Enable a local Ollama instance for self-hosted LLM models"
  type        = bool
  default     = true
}

variable "ollama_models" {
  description = "List of Ollama model tags to pull on startup (e.g., [\"qwen2.5-coder:14b\", \"qwen2.5:14b\"])"
  type        = list(string)
  default     = ["qwen2.5-coder:14b", "qwen2.5:14b"]
}

variable "ollama_gpu" {
  description = "Enable NVIDIA GPU passthrough for the Ollama container"
  type        = bool
  default     = false
}

variable "ollama_separate_vm" {
  description = "Deploy Ollama in a separate Hyper-V VM instead of a container in the main stack"
  type        = bool
  default     = false
}

variable "ollama_vm_processor_count" {
  description = "Number of vCPUs for the Ollama VM (when ollama_separate_vm = true)"
  type        = number
  default     = 8
}

variable "ollama_vm_memory_startup_bytes" {
  description = "Startup RAM in bytes for the Ollama VM"
  type        = number
  default     = 34359738368 # 32 GB
}

variable "ollama_vm_disk_size_bytes" {
  description = "Disk size in bytes for the Ollama VM"
  type        = number
  default     = 107374182400 # 100 GB
}

variable "ollama_vm_static_ip" {
  description = "Static IP for the Ollama VM (CIDR notation). Must be reachable from the main VM."
  type        = string
  default     = ""
}

# =============================================================================
# DATABASE
# =============================================================================

variable "postgres_password" {
  description = "Password for PostgreSQL database. Auto-generated if empty."
  type        = string
  sensitive   = true
  default     = ""
}

# =============================================================================
# SSO / AUTHENTICATION (Optional — leave empty to skip)
# =============================================================================

variable "sso_provider" {
  description = "SSO provider type: 'azure_ad', 'okta', 'generic', or 'none'"
  type        = string
  default     = "none"

  validation {
    condition     = contains(["azure_ad", "okta", "generic", "none"], var.sso_provider)
    error_message = "SSO provider must be azure_ad, okta, generic, or none."
  }
}

# --- Azure AD ---
variable "azure_ad_client_id" {
  description = "Azure AD (Entra ID) application client ID"
  type        = string
  default     = ""
}

variable "azure_ad_client_secret" {
  description = "Azure AD application client secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_ad_tenant_id" {
  description = "Azure AD tenant ID"
  type        = string
  default     = ""
}

# --- Okta ---
variable "okta_client_id" {
  description = "Okta application client ID"
  type        = string
  default     = ""
}

variable "okta_client_secret" {
  description = "Okta application client secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "okta_domain" {
  description = "Okta domain (e.g., your-org.okta.com)"
  type        = string
  default     = ""
}

# --- SSO Group-to-Team Mapping ---
variable "sso_group_field" {
  description = "JWT claim field containing group membership (usually 'groups')"
  type        = string
  default     = "groups"

  validation {
    condition     = can(regex("^[a-zA-Z_][a-zA-Z0-9_.-]*$", var.sso_group_field))
    error_message = "sso_group_field must be a valid JWT claim name (alphanumeric, underscores, hyphens, dots)."
  }
}

variable "sso_group_mapping" {
  description = "Map SSO group names to LiteLLM teams with budgets, rate limits, and model access"
  type = map(object({
    budget          = number
    budget_duration = string
    rpm_limit       = number
    tpm_limit       = number
    models          = list(string)
  }))
  default = {}
}

# =============================================================================
# DLP CONFIGURATION
# =============================================================================

variable "dlp_enable" {
  description = "Enable the Data Loss Prevention pipeline in Open WebUI"
  type        = bool
  default     = true
}

variable "dlp_block_ssn" {
  description = "Block messages containing Social Security Numbers"
  type        = bool
  default     = true
}

variable "dlp_block_credit_cards" {
  description = "Block messages containing credit card numbers"
  type        = bool
  default     = true
}

variable "dlp_block_phi" {
  description = "Block messages containing Protected Health Information patterns"
  type        = bool
  default     = true
}

variable "dlp_block_credentials" {
  description = "Block messages containing API keys, passwords, connection strings"
  type        = bool
  default     = true
}

variable "dlp_custom_patterns" {
  description = "Additional regex patterns to block (map of name => regex)"
  type        = map(string)
  default     = {}
}

# =============================================================================
# FILE CONVERSION (DOCFORGE)
# =============================================================================

variable "docforge_enable" {
  description = "Enable the DocForge file generation and conversion service"
  type        = bool
  default     = true
}

variable "docforge_max_file_size_mb" {
  description = "Maximum file upload size for DocForge conversions (in MB)"
  type        = number
  default     = 50
}

# =============================================================================
# AI GOVERNANCE & OPERATIONS
# =============================================================================

variable "industry" {
  description = "Industry vertical for keyword templates and governance defaults"
  type        = string
  default     = "general"

  validation {
    condition     = contains(["general", "collections", "healthcare", "financial", "insurance", "legal", "realestate", "retail", "education", "government", "manufacturing", "custom"], var.industry)
    error_message = "Industry must be one of: general, collections, healthcare, financial, insurance, legal, realestate, retail, education, government, manufacturing, custom."
  }
}

variable "governance_tier" {
  description = "AI Governance tier: tier1 (material decisions — full controls), tier2 (operational — standard), tier3 (routine tools — lightweight)"
  type        = string
  default     = "tier3"

  validation {
    condition     = contains(["tier1", "tier2", "tier3"], var.governance_tier)
    error_message = "Governance tier must be tier1, tier2, or tier3."
  }
}

variable "data_classification" {
  description = "Highest data classification level handled: public, internal, confidential, restricted"
  type        = string
  default     = "internal"

  validation {
    condition     = contains(["public", "internal", "confidential", "restricted"], var.data_classification)
    error_message = "Data classification must be public, internal, confidential, or restricted."
  }
}

variable "ai_ethics_officer" {
  description = "Name of the AI Ethics Officer (for incident escalation and audit reports)"
  type        = string
  default     = ""
}

variable "ai_ethics_officer_email" {
  description = "Email of the AI Ethics Officer"
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "Number of days to retain API logs and audit trails (governance requires 1095-2555 for Tier 1)"
  type        = number
  default     = 365
}

variable "ops_watchtower_enable" {
  description = "Enable Watchtower for automatic container image updates"
  type        = bool
  default     = true
}

variable "ops_trivy_enable" {
  description = "Enable Trivy daily CVE scanning of container images"
  type        = bool
  default     = true
}

variable "ops_grafana_enable" {
  description = "Enable Grafana + Loki for compliance dashboards and centralized logging"
  type        = bool
  default     = true
}

variable "ops_uptime_kuma_enable" {
  description = "Enable Uptime Kuma for service health monitoring and alerting"
  type        = bool
  default     = true
}

variable "ops_backup_schedule" {
  description = "PostgreSQL backup frequency: daily, weekly, or none"
  type        = string
  default     = "daily"

  validation {
    condition     = contains(["daily", "weekly", "none"], var.ops_backup_schedule)
    error_message = "Backup schedule must be daily, weekly, or none."
  }
}

variable "ops_alert_webhook" {
  description = "Webhook URL for operational alerts (Slack, Teams, etc.)"
  type        = string
  default     = ""
}

variable "guacamole_enable" {
  description = "Enable Apache Guacamole — browser-based RDP/VNC/SSH gateway at /remote/"
  type        = bool
  default     = false
}

variable "keyword_categories" {
  description = "Additional keyword categories for request analysis (map of category name => list of keywords)"
  type        = map(list(string))
  default     = {}
}

variable "keyword_refresh_schedule" {
  description = "Cron schedule for refreshing keyword materialized views (default: every 15 minutes)"
  type        = string
  default     = "*/15 * * * *"
}

# =============================================================================
# OPA POLICY ENGINE
# =============================================================================

variable "policy_engine_enable" {
  description = "Enable the OPA policy enforcement engine (Humility alignment + industry policies)"
  type        = bool
  default     = false
}

variable "policy_engine_industry_policies" {
  description = "Industry regulatory policies to load: hipaa, fdcpa, sox, pci_dss, ferpa, glba"
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for p in var.policy_engine_industry_policies : contains(["hipaa", "fdcpa", "sox", "pci_dss", "ferpa", "glba"], p)])
    error_message = "Industry policies must be from: hipaa, fdcpa, sox, pci_dss, ferpa, glba."
  }
}

variable "policy_engine_fail_mode" {
  description = "Policy engine fail mode: 'closed' (block on error) or 'log_only' (allow but log)"
  type        = string
  default     = "closed"

  validation {
    condition     = contains(["closed", "log_only"], var.policy_engine_fail_mode)
    error_message = "Fail mode must be 'closed' or 'log_only'."
  }
}

# =============================================================================
# ENTERPRISE GOVERNANCE HUB
# =============================================================================

variable "governance_hub_enable" {
  description = "Enable the Governance Hub for central repository sync, change management, and AI advisor"
  type        = bool
  default     = false
}

variable "governance_hub_central_db_type" {
  description = "Central repository database type: postgresql, mariadb, mssql"
  type        = string
  default     = "postgresql"

  validation {
    condition     = contains(["postgresql", "mariadb", "mssql"], var.governance_hub_central_db_type)
    error_message = "Central DB type must be postgresql, mariadb, or mssql."
  }
}

variable "governance_hub_central_db_host" {
  description = "Central repository database hostname"
  type        = string
  default     = ""
}

variable "governance_hub_central_db_port" {
  description = "Central repository database port"
  type        = number
  default     = 5432
}

variable "governance_hub_central_db_name" {
  description = "Central repository database name"
  type        = string
  default     = "insidellm_central"
}

variable "governance_hub_central_db_user" {
  description = "Central repository database username"
  type        = string
  default     = ""
}

variable "governance_hub_central_db_password" {
  description = "Central repository database password"
  type        = string
  sensitive   = true
  default     = ""
}

variable "governance_hub_instance_name" {
  description = "Human-readable name for this InsideLLM instance in the central repository"
  type        = string
  default     = ""
}

variable "governance_hub_sync_schedule" {
  description = "Cron schedule for syncing to central repository (default: every 6 hours)"
  type        = string
  default     = "0 */6 * * *"
}

variable "governance_hub_supervisor_emails" {
  description = "Comma-separated emails of supervisors who can approve governance changes"
  type        = string
  default     = ""
}

variable "governance_hub_advisor_model" {
  description = "LLM model the AI governance advisor uses for analysis"
  type        = string
  default     = "claude-sonnet"
}

variable "governance_hub_registration_token" {
  description = "Fleet registration token for auto-registering this instance with an existing fleet (generated from Fleet tab → Registration Token)"
  type        = string
  default     = ""
  sensitive   = true
}

# =============================================================================
# TLS CONFIGURATION
# =============================================================================

variable "tls_cert_path" {
  description = "Path to TLS certificate file. Leave empty to generate a self-signed cert."
  type        = string
  default     = ""
}

variable "tls_key_path" {
  description = "Path to TLS private key file. Leave empty to generate a self-signed cert."
  type        = string
  default     = ""
}

# =============================================================================
# TAGS / METADATA
# =============================================================================

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "production"
}

variable "owner" {
  description = "Owner of this deployment"
  type        = string
  default     = "Your Company Name"
}

# =============================================================================
# DLP GUARDRAIL — extra knobs (the LiteLLM-level guardrail reuses
# dlp_enable / dlp_block_* / dlp_custom_patterns declared above)
# =============================================================================

variable "dlp_mode" {
  description = "DLP action mode: 'block' rejects matching requests, 'redact' replaces matches with [REDACTED-*]."
  type        = string
  default     = "block"

  validation {
    condition     = contains(["block", "redact"], var.dlp_mode)
    error_message = "dlp_mode must be 'block' or 'redact'."
  }
}

variable "dlp_block_bank_accounts" {
  description = "Block messages containing bank account / routing numbers"
  type        = bool
  default     = true
}

variable "dlp_block_standalone_dates" {
  description = "Block standalone dates (MM/DD/YYYY, YYYY-MM-DD) that may be dates of birth"
  type        = bool
  default     = true
}

variable "dlp_scan_responses" {
  description = "Also scan model responses and redact echoed sensitive data"
  type        = bool
  default     = true
}

# =============================================================================
# CHAT — Mattermost embedded team chat (FOSS, MIT Team Edition)
# =============================================================================

variable "chat_enable" {
  description = "Deploy Mattermost chat server embedded under /chat/ (browser-based team chat for governance-hub users)"
  type        = bool
  default     = false
}

variable "chat_team_name" {
  description = "Mattermost default team URL slug"
  type        = string
  default     = "insidellm"
}

variable "chat_default_channel" {
  description = "Default Mattermost channel created inside the team"
  type        = string
  default     = "general"
}

# =============================================================================
# FLEET / EDGE (Tier 1 modularity + front-door router)
# =============================================================================
# vm_role selects role-derived defaults; explicit *_enable flags above always win.

variable "vm_role" {
  description = "Role of this VM in the fleet. Empty = standalone (default, backwards-compatible). Valid: primary | gateway | workstation | voice | edge | storage"
  type        = string
  default     = ""
  validation {
    condition     = contains(["", "primary", "gateway", "workstation", "voice", "edge", "storage"], var.vm_role)
    error_message = "vm_role must be one of: primary, gateway, workstation, voice, edge, storage, or empty string."
  }
}

variable "fleet_primary_host" {
  description = "Hostname or IP of the fleet primary (Gov-Hub, Grafana, Loki). Non-primary roles point at this for remote logging and capability registry."
  type        = string
  default     = ""
}

variable "fleet_virtual_ip" {
  description = "Virtual IP owned by keepalived on the active edge VM. Clients hit this address via the configured FQDN."
  type        = string
  default     = ""
}

variable "edge_tls_source" {
  description = "How the edge VM obtains its TLS cert: self-signed | letsencrypt | custom"
  type        = string
  default     = "self-signed"
  validation {
    condition     = contains(["self-signed", "letsencrypt", "custom"], var.edge_tls_source)
    error_message = "edge_tls_source must be one of: self-signed, letsencrypt, custom."
  }
}

variable "edge_tls_cert_path" {
  description = "Path on the edge VM to the PEM-encoded certificate (when edge_tls_source = custom)"
  type        = string
  default     = ""
}

variable "edge_tls_key_path" {
  description = "Path on the edge VM to the PEM-encoded private key (when edge_tls_source = custom)"
  type        = string
  default     = ""
}

variable "edge_domain" {
  description = "FQDN served by the edge (e.g., insidellm.corp.example.com). Used for TLS cert CN and OIDC redirect URIs."
  type        = string
  default     = ""
}

variable "department" {
  description = "Department label for this backend gateway (routed to by the edge based on OIDC claim). Empty for non-gateway roles."
  type        = string
  default     = ""
}

variable "fallback_department" {
  description = "If this department backend is down, the edge routes to this sibling's backend. Empty = fail fast (no fallback)."
  type        = string
  default     = ""
}

# Local package mirrors (speeds up 2nd+ VM deploys).
# Primary VM auto-runs apt-cacher-ng + registry mirror when vm_role=primary.
# Every other VM's cloud-init points at the primary for packages and images.

variable "pkg_mirror_enable" {
  description = "Force-enable the local apt + Docker registry mirror on this VM. Default: auto (ON when vm_role=primary)."
  type        = bool
  default     = false
}

variable "apt_mirror_host" {
  description = "Host (IP or FQDN, no scheme) of the apt-cacher-ng mirror to use. Empty = go direct to upstream. Typically equals fleet_primary_host."
  type        = string
  default     = ""
}

variable "docker_mirror_host" {
  description = "Host of the Docker registry pull-through mirror. Empty = go direct to Docker Hub. Typically equals fleet_primary_host."
  type        = string
  default     = ""
}

# Per-VM Claude Code CLI (ops / troubleshooting). Not routed through InsideLLM
# — operators log in with their own Anthropic account via `claude login`.
# One installed CLI per VM lets an operator SSH into a specific instance and
# troubleshoot with an AI assistant that has that VM's full context.
variable "claude_code_enable" {
  description = "Install Claude Code CLI for the admin user on this VM. Auto-skipped for vm_role=edge|voice|storage. Default true."
  type        = bool
  default     = true
}

# XFCE desktop + xrdp for Guacamole-friendly remote access. Off by default
# so headless VMs stay headless. Turn on for operator workstations / jump
# hosts where a browser-based Linux desktop via Guacamole is wanted.
variable "desktop_enable" {
  description = "Install XFCE desktop + xrdp on this VM. Enables Guacamole RDP access via port 3389. Default false."
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# Keycloak — optional local SSO (tenant-scoped; opt-in)
# -----------------------------------------------------------------------------
# Pattern: local Keycloak container reads/writes a dedicated `keycloak`
# database inside the existing insidellm-postgres service. A downstream
# sync service (next phase) pushes realm + group state up to the central
# MSSQL governance store. This keeps Keycloak fast (per-VM) while the
# fleet-wide identity view lives in the central DB.
variable "keycloak_enable" {
  description = "Deploy a local Keycloak instance for SSO. Default false (opt-in)."
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# Demo workers — stub FastAPI backing for showcase declarative agents (P1.6)
# -----------------------------------------------------------------------------
# Production tenants replace this per-tenant; leave false unless running the
# Parent Organization Dispute Handler showcase or another demo agent that references
# http://insidellm-workers:8000 in its action catalog entries.
variable "workers_enable" {
  description = "Deploy the insidellm-workers stub FastAPI service. Default false."
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# n8n tool factory — per-tenant low-code workflow builder (P3.1)
# -----------------------------------------------------------------------------
# n8n Community Edition (Apache 2.0 + Sustainable Use License — fine for
# single-tenant self-host). Each VM runs its own n8n container against the
# shared local Postgres; action catalog entries with backend.type=n8n_webhook
# hit n8n's webhook endpoint via the gov-hub dispatcher.
variable "n8n_enable" {
  description = "Deploy a local n8n workflow service. Default false (opt-in per tenant)."
  type        = bool
  default     = false
}

variable "n8n_version" {
  description = "n8n container image tag. Pin for deterministic deploys."
  type        = string
  default     = "1.67.1"
}

variable "n8n_db_name" {
  description = "Database name n8n uses inside insidellm-postgres."
  type        = string
  default     = "n8n"
}

variable "n8n_webhook_secret" {
  description = "HMAC secret for n8n webhook signature verification. Generate via `openssl rand -hex 32`. Empty = generated at deploy time."
  type        = string
  sensitive   = true
  default     = ""
}

# -----------------------------------------------------------------------------
# Activepieces tool factory — MIT-licensed n8n alternative (P3.2)
# -----------------------------------------------------------------------------
# Drops into the same action-catalog slot as n8n via backend.type =
# activepieces_trigger. Shares local Postgres + Redis; dispatcher signs
# outbound calls with the same HMAC envelope shape as n8n so workflows
# can be ported across by swapping a URL.
variable "activepieces_enable" {
  description = "Deploy a local Activepieces workflow service. Default false (opt-in per tenant)."
  type        = bool
  default     = false
}

variable "activepieces_version" {
  description = "Activepieces container image tag."
  type        = string
  default     = "0.56.0"
}

variable "activepieces_db_name" {
  description = "Database name Activepieces uses inside insidellm-postgres."
  type        = string
  default     = "activepieces"
}

variable "activepieces_webhook_secret" {
  description = "HMAC secret for Activepieces webhook signatures. Empty = auto-generated."
  type        = string
  sensitive   = true
  default     = ""
}

variable "keycloak_version" {
  description = "Keycloak container image tag (keep pinned for deterministic deploys)."
  type        = string
  default     = "25.0.6"
}

variable "keycloak_realm_name" {
  description = "Name of the realm auto-imported on first boot."
  type        = string
  default     = "insidellm"
}

variable "keycloak_db_name" {
  description = "Name of the database Keycloak uses inside insidellm-postgres."
  type        = string
  default     = "keycloak"
}

variable "keycloak_admin_user" {
  description = "Keycloak master-realm admin username. Defaults to insidellm-admin so break-glass stays single-source."
  type        = string
  default     = "insidellm-admin"
}

variable "keycloak_govhub_client_secret" {
  description = "OIDC client secret for the governance-hub client. Generate via `openssl rand -hex 32`."
  type        = string
  sensitive   = true
  default     = ""
}

variable "keycloak_owui_client_secret" {
  description = "OIDC client secret for the open-webui client."
  type        = string
  sensitive   = true
  default     = ""
}

variable "keycloak_litellm_client_secret" {
  description = "OIDC client secret for the litellm client."
  type        = string
  sensitive   = true
  default     = ""
}

# =============================================================================
# CANONICAL SESSIONS (Phase 3.3+)
# Declarative session tier + data residency drive retention, handoff policy,
# mirror-promotion controls, push payload stripping, and cross-region fork
# eligibility. See configs/opa/policies/sessions/*.rego for enforcement.
# =============================================================================

variable "session_security_tier" {
  description = <<EOT
Tenant default security tier for canonical sessions. Valid values:
  T0 Ephemeral       24h retention; break-glass
  T1 Public          30d; public catalog chat
  T2 Standard        90d / 1y; internal ops
  T3 Confidential    30d / 3y; contracts, IP, M&A
  T4 Consumer-fin    60d / 7y; FDCPA/FCRA regulated (dispute-handler)
  T5 Healthcare      30d / 6y; HIPAA
  T6 Financial-svcs  30d / 7y; GLBA/SOX/17a-4 WORM
  T7 High-security   7d; aggressive key rotation
Agent manifests and session classification may only tighten (raise) the tier, never lower it.
EOT
  type        = string
  default     = "T2"
  validation {
    condition     = contains(["T0", "T1", "T2", "T3", "T4", "T5", "T6", "T7"], var.session_security_tier)
    error_message = "session_security_tier must be one of T0..T7."
  }
}

variable "session_data_region" {
  description = "Data residency region for this tenant stack. Used by sessions.residency OPA rule to gate cross-region federation."
  type        = string
  default     = "us-east"
}

variable "session_retention_floor_days_override" {
  description = "Optional per-tenant override raising the tier floor (days). 0 = use tier default."
  type        = number
  default     = 0
}

variable "session_retention_cap_days" {
  description = "Maximum days of cold retention before cryptographic erasure. 0 = use tier default."
  type        = number
  default     = 0
}

# -----------------------------------------------------------------------------
# Progressive Web App + Web Push
# -----------------------------------------------------------------------------

variable "pwa_enable" {
  description = "Enable the installable InsideLLM PWA (OWUI-embedded + governance-hub inbox)."
  type        = bool
  default     = true
}

variable "pwa_theme_color" {
  description = "PWA manifest theme_color."
  type        = string
  default     = "#0b4f8c"
}

variable "pwa_background_color" {
  description = "PWA manifest background_color (splash screen)."
  type        = string
  default     = "#ffffff"
}

variable "pwa_display" {
  description = "PWA display mode: standalone | fullscreen | minimal-ui | browser."
  type        = string
  default     = "standalone"
  validation {
    condition     = contains(["standalone", "fullscreen", "minimal-ui", "browser"], var.pwa_display)
    error_message = "pwa_display must be standalone, fullscreen, minimal-ui, or browser."
  }
}

variable "pwa_tenant_name" {
  description = "Display name for the installable PWA."
  type        = string
  default     = "InsideLLM"
}

variable "pwa_icon_512_path" {
  description = "Path to the 512x512 PNG icon relative to templates/."
  type        = string
  default     = "pwa/icon-512.png"
}

variable "pwa_icon_192_path" {
  description = "Path to the 192x192 PNG icon relative to templates/."
  type        = string
  default     = "pwa/icon-192.png"
}

variable "pwa_allowed_tiers" {
  description = "Tiers permitted to register for Web Push on this tenant. See sessions/push.rego for payload stripping per tier."
  type        = list(string)
  default     = ["T1", "T2", "T3", "T4"]
}

variable "vapid_public_key" {
  description = "Base64url-encoded VAPID public key for Web Push. Auto-generated on apply if empty."
  type        = string
  default     = ""
}

variable "vapid_private_key" {
  description = "Base64url-encoded VAPID private key for Web Push. Auto-generated on apply if empty."
  type        = string
  sensitive   = true
  default     = ""
}

variable "vapid_subject" {
  description = "VAPID subject (mailto: or https:) — contact point for push-endpoint abuse reports."
  type        = string
  default     = "mailto:ops@insidellm.local"
}
