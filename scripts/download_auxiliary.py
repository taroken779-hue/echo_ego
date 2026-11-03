"""Download only translation/ASR; reuse verified legacy assets without removal."""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    'Helsinki-NLP/opus-mt-ja-en': ('translation', '0770961a39ba6bd66305b149c3f4110bcafca2e6'),
    'openai/whisper-large-v3-turbo': ('asr', '41f01f3fe87f28c78e2fbf8b568835947dd65ed9'),
}


def download(root=ROOT, downloader=None):
    if downloader is None:
        from huggingface_hub import snapshot_download
        downloader = snapshot_download
    folder = root/'runtime/auxiliary'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/'manifest.json'
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    legacy_folder = root/'runtime/omnivoice'
    legacy_path = legacy_folder/'manifest.json'
    legacy = json.loads(legacy_path.read_text(encoding='utf-8')) if legacy_path.exists() else {}
    manifest = {'source_revision': 'auxiliary-v1', 'models': dict(old.get('models', {}))}
    for repo, (target, pinned) in MODELS.items():
        revision = old.get('models', {}).get(repo) or legacy.get('models', {}).get(repo) or pinned
        dest, source = folder/target, legacy_folder/target
        # Copy only public model directories, never voice recordings or the TTS model.
        if not dest.exists() and source.is_dir() and legacy.get('models', {}).get(repo) == revision:
            shutil.copytree(source, dest)
        # Pin before downloading so an interrupted first download keeps its revision.
        manifest['models'][repo] = revision
        path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        downloader(repo, revision=revision, local_dir=dest,
                   ignore_patterns=['*.h5', '*.msgpack', '*.onnx'] if target == 'translation'
                   else ['*.bin', '*.h5', '*.msgpack', '*.onnx', '*.tflite'])
    print('Independent Japanese-English translation and reference transcription assets are ready.')


if __name__ == '__main__':
    download()
