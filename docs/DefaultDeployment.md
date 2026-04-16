# InsideLLM &mdash; Default Deployment Reference

**Platform version:** 3.1.0 &nbsp;&middot;&nbsp; **Generated:** 2026-04-15

This document enumerates every Terraform input variable declared in
[`terraform/variables.tf`](../terraform/variables.tf) and the default value that
applies when the variable is omitted from `terraform.tfvars`. These are the
defaults that an out-of-the-box InsideLLM deployment will use.

The [Setup Wizard](../html/Setup.html) surfaces the most commonly tuned
variables and emits a `terraform.tfvars` file; operators are free to override
any variable below by adding it to that file.

Sensitive inputs (API keys, passwords, secrets) have no safe default &mdash; they
must be provided in `terraform.tfvars` and are shown here as **`""` &mdash; secret,
set in tfvars**.

---

## 1. Hyper-V Host & VM

| Variable | Default | Type | Description |
|---|---|---|---|
| `hyperv_user` | `".\\Administrator"` | string | Username for Hyper-V host WinRM connection |
| `hyperv_password` | `""` &mdash; secret, set in tfvars | string | Password for the Hyper-V host administrator account |
| `hyperv_host` | `"127.0.0.1"` | string | Hyper-V host address (127.0.0.1 for local) |
| `hyperv_port` | `5985` | number | WinRM port (5985 HTTP, 5986 HTTPS) |
| `hyperv_https` | `false` | bool | Use HTTPS for WinRM connection |
| `hyperv_insecure` | `true` | bool | Skip TLS verification for WinRM (local/dev only) |
| `vm_name` | `"InsideLLM"` | string | Name for the Hyper-V virtual machine |
| `vm_processor_count` | `8` | number | Number of virtual CPUs for the VM |
| `vm_memory_startup_bytes` | `34359738368` (32 GB) | number | VM startup memory in bytes |
| `vm_memory_dynamic` | `false` | bool | Enable dynamic memory for the VM |
| `vm_disk_size_bytes` | `85899345920` (80 GB) | number | VM boot disk size in bytes |
| `vm_path` | `"C:\\HyperV\\VMs"` | string | Base path on Hyper-V host for VM files |
| `vm_vhd_path` | `"C:\\HyperV\\VHDs"` | string | Path for virtual hard disks |
| `vm_switch_name` | `"InsideLLM"` | string | Name of the Hyper-V virtual switch |
| `vm_switch_type` | `"External"` | string | Type of virtual switch: Internal or External |
| `vm_switch_adapter` | `""` | string | Physical NIC name for External switch |
| `ubuntu_vhdx_source` | `"C:\\HyperV\\Images\\ubuntu-24.04-cloudimg-amd64.vhdx"` | string | Path to Ubuntu 24.04 cloud image VHDX |

## 2. Networking & Identity

| Variable | Default | Type | Description |
|---|---|---|---|
| `vm_static_ip` | `""` | string | Static IP (CIDR, e.g. 192.168.1.100/24). Empty = DHCP |
| `vm_gateway` | `""` | string | Default gateway for static IP config |
| `vm_dns_servers` | `["8.8.8.8", "8.8.4.4"]` | list(string) | DNS servers for the VM |
| `vm_hostname` | `"InsideLLM"` | string | Hostname for the Ubuntu VM |
| `vm_domain` | `"local"` | string | Domain name (FQDN and TLS cert) |
| `ad_domain_join` | `false` | bool | Join the Ubuntu VM to the AD domain |
| `ad_join_user` | `""` | string | AD username with domain-join permission |
| `ad_join_password` | `""` &mdash; secret, set in tfvars | string | Password for the AD join account |
| `ad_join_ou` | `""` | string | OU for the computer account (empty = default) |
| `ad_dns_register` | `true` | bool | Register VM hostname in AD DNS via dynamic update |
| `dc_dns_servers` | `[]` | list(string) | DC IP(s) to use as the VM's DNS resolver |
| `ldap_enable_services` | `false` | bool | Enable LDAP auth in Grafana, Open WebUI, pgAdmin |
| `ldap_bind_dn` | `""` | string | DN of the read-only LDAP service account |
| `ldap_bind_password` | `""` &mdash; secret, set in tfvars | string | Password for the LDAP bind service account |
| `ldap_user_search_base` | `""` | string | Base DN for user lookups (empty = domain DC= chain) |
| `cockpit_enable` | `true` | bool | Install Cockpit and expose at /cockpit/ |
| `ssh_public_key_path` | `"~/.ssh/id_rsa.pub"` | string | SSH public key file on the Windows host |
| `ssh_admin_user` | `"insidellm-admin"` | string | Admin username for the Ubuntu VM |

