<#
.SYNOPSIS
    Applies Terraform across all VMs rendered by Render-Fleet.ps1.

.DESCRIPTION
    For each <OutDir>/<vm_name>/ directory:
      1. Runs `terraform -chdir=terraform apply` with an isolated state file
         (terraform.tfstate in that directory) and the rendered tfvars.
      2. Captures stdout/stderr to apply.log in the VM directory.
      3. Prints a summary table on completion.

    Deploy ordering is role-aware: the primary VM is applied first, then
    gateway / workstation / voice / storage backends, and finally edge VMs
    (so backend IPs exist before the router boots). Use -Stage to restrict
    to a subset.

    Use -DryRun to run `terraform plan` only. Use -Destroy to tear down.
    Use -Parallel N > 1 to apply in parallel within a stage (init is always
    serialized first). Staging order is always respected across stages.

.PARAMETER OutDir
    Directory containing rendered VM folders. Defaults to ./fleet-out.

.PARAMETER Parallel
    Max parallel apply jobs within a single stage. Defaults to 1.

.PARAMETER TargetVM
    Optional VM name to apply only that single instance. Bypasses staging.

.PARAMETER Stage
    Phase to deploy. One of:
      all       - primary, then backends, then edge  (default)
      primary   - only the vm_role = "primary" VM
      backends  - everything except edge VMs (primary + gateways + workstations + voice + storage)
      edge      - only the vm_role = "edge" VMs

.PARAMETER Destroy
    Run `terraform destroy` instead of apply. For a safe teardown, destroy
    the edge first; use `-Stage edge -Destroy`, then `-Stage backends -Destroy`.

.PARAMETER DryRun
    Run `terraform plan` (read-only), do not apply or destroy.

.EXAMPLE
    pwsh ./scripts/Deploy-Fleet.ps1 -Parallel 2

.EXAMPLE
    pwsh ./scripts/Deploy-Fleet.ps1 -Stage backends

.EXAMPLE
    pwsh ./scripts/Deploy-Fleet.ps1 -Stage edge
