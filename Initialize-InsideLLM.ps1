#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Provision the InsideLLM WSL2 environment (WSL2, Docker, SCFW, TLS).

.DESCRIPTION
    This script performs the foundational setup required before deploying
    the InsideLLM application stack:
      1. Install/verify WSL2 and import the Ubuntu 24.04 distro
      2. Install/verify Docker Engine inside WSL2
      3. Install Supply Chain Firewall (SCFW) as a pip wrapper
      4. Generate or deploy TLS certificates

    Run this once on a fresh machine. Afterwards, run Install-InsideLLM-WSL.ps1
    to deploy the full application stack.

.PARAMETER Hostname
    VM/distro hostname (default: InsideLLM).

.PARAMETER Domain
    Domain suffix (default: local).

.PARAMETER Owner
    Organization name used in the TLS certificate subject.

.PARAMETER TlsCertPath
    Path to a user-provided TLS certificate. If omitted, a self-signed cert is generated.

.PARAMETER TlsKeyPath
    Path to the private key matching TlsCertPath.

.PARAMETER WslDistroName
    Name of the WSL2 distro to create/use (default: InsideLLM).

.PARAMETER WslInstallPath
    Windows path where the WSL2 distro disk is stored.

.EXAMPLE
    .\Initialize-InsideLLM.ps1
.EXAMPLE
    .\Initialize-InsideLLM.ps1 -Hostname "MyLLM" -Domain "corp.local" -Owner "Acme Inc"
.EXAMPLE
    .\Initialize-InsideLLM.ps1 -TlsCertPath ".\cert.pem" -TlsKeyPath ".\key.pem"
#>

[CmdletBinding()]
param(
    [string]$Hostname = "InsideLLM",
    [string]$Domain   = "local",
    [string]$Owner    = "Your Company Name",

    [string]$TlsCertPath = "",
    [string]$TlsKeyPath  = "",

    [string]$WslDistroName  = "InsideLLM",
    [string]$WslInstallPath = "C:\WSL\InsideLLM"
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

function Invoke-Wsl {
    param([string]$Command)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = wsl -d $WslDistroName -- bash -c $Command 2>&1
    $ErrorActionPreference = $prev
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
# Step 1: Install WSL2
# =============================================================================

Write-Step "Checking WSL2"

$wslStatus = wsl --status 2>&1 | Out-String
if ($wslStatus -match "not installed" -or $wslStatus -match "not recognized" -or -not (Get-Command wsl -ErrorAction SilentlyContinue)) {
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
    Write-Warn "Creating '$WslDistroName' WSL2 distro (this may take a few minutes)..."

    # Download Ubuntu 24.04 rootfs (cloud image root tarball, works with wsl --import)
    $rootfsUrl = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64-root.tar.xz"
    $rootfsPath = Join-Path $env:TEMP "ubuntu-noble-wsl-rootfs.tar.xz"

    if (-not (Test-Path $rootfsPath)) {
        Write-Host "  Downloading Ubuntu 24.04 rootfs..."
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $rootfsUrl -OutFile $rootfsPath -UseBasicParsing
        $ProgressPreference = 'Continue'
        Write-Ok "Ubuntu 24.04 rootfs downloaded"
    } else {
        Write-Ok "Ubuntu 24.04 rootfs already cached"
    }

    # Create install directory
    $null = New-Item -Path $WslInstallPath -ItemType Directory -Force

    # Import as custom-named distro (defaults to root user, no interactive prompt)
    Write-Host "  Importing as '$WslDistroName'..."
    wsl --import $WslDistroName $WslInstallPath $rootfsPath --version 2
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Failed to import WSL2 distro. Check disk space and WSL2 status."
        exit 1
    }
    Write-Ok "Distro '$WslDistroName' created at $WslInstallPath"

    # Clean up downloaded rootfs
    Remove-Item $rootfsPath -Force -ErrorAction SilentlyContinue
}
Write-Ok "'$WslDistroName' is installed"

# Ensure systemd is enabled
$wslConf = Invoke-Wsl "cat /etc/wsl.conf 2>/dev/null || true"
if (-not ($wslConf -match "systemd\s*=\s*true")) {
    Write-Warn "Enabling systemd in WSL2..."
    Invoke-Wsl "printf '[boot]\nsystemd=true\n' > /etc/wsl.conf"
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
export DEBIAN_FRONTEND=noninteractive
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg 2>/dev/null
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu noble stable' | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
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
# Step 3: Install Supply Chain Firewall (SCFW) as pip wrapper
# =============================================================================

Write-Step "Setting up Supply Chain Firewall (SCFW)"

$scfwCheck = Invoke-Wsl "command -v scfw >/dev/null 2>&1 && echo SCFW_OK || echo SCFW_MISSING"
if (-not ($scfwCheck -match "SCFW_OK")) {
    Write-Warn "Installing SCFW..."
    Invoke-Wsl @"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq pipx python3-pip
pipx ensurepath
export PATH="`$HOME/.local/bin:`$PATH"
pipx install scfw
scfw configure --alias-pip
"@ | Out-Null
    Write-Ok "SCFW installed and configured as pip wrapper"
} else {
    Write-Ok "SCFW is already installed"
}

# =============================================================================
# Step 4: Generate TLS certificates
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
# Done
# =============================================================================

Write-Host ""
Write-Host "=== Initialization Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "  WSL2 distro:  $WslDistroName" -ForegroundColor White
Write-Host "  Docker:       installed and running" -ForegroundColor White
Write-Host "  SCFW:         pip wrapped via Supply Chain Firewall" -ForegroundColor White
Write-Host "  TLS:          certificates at $InstallPath/nginx/ssl/" -ForegroundColor White
Write-Host ""
Write-Host "  Next: run Install-InsideLLM-WSL.ps1 to deploy the application stack." -ForegroundColor Cyan
Write-Host ""
