<#
.SYNOPSIS
    Builds the InsideLLM gold-image VHDX from an official Debian cloud image.

.DESCRIPTION
    Downloads the Debian generic-cloud qcow2, verifies its published SHA512,
    converts to dynamic-subformat VHDX, and places it at the canonical path
    referenced by fleet.yaml's `base_vhdx_source`.

    Why the cloud image (not netinst):
      The platform's terraform/main.tf null_resource.prepare_vm_disk expects
      a cloud-init-ready VHDX to clone + resize for each fleet VM. The
      generic-cloud variant is exactly that: a small (~2 GB), pre-partitioned
      Debian image with cloud-init pre-installed and configured to read its
      datasource from the cloud-init ISO that Terraform attaches at deploy
      time.

      A netinst ISO is interactive installation media — it cannot serve as
      `base_vhdx_source` without first booting it manually, walking through
      the installer, installing cloud-init, and generalizing. This script
      skips all of that by using the official cloud-image artifact.

    The script is idempotent: re-running with the same DistroVersion is a
    no-op unless -Force is passed.

.PARAMETER DistroVersion
    Debian major version. 13 (Trixie) is current stable as of 2025-08-09;
    12 (Bookworm) hits end-of-full-support on 2026-06-10. Default: 13.

.PARAMETER OutDir
    Where to place the gold VHDX. Default: C:\HyperV\Images

.PARAMETER Force
    Re-download + re-convert even if the target VHDX already exists.

.EXAMPLE
    pwsh ./scripts/Build-GoldImage.ps1
    # Builds Debian 13 gold image at C:\HyperV\Images\debian-13-genericcloud-amd64.vhdx

.EXAMPLE
    pwsh ./scripts/Build-GoldImage.ps1 -DistroVersion 12 -Force
    # Rebuilds Debian 12 Bookworm gold image (still supported on LTS until 2028).
#>
[CmdletBinding()]
param(
    [ValidateSet(12, 13)]
    [int]    $DistroVersion = 13,
    [string] $OutDir        = "C:\HyperV\Images",
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# --- Distro metadata --------------------------------------------------------
$codename = switch ($DistroVersion) {
    12 { 'bookworm' }
    13 { 'trixie' }
}

$qcowName = "debian-$DistroVersion-genericcloud-amd64.qcow2"
$vhdxName = "debian-$DistroVersion-genericcloud-amd64.vhdx"
$baseUrl  = "https://cloud.debian.org/images/cloud/$codename/latest"
$qcowUrl  = "$baseUrl/$qcowName"
$shaUrl   = "$baseUrl/SHA512SUMS"

$qcowPath = Join-Path $OutDir $qcowName
$vhdxPath = Join-Path $OutDir $vhdxName

Write-Host ""
Write-Host "=== InsideLLM Gold Image Builder ===" -ForegroundColor Cyan
Write-Host "Distro    : Debian $DistroVersion ($codename)"
Write-Host "Source    : $qcowUrl"
Write-Host "Target    : $vhdxPath"
Write-Host ""

# --- Idempotency check ------------------------------------------------------
if ((Test-Path $vhdxPath) -and -not $Force) {
    $size = [math]::Round((Get-Item $vhdxPath).Length / 1GB, 2)
    Write-Host "Gold image already present: $vhdxPath ($size GB)" -ForegroundColor Yellow
    Write-Host "Pass -Force to rebuild from a fresh download." -ForegroundColor Yellow
    return
}

# --- Output dir -------------------------------------------------------------
if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    Write-Host "Created $OutDir"
}

