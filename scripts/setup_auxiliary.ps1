param([switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv and reopen the terminal.' }
$pythonPath = Join-Path $projectRoot 'runtime/auxiliary/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    uv venv (Join-Path $projectRoot 'runtime/auxiliary/.venv') --python 3.11
    if ($LASTEXITCODE -ne 0) { throw 'Auxiliary Python environment creation failed.' }
}
uv pip install --python $pythonPath torch==2.10.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'Auxiliary CPU PyTorch installation failed.' }
uv pip install --python $pythonPath -r (Join-Path $projectRoot 'requirements-auxiliary.txt')
if ($LASTEXITCODE -ne 0) { throw 'Auxiliary dependency installation failed.' }
uv pip check --python $pythonPath
if ($LASTEXITCODE -ne 0) { throw 'Auxiliary dependency validation failed.' }
if (-not $SkipDownload) {
    & $pythonPath (Join-Path $PSScriptRoot 'download_auxiliary.py')
    if ($LASTEXITCODE -ne 0) { throw 'Auxiliary model download failed. Run again to resume.' }
}
Write-Host 'Independent CPU translation and transcription environment is ready.'
