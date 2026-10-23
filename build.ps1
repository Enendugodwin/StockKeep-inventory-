<#
.SYNOPSIS
Build the StockKeep Windows executable.

.DESCRIPTION
Installs nothing: it uses the project virtual environment, runs the test suite,
regenerates the icon, then produces dist\StockKeep.exe with PyInstaller.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipClean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $root ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $python)) {
    throw "Virtual environment not found at .venv. Create it first: py -3.13 -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt"
}
if (-not (Test-Path $pyinstaller)) {
    throw "PyInstaller is not installed in .venv. Run: .venv\Scripts\python -m pip install -r requirements-dev.txt"
}

if (-not $SkipTests) {
    Write-Host "Running tests..." -ForegroundColor Cyan
    $env:PYTHONPATH = "src"
    $env:QT_QPA_PLATFORM = "offscreen"
    & $python -m pytest tests
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; build aborted." }
}

Write-Host "Generating application icon..." -ForegroundColor Cyan
$env:QT_QPA_PLATFORM = "offscreen"
& $python "tools\make_icon.py"
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }

$arguments = @("StockKeep.spec", "--noconfirm")
if (-not $SkipClean) { $arguments += "--clean" }

Write-Host "Building executable..." -ForegroundColor Cyan
& $pyinstaller @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$exe = Join-Path $root "dist\StockKeep.exe"
if (-not (Test-Path $exe)) { throw "Build reported success but $exe is missing." }

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ""
Write-Host "Built $exe ($size MB)" -ForegroundColor Green
Write-Host "Run it with: .\dist\StockKeep.exe"
