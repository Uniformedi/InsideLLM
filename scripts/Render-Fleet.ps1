<#
.SYNOPSIS
    Renders fleet.yaml into per-VM terraform.tfvars files.

.DESCRIPTION
    Reads a fleet manifest (YAML) with `shared` + `instances` blocks, merges
    shared keys into each instance (instance wins), resolves env: references,
    and writes one terraform.tfvars per VM under -OutDir/<vm_name>/.

    Optional top-level blocks:
      - `edge:`         declares the front-door router topology (VIP, domain,
                        TLS source, VM IPs). Instances whose vm_static_ip
                        matches an entry in edge.vms get vm_role = "edge"
                        and the edge_* / fleet_virtual_ip vars propagated.
      - `departments:`  dept -> {backend, fallback} map. An instance whose
                        vm_name matches a department's backend gets
                        vm_role = "gateway" plus department + optional
                        fallback_department set automatically.

    Role inference rules (only applied when edge: or departments: is present):
      1. An instance with an explicit `vm_role` wins (never overridden).
      2. vm_static_ip in edge.vms      -> vm_role = "edge"
      3. vm_name in departments.*      -> vm_role = "gateway" + department
      4. First remaining instance that is not edge/workstation becomes
         `vm_role = "primary"` unless another primary is already declared.
      5. Every non-primary, non-edge instance gets `fleet_primary_host` set
         to the primary's static IP (CIDR stripped).

    Additionally writes `<OutDir>/_edge-routes.json` - the department ->
    backend-IP map in the shape that Stream C's edge routes.json.tpl expects.

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
    [void] $sb.AppendLine("# Rendered by Render-Fleet.ps1 - do not edit by hand")
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
# Helpers for edge / department inference
# ---------------------------------------------------------------------------
function Get-IpWithoutCidr {
    param([string] $Value)
    if ([string]::IsNullOrEmpty($Value)) { return '' }
    $idx = $Value.IndexOf('/')
    if ($idx -ge 0) { return $Value.Substring(0, $idx) }
    return $Value
}

function Test-InstanceIsEdge {
    param([string] $StaticIp, $EdgeVmList)
    if (-not $EdgeVmList) { return $false }
    $ip = Get-IpWithoutCidr -Value $StaticIp
    if (-not $ip) { return $false }
    foreach ($candidate in $EdgeVmList) {
        if ((Get-IpWithoutCidr -Value ([string] $candidate)) -eq $ip) { return $true }
    }
    return $false
}

function Get-DepartmentForVm {
    param([string] $VmName, $Departments)
    if (-not $Departments) { return $null }
    foreach ($dept in $Departments.Keys) {
        $entry = $Departments[$dept]
        if ($entry -and $entry.ContainsKey('backend') -and ([string] $entry['backend']) -eq $VmName) {
            return $dept
        }
    }
    return $null
}

function Test-FleetHasTopology {
    param($Manifest)
    if ($Manifest.ContainsKey('edge') -and $Manifest['edge']) { return $true }
    if ($Manifest.ContainsKey('departments') -and $Manifest['departments']) { return $true }
    return $false
}

