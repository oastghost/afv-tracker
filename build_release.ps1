# AFV Tracker - one-command release build
#   .\build_release.ps1            -> dist\installer\AFV-Tracker-Setup-<ver>.exe (+ portable zip)
#   .\build_release.ps1 -SkipZip   -> installer only
#
# Requires: the repo .venv (PyInstaller) and Inno Setup 6 (winget install JRSoftware.InnoSetup)

param([switch]$SkipZip)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Version from client/version.py (single source of truth)
$verLine = Select-String -Path "client\version.py" -Pattern 'VERSION\s*=\s*"([^"]+)"'
$version = $verLine.Matches[0].Groups[1].Value
Write-Host "Building AFV Tracker v$version" -ForegroundColor Cyan

# 1. PyInstaller (onedir -> dist\AFV Tracker)
& ".venv\Scripts\pyinstaller.exe" "AFV_Tracker.spec" --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# 2. Inno Setup installer
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    & $iscc "installer.iss" "/DAppVersion=$version"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }
    Write-Host "Installer: dist\installer\AFV-Tracker-Setup-$version.exe" -ForegroundColor Green
} else {
    Write-Warning "Inno Setup not found - skipping installer (winget install JRSoftware.InnoSetup)"
}

# 3. Portable zip (for pilots who prefer no installer)
if (-not $SkipZip) {
    $zip = "dist\installer\AFV-Tracker-$version-portable.zip"
    New-Item -ItemType Directory -Force "dist\installer" | Out-Null
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path "dist\AFV Tracker\*" -DestinationPath $zip
    Write-Host "Portable:  $zip" -ForegroundColor Green
}
