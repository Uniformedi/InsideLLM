###############################################################################
# outputs.tf — Deployment outputs
###############################################################################

output "vm_name" {
  description = "Hyper-V virtual machine name"
  value       = hyperv_machine_instance.insidellm.name
}

output "vm_ip_address" {
  description = "IP address of the deployed VM"
  value       = data.external.vm_ip.result.ip
}

output "open_webui_url" {
  description = "URL for the Open WebUI chat interface"
  value       = "https://${data.external.vm_ip.result.ip}"
}

output "litellm_admin_url" {
  description = "URL for the LiteLLM admin dashboard"
  value       = "https://${data.external.vm_ip.result.ip}/litellm/ui/chat"
}

output "admin_portal_url" {
  description = "URL for the InsideLLM admin portal"
  value       = "https://${data.external.vm_ip.result.ip}/admin"
}

output "netdata_url" {
  description = "URL for the Netdata monitoring dashboard"
  value       = "https://${data.external.vm_ip.result.ip}/netdata/"
}

output "ssh_command" {
  description = "SSH command to connect to the VM"
  value       = "ssh ${var.ssh_admin_user}@${data.external.vm_ip.result.ip}"
}

output "rdp_connection" {
  description = "Remote Desktop connection info"
  value       = "${data.external.vm_ip.result.ip}:3389 (user: ${var.ssh_admin_user})"
}

output "xrdp_password" {
  description = "Password for RDP login"
  value       = local.xrdp_password
  sensitive   = true
}

output "litellm_master_key" {
  description = "LiteLLM master API key (use for admin operations)"
  value       = local.litellm_master_key
  sensitive   = true
}

output "postgres_password" {
  description = "PostgreSQL database password"
  value       = local.postgres_password
  sensitive   = true
}

output "ollama_vm_ip" {
  description = "IP address of the Ollama VM (when deployed separately)"
  value       = var.ollama_separate_vm ? split("/", var.ollama_vm_static_ip)[0] : "N/A (running in main stack)"
}

output "grafana_url" {
  description = "URL for the Grafana compliance dashboard"
  value       = var.ops_grafana_enable ? "https://${data.external.vm_ip.result.ip}/grafana/" : "N/A (Grafana disabled)"
}

output "grafana_password" {
  description = "Grafana admin password"
  value       = local.grafana_password
  sensitive   = true
}

output "uptime_kuma_url" {
  description = "URL for the Uptime Kuma status page"
  value       = var.ops_uptime_kuma_enable ? "https://${data.external.vm_ip.result.ip}/status/" : "N/A (Uptime Kuma disabled)"
}

output "docforge_url" {
  description = "URL for the DocForge file conversion API"
  value       = var.docforge_enable ? "https://${data.external.vm_ip.result.ip}/docforge/api/formats" : "N/A (DocForge disabled)"
}

output "webui_secret_key" {
  description = "Open WebUI secret key"
  value       = local.webui_secret
  sensitive   = true
}

output "deployment_notes" {
  description = "Post-deployment instructions"
  value       = <<-EOT

    ╔══════════════════════════════════════════════════════════════╗
    ║           Inside LLM — Deployed                   ║
    ╠══════════════════════════════════════════════════════════════╣
    ║                                                              ║
    ║  Admin Portal: https://${data.external.vm_ip.result.ip}/admin                 ║
    ║  Open WebUI:   https://${data.external.vm_ip.result.ip}                      ║
    ║  LiteLLM:      https://${data.external.vm_ip.result.ip}/litellm/ui           ║
    ║  Netdata:      https://${data.external.vm_ip.result.ip}/netdata/             ║
    ║  pgAdmin:      http://${data.external.vm_ip.result.ip}:5050                  ║
    ║  SSH:          ssh ${var.ssh_admin_user}@${data.external.vm_ip.result.ip}     ║
    ║  RDP:          ${data.external.vm_ip.result.ip}:3389                         ║
    ║                (terraform output -raw xrdp_password)         ║
    ║                                                              ║
    ║  First Login:                                                ║
    ║  1. Navigate to Open WebUI URL                               ║
    ║  2. The first user to register becomes admin                 ║
    ║  3. Configure additional users via admin panel               ║
    ║                                                              ║
    ║  LiteLLM Admin:                                              ║
    ║  Use: terraform output -raw litellm_master_key               ║
    ║  to retrieve the admin API key                               ║
    ║                                                              ║
    ║  DLP Pipeline: ${var.dlp_enable ? "ENABLED" : "DISABLED"}                                     ║
    ║  DocForge:     ${var.docforge_enable ? "ENABLED" : "DISABLED"}                                     ║
    ║  Governance:   ${var.governance_tier} / ${var.data_classification}                        ║
%{ if var.ops_grafana_enable ~}
    ║  Grafana:      https://${data.external.vm_ip.result.ip}/grafana/             ║
%{ endif ~}
%{ if var.ops_uptime_kuma_enable ~}
    ║  Uptime Kuma:  https://${data.external.vm_ip.result.ip}/status/              ║
%{ endif ~}
    ║  SSO Provider: ${var.sso_provider}                                         ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
  EOT
}
