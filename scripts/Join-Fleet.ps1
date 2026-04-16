<#
.SYNOPSIS
    Bootstraps a new VM into an existing InsideLLM fleet.

.DESCRIPTION
    Consumes a registration token (generated via
    POST /governance/api/v1/fleet/registration-token on the fleet primary)
    and writes a rendered terraform.tfvars ready to be applied.

    Flow:
      1. POST token + local instance_id to the primary's /register endpoint.
      2. Decrypt fleet DB credentials returned by the server (XOR/SHA256
         scheme matches registration_service.py).
      3. Write ./fleet-out/<VmName>/terraform.tfvars with vm_name, vm_role,
         department, fleet_primary_host, and the fleet DB connection info.
      4. Append an `instances:` entry to the local fleet.yaml (if present
         and the entry does not already exist) for record-keeping.
      5. Print next-step apply commands.

    Note: Only the minimal bootstrap returned by the server is written. The
    operator still needs to set Hyper-V credentials (env vars) and any
    provider API keys before running `terraform apply`. If the server's
    bootstrap response is missing fields, the script prints a clear TODO
    and exits without writing incomplete tfvars.

.PARAMETER Leader
    IP or hostname of the fleet primary (serves /governance/api/v1/fleet/*).

.PARAMETER Token
    Single-use registration token from the primary's registration-token
    endpoint.

.PARAMETER Role
    Role of this new VM in the fleet.
    One of: gateway | workstation | voice | edge | storage

.PARAMETER Department
    Optional department tag for gateway roles (must match an IdP claim).

.PARAMETER VmName
    Hostname / directory name for this VM. Defaults to $env:COMPUTERNAME.

.PARAMETER StaticIp
    Optional CIDR static IP (e.g. 10.0.0.123/24). If empty, DHCP is assumed.

.PARAMETER LeaderPort
    Port the primary's governance hub listens on. Default 443.

.PARAMETER Insecure
    Skip TLS verification (self-signed fleet). Default false.

.PARAMETER ManifestPath
    Path to fleet.yaml. Defaults to ./fleet.yaml (used only for local append).

.PARAMETER OutDir
    Output directory for the rendered tfvars. Defaults to ./fleet-out.

.EXAMPLE
    pwsh ./scripts/Join-Fleet.ps1 `
        -Leader 10.0.0.110 `
        -Token reg-xxxxxxxxxxxxxxxx `
        -Role gateway `
        -Department engineering `
        -VmName insidellm-eng2 `
        -StaticIp 10.0.0.127/24 `
        -Insecure
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)] [string] $Leader,
    [Parameter(Mandatory = $true)] [string] $Token,
    [Parameter(Mandatory = $true)]
    [ValidateSet('gateway', 'workstation', 'voice', 'edge', 'storage')]
    [string] $Role,

    [string] $Department   = "",
    [string] $VmName       = $env:COMPUTERNAME,
    [string] $StaticIp     = "",
    [int]    $LeaderPort   = 443,
    [switch] $Insecure,
    [string] $ManifestPath = "./fleet.yaml",
    [string] $OutDir       = "./fleet-out"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Token-based decryption (mirrors registration_service._encrypt_with_token)
# ---------------------------------------------------------------------------
function Unprotect-WithToken {
    param(
        [Parameter(Mandatory = $true)] [string] $EncryptedBase64,
        [Parameter(Mandatory = $true)] [string] $Token
    )
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $key = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Token))
    } finally {
        $sha.Dispose()
    }
    $encrypted = [Convert]::FromBase64String($EncryptedBase64)
    $out = [byte[]]::new($encrypted.Length)
    for ($i = 0; $i -lt $encrypted.Length; $i++) {
        $out[$i] = $encrypted[$i] -bxor $key[$i % $key.Length]
    }
    return [System.Text.Encoding]::UTF8.GetString($out)
}

# ---------------------------------------------------------------------------
# HTTP: POST /register
# ---------------------------------------------------------------------------
function Invoke-FleetRegister {
    param(
        [string] $Leader,
        [int]    $Port,
        [string] $Token,
        [string] $InstanceId,
        [string] $InstanceName,
        [switch] $Insecure
    )
    $url = "https://{0}:{1}/governance/api/v1/fleet/register" -f $Leader, $Port
    $body   = @{
        token         = $Token
        instance_id   = $InstanceId
        instance_name = $InstanceName
    } | ConvertTo-Json -Compress

    $params = @{
        Uri         = $url
        Method      = 'POST'
        Body        = $body
        ContentType = 'application/json'
        ErrorAction = 'Stop'
    }
    if ($Insecure) { $params['SkipCertificateCheck'] = $true }

    try {
        $resp = Invoke-RestMethod @params
    } catch {
        throw "POST $url failed: $($_.Exception.Message)"
    }
    if (-not $resp) { throw "Empty response from $url" }
    $hasSuccess = ($resp.PSObject.Properties.Name -contains 'success')
    if (-not $hasSuccess -or -not $resp.success) {
        $detail = if ($resp.PSObject.Properties.Name -contains 'message') { $resp.message } else { ($resp | ConvertTo-Json -Compress) }
        throw "Registration failed: $detail"
    }
    return $resp
}

# ---------------------------------------------------------------------------
# tfvars writer
# ---------------------------------------------------------------------------
function ConvertTo-HclValue {
    param($Value)
    if ($null -eq $Value) { return '""' }
    if ($Value -is [bool])   { return ($Value ? 'true' : 'false') }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double]) { return [string] $Value }
    $s = [string] $Value
    $s = $s -replace '\\', '\\\\'
    $s = $s -replace '"', '\"'
    return '"' + $s + '"'
}

function Write-BootstrapTfvars {
    param(
        [string] $Path,
        [hashtable] $Data
    )
    $sb = [System.Text.StringBuilder]::new()
    [void] $sb.AppendLine("# Rendered by Join-Fleet.ps1 - do not edit by hand")
    [void] $sb.AppendLine("# Fleet-bootstrap tfvars for $($Data['vm_name'])")
    [void] $sb.AppendLine("")
    foreach ($k in ($Data.Keys | Sort-Object)) {
        $v = ConvertTo-HclValue $Data[$k]
        [void] $sb.AppendLine("$k = $v")
    }
    Set-Content -LiteralPath $Path -Value $sb.ToString() -NoNewline -Encoding UTF8
}

# ---------------------------------------------------------------------------
# fleet.yaml appender
# ---------------------------------------------------------------------------
function Add-ToLocalManifest {
    param(
        [string] $ManifestPath,
        [string] $VmName,
        [string] $StaticIp,
        [string] $Role,
        [string] $Department
    )
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        Write-Host "No local fleet.yaml at $ManifestPath; skipping append." -ForegroundColor DarkYellow
        return
    }
    $text = Get-Content -LiteralPath $ManifestPath -Raw
    # Idempotence: vm_name already present?
    if ($text -match ('(?m)^\s*-?\s*vm_name:\s*"?' + [Regex]::Escape($VmName) + '"?\s*$')) {
        Write-Host "fleet.yaml already contains vm_name '$VmName'; skipping append." -ForegroundColor DarkYellow
        return
    }

    $block = @()
    $block += ""
    $block += "  # --- Added by Join-Fleet.ps1 at $([DateTime]::UtcNow.ToString('o')) ---"
    $block += "  - vm_name:      `"$VmName`""
    $block += "    vm_hostname:  `"$VmName`""
    if ($StaticIp)   { $block += "    vm_static_ip: `"$StaticIp`"" }
    if ($Role)       { $block += "    vm_role:      `"$Role`"" }
    if ($Department) { $block += "    department:   `"$Department`"" }

    $append = ($block -join [Environment]::NewLine) + [Environment]::NewLine
    if ($PSCmdlet.ShouldProcess($ManifestPath, "Append instance block for $VmName")) {
        Add-Content -LiteralPath $ManifestPath -Value $append -Encoding UTF8
        Write-Host "Appended instance entry to $ManifestPath" -ForegroundColor Green
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
function Invoke-Main {
    # Pre-flight
    if (-not $VmName) {
        throw "VmName is empty and `$env:COMPUTERNAME is unset. Pass -VmName explicitly."
    }
    $instanceId = [guid]::NewGuid().ToString()

    $leaderUrl = "https://{0}:{1}" -f $Leader, $LeaderPort
    Write-Host "Registering '$VmName' (role=$Role) with leader $leaderUrl" -ForegroundColor Cyan
    $resp = Invoke-FleetRegister `
        -Leader $Leader -Port $LeaderPort `
        -Token $Token -InstanceId $instanceId -InstanceName $VmName `
        -Insecure:$Insecure

    # Feature-gate: if the server did not return the expected bootstrap
    # payload (e.g., a build that predates Stream A tfvars_vault), bail early.
    $hasFleetDb = ($resp.PSObject.Properties.Name -contains 'fleet_db') -and $resp.fleet_db
    if (-not $hasFleetDb) {
        Write-Host ""
        Write-Host "TODO: fleet primary returned a registration response without a fleet_db" -ForegroundColor Yellow
        Write-Host "      block. Stream A's tfvars_vault bootstrap endpoint appears to be"      -ForegroundColor Yellow
        Write-Host "      unavailable on this build. Re-run Join-Fleet.ps1 once the leader"     -ForegroundColor Yellow
        Write-Host "      exposes encrypted bootstrap config, or fill terraform.tfvars by hand." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "      Minimum response shape expected:"                                      -ForegroundColor Yellow
        Write-Host "        { success: true, fleet_db: { db_type, host, port, db_name, username, password_encrypted }, hub_secret }" -ForegroundColor Yellow
        exit 3
    }

    $fleetDb = $resp.fleet_db
    foreach ($k in 'db_type','host','port','db_name','username','password_encrypted') {
        if (-not ($fleetDb.PSObject.Properties.Name -contains $k)) {
            throw "fleet_db response missing required field '$k'"
        }
    }

    # Decrypt password
    $dbPassword = Unprotect-WithToken -EncryptedBase64 $fleetDb.password_encrypted -Token $Token

    # Assemble minimal tfvars bootstrap
    $primaryHost = $Leader
    $data = @{
        vm_name             = $VmName
        vm_hostname         = $VmName
        vm_role             = $Role
        fleet_primary_host  = $primaryHost
        governance_hub_central_db_type     = [string] $fleetDb.db_type
        governance_hub_central_db_host     = [string] $fleetDb.host
        governance_hub_central_db_port     = [int]    $fleetDb.port
        governance_hub_central_db_name     = [string] $fleetDb.db_name
        governance_hub_central_db_user     = [string] $fleetDb.username
        governance_hub_central_db_password = $dbPassword
    }
    if ($StaticIp)   { $data['vm_static_ip'] = $StaticIp }
    if ($Department) { $data['department']   = $Department }

    # Paths
    $vmDir = Join-Path $OutDir $VmName
    if (-not (Test-Path -LiteralPath $vmDir)) {
        if ($PSCmdlet.ShouldProcess($vmDir, "Create VM output directory")) {
            New-Item -ItemType Directory -Path $vmDir -Force | Out-Null
        }
    }
    $tfvPath = Join-Path $vmDir 'terraform.tfvars'
    if ($PSCmdlet.ShouldProcess($tfvPath, "Write bootstrap tfvars")) {
        Write-BootstrapTfvars -Path $tfvPath -Data $data
        Write-Host "Wrote bootstrap tfvars: $tfvPath" -ForegroundColor Green
    }

    # Sidecar so Render-Fleet re-runs can detect this join
    $sidecar = [ordered] @{
        vm_name        = $VmName
        vm_role        = $Role
        department     = $Department
        joined_at      = (Get-Date).ToUniversalTime().ToString("o")
        leader         = $Leader
        source         = "Join-Fleet.ps1"
    }
    $sidePath = Join-Path $vmDir '.terraform-fleet.json'
    if ($PSCmdlet.ShouldProcess($sidePath, "Write join sidecar")) {
        Set-Content -LiteralPath $sidePath -Value ($sidecar | ConvertTo-Json) -Encoding UTF8
    }

    # Append to local manifest (best-effort)
    Add-ToLocalManifest -ManifestPath $ManifestPath -VmName $VmName `
        -StaticIp $StaticIp -Role $Role -Department $Department

    # Next steps
    Write-Host ""
    Write-Host "Join complete. Next steps:" -ForegroundColor Cyan
    Write-Host "  cd `"$vmDir`"" -ForegroundColor White
    Write-Host "  terraform -chdir=`"$((Resolve-Path ./terraform).Path)`" init" -ForegroundColor White
    Write-Host "  terraform -chdir=`"$((Resolve-Path ./terraform).Path)`" apply -var-file=`"$tfvPath`" -state=`"$(Join-Path $vmDir 'terraform.tfstate')`"" -ForegroundColor White
    Write-Host ""
    Write-Host "Note: You must also export Hyper-V / provider secrets in the environment" -ForegroundColor DarkYellow
    Write-Host "      before terraform apply (FLEET_HYPERV_PASSWORD, FLEET_ANTHROPIC_KEY, etc.)." -ForegroundColor DarkYellow
}

try {
    Invoke-Main
} catch {
    Write-Error $_
    exit 1
}