### Fleet / Edge

Role-aware fleet modularity (see [FleetArchitecture.md](FleetArchitecture.md)).
Leave all of these empty for a standalone single-VM deployment — that is the
historical default and nothing in the platform changes.

| Variable | Default | Type | Description |
|---|---|---|---|
| `vm_role` | `""` | string | Role of this VM in the fleet: primary / gateway / workstation / voice / edge / storage, or empty for standalone |
| `fleet_primary_host` | `""` | string | Hostname/IP of the fleet primary (Gov-Hub, Grafana, Loki) |
| `fleet_virtual_ip` | `""` | string | VIP owned by keepalived on the active edge VM |
| `edge_tls_source` | `"self-signed"` | string | self-signed / letsencrypt / custom |
| `edge_tls_cert_path` | `""` | string | Edge cert path when tls_source=custom |
| `edge_tls_key_path` | `""` | string | Edge key path when tls_source=custom |
| `edge_domain` | `""` | string | FQDN served by the edge (TLS CN, OIDC redirect URI) |
| `department` | `""` | string | Department label routed to by the edge based on OIDC claim |
| `fallback_department` | `""` | string | Sibling backend for edge failover; empty = fail fast |
| `pkg_mirror_enable` | `false` | bool | Force-enable apt-cacher-ng + Docker registry mirror on this VM (auto-ON for vm_role=primary). See [docs/LocalPackageCache.md](LocalPackageCache.md). |
| `apt_mirror_host` | `""` | string | Hostname/IP of the apt-cacher-ng proxy (typically = fleet_primary_host). Empty = direct to upstream |
| `docker_mirror_host` | `""` | string | Hostname/IP of the Docker registry pull-through mirror. Empty = direct to Docker Hub |
| `claude_code_enable` | `true` | bool | Install Claude Code CLI for the admin user on this VM. Auto-skipped for vm_role=edge/voice/storage. See [docs/ClaudeCode-On-VMs.md](ClaudeCode-On-VMs.md). |

## 3. Gov-Hub RBAC

| Variable | Default | Type | Description |
|---|---|---|---|
| `ad_admin_groups` | `"InsideLLM-Admin"` | string | Comma-separated AD groups mapped to admin role |
| `ad_view_groups` | `"InsideLLM-View"` | string | Comma-separated AD groups mapped to view role |
| `ad_approver_groups` | `"InsideLLM-Approve"` | string | Comma-separated AD groups mapped to approver role |
| `oidc_view_group_ids` | `[]` | list(string) | OIDC group object IDs (GUIDs) mapped to view |
| `oidc_admin_group_ids` | `[]` | list(string) | OIDC group object IDs mapped to admin |
| `oidc_approver_group_ids` | `[]` | list(string) | OIDC group object IDs mapped to approver |

## 4. SSO

| Variable | Default | Type | Description |
|---|---|---|---|
| `sso_provider` | `"none"` | string | SSO provider: azure_ad, okta, generic, none |
| `azure_ad_client_id` | `""` | string | Azure AD (Entra ID) application client ID |
| `azure_ad_client_secret` | `""` &mdash; secret, set in tfvars | string | Azure AD application client secret |
| `azure_ad_tenant_id` | `""` | string | Azure AD tenant ID |
| `okta_client_id` | `""` | string | Okta application client ID |
| `okta_client_secret` | `""` &mdash; secret, set in tfvars | string | Okta application client secret |
| `okta_domain` | `""` | string | Okta domain (e.g. your-org.okta.com) |
| `sso_group_field` | `"groups"` | string | JWT claim field containing group membership |
| `sso_group_mapping` | `{}` | map(object) | Map SSO group names to LiteLLM teams/budgets/models |

## 5. LLM Providers

