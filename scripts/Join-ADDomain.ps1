<#
.SYNOPSIS
    Joins a deployed InsideLLM Ubuntu VM to an Active Directory domain and registers it in DNS.

.DESCRIPTION
    Post-deployment script for InsideLLM VMs that were deployed without AD domain join enabled.
    Connects via SSH, installs realmd/sssd/adcli, joins the domain, configures SSSD for
    short-name login, and registers A + PTR records in AD DNS.

    Requires: SSH access to the VM (key-based auth via the insidellm-admin user).

.PARAMETER VmIp
    IP address of the InsideLLM VM.

.PARAMETER Domain
    Active Directory domain to join (e.g., uniformedi.local).

.PARAMETER JoinUser
    AD username with permission to join computers (e.g., Administrator).

.PARAMETER JoinPassword
    Password for the AD join account.

.PARAMETER OuPath
    Optional OU for the computer account (e.g., "OU=Servers,DC=uniformedi,DC=local").

.PARAMETER SshUser
    SSH username on the VM (default: insidellm-admin).

.PARAMETER SshKeyPath
    Path to SSH private key (default: ~/.ssh/id_rsa).

.PARAMETER SkipDnsRegistration
    Skip DNS A and PTR record registration.

.PARAMETER Hostname
    Override the VM hostname for DNS registration. Defaults to the VM's current hostname.

.EXAMPLE
    .\Join-ADDomain.ps1 -VmIp 10.0.0.7 -Domain uniformedi.local -JoinUser Administrator -JoinPassword P@ssw0rd

.EXAMPLE
    .\Join-ADDomain.ps1 -VmIp 10.0.0.7 -Domain corp.local -JoinUser svc_domainjoin -JoinPassword Secret123 -OuPath "OU=AI Servers,DC=corp,DC=local"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$VmIp,
    [Parameter(Mandatory)][string]$Domain,
    [Parameter(Mandatory)][string]$JoinUser,
    [Parameter(Mandatory)][string]$JoinPassword,
    [string]$OuPath = "",
    [string]$SshUser = "insidellm-admin",
    [string]$SshKeyPath = "~/.ssh/id_rsa",
    [switch]$SkipDnsRegistration,
    [string]$Hostname = ""
)

$ErrorActionPreference = "Stop"

# Load defaults from terraform.tfvars if available
. "$PSScriptRoot\Read-TfVars.ps1"
$_tf = Read-TfVars
if ($_tf.Count -gt 0) {
    Write-Host "  [INFO] Loaded defaults from terraform.tfvars" -ForegroundColor DarkGray
    if (-not $PSBoundParameters.ContainsKey('VmIp') -and $_tf["vm_static_ip"])       { $VmIp = ($_tf["vm_static_ip"] -split '/')[0] }
    if (-not $PSBoundParameters.ContainsKey('Domain') -and $_tf["vm_domain"])        { $Domain = $_tf["vm_domain"] }
    if (-not $PSBoundParameters.ContainsKey('SshUser') -and $_tf["ssh_admin_user"])  { $SshUser = $_tf["ssh_admin_user"] }
    if (-not $PSBoundParameters.ContainsKey('Hostname') -and $_tf["vm_hostname"])    { $Hostname = $_tf["vm_hostname"] }
}

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

function Invoke-Ssh($command) {
    $resolvedKey = (Resolve-Path $SshKeyPath -ErrorAction SilentlyContinue).Path
    if (-not $resolvedKey) {
        throw "SSH key not found at $SshKeyPath"
    }
    $result = ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no -i $resolvedKey "${SshUser}@${VmIp}" $command 2>&1
    return $result
}

# ============================================================================
Write-Host ""
Write-Host "  InsideLLM - Active Directory Domain Join" -ForegroundColor Cyan
Write-Host "  VM: $VmIp | Domain: $Domain | User: $JoinUser" -ForegroundColor DarkGray
Write-Host ""

# ============================================================================
# Step 1: Test SSH connectivity
# ============================================================================
Write-Step "Testing SSH connectivity"

try {
    $hostCheck = Invoke-Ssh "hostname"
    $currentHostname = ($hostCheck | Select-Object -First 1).Trim()
    Write-Ok "Connected to $currentHostname ($VmIp)"
} catch {
    Write-Fail "Cannot SSH to ${SshUser}@${VmIp} - check the IP, username, and key path."
    Write-Host "  Key path: $SshKeyPath"
    exit 1
}

if (-not $Hostname) { $Hostname = $currentHostname }

# ============================================================================
# Step 2: Install AD packages
# ============================================================================
Write-Step "Installing Active Directory packages"

$installCmd = @"
sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq && \
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  realmd sssd sssd-tools adcli krb5-user samba-common-bin \
  packagekit libnss-sss libpam-sss dnsutils 2>&1 | tail -3
"@

$installResult = Invoke-Ssh $installCmd
Write-Ok "Packages installed"

# ============================================================================
# Step 3: Configure Kerberos
# ============================================================================
Write-Step "Configuring Kerberos"

$domainUpper = $Domain.ToUpper()

$krbCmd = @"
sudo tee /etc/krb5.conf > /dev/null << 'KRBEOF'
[libdefaults]
  default_realm = $domainUpper
  dns_lookup_realm = true
  dns_lookup_kdc = true
  ticket_lifetime = 24h
  renew_lifetime = 7d
  forwardable = true
  rdns = false

[realms]
  $domainUpper = {
    admin_server = $Domain
  }

[domain_realm]
  .$Domain = $domainUpper
  $Domain = $domainUpper
