<#
.SYNOPSIS
    Applies Terraform across all VMs rendered by Render-Fleet.ps1.

.DESCRIPTION
    For each <OutDir>/<vm_name>/ directory:
      1. Runs `terraform -chdir=terraform apply` with an isolated state file
         (terraform.tfstate in that directory) and the rendered tfvars.
      2. Captures stdout/stderr to apply.log in the VM directory.
      3. Prints a summary table on completion.

    Use -DryRun to run `terraform plan` only. Use -Destroy to tear down.
    Use -Parallel N > 1 to apply in parallel (init is always serialized first).

.PARAMETER OutDir
    Directory containing rendered VM folders. Defaults to ./fleet-out.

.PARAMETER Parallel
    Max parallel apply jobs. Defaults to 1 (sequential).

.PARAMETER TargetVM
    Optional VM name to apply only that single instance.

.PARAMETER Destroy
    Run `terraform destroy` instead of apply.

.PARAMETER DryRun
    Run `terraform plan` (read-only), do not apply or destroy.

.EXAMPLE
    pwsh ./scripts/Deploy-Fleet.ps1 -Parallel 2
#>
[CmdletBinding()]
param(
    [string] $OutDir    = "./fleet-out",
    [int]    $Parallel  = 1,
    [string] $TargetVM  = "",
    [switch] $Destroy,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TfModuleDir= Join-Path $RepoRoot "terraform"

function Get-VMDirectories {
    param([string] $Root, [string] $Only)
    if (-not (Test-Path -LiteralPath $Root)) {
        throw "Output directory not found: $Root. Run Render-Fleet.ps1 first."
    }
    $dirs = Get-ChildItem -LiteralPath $Root -Directory
    if ($Only) {
        $dirs = $dirs | Where-Object { $_.Name -eq $Only }
        if (-not $dirs) { throw "No VM directory named '$Only' under $Root" }
    }
    foreach ($d in $dirs) {
        if (Test-Path -LiteralPath (Join-Path $d.FullName 'terraform.tfvars')) {
            $d
        }
    }
}

function Invoke-TerraformInit {
    param([string] $Module)
    Write-Host "Running: terraform -chdir=`"$Module`" init" -ForegroundColor Cyan
    & terraform "-chdir=$Module" init -input=false
    if ($LASTEXITCODE -ne 0) { throw "terraform init failed (exit $LASTEXITCODE)" }
}

function Invoke-TerraformForVM {
    param(
        [string] $Module,
        [string] $VMName,
        [string] $VMDir,
        [bool]   $DoDestroy,
        [bool]   $DoDryRun
    )
    $tfvars = (Resolve-Path (Join-Path $VMDir 'terraform.tfvars')).Path
    $state  = Join-Path $VMDir 'terraform.tfstate'
    $log    = Join-Path $VMDir 'apply.log'

    $verb = if ($DoDryRun) { 'plan' }
            elseif ($DoDestroy) { 'destroy' }
            else { 'apply' }

    $argList = @("-chdir=$Module", $verb, "-input=false", "-var-file=$tfvars", "-state=$state")
    if ($verb -ne 'plan') { $argList += "-auto-approve" }

    $start = Get-Date
    $result = [ordered] @{
        VMName    = $VMName
        IP        = ''
        Action    = $verb
        Result    = 'pending'
        Seconds   = 0
        LogPath   = $log
    }

    try {
        Write-Host "[$VMName] terraform $verb ..." -ForegroundColor Cyan
        & terraform @argList *>&1 | Tee-Object -FilePath $log | Out-Null
        if ($LASTEXITCODE -ne 0) {
            $result.Result = "failed(exit=$LASTEXITCODE)"
        } else {
            $result.Result = 'ok'
            if ($verb -eq 'apply') {
                try {
                    $outJson = & terraform "-chdir=$Module" output -json -state=$state 2>$null | Out-String
                    if ($outJson.Trim()) {
                        $outs = $outJson | ConvertFrom-Json
                        foreach ($candidate in 'vm_ip','vm_ip_address','vm_static_ip') {
                            if ($outs.PSObject.Properties.Name -contains $candidate) {
                                $result.IP = [string] $outs.$candidate.value
                                break
                            }
                        }
                    }
                } catch { $result.IP = '' }
            }
        }
    } catch {
        $result.Result = "exception: $($_.Exception.Message)"
    }
    $result.Seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
    return [pscustomobject] $result
}

function Invoke-Main {
    $vmDirs = @(Get-VMDirectories -Root $OutDir -Only $TargetVM)
    if (-not $vmDirs -or $vmDirs.Count -eq 0) {
        throw "No VM directories found in $OutDir."
    }

    Invoke-TerraformInit -Module $TfModuleDir

    $results = @()
    if ($Parallel -le 1) {
        foreach ($d in $vmDirs) {
            $results += Invoke-TerraformForVM -Module $TfModuleDir `
                -VMName $d.Name -VMDir $d.FullName `
                -DoDestroy:$Destroy -DoDryRun:$DryRun
        }
    } else {
        if (-not (Get-Command Start-ThreadJob -ErrorAction SilentlyContinue)) {
            throw "Start-ThreadJob not available. Install: Install-Module ThreadJob -Scope CurrentUser"
        }
        $jobs = @()
        $sem  = [System.Threading.SemaphoreSlim]::new($Parallel, $Parallel)
        foreach ($d in $vmDirs) {
            $sem.Wait()
            $jobs += Start-ThreadJob -ScriptBlock {
                param($Module, $Name, $Dir, $D, $P, $Fn)
                $func = [ScriptBlock]::Create($Fn)
                & $func $Module $Name $Dir $D $P
            } -ArgumentList $TfModuleDir, $d.Name, $d.FullName, [bool]$Destroy, [bool]$DryRun, ${function:Invoke-TerraformForVM}.ToString()
        }
        $results = $jobs | Receive-Job -Wait -AutoRemoveJob
    }

    Write-Host ""
    Write-Host "Fleet deploy summary:" -ForegroundColor Cyan
    $results | Format-Table VMName, IP, Action, Result, Seconds, LogPath -AutoSize `
        | Out-String | Write-Host

    $failed = @($results | Where-Object { $_.Result -notmatch '^ok$' })
    if ($failed.Count -gt 0) {
        Write-Host "FAILED: $($failed.Count) of $($results.Count) VMs" -ForegroundColor Red
        exit 2
    }
}

try {
    Invoke-Main
} catch {
    Write-Error $_
    exit 1
}