| Variable | Default | Type | Description |
|---|---|---|---|
| `anthropic_api_key` | `""` &mdash; secret, set in tfvars | string | Anthropic API key (required) |
| `openai_api_key` | `""` &mdash; secret, set in tfvars | string | OpenAI API key. Empty = disabled |
| `gemini_api_key` | `""` &mdash; secret, set in tfvars | string | Google Gemini API key. Empty = disabled |
| `mistral_api_key` | `""` &mdash; secret, set in tfvars | string | Mistral API key. Empty = disabled |
| `cohere_api_key` | `""` &mdash; secret, set in tfvars | string | Cohere API key. Empty = disabled |
| `azure_openai_api_key` | `""` &mdash; secret, set in tfvars | string | Azure OpenAI API key. Empty = disabled |
| `azure_openai_endpoint` | `""` | string | Azure OpenAI endpoint URL |
| `azure_openai_api_version` | `"2024-08-01-preview"` | string | Azure OpenAI API version |
| `azure_openai_deployment` | `""` | string | Azure OpenAI deployment name |
| `aws_bedrock_access_key_id` | `""` &mdash; secret, set in tfvars | string | AWS access key ID for Bedrock |
| `aws_bedrock_secret_access_key` | `""` &mdash; secret, set in tfvars | string | AWS secret access key for Bedrock |
| `aws_bedrock_region` | `"us-east-1"` | string | AWS region for Bedrock |
| `aws_bedrock_model` | `"anthropic.claude-3-5-sonnet-20241022-v2:0"` | string | Bedrock model ID |
| `litellm_master_key` | `""` &mdash; secret, set in tfvars | string | LiteLLM proxy master API key (auto-generated if empty) |
| `litellm_salt_key` | `""` &mdash; secret, set in tfvars | string | LITELLM_SALT_KEY for encrypting virtual keys |
| `litellm_default_model` | `"claude-sonnet"` | string | Default model alias for LiteLLM routing |
| `litellm_enable_haiku` | `true` | bool | Enable Claude Haiku tier in model routing |
| `litellm_enable_opus` | `true` | bool | Enable Claude Opus tier in model routing |
| `litellm_global_max_budget` | `100` | number | Global monthly budget cap in USD (0 = unlimited) |
| `litellm_default_user_budget` | `5.0` | number | Default per-user daily budget in USD |
| `litellm_default_user_rpm` | `30` | number | Default requests per minute per user |
| `litellm_default_user_tpm` | `100000` | number | Default tokens per minute per user |
| `ollama_enable` | `true` | bool | Enable local Ollama instance |
| `ollama_models` | `["qwen2.5-coder:14b", "qwen2.5:14b"]` | list(string) | Ollama model tags to pull on startup |
| `ollama_gpu` | `false` | bool | Enable NVIDIA GPU passthrough for Ollama |
| `ollama_separate_vm` | `false` | bool | Deploy Ollama in its own Hyper-V VM |
| `ollama_vm_processor_count` | `8` | number | vCPUs for the Ollama VM |
| `ollama_vm_memory_startup_bytes` | `34359738368` (32 GB) | number | Startup RAM for the Ollama VM |
| `ollama_vm_disk_size_bytes` | `107374182400` (100 GB) | number | Disk size for the Ollama VM |
| `ollama_vm_static_ip` | `""` | string | Static IP for the Ollama VM (CIDR) |

## 6. Humility / OPA Policy

| Variable | Default | Type | Description |
|---|---|---|---|
| `policy_engine_enable` | `false` | bool | Enable OPA policy engine (Humility + industry) |
| `policy_engine_industry_policies` | `[]` | list(string) | Industry policies to load: hipaa, fdcpa, sox, pci_dss, ferpa, glba |
| `policy_engine_fail_mode` | `"closed"` | string | Fail mode: closed (block) or log_only |
| `industry` | `"general"` | string | Industry vertical for keyword templates and defaults |
| `governance_tier` | `"tier3"` | string | Governance tier: tier1, tier2, or tier3 |
| `data_classification` | `"internal"` | string | Max data classification: public, internal, confidential, restricted |

## 7. DLP