#>
[CmdletBinding()]
param(
    [string] $OutDir    = "./fleet-out",
    [int]    $Parallel  = 1,
    [string] $TargetVM  = "",
    [ValidateSet('all', 'primary', 'backends', 'edge')]
    [string] $Stage     = "all",
    [switch] $Destroy,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TfModuleDir= Join-Path $RepoRoot "terraform"

# Role ordering weight: lower = deployed earlier
$script:RoleOrder = @{
    'primary'     = 0
    'storage'     = 1
    'gateway'     = 2
    'workstation' = 3
    'voice'       = 4
    ''            = 5  # unlabeled / legacy single-VM deploys
    'edge'        = 9  # always last
}

function Get-VmRoleFromTfvars {
    param([string] $TfvarsPath)
    if (-not (Test-Path -LiteralPath $TfvarsPath)) { return '' }
    $lines = Get-Content -LiteralPath $TfvarsPath
    foreach ($line in $lines) {
        if ($line -match '^\s*vm_role\s*=\s*"([^"]*)"\s*$') {
            return $Matches[1]
        }
    }
    return ''
}

function Test-StageIncludesRole {
    param(
        [string] $Stage,
        [string] $Role
    )
    switch ($Stage) {
        'all'      { return $true }
        'primary'  { return ($Role -eq 'primary') }
        'backends' { return ($Role -ne 'edge') }
        'edge'     { return ($Role -eq 'edge') }
    }
    return $true
}

function Get-VMDirectories {
    param(
        [string] $Root,
        [string] $Only,
        [string] $Stage
    )
    if (-not (Test-Path -LiteralPath $Root)) {
        throw "Output directory not found: $Root. Run Render-Fleet.ps1 first."
    }
    $dirs = Get-ChildItem -LiteralPath $Root -Directory
    if ($Only) {
        $dirs = @($dirs | Where-Object { $_.Name -eq $Only })
        if (-not $dirs -or $dirs.Count -eq 0) { throw "No VM directory named '$Only' under $Root" }
    }

    $out = @()
    foreach ($d in $dirs) {
        $tfv = Join-Path $d.FullName 'terraform.tfvars'
        if (-not (Test-Path -LiteralPath $tfv)) { continue }
        $role = Get-VmRoleFromTfvars -TfvarsPath $tfv

        if (-not $Only) {
            if (-not (Test-StageIncludesRole -Stage $Stage -Role $role)) { continue }
        }

        $weight = if ($script:RoleOrder.ContainsKey($role)) { $script:RoleOrder[$role] } else { $script:RoleOrder[''] }
        $out += [pscustomobject] @{
            Directory = $d
            VMName    = $d.Name
            Role      = $role
            Weight    = $weight
        }
    }
    # Sort by role weight (primary first ... edge last), then by name for determinism
    $out = $out | Sort-Object Weight, VMName
    return $out
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
        [string] $Role,
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
        Role      = $Role
        IP        = ''
        Action    = $verb
        Result    = 'pending'
        Seconds   = 0
        LogPath   = $log
    }

    try {
        Write-Host "[$VMName] ($Role) terraform $verb ..." -ForegroundColor Cyan
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
    $vmDirs = @(Get-VMDirectories -Root $OutDir -Only $TargetVM -Stage $Stage)
    if (-not $vmDirs -or $vmDirs.Count -eq 0) {
        if ($TargetVM) {
            throw "No VM directories found for TargetVM='$TargetVM' under $OutDir."
        } else {
            throw "No VM directories match Stage='$Stage' under $OutDir."
        }
    }

    Write-Host ""
    Write-Host "Deploy plan (Stage=$Stage):" -ForegroundColor Cyan
    $vmDirs | Format-Table VMName, Role -AutoSize | Out-String | Write-Host

    Invoke-TerraformInit -Module $TfModuleDir

    # Group by Weight so stages run serially across groups, but can parallelize within
    $groups = $vmDirs | Group-Object Weight | Sort-Object { [int] $_.Name }
    $results = @()

    foreach ($group in $groups) {
        $members = @($group.Group)
        $firstRole = $members[0].Role
        Write-Host ""
        Write-Host "-- Stage group: role=$firstRole ($($members.Count) VM(s)) --" -ForegroundColor Yellow

        if ($Parallel -le 1 -or $members.Count -le 1) {
            foreach ($m in $members) {
                $results += Invoke-TerraformForVM -Module $TfModuleDir `
                    -VMName $m.VMName -VMDir $m.Directory.FullName -Role $m.Role `
                    -DoDestroy:$Destroy -DoDryRun:$DryRun
            }
        } else {
            if (-not (Get-Command Start-ThreadJob -ErrorAction SilentlyContinue)) {
                throw "Start-ThreadJob not available. Install: Install-Module ThreadJob -Scope CurrentUser"
            }
            $jobs = @()
            foreach ($m in $members) {
                $jobs += Start-ThreadJob -ThrottleLimit $Parallel -ScriptBlock {
                    param($Module, $Name, $Dir, $Role, $D, $P, $Fn)
                    $func = [ScriptBlock]::Create($Fn)
                    & $func $Module $Name $Dir $Role $D $P
                } -ArgumentList $TfModuleDir, $m.VMName, $m.Directory.FullName, $m.Role, [bool]$Destroy, [bool]$DryRun, ${function:Invoke-TerraformForVM}.ToString()
            }
            $groupResults = $jobs | Receive-Job -Wait -AutoRemoveJob
            $results += $groupResults
        }

        # If any VM in this stage group failed and we are applying (not plan/destroy),
        # stop before moving on to the next role stage - a backend failure means the
        # edge would route to a dead target.
        if (-not $DryRun -and -not $Destroy) {
            $groupFail = @($results | Where-Object { $_.Role -eq $firstRole -and $_.Result -notmatch '^ok$' })
            if ($groupFail.Count -gt 0) {
                Write-Host "Stage group '$firstRole' had $($groupFail.Count) failure(s); halting before next stage." -ForegroundColor Red
                break
            }
        }
    }

    Write-Host ""
    Write-Host "Fleet deploy summary:" -ForegroundColor Cyan
    $results | Format-Table VMName, Role, IP, Action, Result, Seconds, LogPath -AutoSize `
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
