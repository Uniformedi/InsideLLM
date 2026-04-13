#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Cleanly remove a running InsideLLM Hyper-V deployment.

.DESCRIPTION
    Wraps the teardown path for a Hyper-V (Terraform) deployment:
      1. (Optional) Deregister the instance from the central fleet DB via the
         Governance Hub API so it stops appearing in fleet counts/tiles.
      2. Run `terraform destroy` to remove the VM, VHDX, and cloud-init ISO.
      3. Fall back to direct Hyper-V removal (Remove-VM) when Terraform state
         is missing or destroy fails.

    Fleet history (telemetry, change log, audit entries) is preserved in the
    central DB even after deregistration — this is a soft delete.

.PARAMETER TerraformDir
    Path to the terraform/ directory of the InsideLLM checkout.
    Default: ..\terraform relative to this script.

.PARAMETER TfVarsFile
    Path to terraform.tfvars used during the original deploy.
    Default: ..\terraform.tfvars relative to this script.

.PARAMETER VmName
    Hyper-V VM name. Read from terraform.tfvars when omitted.

.PARAMETER FleetHubUrl
    Base URL of the Governance Hub that owns the central fleet DB
    (e.g. https://governance-hub.corp.local/governance). When set together
    with -InstanceId, the script calls DELETE /api/v1/fleet/instances/{id}
    before destroying the VM.

.PARAMETER InstanceId
    Instance ID to deregister. Typically matches the VM name.

.PARAMETER SkipFleetDeregister
    Skip the fleet deregistration step.

.PARAMETER Force
    Skip all confirmation prompts. Use only in automation.

.EXAMPLE
    .\Remove-InsideLLM.ps1
    Interactive teardown — prompts before each destructive step.

.EXAMPLE
    .\Remove-InsideLLM.ps1 -FleetHubUrl "https://hub.corp.local/governance" -InstanceId "InsideLLM-01"
    Deregisters from the central hub, then destroys the VM.

.EXAMPLE
    .\Remove-InsideLLM.ps1 -Force -SkipFleetDeregister
    Non-interactive teardown, no fleet call.
#>

[CmdletBinding()]
param(
    [string]$TerraformDir        = (Join-Path $PSScriptRoot "..\terraform"),
    [string]$TfVarsFile          = (Join-Path $PSScriptRoot "..\terraform.tfvars"),
    [string]$VmName              = "",
    [string]$FleetHubUrl         = "",
    [string]$InstanceId          = "",
    [switch]$SkipFleetDeregister,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step   { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Info   { param($m) Write-Host "    $m" -ForegroundColor Gray }
function Write-Ok     { param($m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn2  { param($m) Write-Host "    $m" -ForegroundColor Yellow }
function Write-Err    { param($m) Write-Host "    $m" -ForegroundColor Red }

function Confirm-Or-Exit {
    param([string]$Prompt)
    if ($Force) { return }
    $answer = Read-Host "$Prompt [y/N]"
    if ($answer -notmatch '^(y|yes)$') {
        Write-Info "Aborted by user."
        exit 0
    }
}

# ---------------------------------------------------------------------------
# Resolve VM name / instance id from tfvars when not supplied
# ---------------------------------------------------------------------------
function Get-TfVarValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path $Path)) { return "" }
    $line = Select-String -Path $Path -Pattern "^\s*$Key\s*=" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $line) { return "" }
    $value = ($line.Line -split "=", 2)[1].Trim().Trim('"').Trim("'")
    return $value
}

if (-not $VmName) {
    $VmName = Get-TfVarValue -Path $TfVarsFile -Key "vm_name"
}
if (-not $InstanceId) {
    $InstanceId = $VmName
}

Write-Step "InsideLLM Teardown"
Write-Info "Terraform dir: $TerraformDir"
Write-Info "tfvars file:   $TfVarsFile"
Write-Info "VM name:       $(if ($VmName) { $VmName } else { '<unknown>' })"
Write-Info "Instance ID:   $(if ($InstanceId) { $InstanceId } else { '<unknown>' })"

if (-not $VmName) {
    Write-Warn2 "Could not determine VM name from $TfVarsFile."
    Write-Warn2 "Pass -VmName explicitly if you want Hyper-V fallback cleanup."
}

Confirm-Or-Exit "Proceed with teardown of InsideLLM instance '$VmName'?"

# ---------------------------------------------------------------------------
# Step 1: Deregister from central fleet
# ---------------------------------------------------------------------------
if (-not $SkipFleetDeregister -and $FleetHubUrl -and $InstanceId) {
    Write-Step "Deregistering '$InstanceId' from fleet hub at $FleetHubUrl"
    $url = "$($FleetHubUrl.TrimEnd('/'))/api/v1/fleet/instances/$([uri]::EscapeDataString($InstanceId))"
    try {
        $response = Invoke-RestMethod -Uri $url -Method Delete -SkipCertificateCheck -ErrorAction Stop
        Write-Ok ($response | ConvertTo-Json -Compress)
    } catch {
        Write-Warn2 "Fleet deregistration failed: $($_.Exception.Message)"
        Write-Warn2 "Continue anyway?"
        Confirm-Or-Exit "Proceed without fleet deregistration?"
    }
} elseif ($SkipFleetDeregister) {
    Write-Step "Skipping fleet deregistration (per -SkipFleetDeregister)"
} else {
    Write-Step "Skipping fleet deregistration"
    Write-Info "Pass -FleetHubUrl and -InstanceId to deregister from the central hub."
}

# ---------------------------------------------------------------------------
# Step 2: terraform destroy
# ---------------------------------------------------------------------------
$tfDestroyOk = $false
$tfStatePath = Join-Path $TerraformDir "terraform.tfstate"

if ((Test-Path $TerraformDir) -and (Test-Path $tfStatePath)) {
    Write-Step "Running 'terraform destroy' in $TerraformDir"
    Confirm-Or-Exit "This will destroy the VM, VHDX disk, and cloud-init ISO. Continue?"

    Push-Location $TerraformDir
    try {
        $destroyArgs = @("destroy")
        if (Test-Path $TfVarsFile) {
            $destroyArgs += "-var-file=$TfVarsFile"
        }
        if ($Force) { $destroyArgs += "-auto-approve" }

        & terraform @destroyArgs
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "terraform destroy completed."
            $tfDestroyOk = $true
        } else {
            Write-Warn2 "terraform destroy exited with code $LASTEXITCODE — will try Hyper-V fallback."
        }
    } catch {
        Write-Warn2 "terraform destroy raised: $($_.Exception.Message)"
    } finally {
        Pop-Location
    }
} else {
    Write-Step "Skipping terraform destroy"
    if (-not (Test-Path $TerraformDir)) {
        Write-Warn2 "Terraform dir '$TerraformDir' not found."
    } elseif (-not (Test-Path $tfStatePath)) {
        Write-Warn2 "No terraform.tfstate in '$TerraformDir' — using Hyper-V fallback."
    }
}

