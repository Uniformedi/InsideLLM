#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Sets up and installs InsideLLM via Hyper-V Terraform deployment.

.DESCRIPTION
    This script prepares the host, verifies prerequisites, and runs Terraform:
    1. Enables Hyper-V if not already enabled
    2. Configures WinRM for Terraform's Hyper-V provider
    3. Downloads the Ubuntu 24.04 cloud image (skips if recent VHDX exists)
    4. Converts it to VHDX format for Hyper-V Gen2 VMs
    5. Installs genisoimage in WSL for cloud-init ISO creation
    6. Verifies all prerequisites (Terraform, SSH key)
    7. Runs terraform init, plan, and apply

.NOTES
    Requires: Windows 11 Pro or Windows Server 2022+ with admin rights.
    Usage: .\scripts\SetupInstall.ps1
#>

param(
    [string]$ImageDir = "C:\HyperV\Images",
    [string]$VmDir    = "C:\HyperV\VMs",
    [string]$VhdDir   = "C:\HyperV\VHDs",
    [switch]$SkipImageDownload
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
}

# =============================================================================
# Step 1: Check/Enable Hyper-V
# =============================================================================
Write-Step "Checking Hyper-V"

$hypervFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -ErrorAction SilentlyContinue
if ($hypervFeature.State -eq "Enabled") {
    Write-Ok "Hyper-V is enabled"
} else {
    Write-Warn "Hyper-V is not enabled. Enabling now..."
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -NoRestart
    Write-Warn "A REBOOT is required. Please reboot and re-run this script."
    exit 1
}

# =============================================================================
# Step 2: Configure WinRM for Terraform Hyper-V Provider
# =============================================================================
Write-Step "Configuring WinRM"

# Enable PS Remoting
Enable-PSRemoting -Force -SkipNetworkProfileCheck -ErrorAction SilentlyContinue
Write-Ok "PS Remoting enabled"
# Configure WinRM settings via WSMan provider (Set-Item is more reliable than Set-WSManInstance)
Set-Item WSMan:\localhost\Shell\MaxMemoryPerShellMB 1024 -ErrorAction SilentlyContinue
Set-Item WSMan:\localhost\MaxTimeoutms 1800000 -ErrorAction SilentlyContinue
try { Set-Item WSMan:\localhost\Client\TrustedHosts "*" -Force -ErrorAction Stop } catch { }
Set-Item WSMan:\localhost\Service\Auth\Negotiate $true -ErrorAction SilentlyContinue

# Ensure WinRM service is running
Set-Service WinRM -StartupType Automatic
Start-Service WinRM
Write-Ok "WinRM configured and running"

# Test WinRM
$winrmTest = Test-WSMan -ComputerName localhost -ErrorAction SilentlyContinue
if ($winrmTest) {
    Write-Ok "WinRM connectivity test passed"
} else {
    Write-Fail "WinRM connectivity test failed"
    exit 1
}

# =============================================================================
# Step 3: Create directory structure
# =============================================================================
Write-Step "Creating directory structure"

@($ImageDir, $VmDir, $VhdDir) | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Force -Path $_ | Out-Null
        Write-Ok "Created $_"
    } else {
        Write-Ok "$_ already exists"
    }
}

# =============================================================================
# Step 4: Download Ubuntu 24.04 Cloud Image
# =============================================================================
Write-Step "Ubuntu 24.04 Cloud Image"

$ubuntuUrl = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
$imgPath   = Join-Path $ImageDir "ubuntu-24.04-cloudimg-amd64.img"
$vhdxPath  = Join-Path $ImageDir "ubuntu-24.04-cloudimg-amd64.vhdx"

# Skip download+conversion if VHDX exists and was created/modified in the last 7 days
$vhdxRecent = $false
if (Test-Path $vhdxPath) {
    $vhdxAge = (Get-Date) - (Get-Item $vhdxPath).LastWriteTime
    if ($vhdxAge.TotalDays -lt 7) {
        $vhdxRecent = $true
    }
}

