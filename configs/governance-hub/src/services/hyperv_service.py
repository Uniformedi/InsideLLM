"""Hyper-V management via WinRM/PowerShell.

Thin functional equivalent of Windows Admin Center, scoped to the bits
the Governance Hub actually needs: list VMs on a host, get their state,
get host resources, and start/stop/snapshot.

Reuses the same WinRM credentials Terraform's hyperv provider already
uses (see terraform/variables.tf:hyperv_*). No separate trust surface.

Runs read-only by default; write operations (start/stop/snapshot) are
gated to admin role at the router layer.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("insidellm.hyperv")

HYPERV_HOST = os.environ.get("HYPERV_HOST", "")
HYPERV_USER = os.environ.get("HYPERV_USER", "")
HYPERV_PASSWORD = os.environ.get("HYPERV_PASSWORD", "")
HYPERV_PORT = int(os.environ.get("HYPERV_PORT", "5985"))
HYPERV_HTTPS = os.environ.get("HYPERV_HTTPS", "false").lower() == "true"
HYPERV_INSECURE = os.environ.get("HYPERV_INSECURE", "true").lower() == "true"


class HyperVUnavailable(RuntimeError):
    """Raised when WinRM is unconfigured or unreachable."""


def _session():
    """Lazy import + connection. winrm import errors surface as
    HyperVUnavailable so the rest of the Hub still boots if pywinrm is
    missing."""
    if not HYPERV_HOST:
        raise HyperVUnavailable("HYPERV_HOST not configured")
    try:
        import winrm
    except ImportError:
        raise HyperVUnavailable("pywinrm not installed")
    scheme = "https" if HYPERV_HTTPS else "http"
    return winrm.Session(
        f"{scheme}://{HYPERV_HOST}:{HYPERV_PORT}/wsman",
        auth=(HYPERV_USER, HYPERV_PASSWORD),
        transport="ntlm",
        server_cert_validation="ignore" if HYPERV_INSECURE else "validate",
    )


def _run_ps(script: str) -> dict[str, Any]:
    """Run a PowerShell script, return decoded JSON. Adds error wrapping so
    callers always get either {ok: True, data: ...} or {ok: False, err: ...}."""
    try:
        s = _session()
    except HyperVUnavailable as exc:
        return {"ok": False, "err": str(exc)}
    try:
        result = s.run_ps(script)
    except Exception as exc:
        return {"ok": False, "err": f"WinRM call failed: {exc}"}
    if result.status_code != 0:
        return {"ok": False, "err": result.std_err.decode("utf-8", "replace") or "unknown"}
    out = result.std_out.decode("utf-8", "replace").strip()
    if not out:
        return {"ok": True, "data": None}
    try:
        return {"ok": True, "data": json.loads(out)}
    except json.JSONDecodeError:
        return {"ok": True, "data": {"_raw": out}}


# ---- Read endpoints ---------------------------------------------------------

def list_vms() -> dict[str, Any]:
    """Return all VMs on the configured host."""
    return _run_ps(
        r"""
        Get-VM | Select-Object Name, State, Status, CPUUsage, MemoryAssigned,
                                Uptime, Version, AutomaticStartAction,
                                AutomaticStopAction |
            ConvertTo-Json -Depth 3 -AsArray
        """
    )


def get_vm(name: str) -> dict[str, Any]:
    """Detail for one VM."""
    safe = name.replace("'", "''")
    return _run_ps(
        f"""
        Get-VM -Name '{safe}' |
            Select-Object Name, State, Status, CPUUsage, MemoryAssigned,
                          MemoryStartup, MemoryMinimum, MemoryMaximum,
                          ProcessorCount, Uptime, Version, Generation,
                          @{{N='Networks';E={{ ($_ | Get-VMNetworkAdapter | Select-Object Name,SwitchName,@{{N='IPs';E={{$_.IPAddresses}}}}) }}}},
                          @{{N='Disks';E={{ ($_ | Get-VMHardDiskDrive | Select-Object Path,ControllerType,ControllerNumber,ControllerLocation) }}}} |
            ConvertTo-Json -Depth 5
        """
    )


def host_resources() -> dict[str, Any]:
    """Hyper-V host CPU, memory, disk, OS, uptime."""
    return _run_ps(
        r"""
        $os = Get-CimInstance Win32_OperatingSystem
        $cs = Get-CimInstance Win32_ComputerSystem
        $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
            Select-Object DeviceID, @{N='SizeGB';E={[math]::Round($_.Size/1GB,2)}}, @{N='FreeGB';E={[math]::Round($_.FreeSpace/1GB,2)}}
        @{
            Hostname        = $cs.Name
            Domain          = $cs.Domain
            OS              = $os.Caption
            OSVersion       = $os.Version
            TotalMemoryGB   = [math]::Round($cs.TotalPhysicalMemory/1GB,2)
            FreeMemoryGB    = [math]::Round($os.FreePhysicalMemory/1MB,2)
            LogicalCPUs     = $cs.NumberOfLogicalProcessors
            LastBootUpTime  = $os.LastBootUpTime.ToString("o")
            Disks           = $disks
        } | ConvertTo-Json -Depth 4
        """
    )


def list_snapshots(name: str) -> dict[str, Any]:
    safe = name.replace("'", "''")
    return _run_ps(
        f"""
        Get-VMSnapshot -VMName '{safe}' |
            Select-Object Name, CreationTime, ParentSnapshotName, SnapshotType |
            ConvertTo-Json -Depth 3 -AsArray
        """
    )


# ---- Write endpoints --------------------------------------------------------

def start_vm(name: str) -> dict[str, Any]:
    safe = name.replace("'", "''")
    return _run_ps(f"Start-VM -Name '{safe}' -Passthru | Select-Object Name,State | ConvertTo-Json")


def stop_vm(name: str, force: bool = False) -> dict[str, Any]:
    safe = name.replace("'", "''")
    flag = " -Force -TurnOff" if force else ""
    return _run_ps(f"Stop-VM -Name '{safe}'{flag} -Passthru | Select-Object Name,State | ConvertTo-Json")


def snapshot_vm(name: str, snapshot_name: str = "") -> dict[str, Any]:
    safe = name.replace("'", "''")
    if snapshot_name:
        snap_safe = snapshot_name.replace("'", "''")
        cmd = f"Checkpoint-VM -Name '{safe}' -SnapshotName '{snap_safe}' -Passthru"
    else:
        cmd = f"Checkpoint-VM -Name '{safe}' -Passthru"
    return _run_ps(f"{cmd} | Select-Object Name,@{{N='Latest';E={{(Get-VMSnapshot -VMName '{safe}' | Sort-Object CreationTime -Desc | Select-Object -First 1).Name}}}} | ConvertTo-Json")
