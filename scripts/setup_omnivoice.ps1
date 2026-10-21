param([switch]$SkipDownload, [switch]$Cpu)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$sourceDir = Join-Path $projectRoot 'runtime/omnivoice/source'
$sourceRevision = '08be0b4ccbac3e13e374e86fbfead4b4cac343e2'
if (-not (Test-Path -LiteralPath $sourceDir)) {
    git clone https://github.com/k2-fsa/OmniVoice.git $sourceDir
    if ($LASTEXITCODE -ne 0) { throw 'Source download failed.' }
    git -C $sourceDir checkout --detach $sourceRevision
    if ($LASTEXITCODE -ne 0) { throw 'Source version selection failed.' }
} elseif ((git -C $sourceDir rev-parse HEAD) -ne $sourceRevision) { throw 'Existing OmniVoice source differs. It was not overwritten.' }
$pythonPath = Join-Path $projectRoot 'runtime/omnivoice/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { uv venv (Split-Path (Split-Path $pythonPath -Parent) -Parent) --python 3.11 }
if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed.' }
$torchIndex = if ($Cpu) { 'https://download.pytorch.org/whl/cpu' } else { 'https://download.pytorch.org/whl/cu128' }
uv pip install --python $pythonPath torch==2.10.0 torchaudio==2.10.0 --index-url $torchIndex
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }
$dependencyPath = Join-Path $projectRoot 'runtime/omnivoice/requirements-runtime.txt'
# torch/torchaudio were pinned above from the selected CPU or CUDA wheel index.
# Keep the rest of the fixed dependency set without forcing CUDA wheels on CPU.
Get-Content -LiteralPath (Join-Path $projectRoot 'requirements-omnivoice.lock.txt') | Where-Object { $_ -notmatch '^(torch|torchaudio)==' } | Set-Content -LiteralPath $dependencyPath -Encoding utf8
uv pip install --python $pythonPath -r $dependencyPath
if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency installation failed.' }
uv pip install --python $pythonPath --no-deps -e $sourceDir
if ($LASTEXITCODE -ne 0) { throw 'OmniVoice dependency installation failed.' }
if (-not $SkipDownload) {
    & $pythonPath (Join-Path $PSScriptRoot 'download_omnivoice.py')
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Run again to resume.' }
}
Write-Host 'OmniVoice backend and auxiliary services are ready. Existing settings were preserved.'
