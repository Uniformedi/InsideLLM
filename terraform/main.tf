###############################################################################
# main.tf — Root module: orchestrates VM creation and full provisioning
###############################################################################

# ---------------------------------------------------------------------------
# Generate secrets if not provided
# ---------------------------------------------------------------------------

resource "random_password" "litellm_master_key" {
  count   = var.litellm_master_key == "" ? 1 : 0
  length  = 32
  special = false
}

resource "random_password" "postgres_password" {
  count   = var.postgres_password == "" ? 1 : 0
  length  = 24
  special = false
}

resource "random_password" "webui_secret" {
  length  = 32
  special = false
}

resource "random_password" "xrdp_password" {
  length  = 16
  special = false
}

resource "random_password" "grafana_password" {
  count   = var.ops_grafana_enable ? 1 : 0
  length  = 20
  special = false
}

resource "random_password" "governance_hub_secret" {
  count   = var.governance_hub_enable ? 1 : 0
  length  = 32
  special = false
}

locals {
  litellm_master_key = var.litellm_master_key != "" ? var.litellm_master_key : "sk-${random_password.litellm_master_key[0].result}"
  postgres_password  = var.postgres_password != "" ? var.postgres_password : random_password.postgres_password[0].result
  webui_secret       = random_password.webui_secret.result
  xrdp_password      = random_password.xrdp_password.result
  grafana_password   = var.ops_grafana_enable ? random_password.grafana_password[0].result : ""
  governance_hub_secret = var.governance_hub_enable ? random_password.governance_hub_secret[0].result : ""

  vm_fqdn = "${var.vm_hostname}.${var.vm_domain}"

  # Sanitized deployment tfvars — stored on the VM for snapshot/clone.
  # Secrets are replaced with REDACTED placeholders.
  platform_version = trimspace(file("${path.module}/../VERSION"))
  deployment_tfvars = <<-TFVARS
# InsideLLM Deployment Configuration (sanitized — secrets redacted)
# Deployed: ${timestamp()}
# Platform: v${trimspace(file("${path.module}/../VERSION"))}

# Hyper-V
hyperv_user     = "${var.hyperv_user}"
hyperv_password = "REDACTED"
hyperv_host     = "${var.hyperv_host}"

# VM
vm_name              = "${var.vm_name}"
vm_processor_count   = ${var.vm_processor_count}
vm_memory_startup_bytes = ${var.vm_memory_startup_bytes}
vm_disk_size_bytes      = ${var.vm_disk_size_bytes}
vm_path              = "${replace(var.vm_path, "\\", "\\\\")}"
vm_vhd_path          = "${replace(var.vm_vhd_path, "\\", "\\\\")}"
vm_hostname          = "${var.vm_hostname}"
vm_domain            = "${var.vm_domain}"
ubuntu_vhdx_source   = "${replace(var.ubuntu_vhdx_source, "\\", "\\\\")}"

# Network
vm_switch_name    = "${var.vm_switch_name}"
vm_switch_type    = "${var.vm_switch_type}"
vm_switch_adapter = "${var.vm_switch_adapter}"
vm_static_ip      = "${var.vm_static_ip}"
vm_gateway        = "${var.vm_gateway}"
vm_dns_servers    = ${jsonencode(var.vm_dns_servers)}

# SSH
ssh_admin_user      = "${var.ssh_admin_user}"
ssh_public_key_path = "${var.ssh_public_key_path}"

# API
anthropic_api_key = "REDACTED"

# LiteLLM
litellm_master_key         = "REDACTED"
litellm_default_model      = "${var.litellm_default_model}"
litellm_enable_haiku       = ${var.litellm_enable_haiku}
litellm_enable_opus        = ${var.litellm_enable_opus}
litellm_global_max_budget  = ${var.litellm_global_max_budget}
litellm_default_user_budget = ${var.litellm_default_user_budget}
litellm_default_user_rpm   = ${var.litellm_default_user_rpm}
litellm_default_user_tpm   = ${var.litellm_default_user_tpm}

# Database
postgres_password = "REDACTED"

# Ollama
ollama_enable = ${var.ollama_enable}
ollama_models = ${jsonencode(var.ollama_models)}
ollama_gpu    = ${var.ollama_gpu}

# SSO
sso_provider = "${var.sso_provider}"

# AD Domain Join
ad_domain_join   = ${var.ad_domain_join}
ad_admin_groups  = "${var.ad_admin_groups}"

# DLP
dlp_enable           = ${var.dlp_enable}
dlp_block_ssn        = ${var.dlp_block_ssn}
dlp_block_credit_cards = ${var.dlp_block_credit_cards}
dlp_block_phi        = ${var.dlp_block_phi}
dlp_block_credentials = ${var.dlp_block_credentials}

# Optional Services
docforge_enable = ${var.docforge_enable}

# AI Governance
industry                 = "${var.industry}"
governance_tier          = "${var.governance_tier}"
data_classification      = "${var.data_classification}"
ai_ethics_officer        = "${var.ai_ethics_officer}"
ai_ethics_officer_email  = "${var.ai_ethics_officer_email}"
log_retention_days       = ${var.log_retention_days}

# Operations
ops_watchtower_enable    = ${var.ops_watchtower_enable}
ops_trivy_enable         = ${var.ops_trivy_enable}
ops_grafana_enable       = ${var.ops_grafana_enable}
ops_uptime_kuma_enable   = ${var.ops_uptime_kuma_enable}
ops_backup_schedule      = "${var.ops_backup_schedule}"

# Governance Hub
governance_hub_enable              = ${var.governance_hub_enable}
governance_hub_instance_name       = "${var.governance_hub_instance_name != "" ? var.governance_hub_instance_name : var.vm_name}"
governance_hub_sync_schedule       = "${var.governance_hub_sync_schedule}"
governance_hub_supervisor_emails   = "${var.governance_hub_supervisor_emails}"
governance_hub_advisor_model       = "${var.governance_hub_advisor_model}"

# OPA Policy Engine
policy_engine_enable               = ${var.policy_engine_enable}

# Environment
environment = "${var.environment}"
owner       = "${var.owner}"
TFVARS

  # Read SSH public key
  ssh_public_key = file(pathexpand(var.ssh_public_key_path))

  # SSO environment variables block for Docker Compose
  sso_env = var.sso_provider == "azure_ad" ? {
    MICROSOFT_CLIENT_ID     = var.azure_ad_client_id
    MICROSOFT_CLIENT_SECRET = var.azure_ad_client_secret
    MICROSOFT_TENANT        = var.azure_ad_tenant_id
  } : var.sso_provider == "okta" ? {
    GENERIC_CLIENT_ID              = var.okta_client_id
    GENERIC_CLIENT_SECRET          = var.okta_client_secret
    GENERIC_AUTHORIZATION_ENDPOINT = "https://${var.okta_domain}/oauth2/v1/authorize"
    GENERIC_TOKEN_ENDPOINT         = "https://${var.okta_domain}/oauth2/v1/token"
    GENERIC_USERINFO_ENDPOINT      = "https://${var.okta_domain}/oauth2/v1/userinfo"
    GENERIC_USER_ID_ATTRIBUTE      = "sub"
    GENERIC_USER_EMAIL_ATTRIBUTE   = "email"
    GENERIC_USER_DISPLAY_NAME_ATTRIBUTE = "name"
  } : {}
}

