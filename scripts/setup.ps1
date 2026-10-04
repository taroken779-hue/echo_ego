param([switch]$Cpu, [switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/ . Reopen the terminal and run setup.bat.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first: https://git-scm.com/downloads/win . Reopen the terminal and run setup.bat.' }
$sourcePath = Join-Path $projectRoot 'runtime\Irodori-TTS'
$sourceRevision = '89f9d8fbd4d51ea019867ee1197725ede1df13c5'
if (-not (Test-Path -LiteralPath $sourcePath)) {
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'runtime') -Force | Out-Null
    git clone https://github.com/Aratako/Irodori-TTS.git $sourcePath
    if ($LASTEXITCODE -ne 0) { throw 'Irodori source download failed.' }
    git -C $sourcePath checkout --detach $sourceRevision
    if ($LASTEXITCODE -ne 0) { throw 'Irodori version selection failed.' }
} else {
    $actualRevision = git -C $sourcePath rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $actualRevision -ne $sourceRevision) { throw 'Existing runtime source differs from the supported version. Move it aside manually; setup does not overwrite it.' }
}
Write-Host 'Creating an isolated inference environment (Python 3.11)...'
$oldProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
    if ($Cpu) { uv sync --project $sourcePath --python 3.11 --frozen --no-dev --extra cpu }
    else { uv sync --project $sourcePath --python 3.11 --frozen --no-dev --extra cu128 }
    if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Check CUDA/driver, disk space, and network.' }
} finally { $env:UV_PROJECT_ENVIRONMENT = $oldProjectEnvironment }
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
uv pip install --python $pythonPath -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Application dependency installation failed.' }
$configPath = Join-Path $projectRoot 'config.local.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    $config = Get-Content -LiteralPath (Join-Path $projectRoot 'config.example.json') -Raw | ConvertFrom-Json
    if ($Cpu) { $config.device = 'cpu'; $config.precision = 'fp32' }
    $config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
} else { Write-Host 'Preserving existing config.local.json. Select .venv/Scripts/python.exe in settings to use the new environment.' }
if (-not $SkipDownload) {
    & $pythonPath (Join-Path $PSScriptRoot 'download_model.py')
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Run setup.bat again to resume.' }
}
Write-Host 'Setup complete. Double-click start.bat. CPU is a compatibility option and will be slow.'