# ---------------------------------------------------------------------------
# Validation: edge + departments blocks
# ---------------------------------------------------------------------------
function Test-TopologyValid {
    param($Manifest)

    # departments -> backend names must exist in instances
    if ($Manifest.ContainsKey('departments') -and $Manifest['departments']) {
        $vmNames = @()
        foreach ($inst in $Manifest['instances']) {
            if ($inst.ContainsKey('vm_name')) { $vmNames += [string] $inst['vm_name'] }
        }
        foreach ($dept in $Manifest['departments'].Keys) {
            $entry = $Manifest['departments'][$dept]
            if (-not $entry -or -not $entry.ContainsKey('backend')) {
                throw "departments.$dept is missing required 'backend' key."
            }
            $backend = [string] $entry['backend']
            if ($vmNames -notcontains $backend) {
                throw "departments.$dept.backend '$backend' does not match any vm_name in instances: ($($vmNames -join ', '))"
            }
            if ($entry.ContainsKey('fallback') -and $entry['fallback']) {
                $fb = [string] $entry['fallback']
                # fallback refers to another department's backend vm_name (loose check: must be a known vm_name)
                if ($vmNames -notcontains $fb) {
                    throw "departments.$dept.fallback '$fb' does not match any vm_name in instances."
                }
            }
        }
    }

    # edge block validation
    if ($Manifest.ContainsKey('edge') -and $Manifest['edge']) {
        $edge = $Manifest['edge']
        if (-not $edge.ContainsKey('vms') -or -not $edge['vms']) {
            throw "edge.vms must be a non-empty list of IP addresses."
        }
        if (-not ($edge['vms'] -is [System.Collections.IList]) -or $edge['vms'].Count -eq 0) {
            throw "edge.vms must be a non-empty list of IP addresses."
        }
        if (-not $edge.ContainsKey('domain') -or -not $edge['domain']) {
            throw "edge.domain is required when edge: block is present."
        }
        if ($edge.ContainsKey('tls_source')) {
            $tls = [string] $edge['tls_source']
            if ($tls -notin @('self-signed', 'letsencrypt', 'custom')) {
                throw "edge.tls_source must be one of: self-signed, letsencrypt, custom (got '$tls')."
            }
            if ($tls -eq 'custom') {
                if (-not $edge.ContainsKey('tls_cert_path') -or -not $edge['tls_cert_path']) {
                    throw "edge.tls_cert_path is required when edge.tls_source = custom."
                }
                if (-not $edge.ContainsKey('tls_key_path') -or -not $edge['tls_key_path']) {
                    throw "edge.tls_key_path is required when edge.tls_source = custom."
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Role inference pass (mutates a copy of each instance hashtable)
# ---------------------------------------------------------------------------
function Add-RoleMetadata {
    param(
        [hashtable] $Instance,
        [hashtable] $RoleMap
    )
    $vmName = [string] $Instance['vm_name']
    if ($RoleMap.ContainsKey($vmName)) {
        $meta = $RoleMap[$vmName]
        foreach ($k in $meta.Keys) {
            # Never override explicit instance-level values
            if (-not $Instance.ContainsKey($k) -or [string]::IsNullOrEmpty([string] $Instance[$k])) {
                $Instance[$k] = $meta[$k]
            }
        }
    }
    return $Instance
}

function New-RoleMap {
    param(
        $Manifest
    )
    $map = @{}
    if (-not (Test-FleetHasTopology -Manifest $Manifest)) { return $map }

    $edgeVms     = if ($Manifest.ContainsKey('edge') -and $Manifest['edge']) { $Manifest['edge']['vms'] } else { @() }
    $departments = if ($Manifest.ContainsKey('departments')) { $Manifest['departments'] } else { $null }

    $edgeDomain  = ''
    $edgeVip     = ''
    $edgeTls     = 'self-signed'
    $edgeCert    = ''
    $edgeKey     = ''
    if ($Manifest.ContainsKey('edge') -and $Manifest['edge']) {
        $edge = $Manifest['edge']
        if ($edge.ContainsKey('domain'))        { $edgeDomain = [string] $edge['domain'] }
        if ($edge.ContainsKey('vip'))           { $edgeVip    = [string] $edge['vip']    }
        if ($edge.ContainsKey('tls_source'))    { $edgeTls    = [string] $edge['tls_source'] }
        if ($edge.ContainsKey('tls_cert_path')) { $edgeCert   = [string] $edge['tls_cert_path'] }
        if ($edge.ContainsKey('tls_key_path'))  { $edgeKey    = [string] $edge['tls_key_path']  }
    }

    # Pass 1: edge + gateway inference
    $primaryCandidate = $null
    $explicitPrimary  = $null
    foreach ($inst in $Manifest['instances']) {
        $vmName = [string] $inst['vm_name']
        if (-not $vmName) { continue }

        $staticIp = if ($inst.ContainsKey('vm_static_ip')) { [string] $inst['vm_static_ip'] } else { '' }
        $explicitRole = if ($inst.ContainsKey('vm_role')) { [string] $inst['vm_role'] } else { '' }

        $meta = @{}

        if ($explicitRole) {
            # Explicit role wins; still propagate edge_* for edge, department for gateway
            $meta['vm_role'] = $explicitRole
            if ($explicitRole -eq 'primary' -and -not $explicitPrimary) { $explicitPrimary = $staticIp }
        }
        elseif (Test-InstanceIsEdge -StaticIp $staticIp -EdgeVmList $edgeVms) {
            $meta['vm_role'] = 'edge'
        }
        else {
            $dept = Get-DepartmentForVm -VmName $vmName -Departments $departments
            if ($dept) {
                $meta['vm_role']   = 'gateway'
                $meta['department'] = [string] $dept
                if ($departments[$dept].ContainsKey('fallback') -and $departments[$dept]['fallback']) {
                    $meta['fallback_department'] = [string] $departments[$dept]['fallback']
                }
            }
        }

        # Edge-specific propagation (for anything rolled up to edge)
        $effectiveRole = if ($meta.ContainsKey('vm_role')) { $meta['vm_role'] } else { '' }
        if ($effectiveRole -eq 'edge') {
            if ($edgeDomain) { $meta['edge_domain']     = $edgeDomain }
            if ($edgeVip)    { $meta['fleet_virtual_ip'] = $edgeVip    }
            $meta['edge_tls_source'] = $edgeTls
            if ($edgeCert) { $meta['edge_tls_cert_path'] = $edgeCert }
            if ($edgeKey)  { $meta['edge_tls_key_path']  = $edgeKey  }
        }

        # Gateway-role propagation: even if explicit, stamp department when matched
        if ($effectiveRole -eq 'gateway' -and -not $meta.ContainsKey('department')) {
            $dept = Get-DepartmentForVm -VmName $vmName -Departments $departments
            if ($dept) {
                $meta['department'] = [string] $dept
                if ($departments[$dept].ContainsKey('fallback') -and $departments[$dept]['fallback']) {
                    $meta['fallback_department'] = [string] $departments[$dept]['fallback']
                }
            }
        }

        $map[$vmName] = $meta

        # Track primary candidate: first instance that is neither edge nor workstation nor gateway and has no explicit role
        $isEdge       = ($effectiveRole -eq 'edge')
        $isWorkstn    = ($effectiveRole -eq 'workstation')
        $isExplicit   = [bool] $explicitRole
        if (-not $isEdge -and -not $isWorkstn -and -not $isExplicit -and -not $primaryCandidate) {
            $primaryCandidate = [pscustomobject] @{ VmName = $vmName; Ip = $staticIp }
        }
    }

    # Pass 2: ensure a primary exists
    $primaryIp = $explicitPrimary
    if (-not $primaryIp) {
        if ($primaryCandidate) {
            # Promote candidate to primary (only if not already mapped with a non-empty role)
            if (-not $map[$primaryCandidate.VmName].ContainsKey('vm_role') -or
                -not $map[$primaryCandidate.VmName]['vm_role']) {
                $map[$primaryCandidate.VmName]['vm_role'] = 'primary'
            }
            $primaryIp = $primaryCandidate.Ip
        }
    }

    # Pass 3: stamp fleet_primary_host on every non-primary instance
    if ($primaryIp) {
        $primaryHost = Get-IpWithoutCidr -Value $primaryIp
        $vmNames = @($map.Keys)
        foreach ($vmName in $vmNames) {
            $role = if ($map[$vmName].ContainsKey('vm_role')) { $map[$vmName]['vm_role'] } else { '' }
            if ($role -ne 'primary') {
                $map[$vmName]['fleet_primary_host'] = $primaryHost
            }
        }
    }

    return $map
}

# ---------------------------------------------------------------------------
# Edge routes map writer (used by Stream C's routes.json.tpl)
# ---------------------------------------------------------------------------
function Write-EdgeRoutesJson {
    param(
        $Manifest,
        [string] $OutPath,
        [hashtable] $InstanceIpByName
    )
    if (-not $Manifest.ContainsKey('departments') -or -not $Manifest['departments']) { return }

    $routes = [ordered] @{}
    foreach ($dept in ($Manifest['departments'].Keys | Sort-Object)) {
        $entry = $Manifest['departments'][$dept]
        $backendName = [string] $entry['backend']
        $backendIp   = if ($InstanceIpByName.ContainsKey($backendName)) { $InstanceIpByName[$backendName] } else { '' }
        $fallbackName = if ($entry.ContainsKey('fallback')) { [string] $entry['fallback'] } else { '' }
        $fallbackIp   = if ($fallbackName -and $InstanceIpByName.ContainsKey($fallbackName)) { $InstanceIpByName[$fallbackName] } else { '' }
        $routes[$dept] = [ordered] @{
            backend          = $backendName
            backend_ip       = $backendIp
            fallback         = $fallbackName
            fallback_ip      = $fallbackIp
        }
    }

    $edgeBlock = [ordered] @{}
    if ($Manifest.ContainsKey('edge') -and $Manifest['edge']) {
        $edge = $Manifest['edge']
        if ($edge.ContainsKey('domain'))     { $edgeBlock['domain']     = [string] $edge['domain'] }
        if ($edge.ContainsKey('vip'))        { $edgeBlock['vip']        = [string] $edge['vip'] }
        if ($edge.ContainsKey('tls_source')) { $edgeBlock['tls_source'] = [string] $edge['tls_source'] }
        if ($edge.ContainsKey('vms')) {
            $edgeBlock['vms'] = @(foreach ($v in $edge['vms']) { Get-IpWithoutCidr -Value ([string] $v) })
        }
    }

    $payload = [ordered] @{
        edge        = $edgeBlock
        departments = $routes
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $json = $payload | ConvertTo-Json -Depth 6
    if ($PSCmdlet.ShouldProcess($OutPath, "Write edge routes JSON")) {
        Set-Content -LiteralPath $OutPath -Value $json -Encoding UTF8
    }
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

    # Validate edge / departments before any rendering (fail fast)
    Test-TopologyValid -Manifest $manifest

    # Build the role inference map once (keyed by vm_name)
    $roleMap = New-RoleMap -Manifest $manifest

    # Manifest hash for sidecar staleness detection
    $sha = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash

    if (-not (Test-Path -LiteralPath $OutDir)) {
        if ($PSCmdlet.ShouldProcess($OutDir, "Create output directory")) {
            New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
        }
    }

    $report = @()
    $ipByName = @{}  # vm_name -> IP (sans CIDR), used for edge routes JSON

    foreach ($inst in $manifest['instances']) {
        $instHash = @{}
        foreach ($k in $inst.Keys) { $instHash[$k] = $inst[$k] }

        if (-not $instHash.ContainsKey('vm_name')) {
            throw "Instance is missing required 'vm_name': $($instHash | ConvertTo-Json -Compress)"
        }
        $vmName = [string] $instHash['vm_name']

        # Apply role metadata (does not override explicit values)
        $instHash = Add-RoleMetadata -Instance $instHash -RoleMap $roleMap

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
        $ipByName[$vmName] = Get-IpWithoutCidr -Value $ip
        $role = if ($merged.ContainsKey('vm_role')) { [string] $merged['vm_role'] } else { '' }
        $dept = if ($merged.ContainsKey('department')) { [string] $merged['department'] } else { '' }

        if ($PSCmdlet.ShouldProcess($tfvPath, "Write tfvars ($status)")) {
            if (-not (Test-Path -LiteralPath $vmDir)) {
                New-Item -ItemType Directory -Path $vmDir -Force | Out-Null
            }
            if ($status -ne 'unchanged') {
                Set-Content -LiteralPath $tfvPath -Value $tfvars -NoNewline -Encoding UTF8
            }
            $sidecar = [ordered] @{
                vm_name         = $vmName
                vm_role         = $role
                department      = $dept
                rendered_at     = (Get-Date).ToUniversalTime().ToString("o")
                manifest_sha256 = $sha
            }
            Set-Content -LiteralPath $sidePath -Value ($sidecar | ConvertTo-Json) -Encoding UTF8
        }

        $report += [pscustomobject] @{
            VMName     = $vmName
            Role       = $role
            Department = $dept
            IP         = $ip
            TfvarsPath = $tfvPath
            Status     = $status
        }
    }

    # Emit edge-routes.json (only when departments: is present)
    if ($manifest.ContainsKey('departments') -and $manifest['departments']) {
        $routesPath = Join-Path $OutDir '_edge-routes.json'
        Write-EdgeRoutesJson -Manifest $manifest -OutPath $routesPath -InstanceIpByName $ipByName
        Write-Host "Wrote edge routes map: $routesPath" -ForegroundColor DarkCyan
    }

    Write-Host ""
    Write-Host "Fleet render summary:" -ForegroundColor Cyan
    $report | Format-Table VMName, Role, Department, IP, Status, TfvarsPath -AutoSize | Out-String | Write-Host

    # Show any sensitive keys as redacted for sanity
    Write-Verbose "Redacted view of first instance (sanity check):"
    if ($report.Count -gt 0 -and $VerbosePreference -eq 'Continue') {
        $firstInst = $manifest['instances'][0]
        $firstHash = @{}
        foreach ($k in $firstInst.Keys) { $firstHash[$k] = $firstInst[$k] }
        $firstHash = Add-RoleMetadata -Instance $firstHash -RoleMap $roleMap
        $first = Merge-Instance -Shared $shared -Instance $firstHash
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
