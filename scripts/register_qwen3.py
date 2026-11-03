"""Register the separately installed pinned Qwen runtime without changing selected model."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from configuration import ModelConfig

def model_config():
    return ModelConfig(backend='qwen3_fast',label='Qwen3-TTS（低遅延）',
        python_path='runtime/qwen3-fast/.venv/Scripts/python.exe', model_path='runtime/qwen3-tts/model-0.6b',
        manifest_path='runtime/qwen3-fast/manifest.json',device='cuda',precision='bfloat16')


def validate_install(cfg, root=ROOT):
    model = model_config()
    if cfg is not None and 'qwen3' in cfg.models and cfg.models['qwen3'] != model:
        raise SystemExit('Existing qwen3 configuration differs; it was not overwritten.')
    if not (root/model.python_path).is_file() or not (root/model.model_path/'model.safetensors').is_file():
        raise SystemExit('Qwen3 environment/model missing. Run setup_qwen3.bat.')
    metadata = root/model.model_path/'.cache/huggingface/download/model.safetensors.metadata'
    revision = '5d83992436eae1d760afd27aff78a71d676296fc'
    if not metadata.is_file() or metadata.read_text().splitlines()[0] != revision:
        raise SystemExit('Model revision cannot be verified. Run setup_qwen3.bat to fetch the pinned model.')
    manifest = {'source_revision':'faster-qwen3-tts=0.5.4;qwen-tts-hf=0.1.1.post1;transformers=5.15.1;torch=2.10.0+cu128',
        'models':{'Qwen/Qwen3-TTS-12Hz-0.6B-Base':'5d83992436eae1d760afd27aff78a71d676296fc'}}
    (root/model.manifest_path).write_text(json.dumps(manifest,indent=2),encoding='utf-8')


if __name__ == '__main__':
    from scripts.configure_setup import main
    main(['--model', 'qwen3'])
