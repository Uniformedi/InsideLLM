#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Sets up and installs InsideLLM via Hyper-V Terraform deployment.

.DESCRIPTION
    This script prepares the host, verifies prerequisites, and runs Terraform:
    1. Enables Hyper-V if not already enabled
    2. Configures WinRM for Terraform's Hyper-V provider
    3. Downloads the Debian 12 (Bookworm) generic cloud image (skips if recent VHDX exists)
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

# Probe current state first. If everything is already in the shape we need,
# we skip the config writes AND skip the service restart — important on
# hosts that are actively serving another InsideLLM deployment, because
# restarting WinRM can break existing PS-Remoting / Hyper-V sessions and
# fails outright when dependent services are attached (Restart-Service
# without -Force raises "can only be stopped if the Force flag is set").
function Test-WinRMAlreadyConfigured {
    try {
        if (-not (Test-WSMan -ComputerName localhost -ErrorAction Stop)) { return $false }
    } catch { return $false }

    # HTTP listener on 5985 must exist
    $listener = Get-WSManInstance -ResourceURI winrm/config/listener `
        -SelectorSet @{Address="*";Transport="HTTP"} -ErrorAction SilentlyContinue
    if (-not $listener) { return $false }

    # Service-side auth + transport flags must match what Terraform needs
    $svc = Get-Item -Path WSMan:\localhost\Service -ErrorAction SilentlyContinue
    try {
        $au = (Get-Item WSMan:\localhost\Service\AllowUnencrypted).Value
        $basic = (Get-Item WSMan:\localhost\Service\Auth\Basic).Value
        $nego = (Get-Item WSMan:\localhost\Service\Auth\Negotiate).Value
        if ($au -ne 'true' -or $basic -ne 'true' -or $nego -ne 'true') { return $false }
    } catch { return $false }

    # TrustedHosts should include *
    try {
        $th = (Get-Item WSMan:\localhost\Client\TrustedHosts).Value
        if ($th -notmatch '\*') { return $false }
    } catch { return $false }

    return $true
}

if (Test-WinRMAlreadyConfigured) {
    Write-Ok "WinRM already configured — skipping reconfig and restart (existing deployments unaffected)"
} else {
    # Enable PS Remoting (idempotent — restarts WinRM internally on first run)
    Enable-PSRemoting -Force -SkipNetworkProfileCheck -ErrorAction SilentlyContinue
    Write-Ok "PS Remoting enabled"

    # Configure WinRM for Terraform Hyper-V provider (HTTP on 5985)
    Set-Item WSMan:\localhost\Shell\MaxMemoryPerShellMB 1024 -ErrorAction SilentlyContinue
    Set-Item WSMan:\localhost\MaxTimeoutms 1800000 -ErrorAction SilentlyContinue
    try { Set-Item WSMan:\localhost\Client\TrustedHosts "*" -Force -ErrorAction Stop } catch { }
    Set-Item WSMan:\localhost\Service\Auth\Negotiate $true -ErrorAction SilentlyContinue
    Set-Item WSMan:\localhost\Service\Auth\Basic $true -ErrorAction SilentlyContinue
    Set-Item WSMan:\localhost\Service\AllowUnencrypted $true -ErrorAction SilentlyContinue
    Set-Item WSMan:\localhost\Client\AllowUnencrypted $true -ErrorAction SilentlyContinue

    # Configure via winrm command for settings not accessible via WSMan provider
    winrm set winrm/config/service '@{AllowUnencrypted="true"}' 2>$null
    winrm set winrm/config/service/auth '@{Basic="true";Negotiate="true"}' 2>$null
    winrm set winrm/config/client '@{AllowUnencrypted="true"}' 2>$null

    # Ensure HTTP listener exists on 5985
    $httpListener = Get-WSManInstance -ResourceURI winrm/config/listener -SelectorSet @{Address="*";Transport="HTTP"} -ErrorAction SilentlyContinue
    if (-not $httpListener) {
        New-WSManInstance -ResourceURI winrm/config/listener -SelectorSet @{Address="*";Transport="HTTP"} -ValueSet @{Port=5985} -ErrorAction SilentlyContinue
        Write-Ok "Created WinRM HTTP listener on port 5985"
    } else {
        Write-Ok "WinRM HTTP listener already exists"
    }

    # Ensure WinRM service is running. Pass -Force to Restart-Service so it
    # can stop even when dependent services are attached (common on hosts
    # that also run Hyper-V or IIS management).
    Set-Service WinRM -StartupType Automatic
    Restart-Service WinRM -Force
    Write-Ok "WinRM configured and restarted"
}

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
# Step 4: Download Debian 12 (Bookworm) Generic Cloud Image
# =============================================================================
Write-Step "Debian 12 (Bookworm) Cloud Image"

# Debian Cloud's "genericcloud" image is the hardware-agnostic build suitable
# for Hyper-V. The "generic" image also works; genericcloud is smaller and
# strips out non-cloud kernel modules we don't need.
$debianUrl = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2"
$imgPath   = Join-Path $ImageDir "debian-12-genericcloud-amd64.qcow2"
$vhdxPath  = Join-Path $ImageDir "debian-12-genericcloud-amd64.vhdx"

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
    Write-Ok "VHDX already exists at $vhdxPath$ageMsg - skipping download and conversion"
} else {
    if (-not (Test-Path $imgPath)) {
        Write-Host "  Downloading Debian 12 genericcloud image (~350MB)..."
        Write-Host "  From: $debianUrl"
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $debianUrl -OutFile $imgPath -UseBasicParsing
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

# Resolve project root (one level above scripts/)
$projectRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$setupHtmlPath = Join-Path $projectRoot "html\Setup.html"
$terraformDir  = Join-Path $projectRoot "terraform"

# Look for terraform.tfvars in multiple locations
$tfvarsPath = $null
$tfvarsCandidates = @(
    (Join-Path $terraformDir "terraform.tfvars"),   # terraform/ subfolder
    (Join-Path $projectRoot "terraform.tfvars")      # project root
)
foreach ($candidate in $tfvarsCandidates) {
    if (Test-Path $candidate) {
        $tfvarsPath = $candidate
        break
    }
}

# Check if terraform.tfvars exists - if not, prompt to create it first
if (-not $tfvarsPath) {
    Write-Host "  Next step:" -ForegroundColor Yellow
    Write-Host "  Open the Setup Wizard and save the output to one of:" -ForegroundColor White
    Write-Host "    $($tfvarsCandidates[0])" -ForegroundColor Cyan
    Write-Host "    $($tfvarsCandidates[1])" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Setup Wizard: $setupHtmlPath" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  After creating terraform.tfvars, re-run this script to deploy." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    return
}

Write-Host "  terraform.tfvars found at: $tfvarsPath" -ForegroundColor Green

# If tfvars is outside terraform/, use -var-file to point Terraform at it
$varFileArg = ""
if ($tfvarsPath -ne (Join-Path $terraformDir "terraform.tfvars")) {
    $varFileArg = "-var-file=`"$tfvarsPath`""
    Write-Host "  (using -var-file since tfvars is outside terraform/ folder)" -ForegroundColor DarkGray
}

