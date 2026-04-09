#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Configure GPU passthrough for the InsideLLM Hyper-V VM.

.DESCRIPTION
    This script enables GPU access inside the InsideLLM VM using one of two methods:

    GPU-PV (Partitioning) - DEFAULT, RECOMMENDED
      Shares the GPU between Windows host and VM. The host keeps using the GPU
      for display while the VM gets compute access. Requires Windows 11 with a
      compatible NVIDIA GPU. No driver installation needed inside the VM.

    DDA (Discrete Device Assignment) - ADVANCED
      Full GPU passthrough. The GPU is dismounted from the Windows host and
      exclusively assigned to the VM. The host loses access to the GPU entirely.
      Requires a second GPU or integrated graphics for the host display.

    After GPU assignment, the script SSHs into the VM to install
    nvidia-container-toolkit so Docker containers can use the GPU.

    Run this AFTER terraform apply has created and started the VM.

.PARAMETER VMName
    Name of the Hyper-V VM. Default: InsideLLM

.PARAMETER Mode
    GPU passthrough mode: GpuPV (default) or DDA

.PARAMETER VMIpAddress
    IP address of the VM for SSH. Default: 192.168.100.10

.PARAMETER SshUser
    SSH username. Default: insidellm-admin

.PARAMETER SshKeyPath
    Path to SSH private key. Default: ~/.ssh/id_rsa

.PARAMETER Remove
    Remove GPU assignment from the VM and restore it to the host.

.EXAMPLE
    .\Setup-GPU-Passthrough.ps1                                # GPU-PV (recommended)
    .\Setup-GPU-Passthrough.ps1 -Mode DDA                      # Full passthrough
    .\Setup-GPU-Passthrough.ps1 -Remove                        # Remove GPU from VM
    .\Setup-GPU-Passthrough.ps1 -VMName "MyVM" -Mode GpuPV     # Custom VM name
#>

