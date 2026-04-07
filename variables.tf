###############################################################################
# variables.tf — Input variables for the Claude Wrapper deployment
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

variable "ubuntu_vhdx_source" {
  description = "Path to the Ubuntu 24.04 cloud image VHDX on the Hyper-V host (created by Setup-Prerequisites.ps1)"
  type        = string
  default     = "C:\\HyperV\\Images\\ubuntu-24.04-cloudimg-amd64.vhdx"
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
  default     = "uniformedi.local"
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
# LITELLM CONFIGURATION
# =============================================================================

variable "litellm_master_key" {
  description = "Master API key for LiteLLM proxy admin access. Auto-generated if empty."
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
