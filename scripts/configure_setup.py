"""Register installed components; fresh Qwen setup never registers OmniVoice."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from configuration import CONFIG_PATH, ModelConfig, RuntimeConfig, load_config, save_config
from scripts.register_qwen3 import model_config as qwen_config, validate_install

AUXILIARY = {
    'auxiliary_python': 'runtime/auxiliary/.venv/Scripts/python.exe',
    'auxiliary_manifest': 'runtime/auxiliary/manifest.json',
    'translation_model': 'runtime/auxiliary/translation',
    'asr_model': 'runtime/auxiliary/asr',
}


def setup_config(existing, model, cpu=False):
    if cpu and model != 'omnivoice':
        raise ValueError('Qwen3 requires a CUDA GPU')
    chosen = qwen_config() if model == 'qwen3' else ModelConfig()
    if existing is None:
        config = RuntimeConfig(models={model: chosen}, default_model=model, **AUXILIARY)
    else:
        config = existing.model_copy(deep=True)
        config.models.setdefault(model, chosen)
        # Move only former standard auxiliary locations; retain user custom paths.
        for key, value in AUXILIARY.items():
            legacy = value.replace('runtime/auxiliary/', 'runtime/omnivoice/')
            if getattr(config, key) == legacy:
                setattr(config, key, value)
    if cpu:
        config.models['omnivoice'].device = 'cpu'
        config.models['omnivoice'].precision = 'float32'
    return RuntimeConfig.model_validate(config.model_dump())


def validate_auxiliary(root=ROOT):
    for path in [AUXILIARY['auxiliary_python'], AUXILIARY['auxiliary_manifest'],
                 AUXILIARY['translation_model']+'/config.json', AUXILIARY['asr_model']+'/model.safetensors']:
        if not (root/path).is_file():
            raise ValueError('Independent auxiliary components are incomplete. Run setup.bat.')
    folder = root/AUXILIARY['translation_model']
    if not any((folder/name).is_file() for name in ['pytorch_model.bin', 'model.safetensors']):
        raise ValueError('Translation weights are missing. Run setup.bat.')
    manifest = json.loads((root/AUXILIARY['auxiliary_manifest']).read_text(encoding='utf-8'))
    if not all(manifest.get('models', {}).get(repo) for repo in
               ['Helsinki-NLP/opus-mt-ja-en', 'openai/whisper-large-v3-turbo']):
        raise ValueError('Auxiliary model revisions are missing. Run setup.bat.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['qwen3', 'omnivoice'], required=True)
    parser.add_argument('--cpu', action='store_true')
    args = parser.parse_args(argv)
    existing = load_config() if CONFIG_PATH.exists() else None
    config = setup_config(existing, args.model, args.cpu)
    validate_auxiliary()
    if args.model == 'qwen3':
        validate_install(existing)
    else:
        from speech.backends.omnivoice import OmniVoiceBackend
        if not OmniVoiceBackend.installed(config.models['omnivoice']):
            raise ValueError('OmniVoice components are missing. Run setup_omnivoice.bat.')
    save_config(config)
    print('Installed components registered. Existing model selection, voices and history were preserved.')


if __name__ == '__main__':
    main()