if (($SkipImageDownload -or $vhdxRecent) -and (Test-Path $vhdxPath)) {
    $ageMsg = if ($vhdxRecent) { " (modified $([math]::Round($vhdxAge.TotalDays,1)) days ago)" } else { "" }
    Write-Ok "VHDX already exists at $vhdxPath$ageMsg — skipping download and conversion"
} else {
    if (-not (Test-Path $imgPath)) {
        Write-Host "  Downloading Ubuntu 24.04 cloud image (~700MB)..."
        Write-Host "  From: $ubuntuUrl"
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $ubuntuUrl -OutFile $imgPath -UseBasicParsing
        $ProgressPreference = 'Continue'
        Write-Ok "Downloaded to $imgPath"
    } else {
        Write-Ok "Image already downloaded at $imgPath"
    }

    # Convert qcow2 to VHDX
    Write-Host "  Converting to VHDX format..."

    # Try qemu-img first (if installed)
    $qemuImg = Get-Command qemu-img.exe -ErrorAction SilentlyContinue
    if ($qemuImg) {
        & qemu-img.exe convert -p -f qcow2 -O vhdx $imgPath $vhdxPath
        Write-Ok "Converted with qemu-img"
    } else {
        # Try WSL
        $wslCheck = wsl --list --quiet 2>$null
        if ($LASTEXITCODE -eq 0 -and $wslCheck) {
            Write-Host "  Using WSL for conversion..."
            $wslImg  = wsl wslpath -a $imgPath.Replace('\', '/')
            $wslVhdx = wsl wslpath -a $vhdxPath.Replace('\', '/')
            $bashCmd = 'which qemu-img > /dev/null 2>&1 || sudo apt-get install -y qemu-utils > /dev/null 2>&1; qemu-img convert -f qcow2 -O vhdx '
            $bashCmd += "'" + $wslImg + "' '" + $wslVhdx + "'"
            wsl bash -c $bashCmd
            if (Test-Path $vhdxPath) {
                Write-Ok "Converted with WSL qemu-img"
            } else {
                Write-Fail "Conversion failed. Install qemu-img: winget install qemu or via WSL"
                exit 1
            }
        } else {
            Write-Fail "Neither qemu-img nor WSL available for image conversion."
            Write-Host "  Install one of:"
            Write-Host "    - qemu-img: winget install SoftwareFreedomConservancy.QEMU"
            Write-Host "    - WSL: wsl --install"
            exit 1
        }
    }
}

# =============================================================================
# Step 5: Ensure WSL has genisoimage for cloud-init ISO creation
# =============================================================================
Write-Step "Checking WSL for cloud-init ISO tools"

$wslCheck = wsl --list --quiet 2>$null
if ($LASTEXITCODE -eq 0 -and $wslCheck) {
    $bashInstallCmd = 'which genisoimage > /dev/null 2>&1 || sudo apt-get install -y genisoimage > /dev/null 2>&1'
    wsl bash -c $bashInstallCmd
    $bashCheckCmd = 'which genisoimage && echo OK'
    $genisoCheck = wsl bash -c $bashCheckCmd
    if ($genisoCheck -match "OK") {
        Write-Ok "genisoimage available in WSL"
    } else {
        Write-Warn "Could not install genisoimage in WSL. Cloud-init ISO creation may fail."
        Write-Host "  Try: wsl sudo apt-get install -y genisoimage"
    }
} else {
    # Check for oscdimg (Windows ADK)
    $oscdimg = Get-Command oscdimg.exe -ErrorAction SilentlyContinue
    if ($oscdimg) {
        Write-Ok "oscdimg.exe found (Windows ADK)"
    } else {
        Write-Warn "Neither WSL nor oscdimg available for cloud-init ISO creation."
        Write-Host "  Install WSL: wsl --install"
        Write-Host "  Or install Windows ADK: https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install"
    }
}

# =============================================================================
# Step 6: Check Terraform
# =============================================================================
Write-Step "Checking Terraform"

$terraform = Get-Command terraform -ErrorAction SilentlyContinue
if ($terraform) {
    $tfVersion = terraform version -json | ConvertFrom-Json
    Write-Ok "Terraform $($tfVersion.terraform_version) installed"
} else {
    Write-Warn "Terraform not found in PATH"
    Write-Host "  Install: winget install HashiCorp.Terraform"
    Write-Host "  Or: choco install terraform"
}

# =============================================================================
# Step 7: Check SSH key
# =============================================================================
Write-Step "Checking SSH key"

$sshKeyPath = Join-Path $env:USERPROFILE ".ssh\id_rsa.pub"
if (Test-Path $sshKeyPath) {
    Write-Ok "SSH public key found at $sshKeyPath"
} else {
    Write-Warn "No SSH key found. Generating one..."
    ssh-keygen -t rsa -b 4096 -f (Join-Path $env:USERPROFILE ".ssh\id_rsa") -N '""' -q
    if (Test-Path $sshKeyPath) {
        Write-Ok "SSH key generated at $sshKeyPath"
    } else {
        Write-Fail "Failed to generate SSH key"
    }
}

# =============================================================================
# Summary
# =============================================================================
Write-Host "`n" -NoNewline
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Prerequisites Complete!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Ubuntu VHDX:  $vhdxPath"
Write-Host "  VM Directory: $VmDir"
Write-Host "  VHD Directory: $VhdDir"
Write-Host ""

$setupHtmlPath = Join-Path $PSScriptRoot "..\html\Setup.html"
$terraformDir  = Join-Path $PSScriptRoot "..\terraform"
$tfvarsPath    = Join-Path $terraformDir "terraform.tfvars"

# Check if terraform.tfvars exists — if not, prompt to create it first
if (-not (Test-Path $tfvarsPath)) {
    Write-Host "  Next step:" -ForegroundColor Yellow
    Write-Host "  Open the Setup Wizard and save the output as:" -ForegroundColor White
    Write-Host "    $tfvarsPath" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Setup Wizard: $setupHtmlPath" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  After creating terraform.tfvars, re-run this script to deploy." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    return
}

Write-Host "  terraform.tfvars found — proceeding to deploy." -ForegroundColor Green
Write-Host ""

# --- Terraform Init ---
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Running: terraform init" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

Push-Location $terraformDir
try {
    terraform init
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  terraform init failed. Fix the errors above and retry." -ForegroundColor Red
        Read-Host "  Press Enter to exit"
        return
    }
    Write-Host ""
    Write-Host "  [OK] terraform init succeeded" -ForegroundColor Green

    # --- Terraform Plan ---
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  Running: terraform plan -out=tfplan" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""

    terraform plan -out=tfplan
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  terraform plan failed. Fix the errors above and retry." -ForegroundColor Red
        Read-Host "  Press Enter to exit"
        return
    }
    Write-Host ""
    Write-Host "  [OK] terraform plan succeeded" -ForegroundColor Green

    # --- Terraform Apply ---
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  Running: terraform apply tfplan" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""

    terraform apply tfplan
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  terraform apply failed. Check the errors above." -ForegroundColor Red
        Read-Host "  Press Enter to exit"
        return
    }

    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "  InsideLLM Deployed Successfully!" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host ""
    terraform output -no-color 2>$null | ForEach-Object { Write-Host "  $_" }
    Write-Host ""
}
finally {
    Pop-Location
}

Read-Host "  Press Enter to exit"
