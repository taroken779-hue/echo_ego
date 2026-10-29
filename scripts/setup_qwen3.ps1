param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot 'runtime/qwen3-fast/.venv/Scripts/python.exe'
if (-not $SkipInstall) {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        uv venv runtime/qwen3-fast/.venv --python 3.11
        if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
    }
    uv pip install --python $pythonPath torch==2.10.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch installation failed.' }
    uv pip install --python $pythonPath faster-qwen3-tts==0.5.4 qwen-tts-hf==0.1.1.post1 transformers==5.15.1
    if ($LASTEXITCODE -ne 0) { throw 'Qwen runtime installation failed.' }
    & $pythonPath -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-TTS-12Hz-0.6B-Base', revision='5d83992436eae1d760afd27aff78a71d676296fc', local_dir='runtime/qwen3-tts/model-0.6b')"
    if ($LASTEXITCODE -ne 0) { throw 'Qwen model download failed.' }
}
uv pip check --python $pythonPath
if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }
& runtime/app/.venv/Scripts/python.exe scripts/register_qwen3.py
if ($LASTEXITCODE -ne 0) { throw 'Qwen registration failed.' }
