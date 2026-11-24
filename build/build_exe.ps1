# Build the onefile Windows executable.
# Build-time dependency only: pip install pyinstaller
# The end user needs nothing installed.

param(
    [string]$Python = 'python',
    [string]$OutputDirectory = 'dist',
    [string]$WorkDirectory = 'build/work'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

if (Test-Path -LiteralPath $OutputDirectory) {
    throw 'Choose a new OutputDirectory; an existing release or user session directory must not be overwritten.'
}

& $Python -m PyInstaller build/a9tool.spec --clean --noconfirm --distpath $OutputDirectory --workpath $WorkDirectory
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }

$exe = Join-Path (Join-Path $root $OutputDirectory) 'ILCE-9_Slog_Project.exe'
if (-not (Test-Path $exe)) { throw "Build produced no exe at $exe" }

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "Built: $exe ($size MB)"
Write-Host 'Smoke test: run it, confirm the window opens and a sessions/ folder appears next to the exe.'