# ---------------------------------------------------------------------------
# Generate self-signed TLS certificate (if none provided)
# ---------------------------------------------------------------------------

resource "tls_private_key" "self_signed" {
  count     = var.tls_cert_path == "" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "self_signed" {
  count           = var.tls_cert_path == "" ? 1 : 0
  private_key_pem = tls_private_key.self_signed[0].private_key_pem

  subject {
    common_name  = local.vm_fqdn
    organization = var.owner
  }

  dns_names = [
    local.vm_fqdn,
    var.vm_hostname,
    "localhost",
  ]

  ip_addresses = compact([
    var.vm_static_ip != "" ? split("/", var.vm_static_ip)[0] : "",
    "127.0.0.1",
  ])

  validity_period_hours = 8760 # 1 year

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

locals {
  tls_cert = var.tls_cert_path != "" ? file(var.tls_cert_path) : tls_self_signed_cert.self_signed[0].cert_pem
  tls_key  = var.tls_key_path != "" ? file(var.tls_key_path) : tls_private_key.self_signed[0].private_key_pem
}

# ---------------------------------------------------------------------------
# Archive DocForge source for cloud-init deployment
# ---------------------------------------------------------------------------

data "archive_file" "docforge" {
  count       = var.docforge_enable ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/../configs/docforge"
  output_path = "${path.module}/.terraform/tmp/docforge.zip"
}

data "archive_file" "opa_policies" {
  count       = var.policy_engine_enable ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/../configs/opa"
  output_path = "${path.module}/.terraform/tmp/opa-policies.zip"
}

data "archive_file" "governance_hub" {
  count       = var.governance_hub_enable ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/../configs/governance-hub"
  output_path = "${path.module}/.terraform/tmp/governance-hub.zip"
}

# ---------------------------------------------------------------------------
# Render configuration templates
# ---------------------------------------------------------------------------

# --- LiteLLM config ---
locals {
  litellm_config = templatefile("${path.module}/../configs/litellm/config.yaml.tpl", {
    anthropic_api_key       = var.anthropic_api_key
    enable_haiku            = var.litellm_enable_haiku
    enable_opus             = var.litellm_enable_opus
    openai_enable           = var.openai_api_key != ""
    gemini_enable           = var.gemini_api_key != ""
    mistral_enable          = var.mistral_api_key != ""
    cohere_enable           = var.cohere_api_key != ""
    azure_openai_enable     = var.azure_openai_api_key != "" && var.azure_openai_endpoint != "" && var.azure_openai_deployment != ""
    azure_openai_endpoint   = var.azure_openai_endpoint
    azure_openai_api_version = var.azure_openai_api_version
    azure_openai_deployment = var.azure_openai_deployment
    bedrock_enable          = var.aws_bedrock_access_key_id != "" && var.aws_bedrock_secret_access_key != ""
    bedrock_region          = var.aws_bedrock_region
    bedrock_model           = var.aws_bedrock_model
    default_user_budget     = var.litellm_default_user_budget
    default_user_rpm        = var.litellm_default_user_rpm
    default_user_tpm        = var.litellm_default_user_tpm
    global_max_budget       = var.litellm_global_max_budget
    ollama_enable               = var.ollama_enable
    ollama_models               = var.ollama_models
    ollama_api_base             = var.ollama_separate_vm ? "http://${split("/", var.ollama_vm_static_ip)[0]}:11434" : "http://ollama:11434"
    sso_enabled                 = var.sso_provider != "none"
    sso_group_mapping_enabled   = var.sso_provider != "none" && length(var.sso_group_mapping) > 0
    sso_group_field             = var.sso_group_field
  })
}

# --- Docker Compose ---
locals {
  docker_compose = templatefile("${path.module}/../templates/docker-compose.yml.tpl", {
    postgres_password  = local.postgres_password
    litellm_master_key = local.litellm_master_key
    anthropic_api_key  = var.anthropic_api_key
    openai_api_key                = var.openai_api_key
    gemini_api_key                = var.gemini_api_key
    mistral_api_key               = var.mistral_api_key
    cohere_api_key                = var.cohere_api_key
    azure_openai_api_key          = var.azure_openai_api_key
    azure_openai_endpoint         = var.azure_openai_endpoint
    azure_openai_api_version      = var.azure_openai_api_version
    aws_bedrock_access_key_id     = var.aws_bedrock_access_key_id
    aws_bedrock_secret_access_key = var.aws_bedrock_secret_access_key
    aws_bedrock_region            = var.aws_bedrock_region
    webui_secret       = local.webui_secret
    sso_provider       = var.sso_provider
    sso_env            = local.sso_env
    sso_client_id      = var.sso_provider == "azure_ad" ? var.azure_ad_client_id : var.sso_provider == "okta" ? var.okta_client_id : ""
    sso_client_secret  = var.sso_provider == "azure_ad" ? var.azure_ad_client_secret : var.sso_provider == "okta" ? var.okta_client_secret : ""
    sso_tenant_id      = var.sso_provider == "azure_ad" ? var.azure_ad_tenant_id : ""
    sso_okta_domain    = var.sso_provider == "okta" ? var.okta_domain : ""
    admin_auth_mode    = var.sso_provider != "none" ? "oidc" : var.ad_domain_join ? "ldap" : "none"
    ad_domain          = var.vm_domain
    ad_admin_groups    = var.ad_admin_groups
    dc_dns_servers     = var.dc_dns_servers
    ldap_enable_services  = var.ldap_enable_services
    ldap_bind_dn          = var.ldap_bind_dn
    ldap_bind_password    = var.ldap_bind_password
    ldap_user_search_base = var.ldap_user_search_base != "" ? var.ldap_user_search_base : join(",", [for p in split(".", var.vm_domain) : "DC=${p}"])
    oidc_issuer_url    = var.sso_provider == "azure_ad" ? "https://login.microsoftonline.com/${var.azure_ad_tenant_id}/v2.0" : var.sso_provider == "okta" ? "https://${var.okta_domain}" : ""
    ollama_enable      = var.ollama_enable && !var.ollama_separate_vm
    ollama_models      = var.ollama_models
    ollama_gpu               = var.ollama_gpu
    docforge_enable          = var.docforge_enable
    ops_watchtower_enable    = var.ops_watchtower_enable
    ops_grafana_enable       = var.ops_grafana_enable
    ops_uptime_kuma_enable   = var.ops_uptime_kuma_enable
    ops_alert_webhook        = var.ops_alert_webhook
    server_name                     = local.vm_fqdn
    grafana_admin_password          = local.grafana_password
    postgres_password_plain         = local.postgres_password
    policy_engine_enable            = var.policy_engine_enable
    policy_engine_fail_mode         = var.policy_engine_fail_mode
    governance_hub_enable           = var.governance_hub_enable
    governance_hub_central_db_type  = var.governance_hub_central_db_type
    governance_hub_central_db_host  = var.governance_hub_central_db_host
    governance_hub_central_db_port  = var.governance_hub_central_db_port
    governance_hub_central_db_name  = var.governance_hub_central_db_name
    governance_hub_central_db_user  = var.governance_hub_central_db_user
    governance_hub_central_db_password = var.governance_hub_central_db_password
    platform_version               = trimspace(file("${path.module}/../VERSION"))
    governance_hub_instance_id      = var.vm_name
    governance_hub_instance_name    = var.governance_hub_instance_name != "" ? var.governance_hub_instance_name : var.vm_name
    governance_hub_sync_schedule    = var.governance_hub_sync_schedule
    governance_hub_supervisor_emails = var.governance_hub_supervisor_emails
    governance_hub_advisor_model    = var.governance_hub_advisor_model
    governance_hub_registration_token = var.governance_hub_registration_token
    governance_hub_secret           = local.governance_hub_secret
    governance_hub_industry         = var.industry
    governance_hub_tier             = var.governance_tier
    governance_hub_classification   = var.data_classification
    # --- DLP guardrail (LiteLLM-level) ---
    dlp_enabled                  = var.dlp_enable
    dlp_mode                     = var.dlp_mode
    dlp_block_ssn                = var.dlp_block_ssn
    dlp_block_credit_cards       = var.dlp_block_credit_cards
    dlp_block_phi                = var.dlp_block_phi
    dlp_block_credentials        = var.dlp_block_credentials
    dlp_block_bank_accounts      = var.dlp_block_bank_accounts
    dlp_block_standalone_dates   = var.dlp_block_standalone_dates
    dlp_scan_responses           = var.dlp_scan_responses
    dlp_custom_patterns          = jsonencode(var.dlp_custom_patterns)
    chat_enable                  = var.chat_enable
    chat_team_name               = var.chat_team_name
    chat_default_channel         = var.chat_default_channel
    chat_site_url                = "https://${local.vm_fqdn}/chat"
  })
}

# --- Nginx config ---
locals {
  nginx_conf = templatefile("${path.module}/../configs/nginx/nginx.conf.tpl", {
    server_name            = local.vm_fqdn
    vm_hostname            = var.vm_hostname
    docforge_enable        = var.docforge_enable
    docforge_max_body_size = var.docforge_max_file_size_mb
    ops_grafana_enable      = var.ops_grafana_enable
    ops_uptime_kuma_enable  = var.ops_uptime_kuma_enable
    governance_hub_enable   = var.governance_hub_enable
    admin_auth_mode        = var.sso_provider != "none" ? "oidc" : var.ad_domain_join ? "ldap" : "none"
    chat_enable             = var.chat_enable
    ldap_enable_services   = var.ldap_enable_services
  })
}

# --- Cloud-init user-data ---
locals {
  cloud_init_userdata = templatefile("${path.module}/../configs/cloud-init/user-data.yaml.tpl", {
    hostname           = var.vm_hostname
    fqdn               = local.vm_fqdn
    ssh_admin_user     = var.ssh_admin_user
    ssh_public_key     = local.ssh_public_key
    docker_compose_yml = local.docker_compose
    litellm_config     = local.litellm_config
    nginx_conf         = local.nginx_conf
    tls_cert           = local.tls_cert
    tls_key            = local.tls_key
    dlp_pipeline_py    = file("${path.module}/../configs/open-webui/dlp-pipeline.py")
    provision_owui_svc_sh = file("${path.module}/../scripts/provision-owui-service-account.sh")
    admin_html         = file("${path.module}/../html/admin.html")
    humility_callback_py    = file("${path.module}/../configs/litellm/callbacks/humility_prompt.py")
    humility_guardrail_py   = file("${path.module}/../configs/litellm/callbacks/humility_guardrail.py")
    dlp_guardrail_py        = file("${path.module}/../configs/litellm/callbacks/dlp_guardrail.py")
    setup_html         = file("${path.module}/../html/Setup.html")
    deployment_tfvars_b64 = base64encode(local.deployment_tfvars)
    xrdp_password      = local.xrdp_password
    docforge_enable          = var.docforge_enable
    docforge_zip_b64         = var.docforge_enable ? filebase64(data.archive_file.docforge[0].output_path) : ""
    docforge_tool_py         = var.docforge_enable ? file("${path.module}/../configs/open-webui/docforge-tool.py") : ""
    ops_grafana_enable       = var.ops_grafana_enable
    ops_uptime_kuma_enable   = var.ops_uptime_kuma_enable
    ops_trivy_enable         = var.ops_trivy_enable
    ops_backup_schedule      = var.ops_backup_schedule
    grafana_datasources_yml  = var.ops_grafana_enable ? templatefile("${path.module}/../configs/grafana/provisioning/datasources/datasources.yml", { postgres_password = local.postgres_password }) : ""
    grafana_dashboards_yml   = var.ops_grafana_enable ? file("${path.module}/../configs/grafana/provisioning/dashboards/dashboards.yml") : ""
    grafana_compliance_json  = var.ops_grafana_enable ? file("${path.module}/../configs/grafana/dashboards/compliance.json") : ""
    grafana_fleet_json       = var.ops_grafana_enable && var.governance_hub_enable ? file("${path.module}/../configs/grafana/dashboards/fleet.json") : ""
    loki_config              = var.ops_grafana_enable ? file("${path.module}/../configs/loki/loki-config.yml") : ""
    promtail_config          = var.ops_grafana_enable ? file("${path.module}/../configs/promtail/promtail-config.yml") : ""
    trivy_scan_sh            = var.ops_trivy_enable ? file("${path.module}/../configs/trivy/scan.sh") : ""
    governance_tier              = var.governance_tier
    data_classification          = var.data_classification
    ai_ethics_officer            = var.ai_ethics_officer
    ai_ethics_officer_email      = var.ai_ethics_officer_email
    governance_hub_enable        = var.governance_hub_enable
    governance_hub_zip_b64       = var.governance_hub_enable ? filebase64(data.archive_file.governance_hub[0].output_path) : ""
    governance_advisor_tool_py   = var.governance_hub_enable ? file("${path.module}/../configs/open-webui/governance-advisor-tool.py") : ""
    fleet_management_tool_py     = var.governance_hub_enable ? file("${path.module}/../configs/open-webui/fleet-management-tool.py") : ""
    system_designer_tool_py      = var.governance_hub_enable ? file("${path.module}/../configs/open-webui/system-designer-tool.py") : ""
    data_connector_tool_py       = var.governance_hub_enable ? file("${path.module}/../configs/open-webui/data-connector-tool.py") : ""
    policy_engine_enable         = var.policy_engine_enable
    policy_engine_fail_mode      = var.policy_engine_fail_mode
    opa_zip_b64                  = var.policy_engine_enable ? filebase64(data.archive_file.opa_policies[0].output_path) : ""
    opa_policy_pipeline_py       = var.policy_engine_enable ? file("${path.module}/../configs/open-webui/opa-policy-pipeline.py") : ""
    ollama_enable                = var.ollama_enable && !var.ollama_separate_vm
    ad_domain_join               = var.ad_domain_join
    ad_join_user                 = var.ad_join_user
    ad_join_password             = var.ad_join_password
    ad_join_ou                   = var.ad_join_ou
    ad_dns_register              = var.ad_dns_register
    vm_domain                    = var.vm_domain
    dc_dns_servers               = var.dc_dns_servers
    ad_domain                    = var.vm_domain
    ad_admin_groups              = var.ad_admin_groups
    ldap_enable_services         = var.ldap_enable_services
    ldap_bind_dn                 = var.ldap_bind_dn
    ldap_bind_password           = var.ldap_bind_password
    ldap_user_search_base        = var.ldap_user_search_base != "" ? var.ldap_user_search_base : join(",", [for p in split(".", var.vm_domain) : "DC=${p}"])
    post_deploy_sh               = templatefile("${path.module}/../templates/post-deploy.sh.tpl", {
      litellm_master_key  = local.litellm_master_key
      default_user_budget = var.litellm_default_user_budget
      vm_fqdn             = local.vm_fqdn
      instance_id         = var.vm_name
      ollama_enable       = var.ollama_enable && !var.ollama_separate_vm
      ollama_models       = var.ollama_models
      docforge_enable        = var.docforge_enable
      sso_group_mapping      = var.sso_group_mapping
      ops_grafana_enable     = var.ops_grafana_enable
      ops_uptime_kuma_enable = var.ops_uptime_kuma_enable
      keyword_categories       = var.keyword_categories
      governance_hub_enable    = var.governance_hub_enable
      policy_engine_enable     = var.policy_engine_enable
      chat_enable              = var.chat_enable
    })
  })

  cloud_init_metadata = templatefile("${path.module}/../configs/cloud-init/meta-data.yaml.tpl", {
    instance_id = var.vm_name
    hostname    = var.vm_hostname
  })

  cloud_init_network = var.vm_static_ip != "" ? templatefile("${path.module}/../configs/cloud-init/network-config.yaml.tpl", {
    ip_address  = var.vm_static_ip
    gateway     = var.vm_gateway
    dns_servers = var.vm_dns_servers
  }) : ""
}

# ---------------------------------------------------------------------------
# Create Hyper-V virtual switch
# ---------------------------------------------------------------------------

resource "null_resource" "ensure_vm_switch" {
  # Create the Hyper-V virtual switch only if it doesn't already exist.
  # This prevents error 0x8007054F when a switch with the same name
  # is already bound to the network adapter.

  provisioner "local-exec" {
    command     = <<-EOT
      $switchName = "${var.vm_switch_name}"
      $existing = Get-VMSwitch -Name $switchName -ErrorAction SilentlyContinue
      if ($existing) {
        Write-Host "Virtual switch '$switchName' already exists ($($existing.SwitchType)) — skipping creation"
      } else {
        Write-Host "Creating virtual switch '$switchName' (${var.vm_switch_type})..."
        if ("${var.vm_switch_type}" -eq "External") {
          New-VMSwitch -Name $switchName -NetAdapterName "${var.vm_switch_adapter}" -AllowManagementOS $true
        } elseif ("${var.vm_switch_type}" -eq "Internal") {
          New-VMSwitch -Name $switchName -SwitchType Internal
        } else {
          New-VMSwitch -Name $switchName -SwitchType Private
        }
        Write-Host "Virtual switch '$switchName' created"
      }
    EOT
    interpreter = ["PowerShell", "-NoProfile", "-Command"]
  }
}

# ---------------------------------------------------------------------------
# Create the VM boot disk (copy from golden image)
# ---------------------------------------------------------------------------

resource "null_resource" "prepare_vm_disk" {
  depends_on = [null_resource.ensure_vm_switch]

  provisioner "local-exec" {
    command     = <<-EOT
      # Ensure directories exist
      New-Item -ItemType Directory -Force -Path "${var.vm_vhd_path}"
      New-Item -ItemType Directory -Force -Path "${var.vm_path}"

      $destVhdx = Join-Path "${var.vm_vhd_path}" "${var.vm_name}-boot.vhdx"

      # Copy the golden image
      if (-not (Test-Path $destVhdx)) {
        Write-Host "Copying Ubuntu cloud image to $destVhdx ..."
        Copy-Item -Path "${var.ubuntu_vhdx_source}" -Destination $destVhdx -Force

        # Resize to target size
        Write-Host "Resizing disk to ${var.vm_disk_size_bytes / 1073741824} GB ..."
        Resize-VHD -Path $destVhdx -SizeBytes ${var.vm_disk_size_bytes}
      } else {
        Write-Host "Boot disk already exists at $destVhdx"
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
  }
}

# ---------------------------------------------------------------------------
# Write cloud-init files to disk (avoids command-line length limits)
# ---------------------------------------------------------------------------

resource "local_file" "cloud_init_userdata" {
  content  = local.cloud_init_userdata
  filename = "${var.vm_path}/${var.vm_name}-cloud-init/user-data"
}

resource "local_file" "cloud_init_metadata" {
  content  = local.cloud_init_metadata
  filename = "${var.vm_path}/${var.vm_name}-cloud-init/meta-data"
}

resource "local_file" "cloud_init_network" {
  count    = var.vm_static_ip != "" ? 1 : 0
  content  = local.cloud_init_network
  filename = "${var.vm_path}/${var.vm_name}-cloud-init/network-config"
}

# ---------------------------------------------------------------------------
# Build cloud-init ISO (required for Hyper-V cloud-init datasource)
# ---------------------------------------------------------------------------

resource "null_resource" "create_cloud_init_iso" {
  depends_on = [
    null_resource.prepare_vm_disk,
    local_file.cloud_init_userdata,
    local_file.cloud_init_metadata,
    local_file.cloud_init_network,
  ]

  provisioner "local-exec" {
    command     = <<-EOT
      $isoDir  = Join-Path "${var.vm_path}" "${var.vm_name}-cloud-init"
      $isoFile = Join-Path "${var.vm_path}" "${var.vm_name}-cloud-init.iso"

      # Build cloud-init ISO (tries: oscdimg > WSL genisoimage > PowerShell native)
      & "${path.module}\..\scripts\New-CloudInitIso.ps1" -SourceDir $isoDir -OutputIso $isoFile -VolumeLabel "cidata"
    EOT
    interpreter = ["PowerShell", "-Command"]
  }
}

# ---------------------------------------------------------------------------
# Create the Hyper-V VM
# ---------------------------------------------------------------------------

resource "hyperv_machine_instance" "insidellm" {
  depends_on = [
    null_resource.prepare_vm_disk,
    null_resource.create_cloud_init_iso,
    null_resource.ensure_vm_switch,
  ]

  name                 = var.vm_name
  path                 = var.vm_path
  generation           = 2
  processor_count      = var.vm_processor_count
  memory_startup_bytes = var.vm_memory_startup_bytes
  static_memory        = !var.vm_memory_dynamic
  state                = "Running"

  # Automatic actions
  automatic_start_action = "StartIfRunning"
  automatic_stop_action  = "ShutDown"
  automatic_start_delay  = 0

  checkpoint_type     = "Disabled"
  notes               = "Inside LLM - ${var.environment} - Managed by Terraform"

  vm_firmware {
    enable_secure_boot   = "On"
    secure_boot_template = "MicrosoftUEFICertificateAuthority"

    # Boot order: disk first, then DVD (cloud-init ISO)
    boot_order {
      boot_type           = "HardDiskDrive"
      controller_number   = 0
      controller_location = 0
    }
  }

  # Boot disk
  hard_disk_drives {
    controller_type     = "Scsi"
    controller_number   = 0
    controller_location = 0
    path                = "${var.vm_vhd_path}\\${var.vm_name}-boot.vhdx"
  }

  # Cloud-init ISO
  dvd_drives {
    controller_number   = 0
    controller_location = 1
    path                = "${var.vm_path}\\${var.vm_name}-cloud-init.iso"
  }

  # Network adapter
  network_adaptors {
    name        = "eth0"
    switch_name = var.vm_switch_name
  }

  integration_services = {
    "Guest Service Interface" = true
    "Heartbeat"               = true
    "Key-Value Pair Exchange"  = true
    "Shutdown"                = true
    "Time Synchronization"    = true
    "VSS"                     = true
  }
}

# ===========================================================================
# Ollama Separate VM (conditional)
# ===========================================================================

locals {
  ollama_vm_name = "${var.vm_name}-Ollama"
  ollama_vm_fqdn = "${var.vm_hostname}-ollama.${var.vm_domain}"

  ollama_cloud_init_userdata = var.ollama_separate_vm ? templatefile("${path.module}/../configs/cloud-init/ollama-user-data.yaml.tpl", {
    hostname       = "${var.vm_hostname}-ollama"
    fqdn           = local.ollama_vm_fqdn
    ssh_admin_user = var.ssh_admin_user
    ssh_public_key = local.ssh_public_key
    ollama_models  = var.ollama_models
    ollama_gpu     = var.ollama_gpu
  }) : ""

  ollama_cloud_init_metadata = var.ollama_separate_vm ? templatefile("${path.module}/../configs/cloud-init/meta-data.yaml.tpl", {
    instance_id = local.ollama_vm_name
    hostname    = "${var.vm_hostname}-ollama"
  }) : ""

  ollama_cloud_init_network = var.ollama_separate_vm && var.ollama_vm_static_ip != "" ? templatefile("${path.module}/../configs/cloud-init/network-config.yaml.tpl", {
    ip_address  = var.ollama_vm_static_ip
    gateway     = var.vm_gateway
    dns_servers = var.vm_dns_servers
  }) : ""
}

resource "null_resource" "prepare_ollama_vm_disk" {
  count      = var.ollama_separate_vm ? 1 : 0
  depends_on = [null_resource.ensure_vm_switch]

  provisioner "local-exec" {
    command     = <<-EOT
      New-Item -ItemType Directory -Force -Path "${var.vm_vhd_path}"
      $destVhdx = Join-Path "${var.vm_vhd_path}" "${local.ollama_vm_name}-boot.vhdx"
      if (-not (Test-Path $destVhdx)) {
        Copy-Item -Path "${var.ubuntu_vhdx_source}" -Destination $destVhdx
        Resize-VHD -Path $destVhdx -SizeBytes ${var.ollama_vm_disk_size_bytes}
        Write-Host "Ollama VM boot disk created: $destVhdx"
      } else {
        Write-Host "Ollama VM boot disk already exists: $destVhdx"
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
  }
}

resource "null_resource" "create_ollama_cloud_init_iso" {
  count      = var.ollama_separate_vm ? 1 : 0
  depends_on = [null_resource.prepare_ollama_vm_disk]

  provisioner "local-exec" {
    command     = <<-EOT
      $ciDir = "${var.vm_path}\${local.ollama_vm_name}-cloud-init"
      New-Item -ItemType Directory -Force -Path $ciDir

      Set-Content -Path "$ciDir\user-data" -Value @'
${local.ollama_cloud_init_userdata}
'@ -Encoding UTF8NoBOM

      Set-Content -Path "$ciDir\meta-data" -Value @'
${local.ollama_cloud_init_metadata}
'@ -Encoding UTF8NoBOM

      if ("${local.ollama_cloud_init_network}" -ne "") {
        Set-Content -Path "$ciDir\network-config" -Value @'
${local.ollama_cloud_init_network}
'@ -Encoding UTF8NoBOM
      }

      $isoPath = "${var.vm_path}\${local.ollama_vm_name}-cloud-init.iso"

      # Build cloud-init ISO (tries: oscdimg > WSL genisoimage > PowerShell native)
      & "${path.module}\..\scripts\New-CloudInitIso.ps1" -SourceDir $ciDir -OutputIso $isoPath -VolumeLabel "cidata"
    EOT
    interpreter = ["PowerShell", "-Command"]
  }
}

resource "hyperv_machine_instance" "ollama" {
  count = var.ollama_separate_vm ? 1 : 0
  depends_on = [
    null_resource.prepare_ollama_vm_disk,
    null_resource.create_ollama_cloud_init_iso,
    null_resource.ensure_vm_switch,
  ]

  name                 = local.ollama_vm_name
  path                 = var.vm_path
  generation           = 2
  processor_count      = var.ollama_vm_processor_count
  memory_startup_bytes = var.ollama_vm_memory_startup_bytes
  static_memory        = true
  state                = "Running"

  vm_firmware {
    enable_secure_boot = "On"
    secure_boot_template = "MicrosoftUEFICertificateAuthority"
  }

  hard_disk_drives {
    controller_type     = "Scsi"
    controller_number   = 0
    controller_location = 0
    path                = "${var.vm_vhd_path}\\${local.ollama_vm_name}-boot.vhdx"
  }

  dvd_drives {
    controller_number   = 0
    controller_location = 1
    path                = "${var.vm_path}\\${local.ollama_vm_name}-cloud-init.iso"
  }

  network_adaptors {
    name        = "eth0"
    switch_name = var.vm_switch_name
  }

  integration_services = {
    "Guest Service Interface" = true
    "Heartbeat"               = true
    "Key-Value Pair Exchange"  = true
    "Shutdown"                = true
    "Time Synchronization"    = true
    "VSS"                     = true
  }
}

# ---------------------------------------------------------------------------
# Configure NAT on host (for Internal switch only)
# ---------------------------------------------------------------------------

resource "null_resource" "configure_nat" {
  count      = var.vm_switch_type == "Internal" ? 1 : 0
  depends_on = [hyperv_machine_instance.insidellm]

  provisioner "local-exec" {
    command     = <<-EOT
      # Configure the Internal switch adapter with a gateway IP
      $adapter = Get-NetAdapter | Where-Object { $_.Name -like "*${var.vm_switch_name}*" }
      if ($adapter) {
        # Remove existing IP if any
        $adapter | Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue

        # Set the gateway IP on the host side
        New-NetIPAddress -InterfaceIndex $adapter.ifIndex `
          -IPAddress "${var.vm_gateway}" `
          -PrefixLength 24 `
          -ErrorAction SilentlyContinue

        # Create NAT network
        $natName = "claude-nat"
        $existing = Get-NetNat -Name $natName -ErrorAction SilentlyContinue
        if (-not $existing) {
          $subnet = "${split("/", var.vm_static_ip)[0]}".Split('.')[0..2] -join '.'
          New-NetNat -Name $natName -InternalIPInterfaceAddressPrefix "$subnet.0/24"
          Write-Host "NAT configured: $subnet.0/24 -> Internet"
        } else {
          Write-Host "NAT '$natName' already exists"
        }
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
  }
}

# ---------------------------------------------------------------------------
# Wait for VM to boot and cloud-init to complete
# ---------------------------------------------------------------------------

resource "null_resource" "wait_for_cloud_init" {
  depends_on = [
    hyperv_machine_instance.insidellm,
    null_resource.configure_nat,
  ]

  provisioner "local-exec" {
    command     = <<-EOT
      Write-Host "Waiting for VM to boot and cloud-init to complete..."
      Write-Host "This typically takes 5-8 minutes on first boot."
      Write-Host ""

      $maxWait = 600  # 10 minutes
      $elapsed = 0
      $interval = 15

      # Get VM IP
      while ($elapsed -lt $maxWait) {
        $vm = Get-VM -Name "${var.vm_name}" -ErrorAction SilentlyContinue
        if ($vm -and $vm.State -eq "Running") {
          $ip = ($vm | Get-VMNetworkAdapter).IPAddresses | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" } | Select-Object -First 1
          if ($ip) {
            Write-Host "`nVM IP detected: $ip"

            # Try SSH to check if cloud-init finished
            $result = ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes "${var.ssh_admin_user}@$ip" "test -f /var/lib/cloud/instance/boot-finished && echo READY" 2>$null
            if ($result -eq "READY") {
              Write-Host "Cloud-init completed successfully!"
              Write-Host ""
              Write-Host "=== DEPLOYMENT COMPLETE ==="
              Write-Host "Open WebUI:  https://$ip"
              Write-Host "LiteLLM UI:  https://$ip/litellm"
              Write-Host "SSH:         ssh ${var.ssh_admin_user}@$ip"
              Write-Host "RDP:         $ip`:3389 (user: ${var.ssh_admin_user})"
              break
            }
          }
        }

        $elapsed += $interval
        $pct = [math]::Round(($elapsed / $maxWait) * 100)
        Write-Host "  [$pct%] Waiting... ($elapsed/$maxWait seconds)"
        Start-Sleep -Seconds $interval
      }

      if ($elapsed -ge $maxWait) {
        Write-Host "WARNING: Timed out waiting for cloud-init. The VM may still be provisioning."
        Write-Host "SSH into the VM and check: sudo cloud-init status --wait"
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
  }
}

# ---------------------------------------------------------------------------
# Retrieve VM IP for outputs
# ---------------------------------------------------------------------------

data "external" "vm_ip" {
  depends_on = [null_resource.wait_for_cloud_init]

  program = ["powershell", "-Command", <<-EOT
    $vm = Get-VM -Name "${var.vm_name}" -ErrorAction SilentlyContinue
    $ip = ""
    if ($vm) {
      $ips = ($vm | Get-VMNetworkAdapter).IPAddresses | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" }
      if ($ips) { $ip = $ips[0] }
    }
    # Fall back to the static IP from terraform.tfvars if VM query returned nothing
    if (-not $ip -and "${var.vm_static_ip}" -ne "") {
      $ip = "${var.vm_static_ip}".Split("/")[0]
    }
    if (-not $ip) { $ip = "unknown" }
    @{ ip = $ip } | ConvertTo-Json
  EOT
  ]
}
