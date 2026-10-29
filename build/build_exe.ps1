# Build the onefile Windows executable.
# Build-time dependency only: pip install pyinstaller
# The end user needs nothing installed.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

if (Test-Path 'dist') { Remove-Item -Recurse -Force 'dist' }
if (Test-Path 'build/work') { Remove-Item -Recurse -Force 'build/work' }

python -m PyInstaller build/a9tool.spec --clean --noconfirm --distpath dist --workpath build/work

$exe = Join-Path $root 'dist/ILCE-9_Slog_Project.exe'
if (-not (Test-Path $exe)) { throw "Build produced no exe at $exe" }

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "Built: $exe ($size MB)"
Write-Host 'Smoke test: run it, confirm the window opens and a sessions/ folder appears next to the exe.'