# --- Prereq: qemu-img -------------------------------------------------------
if (-not (Get-Command qemu-img -ErrorAction SilentlyContinue)) {
    Write-Host "qemu-img not on PATH; installing..." -ForegroundColor Yellow
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        Write-Host "  Installing Chocolatey first..."
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = `
            [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
        Invoke-Expression ((New-Object System.Net.WebClient).DownloadString(
            'https://community.chocolatey.org/install.ps1'))
    }
    choco install qemu -y --no-progress | Out-Null
    if (Test-Path "C:\Program Files\qemu") {
        $env:Path += ";C:\Program Files\qemu"
    }
    if (-not (Get-Command qemu-img -ErrorAction SilentlyContinue)) {
        throw "qemu-img still not on PATH after install. Open a new shell and re-run, or install qemu manually from https://qemu.weilnetz.de/w64/"
    }
}

# --- Prereq: Hyper-V (warn only) --------------------------------------------
$hv = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V `
    -ErrorAction SilentlyContinue
if (-not $hv -or $hv.State -ne 'Enabled') {
    Write-Host "  WARNING: Hyper-V is not enabled on this host. The gold image" -ForegroundColor Yellow
    Write-Host "  will still build, but Deploy-Fleet.ps1 won't work without it." -ForegroundColor Yellow
}

# --- Download qcow2 ---------------------------------------------------------
if ((Test-Path $qcowPath) -and -not $Force) {
    Write-Host "qcow2 already downloaded: $qcowPath"
} else {
    Write-Host "Downloading $qcowName ..."
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $qcowUrl -OutFile $qcowPath -UseBasicParsing
    $sizeMB = [math]::Round((Get-Item $qcowPath).Length / 1MB, 1)
    Write-Host "  -> $sizeMB MB"
}

# --- Verify SHA512 against published manifest -------------------------------
Write-Host "Verifying SHA512 against $shaUrl ..."
$shaTmp = Join-Path $env:TEMP "debian-cloud-sha512sums-$DistroVersion.txt"
Invoke-WebRequest -Uri $shaUrl -OutFile $shaTmp -UseBasicParsing
$expectedLine = Select-String -Path $shaTmp -Pattern ([regex]::Escape($qcowName)) `
    | Select-Object -First 1
if (-not $expectedLine) {
    throw "Could not find $qcowName in published SHA512SUMS"
}
$expected = ($expectedLine.Line -split '\s+')[0].ToLower()
$actual   = (Get-FileHash -Algorithm SHA512 -Path $qcowPath).Hash.ToLower()
if ($actual -ne $expected) {
    throw @"
SHA512 mismatch on $qcowPath
  Expected: $expected
  Actual  : $actual

Re-run with -Force to redownload, or remove the file manually and try again.
"@
}
Write-Host "  OK ($($actual.Substring(0,16))...)" -ForegroundColor Green

# --- Convert qcow2 -> dynamic VHDX ------------------------------------------
Write-Host "Converting qcow2 -> vhdx (dynamic subformat) ..."
& qemu-img convert -p -f qcow2 -O vhdx -o subformat=dynamic $qcowPath $vhdxPath
if ($LASTEXITCODE -ne 0) {
    throw "qemu-img convert failed (exit code $LASTEXITCODE)"
}

# --- Done -------------------------------------------------------------------
$result = Get-Item $vhdxPath
$sizeGB = [math]::Round($result.Length / 1GB, 2)
Write-Host ""
Write-Host "=== Gold image ready ===" -ForegroundColor Green
Write-Host "  Path  : $($result.FullName)"
Write-Host "  Size  : $sizeGB GB (dynamic; expands to vm_disk_size_bytes per-VM at deploy)"
Write-Host "  Distro: Debian $DistroVersion ($codename)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Verify fleet.yaml's base_vhdx_source points at this path"
Write-Host "  2. Re-render fleet.yaml -> per-VM tfvars:"
Write-Host "       pwsh ./scripts/Render-Fleet.ps1"
Write-Host "  3. Dry-run the deploy:"
Write-Host "       pwsh ./scripts/Deploy-Fleet.ps1 -DryRun"
Write-Host "  4. If plan looks right, apply:"
Write-Host "       pwsh ./scripts/Deploy-Fleet.ps1"
Write-Host ""
Write-Host "Note: the source qcow2 is kept at $qcowPath for re-runs without"
Write-Host "      re-downloading. Safe to delete if you want to reclaim ~400 MB."
Write-Host ""