KRBEOF
echo "Kerberos configured for $domainUpper"
"@

$krbResult = Invoke-Ssh $krbCmd
Write-Ok "Kerberos realm: $domainUpper"

# ============================================================================
# Step 4: Discover domain
# ============================================================================
Write-Step "Discovering domain $Domain"

$discoverResult = Invoke-Ssh "sudo realm discover $Domain 2>&1"
if ($discoverResult -match "realm-name") {
    Write-Ok "Domain discovered successfully"
    $discoverResult | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
} else {
    Write-Warn "Domain discovery returned unexpected output:"
    $discoverResult | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "  This may be a DNS issue. Ensure the VM can resolve $Domain." -ForegroundColor Yellow
    Write-Host "  Check: ssh ${SshUser}@${VmIp} 'nslookup $Domain'" -ForegroundColor Yellow

    $continue = Read-Host "  Continue anyway? (y/N)"
    if ($continue -ne "y") { exit 1 }
}

# ============================================================================
# Step 5: Join the domain
# ============================================================================
Write-Step "Joining domain $Domain"

$ouArg = ""
if ($OuPath) { $ouArg = "--computer-ou=`"$OuPath`"" }

# Escape single quotes in password for bash
$escapedPass = $JoinPassword.Replace("'", "'\\''")

$joinCmd = "echo '$escapedPass' | sudo realm join --user=$JoinUser $ouArg $Domain 2>&1"
$joinResult = Invoke-Ssh $joinCmd

if ($LASTEXITCODE -eq 0 -and ($joinResult -notmatch "error|failed|denied")) {
    Write-Ok "Successfully joined $Domain"
} else {
    # Check if already joined
    $statusResult = Invoke-Ssh "sudo realm list 2>&1"
    if ($statusResult -match $Domain) {
        Write-Ok "Already joined to $Domain"
    } else {
        Write-Fail "Domain join failed:"
        $joinResult | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        exit 1
    }
}

# ============================================================================
# Step 6: Configure SSSD
# ============================================================================
Write-Step "Configuring SSSD"

$sssdCmd = @"
sudo sed -i 's/use_fully_qualified_names = True/use_fully_qualified_names = False/' /etc/sssd/sssd.conf 2>/dev/null
sudo sed -i 's|fallback_homedir = /home/%u@%d|fallback_homedir = /home/%u|' /etc/sssd/sssd.conf 2>/dev/null
sudo systemctl restart sssd 2>/dev/null
sudo realm permit --all 2>/dev/null
echo "SSSD configured"
"@

$sssdResult = Invoke-Ssh $sssdCmd
Write-Ok "SSSD configured - AD users can log in with short names"

# ============================================================================
# Step 7: Register in DNS
# ============================================================================
if (-not $SkipDnsRegistration) {
    Write-Step "Registering $Hostname.$Domain in AD DNS"

    $dnsCmd = @"
VM_IP=`$(hostname -I | awk '{print `$1}')
DNS_SERVER=`$(grep -m1 nameserver /etc/resolv.conf | awk '{print `$2}')

echo "VM IP: `$VM_IP"
echo "DNS Server: `$DNS_SERVER"
echo "Hostname: $Hostname.$Domain"

# Get Kerberos ticket
echo '$escapedPass' | kinit $JoinUser@$domainUpper 2>&1

# A record
sudo nsupdate -g << DNSEOF 2>&1
server `$DNS_SERVER
zone $Domain
update delete $Hostname.$Domain. A
update add $Hostname.$Domain. 3600 A `$VM_IP
send
DNSEOF

# PTR record
IP_REVERSE=`$(echo "`$VM_IP" | awk -F. '{print `$4"."`$3"."`$2"."`$1}')
sudo nsupdate -g << PTREOF 2>&1
server `$DNS_SERVER
update delete `$IP_REVERSE.in-addr.arpa. PTR
update add `$IP_REVERSE.in-addr.arpa. 3600 PTR $Hostname.$Domain.
send
PTREOF

kdestroy 2>/dev/null
echo "DNS registration complete"
"@

    $dnsResult = Invoke-Ssh $dnsCmd
    $dnsResult | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

    # Verify
    try {
        $resolved = Resolve-DnsName "$Hostname.$Domain" -ErrorAction SilentlyContinue
        if ($resolved) {
            Write-Ok "$Hostname.$Domain resolves to $($resolved.IPAddress)"
        } else {
            Write-Warn "DNS resolution not yet working - may take a few minutes to propagate"
        }
    } catch {
        Write-Warn "Could not verify DNS from this host - check with: nslookup $Hostname.$Domain"
    }
} else {
    Write-Host "`n  Skipping DNS registration (--SkipDnsRegistration)" -ForegroundColor DarkGray
}

# ============================================================================
# Summary
# ============================================================================
Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "  Domain Join Complete" -ForegroundColor Green
Write-Host "  ========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  VM:       $VmIp ($Hostname)" -ForegroundColor White
Write-Host "  Domain:   $Domain" -ForegroundColor White
Write-Host "  FQDN:     $Hostname.$Domain" -ForegroundColor White
if (-not $SkipDnsRegistration) {
    Write-Host "  DNS:      Registered (A + PTR)" -ForegroundColor White
}
Write-Host ""
Write-Host "  AD users can now connect via:" -ForegroundColor White
Write-Host "    SSH:  ssh username@$VmIp" -ForegroundColor Cyan
Write-Host "    SSH:  ssh username@$Hostname.$Domain" -ForegroundColor Cyan
Write-Host "    RDP:  $Hostname.$Domain:3389" -ForegroundColor Cyan
Write-Host ""