# ---------------------------------------------------------------------------
# Step 3: Hyper-V fallback (only if terraform didn't fully clean up)
# ---------------------------------------------------------------------------
if (-not $tfDestroyOk -and $VmName) {
    $vm = Get-VM -Name $VmName -ErrorAction SilentlyContinue
    if (-not $vm) {
        Write-Step "Hyper-V fallback: VM '$VmName' not present — nothing to remove."
    } else {
        Write-Step "Hyper-V fallback: removing VM '$VmName'"
        Confirm-Or-Exit "Force-stop and remove Hyper-V VM '$VmName' and its VHDX files?"

        try {
            if ($vm.State -ne "Off") {
                Write-Info "Stopping VM..."
                Stop-VM -Name $VmName -TurnOff -Force -ErrorAction Stop
            }

            $vhdPaths = (Get-VMHardDiskDrive -VMName $VmName).Path
            Remove-VM -Name $VmName -Force -ErrorAction Stop
            Write-Ok "VM removed."

            foreach ($vhd in $vhdPaths) {
                if ($vhd -and (Test-Path $vhd)) {
                    Remove-Item -Path $vhd -Force -ErrorAction Stop
                    Write-Ok "Removed VHD: $vhd"
                }
            }
        } catch {
            Write-Err "Hyper-V cleanup failed: $($_.Exception.Message)"
            exit 1
        }
    }
}

Write-Step "Teardown complete."
Write-Info "If this was part of a fleet, history for '$InstanceId' is preserved"
Write-Info "in the central DB (status='deregistered') for audit."
Write-Info "Delete the repo checkout manually if you no longer need it."
