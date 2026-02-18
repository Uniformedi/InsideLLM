###############################################################################
# providers.tf — Terraform provider configuration for Hyper-V
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    hyperv = {
      source  = "taliesins/hyperv"
      version = "~> 1.2.1"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

# ---------------------------------------------------------------------------
# Hyper-V Provider
# Uses WinRM (PowerShell Remoting) to manage the local Hyper-V host.
# For local execution, use 127.0.0.1 with HTTP on port 5985.
# For remote Hyper-V hosts, use HTTPS on port 5986 with proper certs.
# ---------------------------------------------------------------------------
provider "hyperv" {
  user     = var.hyperv_user
  password = var.hyperv_password
  host     = var.hyperv_host
  port     = var.hyperv_port
  https    = var.hyperv_https
  insecure = var.hyperv_insecure
  use_ntlm = true
  timeout  = "120s"
}
