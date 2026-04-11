<#
.SYNOPSIS
    Shared helper: reads terraform.tfvars and returns a hashtable of values.

.DESCRIPTION
    Searches for terraform.tfvars in the project root and terraform/ subfolder.
    Parses simple HCL variable assignments (key = "value" or key = value).
    Used by Install, SetupInstall, GPU-Passthrough, and other scripts to
    avoid hardcoded defaults.

.EXAMPLE
    . .\scripts\Read-TfVars.ps1
    $config = Read-TfVars
    $vmName = $config["vm_name"]
#>

function Read-TfVars {
    param(
        [string]$ProjectRoot = ""
    )

    if (-not $ProjectRoot) {
        $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }

    # Search for terraform.tfvars
    $candidates = @(
        (Join-Path $ProjectRoot "terraform" "terraform.tfvars"),
        (Join-Path $ProjectRoot "terraform.tfvars")
    )

    $tfvarsPath = $null
    foreach ($c in $candidates) {
        if (Test-Path $c) { $tfvarsPath = $c; break }
    }

    $config = @{}
    if (-not $tfvarsPath) { return $config }

    # Parse HCL-style variable assignments
    Get-Content $tfvarsPath | ForEach-Object {
        $line = $_.Trim()
        # Skip comments and empty lines
        if ($line -match '^\s*#' -or $line -match '^\s*$' -or $line -match '^\s*//') { return }
        # Match: key = "value" or key = value
        if ($line -match '^\s*(\w+)\s*=\s*"([^"]*)"') {
            $config[$Matches[1]] = $Matches[2]
        }
        elseif ($line -match '^\s*(\w+)\s*=\s*(true|false)') {
            $config[$Matches[1]] = ($Matches[2] -eq 'true')
        }
        elseif ($line -match '^\s*(\w+)\s*=\s*(\d+\.?\d*)') {
            $config[$Matches[1]] = [double]$Matches[2]
        }
    }

    return $config
}
