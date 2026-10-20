param([switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$sourceDir = Join-Path $projectRoot 'runtime/omnivoice/source'
$sourceRevision = '08be0b4ccbac3e13e374e86fbfead4b4cac343e2'
if (-not (Test-Path -LiteralPath $sourceDir)) {
    git clone https://github.com/k2-fsa/OmniVoice.git $sourceDir
    if ($LASTEXITCODE -ne 0) { throw 'Source download failed.' }
    git -C $sourceDir checkout --detach $sourceRevision
} elseif ((git -C $sourceDir rev-parse HEAD) -ne $sourceRevision) { throw 'Existing OmniVoice source differs. It was not overwritten.' }
$pythonPath = Join-Path $projectRoot 'runtime/omnivoice/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { uv venv (Split-Path (Split-Path $pythonPath -Parent) -Parent) --python 3.11 }
if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed.' }
uv pip install --python $pythonPath torch==2.10.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }
uv pip install --python $pythonPath -r (Join-Path $projectRoot 'requirements-omnivoice.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency installation failed.' }
uv pip install --python $pythonPath --no-deps -e $sourceDir
if ($LASTEXITCODE -ne 0) { throw 'OmniVoice dependency installation failed.' }
if (-not $SkipDownload) {
    & $pythonPath (Join-Path $PSScriptRoot 'download_omnivoice.py')
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Run again to resume.' }
}
Write-Host 'OmniVoice setup complete. Existing Irodori settings were preserved.'
