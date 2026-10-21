param([switch]$Cpu, [switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv and reopen the terminal.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows and reopen the terminal.' }
$pythonPath = Join-Path $projectRoot 'runtime/app/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    uv venv (Join-Path $projectRoot 'runtime/app/.venv') --python 3.11
    if ($LASTEXITCODE -ne 0) { throw 'Application Python environment creation failed.' }
}
uv pip install --python $pythonPath -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Application dependency installation failed.' }
& (Join-Path $PSScriptRoot 'setup_omnivoice.ps1') -SkipDownload:$SkipDownload -Cpu:$Cpu
if (-not $?) { throw 'OmniVoice setup failed.' }
$migrationArgs = @((Join-Path $PSScriptRoot 'migrate_config.py'))
if ($Cpu) { $migrationArgs += '--cpu' }
& $pythonPath @migrationArgs
if ($LASTEXITCODE -ne 0) { throw 'Configuration migration failed.' }
Write-Host 'Setup complete. Double-click start.bat.'
