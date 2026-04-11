#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Port-forward host ports to the InsideLLM VM so LAN clients can access all services.

.DESCRIPTION
    Creates netsh port proxy rules that forward traffic arriving on the Windows host
    to the InsideLLM Hyper-V VM (Internal switch + NAT at 192.168.100.10).

    Forwarded ports:
      443  -> HTTPS  (Open WebUI, LiteLLM UI, API - via Nginx)
       80  -> HTTP   (health check / HTTPS redirect - via Nginx)
     4000  -> LiteLLM direct API access (optional, for CLI tools)
       22  -> SSH    (admin access to VM)

    Also opens the corresponding Windows Firewall rules.

.PARAMETER VMAddress
    IP address of the InsideLLM VM. Default: 192.168.100.10

.PARAMETER Remove
    Remove all port-forward rules and firewall rules instead of creating them.

.EXAMPLE
    .\Port-Forward-InsideLLM.ps1                  # Create rules
    .\Port-Forward-InsideLLM.ps1 -Remove          # Remove rules
    .\Port-Forward-InsideLLM.ps1 -VMAddress 192.168.100.50   # Custom VM IP
#>

[CmdletBinding()]
param(
    [string]$VMAddress = "192.168.100.10",

    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Load defaults from terraform.tfvars if available
. "$PSScriptRoot\Read-TfVars.ps1"
$_tf = Read-TfVars
if ($_tf.Count -gt 0) {
    Write-Host "  [INFO] Loaded defaults from terraform.tfvars" -ForegroundColor DarkGray
    if (-not $PSBoundParameters.ContainsKey('VMAddress') -and $_tf["vm_static_ip"]) {
        $VMAddress = ($_tf["vm_static_ip"] -split '/')[0]
    }
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
$ports = @(
    @{ Port = 443;  Protocol = "TCP"; Description = "InsideLLM HTTPS (Nginx)" }
    @{ Port = 80;   Protocol = "TCP"; Description = "InsideLLM HTTP redirect" }
    @{ Port = 4000;  Protocol = "TCP"; Description = "InsideLLM LiteLLM API" }
    @{ Port = 5050;  Protocol = "TCP"; Description = "InsideLLM pgAdmin" }
    @{ Port = 11434; Protocol = "TCP"; Description = "InsideLLM Ollama API" }
    @{ Port = 22;    Protocol = "TCP"; Description = "InsideLLM SSH" }
)

$firewallGroupName = "InsideLLM Port Forwarding"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Status {
    param([string]$Message, [string]$Status = "INFO")
    $color = switch ($Status) {
        "OK"    { "Green" }
        "WARN"  { "Yellow" }
        "ERROR" { "Red" }
        default { "Cyan" }
    }
    Write-Host "[$Status] " -ForegroundColor $color -NoNewline
    Write-Host $Message
}

# ---------------------------------------------------------------------------
# Remove mode
# ---------------------------------------------------------------------------
if ($Remove) {
    Write-Status "Removing InsideLLM port-forwarding rules..." "INFO"

    foreach ($entry in $ports) {
        $p = $entry.Port

        # Remove netsh portproxy
        $existing = netsh interface portproxy show v4tov4 | Select-String "\s+$p\s+"
        if ($existing) {
            netsh interface portproxy delete v4tov4 listenport=$p listenaddress=0.0.0.0 | Out-Null
            Write-Status "Removed portproxy for port $p" "OK"
        }
        else {
            Write-Status "No portproxy found for port $p" "WARN"
        }

        # Remove firewall rules
        $fwRule = Get-NetFirewallRule -DisplayName "$($entry.Description)" -ErrorAction SilentlyContinue
        if ($fwRule) {
            Remove-NetFirewallRule -DisplayName "$($entry.Description)" -ErrorAction SilentlyContinue
            Write-Status "Removed firewall rule: $($entry.Description)" "OK"
        }
    }

    Write-Status "All InsideLLM port-forwarding rules removed." "OK"
    exit 0
}

# ---------------------------------------------------------------------------
# Create mode
# ---------------------------------------------------------------------------
Write-Status "Setting up port forwarding to InsideLLM VM at $VMAddress" "INFO"

# Verify VM is reachable
$ping = Test-Connection -ComputerName $VMAddress -Count 1 -Quiet -ErrorAction SilentlyContinue
if (-not $ping) {
    Write-Status "Cannot reach VM at $VMAddress - the VM may be off or the NAT is not configured." "WARN"
    Write-Status "Continuing anyway (rules will work once the VM is reachable)..." "WARN"
}
else {
    Write-Status "VM at $VMAddress is reachable" "OK"
}

# Create portproxy rules
foreach ($entry in $ports) {
    $p = $entry.Port

    # Remove any existing rule for this port first to make idempotent
    $null = netsh interface portproxy delete v4tov4 listenport=$p listenaddress=0.0.0.0 2>&1

    netsh interface portproxy add v4tov4 `
        listenport=$p `
        listenaddress=0.0.0.0 `
        connectport=$p `
        connectaddress=$VMAddress | Out-Null

    Write-Status "Port $p -> ${VMAddress}:$p  ($($entry.Description))" "OK"
}

# Create firewall rules
foreach ($entry in $ports) {
    $p = $entry.Port
    $name = $entry.Description

    # Remove existing rule to avoid duplicates
    Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue

    New-NetFirewallRule `
        -DisplayName $name `
        -Group $firewallGroupName `
        -Direction Inbound `
        -Protocol $entry.Protocol `
        -LocalPort $p `
        -Action Allow `
        -Profile @("Domain", "Private") `
        -Enabled True | Out-Null

    Write-Status "Firewall rule created: $name (port $p, Domain+Private profiles)" "OK"
}

# ---------------------------------------------------------------------------
# Enable IP routing (required for portproxy to forward across interfaces)
# ---------------------------------------------------------------------------
$ipForward = Get-NetIPInterface -AddressFamily IPv4 |
    Where-Object { $_.Forwarding -eq "Enabled" }

if (-not $ipForward) {
    # Enable forwarding on all IPv4 interfaces
    Get-NetIPInterface -AddressFamily IPv4 | Set-NetIPInterface -Forwarding Enabled
    Write-Status "IPv4 forwarding enabled on all interfaces" "OK"
}
else {
    Write-Status "IPv4 forwarding already enabled" "OK"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  InsideLLM Port Forwarding - Active" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Open WebUI:    https://<host-ip>"
Write-Host "  LiteLLM UI:    https://<host-ip>/litellm/ui/chat"
Write-Host "  LiteLLM API:   https://<host-ip>/v1/   (or http://<host-ip>:4000)"
Write-Host "  SSH:           ssh insidellm-admin@<host-ip>"
Write-Host ""
Write-Host "  VM address:    $VMAddress"
Write-Host ""

# Show current portproxy rules
Write-Status "Current portproxy rules:" "INFO"
netsh interface portproxy show v4tov4
