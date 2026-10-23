<#
.SYNOPSIS
Build the StockKeep Windows setup executable.

.DESCRIPTION
Builds dist\StockKeep.exe (unless -SkipAppBuild is used) and packages it with
Inno Setup into dist\StockKeepSetup-<version>.exe.  Inno Setup 6 is required; the
script looks in the usual per-user and machine-wide install folders.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\build-setup.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\build-setup.ps1 -SkipTests -SkipAppBuild
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipAppBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not $SkipAppBuild) {
    $buildArgs = @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "build.ps1"))
    if ($SkipTests) { $buildArgs += "-SkipTests" }
    & powershell @buildArgs
    if ($LASTEXITCODE -ne 0) { throw "Application build failed." }
}

$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    throw "Inno Setup 6 was not found. Install it with: winget install --id JRSoftware.InnoSetup -e"
}

$appExe = Join-Path $root "dist\StockKeep.exe"
if (-not (Test-Path $appExe)) {
    throw "dist\StockKeep.exe is missing. Run build.ps1 first (or omit -SkipAppBuild)."
}

Write-Host "Compiling installer..." -ForegroundColor Cyan
$versionMatch = Select-String -Path (Join-Path $root "pyproject.toml") -Pattern '^version = "([^"]+)"'
if (-not $versionMatch) { throw "Could not read the version from pyproject.toml." }
$version = $versionMatch.Matches[0].Groups[1].Value
& $iscc "/Qp" "/DAppVersion=$version" (Join-Path $root "installer\StockKeep.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }

$setup = Join-Path $root "dist\StockKeepSetup-$version.exe"
if (-not (Test-Path $setup)) { throw "Expected installer was not produced: $setup" }
$size = [math]::Round((Get-Item $setup).Length / 1MB, 1)
Write-Host "Setup ready: $setup ($size MB)" -ForegroundColor Green
