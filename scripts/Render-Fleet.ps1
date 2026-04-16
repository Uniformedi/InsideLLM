<#
.SYNOPSIS
    Renders fleet.yaml into per-VM terraform.tfvars files.

.DESCRIPTION
    Reads a fleet manifest (YAML) with `shared` + `instances` blocks, merges
    shared keys into each instance (instance wins), resolves env: references,
    and writes one terraform.tfvars per VM under -OutDir/<vm_name>/.

.PARAMETER ManifestPath
    Path to fleet.yaml. Defaults to ./fleet.yaml.

.PARAMETER OutDir
    Output root directory. Defaults to ./fleet-out.

.PARAMETER WhatIf
    Print what would be rendered without writing.

.EXAMPLE
    pwsh ./scripts/Render-Fleet.ps1 -ManifestPath ./fleet.yaml
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $ManifestPath = "./fleet.yaml",
    [string] $OutDir       = "./fleet-out"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# YAML loader (powershell-yaml; installed to CurrentUser on first run)
# ---------------------------------------------------------------------------
function Import-YamlModule {
    if (Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue) { return }
    try {
        Import-Module powershell-yaml -ErrorAction Stop
    } catch {
        Write-Verbose "Installing powershell-yaml module to CurrentUser scope..."
        try {
            Install-Module powershell-yaml -Scope CurrentUser -Force -AllowClobber -ErrorAction Stop
            Import-Module powershell-yaml -ErrorAction Stop
        } catch {
            throw "powershell-yaml module is required. Install manually: Install-Module powershell-yaml -Scope CurrentUser"
        }
    }
}

function Get-MaskedValue {
    param([string] $Key, $Value)
    $sensitive = @('password', 'secret', 'api_key', 'anthropic')
    foreach ($needle in $sensitive) {
        if ($Key -match $needle) { return '***REDACTED***' }
    }
    return [string] $Value
}

function Resolve-SecretValue {
    param([string] $Key, $Value)
    if ($Value -is [string] -and $Value.StartsWith('env:')) {
        $envName = $Value.Substring(4).Trim()
        if (-not $envName) {
            throw "Empty env var name in '$Key': '$Value'"
        }
        $envVal = [Environment]::GetEnvironmentVariable($envName)
        if ([string]::IsNullOrEmpty($envVal)) {
            throw "Environment variable '$envName' (referenced by '$Key') is not set."
        }
        return $envVal
    }
    return $Value
}

# ---------------------------------------------------------------------------
# HCL serialization
# ---------------------------------------------------------------------------
function ConvertTo-HclValue {
    param($Value)
    if ($null -eq $Value) { return '""' }
    if ($Value -is [bool])    { return ($Value ? 'true' : 'false') }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) {
        return [string] $Value
    }
    if ($Value -is [System.Collections.IList]) {
        $items = foreach ($x in $Value) { ConvertTo-HclValue $x }
        return '[' + ($items -join ', ') + ']'
    }
    # Default: quote as string, escape backslashes and double quotes
    $s = [string] $Value
    $s = $s -replace '\\', '\\\\'
    $s = $s -replace '"', '\"'
    return '"' + $s + '"'
}

function ConvertTo-TfVars {
    param([hashtable] $Data)
    $sb = [System.Text.StringBuilder]::new()
    [void] $sb.AppendLine("# Rendered by Render-Fleet.ps1 — do not edit by hand")
    [void] $sb.AppendLine("# Source manifest: fleet.yaml")
    [void] $sb.AppendLine("")
    foreach ($k in ($Data.Keys | Sort-Object)) {
        $v = ConvertTo-HclValue $Data[$k]
        [void] $sb.AppendLine("$k = $v")
    }
    return $sb.ToString()
}

