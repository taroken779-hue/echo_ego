param([ValidateSet('qwen3', 'omnivoice')][string]$Model = 'qwen3', [switch]$Cpu, [switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv and reopen the terminal.' }
if ($Cpu -and $Model -ne 'omnivoice') { throw 'Qwen3 requires a CUDA GPU. For CPU use: scripts/setup.ps1 -Model omnivoice -Cpu' }
if ($Model -eq 'omnivoice' -and -not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows and reopen the terminal.' }
& (Join-Path $PSScriptRoot 'setup_app.ps1')
if (-not $?) { throw 'Application setup failed.' }
& (Join-Path $PSScriptRoot 'setup_auxiliary.ps1') -SkipDownload:$SkipDownload
if (-not $?) { throw 'Auxiliary setup failed.' }
$pythonPath = Join-Path $projectRoot 'runtime/app/.venv/Scripts/python.exe'
if ($Model -eq 'qwen3') {
    & (Join-Path $PSScriptRoot 'setup_qwen3.ps1') -SkipDownload:$SkipDownload
} else {
    & (Join-Path $PSScriptRoot 'setup_omnivoice.ps1') -SkipDownload:$SkipDownload -Cpu:$Cpu
}
if (-not $?) { throw 'TTS backend setup failed.' }
$setupArgs = @((Join-Path $PSScriptRoot 'configure_setup.py'), '--model', $Model)
if ($Cpu) { $setupArgs += '--cpu' }
& $pythonPath @setupArgs
if ($LASTEXITCODE -ne 0) { throw 'Setup configuration failed.' }
$migrationArgs = @((Join-Path $PSScriptRoot 'migrate_config.py'))
& $pythonPath @migrationArgs
if ($LASTEXITCODE -ne 0) { throw 'Configuration migration failed.' }
Write-Host 'Setup complete. Double-click start.bat.'
