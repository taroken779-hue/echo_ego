import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from configuration import load_config, resolve
config = load_config()
os.environ["HF_HOME"] = str(resolve(config.hf_home))
os.environ["HF_HUB_OFFLINE"] = "0"
from huggingface_hub import snapshot_download

root = Path(__file__).resolve().parents[1]
path = snapshot_download(
    "Aratako/Irodori-TTS-v4.1-Small-MF",
    revision="ccc78f5d480b6e51b69b2d5042a14c4da04fea6e",
    local_dir=root / "runtime" / "models" / "MF",
    cache_dir=root / "runtime" / "download-cache",
    allow_patterns=["model.safetensors", "tokenizer/*", "config.json"],
)
print(path, flush=True)
for repository, revision, patterns in [
    ("Aratako/Semantic-DACVAE-Japanese-32dim", "47376ee24834d7a05a48ebabfe3cde29b3c5e214", ["weights.pth", "README.md"]),
    # SilentCipher calls snapshot_download without allow_patterns. New Hub releases
    # require the complete cached manifest even when only the 44.1k model is used.
    ("sony/silentcipher", "a1c4d021905e0dc5b24be5f68db5fc4dba410ee1", None),
]:
    hub = resolve(config.hf_home) / "hub"
    snapshot_download(repository, revision=revision, cache_dir=hub, allow_patterns=patterns)
    # Upstream runtime asks for main; map that name to the version downloaded above.
    refs = hub / ("models--" + repository.replace("/", "--")) / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(revision, encoding="utf-8")
print("MF model, codec and audio-watermark weights are ready for offline execution.", flush=True)