# ---------------------------------------------------------------------------
# Merge shared + instance, resolve env refs
# ---------------------------------------------------------------------------
function Merge-Instance {
    param(
        [hashtable] $Shared,
        [hashtable] $Instance
    )
    $merged = @{}
    if ($Shared) {
        foreach ($k in $Shared.Keys) { $merged[$k] = $Shared[$k] }
    }
    foreach ($k in $Instance.Keys) { $merged[$k] = $Instance[$k] }

    $resolved = @{}
    foreach ($k in $merged.Keys) {
        $resolved[$k] = Resolve-SecretValue -Key $k -Value $merged[$k]
    }
    return $resolved
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
function Invoke-Main {
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        throw "Manifest not found: $ManifestPath"
    }

    Import-YamlModule
    $raw = Get-Content -LiteralPath $ManifestPath -Raw
    $manifest = ConvertFrom-Yaml $raw

    if (-not $manifest.ContainsKey('instances') -or -not $manifest['instances']) {
        throw "Manifest has no 'instances' block."
    }

    $shared = @{}
    if ($manifest.ContainsKey('shared') -and $manifest['shared']) {
        foreach ($k in $manifest['shared'].Keys) { $shared[$k] = $manifest['shared'][$k] }
    }

    # Manifest hash for sidecar staleness detection
    $sha = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash

    if (-not (Test-Path -LiteralPath $OutDir)) {
        if ($PSCmdlet.ShouldProcess($OutDir, "Create output directory")) {
            New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
        }
    }

    $report = @()
    foreach ($inst in $manifest['instances']) {
        $instHash = @{}
        foreach ($k in $inst.Keys) { $instHash[$k] = $inst[$k] }

        if (-not $instHash.ContainsKey('vm_name')) {
            throw "Instance is missing required 'vm_name': $($instHash | ConvertTo-Json -Compress)"
        }
        $vmName = [string] $instHash['vm_name']

        $merged = Merge-Instance -Shared $shared -Instance $instHash
        $tfvars = ConvertTo-TfVars -Data $merged

        $vmDir   = Join-Path $OutDir $vmName
        $tfvPath = Join-Path $vmDir  'terraform.tfvars'
        $sidePath= Join-Path $vmDir  '.terraform-fleet.json'

        $status = 'new'
        if (Test-Path -LiteralPath $tfvPath) {
            $existing = Get-Content -LiteralPath $tfvPath -Raw
            $status = ($existing -eq $tfvars) ? 'unchanged' : 'updated'
        }

        $ip = if ($merged.ContainsKey('vm_static_ip')) { [string] $merged['vm_static_ip'] } else { '' }

        if ($PSCmdlet.ShouldProcess($tfvPath, "Write tfvars ($status)")) {
            if (-not (Test-Path -LiteralPath $vmDir)) {
                New-Item -ItemType Directory -Path $vmDir -Force | Out-Null
            }
            if ($status -ne 'unchanged') {
                Set-Content -LiteralPath $tfvPath -Value $tfvars -NoNewline -Encoding UTF8
            }
            $sidecar = [ordered] @{
                vm_name         = $vmName
                rendered_at     = (Get-Date).ToUniversalTime().ToString("o")
                manifest_sha256 = $sha
            }
            Set-Content -LiteralPath $sidePath -Value ($sidecar | ConvertTo-Json) -Encoding UTF8
        }

        $report += [pscustomobject] @{
            VMName   = $vmName
            IP       = $ip
            TfvarsPath = $tfvPath
            Status   = $status
        }
    }

    Write-Host ""
    Write-Host "Fleet render summary:" -ForegroundColor Cyan
    $report | Format-Table -AutoSize | Out-String | Write-Host

    # Show any sensitive keys as redacted for sanity
    Write-Verbose "Redacted view of first instance (sanity check):"
    if ($report.Count -gt 0 -and $VerbosePreference -eq 'Continue') {
        $firstInst = $manifest['instances'][0]
        $first = Merge-Instance -Shared $shared -Instance ([hashtable] $firstInst)
        foreach ($k in ($first.Keys | Sort-Object)) {
            Write-Verbose ("  {0} = {1}" -f $k, (Get-MaskedValue -Key $k -Value $first[$k]))
        }
    }
}

try {
    Invoke-Main
} catch {
    Write-Error $_
    exit 1
}