| Variable | Default | Type | Description |
|---|---|---|---|
| `dlp_enable` | `true` | bool | Enable the DLP pipeline |
| `dlp_mode` | `"block"` | string | DLP action: block or redact |
| `dlp_block_ssn` | `true` | bool | Block Social Security Numbers |
| `dlp_block_credit_cards` | `true` | bool | Block credit card numbers |
| `dlp_block_phi` | `true` | bool | Block Protected Health Information patterns |
| `dlp_block_credentials` | `true` | bool | Block API keys, passwords, connection strings |
| `dlp_block_bank_accounts` | `true` | bool | Block bank account / routing numbers |
| `dlp_block_standalone_dates` | `true` | bool | Block standalone dates (possible DOBs) |
| `dlp_scan_responses` | `true` | bool | Also scan model responses and redact echoed data |
| `dlp_custom_patterns` | `{}` | map(string) | Additional regex patterns (name => regex) |

## 8. Optional Services

| Variable | Default | Type | Description |
|---|---|---|---|
| `docforge_enable` | `true` | bool | Enable DocForge file generation/conversion service |
| `docforge_max_file_size_mb` | `50` | number | Max file upload size for DocForge (MB) |
| `governance_hub_enable` | `false` | bool | Enable Governance Hub (central sync + advisor) |
| `governance_hub_central_db_type` | `"postgresql"` | string | Central DB type: postgresql, mariadb, mssql |
| `governance_hub_central_db_host` | `""` | string | Central DB hostname |
| `governance_hub_central_db_port` | `5432` | number | Central DB port |
| `governance_hub_central_db_name` | `"insidellm_central"` | string | Central DB name |
| `governance_hub_central_db_user` | `""` | string | Central DB username |
| `governance_hub_central_db_password` | `""` &mdash; secret, set in tfvars | string | Central DB password |
| `governance_hub_instance_name` | `""` | string | Human-readable name for this instance |
| `governance_hub_sync_schedule` | `"0 */6 * * *"` | string | Cron schedule for central sync |
| `governance_hub_supervisor_emails` | `""` | string | Comma-separated supervisor emails |
| `governance_hub_advisor_model` | `"claude-sonnet"` | string | LLM model used by AI governance advisor |
| `governance_hub_registration_token` | `""` &mdash; secret, set in tfvars | string | Fleet registration token |
| `ops_watchtower_enable` | `true` | bool | Enable Watchtower for container image updates |
| `ops_trivy_enable` | `true` | bool | Enable Trivy daily CVE scans |
| `ops_grafana_enable` | `true` | bool | Enable Grafana + Loki |
| `ops_uptime_kuma_enable` | `true` | bool | Enable Uptime Kuma |
| `guacamole_enable` | `false` | bool | Enable Apache Guacamole &mdash; browser-based RDP/VNC/SSH gateway at /remote/ |
| `chat_enable` | `false` | bool | Deploy Mattermost chat under /chat/ |
| `chat_team_name` | `"insidellm"` | string | Mattermost default team URL slug |
| `chat_default_channel` | `"general"` | string | Default Mattermost channel |

## 9. Monitoring & Alerts

| Variable | Default | Type | Description |
|---|---|---|---|
| `ops_backup_schedule` | `"daily"` | string | PostgreSQL backup frequency: daily, weekly, none |
| `ops_alert_webhook` | `""` | string | Webhook URL for operational alerts (Slack/Teams) |
| `ai_ethics_officer` | `""` | string | Name of the AI Ethics Officer |
| `ai_ethics_officer_email` | `""` | string | Email of the AI Ethics Officer |
| `log_retention_days` | `365` | number | Days to retain API logs and audit trails |

## 10. Misc / Advanced

| Variable | Default | Type | Description |
|---|---|---|---|
| `postgres_password` | `""` &mdash; secret, set in tfvars | string | PostgreSQL password (auto-generated if empty) |
| `keyword_categories` | `{}` | map(list(string)) | Additional keyword categories for request analysis |
| `keyword_refresh_schedule` | `"*/15 * * * *"` | string | Cron schedule for keyword materialized-view refresh |
| `tls_cert_path` | `""` | string | Path to TLS cert (empty = self-signed) |
| `tls_key_path` | `""` | string | Path to TLS private key (empty = self-signed) |
| `environment` | `"production"` | string | Deployment environment tag |
| `owner` | `"Your Company Name"` | string | Owner of this deployment |
