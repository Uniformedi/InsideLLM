###############################################################################
# outputs.tf — Deployment outputs
###############################################################################

output "vm_name" {
  description = "Hyper-V virtual machine name"
  value       = hyperv_machine_instance.claude_wrapper.name
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
  value       = "https://${data.external.vm_ip.result.ip}/litellm/ui"
}

output "ssh_command" {
  description = "SSH command to connect to the VM"
  value       = "ssh ${var.ssh_admin_user}@${data.external.vm_ip.result.ip}"
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
    ║  Open WebUI:   https://${data.external.vm_ip.result.ip}                      ║
    ║  LiteLLM:      https://${data.external.vm_ip.result.ip}/litellm/ui           ║
    ║  SSH:          ssh ${var.ssh_admin_user}@${data.external.vm_ip.result.ip}     ║
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
    ║  SSO Provider: ${var.sso_provider}                                         ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
  EOT
}
