<#
.SYNOPSIS
    Creates a cloud-init ISO (ISO 9660 / CDROM) from a directory.

.DESCRIPTION
    Pure PowerShell ISO creation with no external dependencies.
    Tries tools in order: oscdimg (Windows ADK) > WSL genisoimage > PowerShell native.
    The native fallback uses .NET to write a minimal ISO 9660 image.

.PARAMETER SourceDir
    Directory containing cloud-init files (user-data, meta-data, network-config).

.PARAMETER OutputIso
    Path for the output ISO file.

.PARAMETER VolumeLabel
    ISO volume label (default: cidata, required by cloud-init).
#>
param(
    [Parameter(Mandatory)][string]$SourceDir,
    [Parameter(Mandatory)][string]$OutputIso,
    [string]$VolumeLabel = "cidata"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SourceDir)) {
    throw "Source directory not found: $SourceDir"
}

# ---- Method 1: oscdimg (Windows ADK) ----
$oscdimg = Get-Command oscdimg.exe -ErrorAction SilentlyContinue
if ($oscdimg) {
    Write-Host "Creating ISO with oscdimg (Windows ADK)..."
    & oscdimg.exe -j2 -l"$VolumeLabel" $SourceDir $OutputIso
    if (Test-Path $OutputIso) {
        Write-Host "ISO created: $OutputIso"
        return
    }
}

