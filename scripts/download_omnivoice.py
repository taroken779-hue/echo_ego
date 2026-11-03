"""Download pinned local assets, never recordings. Run with the OmniVoice Python."""
import json
from pathlib import Path
import subprocess
from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / "runtime/omnivoice"
    manifest_path = folder / "manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest = {"source_revision":subprocess.check_output(["git","-C",str(folder/"source"),"rev-parse","HEAD"],text=True).strip(),"models":dict(old.get("models", {}))}
    api = HfApi()
    for repo, target in [("k2-fsa/OmniVoice","model"),("eustlb/higgs-audio-v2-tokenizer","model/audio_tokenizer")]:
        revision = old.get("models",{}).get(repo) or api.model_info(repo).sha
        snapshot_download(repo,revision=revision,local_dir=folder/target,
                          ignore_patterns=["*.bin","*.h5","*.msgpack","*.onnx","*.tflite"] if repo != "Helsinki-NLP/opus-mt-ja-en" else ["*.h5","*.msgpack","*.onnx"])
        manifest["models"][repo] = revision
        # Save progress, so interrupted downloads resume the same revisions.
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print("Optional OmniVoice TTS and codec assets are ready. Auxiliary services are installed separately.")


if __name__ == "__main__":
    main()
