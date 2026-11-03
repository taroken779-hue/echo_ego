param([switch]$SkipInstall, [switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv and reopen the terminal. See docs/SETUP.md.' }
$appPythonPath = Join-Path $projectRoot 'runtime/app/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $appPythonPath)) { throw 'Run setup.bat or setup_qwen3.bat to install the app, auxiliary services and Qwen3.' }
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
    & $pythonPath -c "import torch; assert torch.cuda.is_available(), 'Qwen3 requires an NVIDIA CUDA GPU and a compatible driver.'; assert torch.cuda.is_bf16_supported(), 'Qwen3 requires bfloat16 support with the configured CUDA runtime.'"
    if ($LASTEXITCODE -ne 0) { throw 'Qwen3 GPU validation failed. See docs/QWEN3_GUIDE.md.' }
    if (-not $SkipDownload) {
        & $pythonPath -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-TTS-12Hz-0.6B-Base', revision='5d83992436eae1d760afd27aff78a71d676296fc', local_dir='runtime/qwen3-tts/model-0.6b')"
        if ($LASTEXITCODE -ne 0) { throw 'Qwen model download failed.' }
    }
}
uv pip check --python $pythonPath
if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }
Write-Host 'Qwen3 backend is ready. The main setup will register its configuration.'