# ---- Method 2: WSL genisoimage ----
$wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($wslCmd) {
    $wslCheck = wsl --list --quiet 2>$null
    if ($LASTEXITCODE -eq 0 -and $wslCheck) {
        $geniso = wsl bash -c "command -v genisoimage 2>/dev/null && echo FOUND"
        if ($geniso -match "FOUND") {
            Write-Host "Creating ISO with WSL genisoimage..."
            # Remove any stale ISO first so we can verify fresh creation
            if (Test-Path $OutputIso) { Remove-Item $OutputIso -Force }
            $winDir  = $SourceDir.Replace('\', '/')
            $winIso  = $OutputIso.Replace('\', '/')
            $wslDir  = (wsl wslpath -a $winDir).Trim()
            $wslIso  = (wsl wslpath -a $winIso).Trim()
            if ($wslDir -and $wslIso) {
                wsl bash -c "genisoimage -output '$wslIso' -volid '$VolumeLabel' -joliet -rock '$wslDir'" 2>&1
                if ((Test-Path $OutputIso) -and (Get-Item $OutputIso).Length -gt 0) {
                    Write-Host "ISO created: $OutputIso"
                    return
                } else {
                    Write-Host "WSL genisoimage failed (permission denied or empty output) — falling back to native..."
                }
            }
        }
    }
}

# ---- Method 3: PowerShell native (no external dependencies) ----
Write-Host "Creating ISO with PowerShell native method (no ADK or WSL required)..."

# Collect files
$files = Get-ChildItem -Path $SourceDir -File
if ($files.Count -eq 0) {
    throw "No files found in $SourceDir"
}

# ISO 9660 constants
$SECTOR_SIZE = 2048
$volLabel = $VolumeLabel.ToUpper().PadRight(32, " ").Substring(0, 32)

# Read all file contents
$fileEntries = @()
foreach ($f in $files) {
    $fileEntries += @{
        Name    = $f.Name.ToUpper().Replace("-", "_")
        Content = [System.IO.File]::ReadAllBytes($f.FullName)
        OriginalName = $f.Name
    }
}

$stream = [System.IO.FileStream]::new($OutputIso, [System.IO.FileMode]::Create)
$writer = [System.IO.BinaryWriter]::new($stream)

try {
    # System Area (16 sectors of zeros)
    $writer.Write([byte[]]::new(16 * $SECTOR_SIZE))

    # Primary Volume Descriptor (sector 16)
    $pvd = [byte[]]::new($SECTOR_SIZE)
    $pvd[0] = 1                          # Type: Primary
    [System.Text.Encoding]::ASCII.GetBytes("CD001").CopyTo($pvd, 1)  # Standard ID
    $pvd[6] = 1                          # Version
    [System.Text.Encoding]::ASCII.GetBytes($volLabel).CopyTo($pvd, 40)   # Volume ID
    [System.Text.Encoding]::ASCII.GetBytes($volLabel).CopyTo($pvd, 318)  # Volume Set ID

    # Calculate sizes
    $rootDirSector = 18
    $rootDirSize = $SECTOR_SIZE    # One sector for root directory
    $firstFileSector = 19
    $totalSectors = $firstFileSector
    foreach ($fe in $fileEntries) {
        $totalSectors += [Math]::Ceiling($fe.Content.Length / $SECTOR_SIZE)
        if ($totalSectors * $SECTOR_SIZE -lt $fe.Content.Length) { $totalSectors++ }
    }

    # Volume Space Size (both-endian 32-bit at offset 80)
    $sizeLE = [BitConverter]::GetBytes([int32]$totalSectors)
    $sizeBE = [byte[]]@($sizeLE[3], $sizeLE[2], $sizeLE[1], $sizeLE[0])
    $sizeLE.CopyTo($pvd, 80)
    $sizeBE.CopyTo($pvd, 84)

    # Logical Block Size (both-endian 16-bit at offset 128)
    $pvd[128] = 0; $pvd[129] = 8; $pvd[130] = 8; $pvd[131] = 0  # 2048

    # Root directory record (at offset 156, 34 bytes)
    $rootRec = [byte[]]::new(34)
    $rootRec[0] = 34                      # Record length
    $rootRec[2] = [byte]($rootDirSector); $rootRec[5] = [byte]($rootDirSector)  # Location
    $rootRec[10] = [byte]($rootDirSize -band 0xFF)  # Data length LE
    $rootRec[11] = [byte](($rootDirSize -shr 8) -band 0xFF)
    $rootRec[14] = [byte](($rootDirSize -shr 8) -band 0xFF)  # Data length BE
    $rootRec[15] = [byte]($rootDirSize -band 0xFF)
    $rootRec[25] = 2                      # Flags: directory
    $rootRec[32] = 1                      # File ID length
    $rootRec[33] = 0                      # File ID: root
    $rootRec.CopyTo($pvd, 156)

    $writer.Write($pvd)

    # Volume Descriptor Set Terminator (sector 17)
    $term = [byte[]]::new($SECTOR_SIZE)
    $term[0] = 255
    [System.Text.Encoding]::ASCII.GetBytes("CD001").CopyTo($term, 1)
    $term[6] = 1
    $writer.Write($term)

    # Root Directory (sector 18)
    $dirData = [byte[]]::new($SECTOR_SIZE)
    $dirOffset = 0

    # Self entry "."
    $selfRec = [byte[]]::new(34)
    $selfRec[0] = 34; $selfRec[2] = [byte]$rootDirSector; $selfRec[5] = [byte]$rootDirSector
    $selfRec[10] = [byte]($rootDirSize -band 0xFF); $selfRec[11] = [byte](($rootDirSize -shr 8) -band 0xFF)
    $selfRec[14] = [byte](($rootDirSize -shr 8) -band 0xFF); $selfRec[15] = [byte]($rootDirSize -band 0xFF)
    $selfRec[25] = 2; $selfRec[32] = 1; $selfRec[33] = 0
    $selfRec.CopyTo($dirData, $dirOffset); $dirOffset += 34

    # Parent entry ".."
    $parentRec = [byte[]]::new(34)
    $parentRec[0] = 34; $parentRec[2] = [byte]$rootDirSector; $parentRec[5] = [byte]$rootDirSector
    $parentRec[10] = [byte]($rootDirSize -band 0xFF); $parentRec[11] = [byte](($rootDirSize -shr 8) -band 0xFF)
    $parentRec[14] = [byte](($rootDirSize -shr 8) -band 0xFF); $parentRec[15] = [byte]($rootDirSize -band 0xFF)
    $parentRec[25] = 2; $parentRec[32] = 1; $parentRec[33] = 1
    $parentRec.CopyTo($dirData, $dirOffset); $dirOffset += 34

    # File entries
    $currentSector = $firstFileSector
    foreach ($fe in $fileEntries) {
        $fName = $fe.Name
        if (-not $fName.Contains(".")) { $fName += ".;1" } else { $fName += ";1" }
        $nameBytes = [System.Text.Encoding]::ASCII.GetBytes($fName)
        $recLen = 33 + $nameBytes.Length
        if ($recLen % 2 -ne 0) { $recLen++ }  # Pad to even

        $fileRec = [byte[]]::new($recLen)
        $fileRec[0] = [byte]$recLen
        # Location (both-endian)
        $locLE = [BitConverter]::GetBytes([int32]$currentSector)
        $locBE = [byte[]]@($locLE[3], $locLE[2], $locLE[1], $locLE[0])
        $locLE.CopyTo($fileRec, 2); $locBE.CopyTo($fileRec, 6)
        # Data length (both-endian)
        $lenLE = [BitConverter]::GetBytes([int32]$fe.Content.Length)
        $lenBE = [byte[]]@($lenLE[3], $lenLE[2], $lenLE[1], $lenLE[0])
        $lenLE.CopyTo($fileRec, 10); $lenBE.CopyTo($fileRec, 14)
        # File flags: 0 (regular file)
        $fileRec[25] = 0
        $fileRec[32] = [byte]$nameBytes.Length
        $nameBytes.CopyTo($fileRec, 33)

        $fileRec.CopyTo($dirData, $dirOffset)
        $dirOffset += $recLen

        $sectorsNeeded = [Math]::Ceiling($fe.Content.Length / $SECTOR_SIZE)
        if ($sectorsNeeded -eq 0) { $sectorsNeeded = 1 }
        $currentSector += $sectorsNeeded
    }
    $writer.Write($dirData)

    # File data (sectors 19+)
    foreach ($fe in $fileEntries) {
        $data = $fe.Content
        $padded = [Math]::Ceiling($data.Length / $SECTOR_SIZE) * $SECTOR_SIZE
        if ($padded -eq 0) { $padded = $SECTOR_SIZE }
        $writer.Write($data)
        $remaining = $padded - $data.Length
        if ($remaining -gt 0) {
            $writer.Write([byte[]]::new($remaining))
        }
    }
}
finally {
    $writer.Close()
    $stream.Close()
}

if (Test-Path $OutputIso) {
    Write-Host "ISO created (PowerShell native): $OutputIso"
} else {
    throw "Failed to create ISO at $OutputIso"
}