# Read tfvars to get the VM name for pre-flight checks
. "$PSScriptRoot\Read-TfVars.ps1"
$_tf = Read-TfVars -ProjectRoot $projectRoot
$vmName = $_tf["vm_name"]
if (-not $vmName) { $vmName = $_tf["vm_hostname"]; if (-not $vmName) { $vmName = "InsideLLM" } }
Write-Host "  VM Name: $vmName" -ForegroundColor Green

# =============================================================================
# Pre-flight: Hyper-V Virtual Switch selection
# =============================================================================
Write-Step "Hyper-V Virtual Switch"

$cfgSwitchName = if ($_tf["vm_switch_name"]) { $_tf["vm_switch_name"] } else { "InsideLLM" }

# Discover existing switches that have external (or internal) network access
$externalSwitches = @(Get-VMSwitch -ErrorAction SilentlyContinue | Where-Object { $_.SwitchType -eq 'External' })

if ($externalSwitches.Count -gt 0) {
    Write-Host "  Found $($externalSwitches.Count) existing External virtual switch(es):" -ForegroundColor White
    Write-Host ""
    for ($i = 0; $i -lt $externalSwitches.Count; $i++) {
        $sw = $externalSwitches[$i]
        $adapter = ($sw.NetAdapterInterfaceDescription | Out-String).Trim()
        if (-not $adapter) { $adapter = "(unknown adapter)" }
        $marker = if ($sw.Name -eq $cfgSwitchName) { " <-- current tfvars" } else { "" }
        Write-Host "    [$($i + 1)] $($sw.Name)  -  $adapter$marker" -ForegroundColor Cyan
    }
    Write-Host "    [N] Create a new switch named '$cfgSwitchName'" -ForegroundColor Yellow
    Write-Host ""
    $switchChoice = Read-Host "  Select a switch [1-$($externalSwitches.Count)/N]"

    if ($switchChoice -and $switchChoice.ToUpper() -ne 'N') {
        $idx = 0
        if ([int]::TryParse($switchChoice, [ref]$idx) -and $idx -ge 1 -and $idx -le $externalSwitches.Count) {
            $chosen = $externalSwitches[$idx - 1]
            Write-Ok "Using existing switch: $($chosen.Name)"

            # Update in-memory tfvars and patch the file so Terraform sees the right switch
            if ($chosen.Name -ne $cfgSwitchName) {
                $_tf["vm_switch_name"] = $chosen.Name
                $_tf["vm_switch_type"] = "External"
                # Patch tfvars file
                $tfContent = Get-Content $tfvarsPath -Raw
                $tfContent = $tfContent -replace '(?m)^vm_switch_name\s*=\s*"[^"]*"', "vm_switch_name    = `"$($chosen.Name)`""
                $tfContent = $tfContent -replace '(?m)^vm_switch_type\s*=\s*"[^"]*"', 'vm_switch_type    = "External"'
                Set-Content -Path $tfvarsPath -Value $tfContent -NoNewline
                Write-Ok "Updated terraform.tfvars with switch '$($chosen.Name)'"
            }
        } else {
            Write-Fail "Invalid selection. Exiting."
            Read-Host "  Press Enter to exit"
            return
        }
    } else {
        Write-Host "  Will create new switch '$cfgSwitchName' during terraform apply" -ForegroundColor DarkGray
    }
} else {
    Write-Host "  No existing External virtual switches found." -ForegroundColor DarkGray
    Write-Host "  A new switch '$cfgSwitchName' will be created during terraform apply." -ForegroundColor DarkGray
}

Write-Host ""

# Pre-flight: check if a VM with this name already exists on this Hyper-V host
try {
    $existingVm = Get-VM -Name $vmName -ErrorAction SilentlyContinue
} catch {
    $existingVm = $null
}

if ($existingVm) {
    Write-Host ""
    Write-Host "  WARNING: A VM named '$vmName' already exists on this host!" -ForegroundColor Yellow
    Write-Host "  Status: $($existingVm.State)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Choose an action:" -ForegroundColor White
    Write-Host "    [I] Import - adopt existing VM into Terraform state (default)" -ForegroundColor Green
    Write-Host "    [R] Remove - delete old VM and create fresh" -ForegroundColor Yellow
    Write-Host "    [E] Exit   - abort so you can change vm_name in terraform.tfvars" -ForegroundColor DarkGray
    Write-Host ""
    $choice = Read-Host "  Enter choice [I/R/E]"
    $choice = if ($choice) { $choice.ToUpper() } else { "I" }

    if ($choice -eq 'E') { return }

    if ($choice -eq 'R') {
        Write-Host ""
        Write-Host "  Removing existing VM '$vmName'..." -ForegroundColor Yellow
        try {
            Stop-VM -Name $vmName -Force -TurnOff -ErrorAction SilentlyContinue
            Remove-VM -Name $vmName -Force
            Write-Ok "VM '$vmName' removed"
        } catch {
            Write-Fail "Failed to remove VM: $_"
            return
        }
    }

    if ($choice -eq 'I') {
        Write-Host ""
        Write-Host "  Importing existing VM into Terraform state..." -ForegroundColor Cyan
        Push-Location $terraformDir
        try {
            Write-Host "  Running terraform init..." -ForegroundColor DarkGray
            terraform init -input=false
            if ($LASTEXITCODE -ne 0) {
                Write-Fail "terraform init failed - cannot import"
                Pop-Location
                return
            }
            # Import the VM
            $importArgs = @("import")
            if ($varFileArg) { $importArgs += $varFileArg }
            $importArgs += "hyperv_machine_instance.insidellm"
            $importArgs += $vmName
            Write-Host "  > terraform $($importArgs -join ' ')" -ForegroundColor DarkGray
            & terraform @importArgs
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "VM '$vmName' imported into Terraform state"
            } else {
                Write-Warn "Import failed - continuing to plan (may need manual resolution)"
            }

            # Also import the switch if it exists
            $switchName = if ($_tf["vm_switch_name"]) { $_tf["vm_switch_name"] } else { "InsideLLM" }
            $existingSwitch = Get-VMSwitch -Name $switchName -ErrorAction SilentlyContinue
            if ($existingSwitch) {
                Write-Host "  Importing existing virtual switch..." -ForegroundColor DarkGray
                # Switch is now a null_resource, no import needed
                Write-Ok "Virtual switch handled by null_resource (no import needed)"
            }
        } finally { Pop-Location }
    }
}

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

    $planCmd = "terraform plan -out=tfplan $varFileArg".Trim()
    Write-Host "  > $planCmd" -ForegroundColor DarkGray
    Invoke-Expression $planCmd
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

    # -----------------------------------------------------------------
    # Trust the VM's SSH host key. Every fresh deploy generates new host
    # keys; without this step operators hit "REMOTE HOST IDENTIFICATION
    # HAS CHANGED!" and either have to manually ssh-keygen -R or (worse)
    # disable strict host checking. We pre-seed known_hosts with the new
    # key so subsequent SSH / terraform provisioner / Ansible-style use
    # works cleanly.
    # -----------------------------------------------------------------
    try {
        $vmIp = ""
        try { $vmIp = (terraform output -raw vm_ip 2>$null) } catch {}
        if (-not $vmIp) {
            # Fall back to parsing vm_static_ip from tfvars (strip /CIDR)
            $tfvarsFile = Get-ChildItem -Path (Get-Location) -Filter "*.tfvars" -File | Select-Object -First 1
            if ($tfvarsFile) {
                $line = Select-String -Path $tfvarsFile.FullName -Pattern '^\s*vm_static_ip\s*=' | Select-Object -First 1
                if ($line) {
                    $vmIp = ($line.Line -split '=')[1].Trim() -replace '"', '' -replace '\s.*', ''
                    $vmIp = ($vmIp -split '/')[0]
                }
            }
        }

        if ($vmIp) {
            Write-Host "  Trusting VM SSH host key ($vmIp)..." -ForegroundColor Cyan
            $knownHostsLocations = @(
                Join-Path $env:USERPROFILE ".ssh\known_hosts"
            )
            # Also cover git-bash's HOME if it differs (resolves to I:\ or
            # similar on some Windows setups — ssh-keyscan from bash uses
            # that one).
            if ($env:HOME -and ($env:HOME -ne $env:USERPROFILE)) {
                $knownHostsLocations += (Join-Path $env:HOME ".ssh\known_hosts")
            }
            foreach ($kh in $knownHostsLocations) {
                $dir = Split-Path $kh
                if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
                if (-not (Test-Path $kh))  { New-Item -ItemType File -Force -Path $kh | Out-Null }
                # Drop any stale keys for this IP (silent if none present)
                & ssh-keygen -R $vmIp -f $kh 2>&1 | Out-Null
            }
            # Scan the fresh key(s) once and append to every known_hosts
            $scan = & ssh-keyscan -T 5 -H $vmIp 2>$null
            if ($scan) {
                foreach ($kh in $knownHostsLocations) {
                    Add-Content -Path $kh -Value $scan -Encoding ASCII
                }
                Write-Host "  Host key trusted in: $($knownHostsLocations -join ', ')" -ForegroundColor Green
            } else {
                Write-Host "  (ssh-keyscan returned no keys — VM may still be booting; rerun ssh-keyscan -H $vmIp >> ~/.ssh/known_hosts manually once SSH is up)" -ForegroundColor Yellow
            }
        }
    } catch {
        Write-Host "  (host-key trust step failed: $($_.Exception.Message); not fatal)" -ForegroundColor Yellow
    }
}
finally {
    Pop-Location
}

Read-Host "  Press Enter to exit"
