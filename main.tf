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

locals {
  litellm_master_key = var.litellm_master_key != "" ? var.litellm_master_key : "sk-${random_password.litellm_master_key[0].result}"
  postgres_password  = var.postgres_password != "" ? var.postgres_password : random_password.postgres_password[0].result
  webui_secret       = random_password.webui_secret.result

  vm_fqdn = "${var.vm_hostname}.${var.vm_domain}"

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
# Render configuration templates
# ---------------------------------------------------------------------------

# --- LiteLLM config ---
locals {
  litellm_config = templatefile("${path.module}/configs/litellm/config.yaml.tpl", {
    anthropic_api_key       = var.anthropic_api_key
    enable_haiku            = var.litellm_enable_haiku
    enable_opus             = var.litellm_enable_opus
    default_user_budget     = var.litellm_default_user_budget
    default_user_rpm        = var.litellm_default_user_rpm
    default_user_tpm        = var.litellm_default_user_tpm
    global_max_budget       = var.litellm_global_max_budget
  })
}

# --- Docker Compose ---
locals {
  docker_compose = templatefile("${path.module}/scripts/docker-compose.yml.tpl", {
    postgres_password  = local.postgres_password
    litellm_master_key = local.litellm_master_key
    anthropic_api_key  = var.anthropic_api_key
    webui_secret       = local.webui_secret
    sso_provider       = var.sso_provider
    sso_env            = local.sso_env
  })
}

# --- Nginx config ---
locals {
  nginx_conf = templatefile("${path.module}/configs/nginx/nginx.conf.tpl", {
    server_name = local.vm_fqdn
    vm_hostname = var.vm_hostname
  })
}

# --- Cloud-init user-data ---
locals {
  cloud_init_userdata = templatefile("${path.module}/configs/cloud-init/user-data.yaml.tpl", {
    hostname           = var.vm_hostname
    fqdn               = local.vm_fqdn
    ssh_admin_user     = var.ssh_admin_user
    ssh_public_key     = local.ssh_public_key
    docker_compose_yml = local.docker_compose
    litellm_config     = local.litellm_config
    nginx_conf         = local.nginx_conf
    tls_cert           = local.tls_cert
    tls_key            = local.tls_key
    dlp_pipeline_py    = file("${path.module}/configs/open-webui/dlp-pipeline.py")
    post_deploy_sh     = templatefile("${path.module}/scripts/post-deploy.sh.tpl", {
      litellm_master_key  = local.litellm_master_key
      default_user_budget = var.litellm_default_user_budget
      vm_fqdn             = local.vm_fqdn
    })
  })

  cloud_init_metadata = templatefile("${path.module}/configs/cloud-init/meta-data.yaml.tpl", {
    instance_id = var.vm_name
    hostname    = var.vm_hostname
  })

  cloud_init_network = var.vm_static_ip != "" ? templatefile("${path.module}/configs/cloud-init/network-config.yaml.tpl", {
    ip_address  = var.vm_static_ip
    gateway     = var.vm_gateway
    dns_servers = var.vm_dns_servers
  }) : ""
}

# ---------------------------------------------------------------------------
# Create Hyper-V virtual switch
# ---------------------------------------------------------------------------

resource "hyperv_network_switch" "claude_switch" {
  name        = var.vm_switch_name
  switch_type = var.vm_switch_type

  # Only set net_adapter_names for External switches
  net_adapter_names = var.vm_switch_type == "External" ? [var.vm_switch_adapter] : []
}

# ---------------------------------------------------------------------------
# Create the VM boot disk (copy from golden image)
# ---------------------------------------------------------------------------

resource "null_resource" "prepare_vm_disk" {
  depends_on = [hyperv_network_switch.claude_switch]

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

      # Build ISO using oscdimg (Windows ADK) or genisoimage via WSL
      $oscdimg = Get-Command oscdimg.exe -ErrorAction SilentlyContinue
      if ($oscdimg) {
        & oscdimg.exe -j2 -lcidata $isoDir $isoFile
      } else {
        # Convert Windows paths to WSL paths
        $winIsoDir  = $isoDir.Replace('\', '/')
        $winIsoFile = $isoFile.Replace('\', '/')
        $wslIsoDir  = (wsl wslpath -a $winIsoDir).Trim()
        $wslIsoFile = (wsl wslpath -a $winIsoFile).Trim()
        Write-Host "WSL ISO dir: $wslIsoDir"
        Write-Host "WSL ISO file: $wslIsoFile"
        wsl bash -c "genisoimage -output '$wslIsoFile' -volid cidata -joliet -rock '$wslIsoDir'"
        if (-not (Test-Path $isoFile)) {
          throw "Failed to create cloud-init ISO at $isoFile"
        }
      }

      Write-Host "Cloud-init ISO created at $isoFile"
    EOT
    interpreter = ["PowerShell", "-Command"]
  }
}

# ---------------------------------------------------------------------------
# Create the Hyper-V VM
# ---------------------------------------------------------------------------

resource "hyperv_machine_instance" "claude_wrapper" {
  depends_on = [
    null_resource.prepare_vm_disk,
    null_resource.create_cloud_init_iso,
    hyperv_network_switch.claude_switch,
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
  notes               = "Claude Wrapper Stack - ${var.environment} - Managed by Terraform"

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
    switch_name = hyperv_network_switch.claude_switch.name
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
  depends_on = [hyperv_machine_instance.claude_wrapper]

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
    hyperv_machine_instance.claude_wrapper,
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
    $ip = "unknown"
    if ($vm) {
      $ips = ($vm | Get-VMNetworkAdapter).IPAddresses | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" }
      if ($ips) { $ip = $ips[0] }
    }
    @{ ip = $ip } | ConvertTo-Json
  EOT
  ]
}
