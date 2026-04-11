@echo off
REM =========================================================================
REM Deploy-InsideLLM.bat — One-click deployment from fresh clone
REM
REM Clones (or re-clones) the InsideLLM repo to C:\InsideLLM, copies
REM terraform.tfvars from Downloads, and runs SetupInstall.ps1.
REM
REM Usage: Right-click > Run as administrator (or just double-click)
REM =========================================================================

REM Check for admin rights, self-elevate if needed
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

echo.
echo =========================================================================
echo   InsideLLM Deployment
echo =========================================================================
echo.

REM Run the deployment in PowerShell 5.1+ (required for our scripts)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Version 5.1 -Command ^
  "Set-StrictMode -Version Latest; $ErrorActionPreference = 'Stop'; " ^
  "Write-Host '  [1/4] Preparing C:\InsideLLM...' -ForegroundColor Cyan; " ^
  "if (Test-Path 'C:\InsideLLM') { Remove-Item -Recurse -Force 'C:\InsideLLM' }; " ^
  "Set-Location 'C:\'; " ^
  "Write-Host '  [2/4] Cloning repository...' -ForegroundColor Cyan; " ^
  "git clone https://github.com/Uniformedi/InsideLLM.git InsideLLM; " ^
  "if (-not (Test-Path 'C:\InsideLLM')) { throw 'Clone failed' }; " ^
  "Set-Location 'C:\InsideLLM'; " ^
  "Write-Host '  [3/4] Copying terraform.tfvars from Downloads...' -ForegroundColor Cyan; " ^
  "$tfvars = Get-ChildItem \"$env:USERPROFILE\Downloads\" -Filter '*.tfvars' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; " ^
  "if ($tfvars) { Copy-Item $tfvars.FullName -Destination 'C:\InsideLLM\terraform.tfvars'; Write-Host \"  Copied: $($tfvars.Name)\" -ForegroundColor Green } " ^
  "else { Write-Host '  [WARN] No .tfvars file found in Downloads — generate one from the Setup Wizard' -ForegroundColor Yellow }; " ^
  "Write-Host '  [4/4] Running SetupInstall...' -ForegroundColor Cyan; " ^
  "& '.\scripts\SetupInstall.ps1'"

if %errorlevel% neq 0 (
    echo.
    echo   Deployment encountered errors. Check the output above.
    echo.
)

pause