[CmdletBinding()]
param(
    [string]$VMName = "InsideLLM",

    [ValidateSet("GpuPV", "DDA")]
    [string]$Mode = "GpuPV",

    [string]$VMIpAddress = "192.168.100.10",
    [string]$SshUser     = "insidellm-admin",
    [string]$SshKeyPath  = "$env:USERPROFILE\.ssh\id_rsa",

    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-Step  { param([string]$M) Write-Host "`n=== $M ===" -ForegroundColor Cyan }
function Write-Ok    { param([string]$M) Write-Host "  [OK] $M" -ForegroundColor Green }
function Write-Warn  { param([string]$M) Write-Host "  [WARN] $M" -ForegroundColor Yellow }
function Write-Fail  { param([string]$M) Write-Host "  [FAIL] $M" -ForegroundColor Red }

function Invoke-Ssh {
    param([string]$Command)
    $sshArgs = @(
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-i", $SshKeyPath,
        "$SshUser@$VMIpAddress",
        $Command
    )
    $output = & ssh @sshArgs 2>&1
    return $output
}

# ---------------------------------------------------------------------------
# Validate VM exists
# ---------------------------------------------------------------------------

$vm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
if (-not $vm) {
    Write-Fail "VM '$VMName' not found. Run 'terraform apply' first."
    exit 1
}

# ---------------------------------------------------------------------------
# Find NVIDIA GPU
# ---------------------------------------------------------------------------

Write-Step "Detecting NVIDIA GPU"

$nvidiaDevices = Get-PnpDevice -Class Display -Status OK -ErrorAction SilentlyContinue |
    Where-Object { $_.FriendlyName -match "NVIDIA" }

if (-not $nvidiaDevices) {
    Write-Fail "No NVIDIA GPU detected on this host."
    Write-Host "  GPU passthrough requires an NVIDIA GPU installed in this machine."
    exit 1
}

$gpu = $nvidiaDevices | Select-Object -First 1
Write-Ok "Found: $($gpu.FriendlyName)"
Write-Ok "Instance ID: $($gpu.InstanceId)"

# ---------------------------------------------------------------------------
# Remove mode
# ---------------------------------------------------------------------------

if ($Remove) {
    Write-Step "Removing GPU from VM '$VMName'"

    $wasRunning = $vm.State -eq "Running"
    if ($wasRunning) {
        Write-Warn "Stopping VM..."
        Stop-VM -Name $VMName -Force
        Start-Sleep -Seconds 5
    }

    if ($Mode -eq "GpuPV") {
        $adapters = Get-VMGpuPartitionAdapter -VMName $VMName -ErrorAction SilentlyContinue
        if ($adapters) {
            Remove-VMGpuPartitionAdapter -VMName $VMName
            Write-Ok "GPU partition adapter removed"
        } else {
            Write-Warn "No GPU partition adapter found on VM"
        }
    } else {
        $assigned = Get-VMAssignableDevice -VMName $VMName -ErrorAction SilentlyContinue
        if ($assigned) {
            Remove-VMAssignableDevice -VMName $VMName -Verbose
            Write-Ok "DDA device removed from VM"
            Write-Warn "You may need to re-enable the GPU in Device Manager"
        } else {
            Write-Warn "No DDA device found on VM"
        }
    }

    if ($wasRunning) {
        Start-VM -Name $VMName
        Write-Ok "VM restarted"
    }

    Write-Host "`nGPU removed from VM." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
# GPU-PV (Partitioning) mode
# ---------------------------------------------------------------------------

if ($Mode -eq "GpuPV") {
    Write-Step "Configuring GPU Partitioning (GPU-PV)"

    # Check if already configured
    $existing = Get-VMGpuPartitionAdapter -VMName $VMName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Ok "GPU partition adapter already present on VM"
    } else {
        # VM must be off to add GPU partition adapter
        $wasRunning = $vm.State -eq "Running"
        if ($wasRunning) {
            Write-Warn "Stopping VM to configure GPU..."
            Stop-VM -Name $VMName -Force
            Start-Sleep -Seconds 5
        }

        # Set the host GPU as partitionable
        Write-Host "  Configuring host GPU for partitioning..."
        Set-VMPartitionableGpu -ComputerName $env:COMPUTERNAME `
            -MinPartitionVRAM       0 `
            -MaxPartitionVRAM       1000000000 `
            -OptimalPartitionVRAM   1000000000 `
            -MinPartitionEncode     0 `
            -MaxPartitionEncode     18446744073709551615 `
            -OptimalPartitionEncode 18446744073709551615 `
            -MinPartitionDecode     0 `
            -MaxPartitionDecode     1000000000 `
            -OptimalPartitionDecode 1000000000 `
            -MinPartitionCompute    0 `
            -MaxPartitionCompute    1000000000 `
            -OptimalPartitionCompute 1000000000

        Write-Ok "Host GPU marked as partitionable"

        # Add GPU partition adapter to VM
        Add-VMGpuPartitionAdapter -VMName $VMName
        Write-Ok "GPU partition adapter added to VM"

        # Configure the partition adapter
        Set-VMGpuPartitionAdapter -VMName $VMName `
            -MinPartitionVRAM       0 `
            -MaxPartitionVRAM       1000000000 `
            -OptimalPartitionVRAM   1000000000 `
            -MinPartitionEncode     0 `
            -MaxPartitionEncode     18446744073709551615 `
            -OptimalPartitionEncode 18446744073709551615 `
            -MinPartitionDecode     0 `
            -MaxPartitionDecode     1000000000 `
            -OptimalPartitionDecode 1000000000 `
            -MinPartitionCompute    0 `
            -MaxPartitionCompute    1000000000 `
            -OptimalPartitionCompute 1000000000

        Write-Ok "GPU partition adapter configured"

        # Copy host GPU driver files into VM
        # GPU-PV requires the host driver to be available inside the VM
        $hostDriverPath = "C:\Windows\System32\DriverStore\FileRepository"
        $nvDriverDir = Get-ChildItem $hostDriverPath -Directory -Filter "nv*" |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1

        if ($nvDriverDir) {
            # Set VM to allow host driver path access
            Set-VM -Name $VMName -GuestControlledCacheTypes $true -LowMemoryMappedIoSpace 1GB -HighMemoryMappedIoSpace 32GB
            Write-Ok "VM memory-mapped I/O configured"
        } else {
            Write-Warn "Could not locate NVIDIA driver directory in DriverStore"
        }

        if ($wasRunning) {
            Start-VM -Name $VMName
            Write-Host "  Waiting 30 seconds for VM to boot..."
            Start-Sleep -Seconds 30
        }
    }
}

# ---------------------------------------------------------------------------
# DDA (Discrete Device Assignment) mode
# ---------------------------------------------------------------------------

if ($Mode -eq "DDA") {
    Write-Step "Configuring Discrete Device Assignment (DDA)"

    Write-Warn "DDA will REMOVE the GPU from the Windows host."
    Write-Warn "The host will lose access to this GPU entirely."
    Write-Warn "Ensure you have another display adapter (integrated graphics or second GPU)."
    Write-Host ""

    # Get the location path for DDA
    $locationPath = (Get-PnpDeviceProperty -InstanceId $gpu.InstanceId `
        -KeyName "DEVPKEY_Device_LocationPaths" -ErrorAction SilentlyContinue).Data |
        Where-Object { $_ -match "PCIROOT" } | Select-Object -First 1

    if (-not $locationPath) {
        Write-Fail "Could not determine PCI location path for GPU."
        Write-Host "  DDA requires a PCI location path. Your GPU may not support DDA."
        exit 1
    }
    Write-Ok "Location path: $locationPath"

    # Check for existing assignment
    $assigned = Get-VMAssignableDevice -VMName $VMName -ErrorAction SilentlyContinue
    if ($assigned) {
        Write-Ok "GPU already assigned to VM via DDA"
    } else {
        $wasRunning = $vm.State -eq "Running"
        if ($wasRunning) {
            Write-Warn "Stopping VM..."
            Stop-VM -Name $VMName -Force
            Start-Sleep -Seconds 5
        }

        # Configure VM for DDA
        Set-VM -Name $VMName -GuestControlledCacheTypes $true -LowMemoryMappedIoSpace 1GB -HighMemoryMappedIoSpace 32GB
        Set-VM -Name $VMName -AutomaticStopAction TurnOff
        Write-Ok "VM configured for DDA"

        # Disable and dismount GPU from host
        Write-Warn "Dismounting GPU from host..."
        Disable-PnpDevice -InstanceId $gpu.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
        Dismount-VMHostAssignableDevice -LocationPath $locationPath -Force
        Write-Ok "GPU dismounted from host"

        # Assign to VM
        Add-VMAssignableDevice -VMName $VMName -LocationPath $locationPath
        Write-Ok "GPU assigned to VM via DDA"

        if ($wasRunning) {
            Start-VM -Name $VMName
            Write-Host "  Waiting 30 seconds for VM to boot..."
            Start-Sleep -Seconds 30
        }
    }
}

# ---------------------------------------------------------------------------
# Install nvidia-container-toolkit inside VM
# ---------------------------------------------------------------------------

Write-Step "Installing nvidia-container-toolkit in VM"

Write-Host "  Connecting to VM via SSH..."
$ping = Test-Connection -ComputerName $VMIpAddress -Count 1 -Quiet -ErrorAction SilentlyContinue
if (-not $ping) {
    Write-Warn "Cannot reach VM at $VMIpAddress. Ensure the VM is running."
    Write-Warn "You can install nvidia-container-toolkit manually later:"
    Write-Host ""
    Write-Host "  ssh $SshUser@$VMIpAddress"
    Write-Host '  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg'
    Write-Host '  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list'
    Write-Host '  sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit'
    Write-Host '  sudo nvidia-ctk runtime configure --runtime=docker'
    Write-Host '  sudo systemctl restart docker'
    exit 0
}

$toolkitCheck = Invoke-Ssh "dpkg -l nvidia-container-toolkit 2>/dev/null | grep -q '^ii' && echo INSTALLED || echo MISSING"
if ($toolkitCheck -match "INSTALLED") {
    Write-Ok "nvidia-container-toolkit already installed"
} else {
    Write-Host "  Installing nvidia-container-toolkit (this takes a minute)..."
    Invoke-Ssh @'
set -e
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
sudo apt-get update -qq
sudo apt-get install -y -qq nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
'@ | Out-Null
    Write-Ok "nvidia-container-toolkit installed and configured"
}

# Verify GPU visibility inside VM
Write-Host "  Verifying GPU visibility..."
$gpuCheck = Invoke-Ssh "nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo GPU_NOT_VISIBLE"
if ($gpuCheck -match "GPU_NOT_VISIBLE") {
    if ($Mode -eq "GpuPV") {
        Write-Warn "GPU not yet visible inside VM."
        Write-Host "  GPU-PV may need a VM reboot and host NVIDIA driver files copied into the VM."
        Write-Host "  Try: Stop-VM -Name $VMName; Start-VM -Name $VMName"
    } else {
        Write-Warn "GPU not visible inside VM. You may need to install NVIDIA drivers inside Ubuntu:"
        Write-Host "  ssh $SshUser@$VMIpAddress"
        Write-Host "  sudo apt-get install -y nvidia-driver-550-server"
        Write-Host "  sudo reboot"
    }
} else {
    Write-Ok "GPU visible in VM: $($gpuCheck.Trim())"
}

# ---------------------------------------------------------------------------
# Reminder to enable ollama_gpu
# ---------------------------------------------------------------------------

Write-Step "Next Steps"

Write-Host ""
Write-Host "  GPU passthrough is configured ($Mode mode)." -ForegroundColor Green
Write-Host ""
Write-Host "  To use GPU with Ollama, ensure ollama_gpu = true in terraform.tfvars"
Write-Host "  and redeploy, or edit the docker-compose directly:"
Write-Host ""
Write-Host "    ssh $SshUser@$VMIpAddress"
Write-Host "    cd /opt/InsideLLM"
Write-Host "    sudo docker compose down"
Write-Host "    # Edit docker-compose.yml to add deploy.resources.reservations.devices"
Write-Host "    sudo docker compose up -d"
Write-Host ""
Write-Host "  To verify GPU access from a container:"
Write-Host "    ssh $SshUser@$VMIpAddress"
Write-Host '    sudo docker run --rm --gpus all nvidia/cuda:12.3.1-base-ubuntu22.04 nvidia-smi'
Write-Host ""
