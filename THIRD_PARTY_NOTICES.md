# Third-party components

Echo Ego's LICENSE covers its own application source. Models, upstream software and user recordings retain their own terms. This source distribution does not bundle model weights or third-party recordings.

- PyTorch and Python ecosystem packages: installed into separate application and backend environments from requirements.txt and requirements-omnivoice.lock.txt; their licenses remain applicable.
- Echo Ego icons and gear decoration are original SVG assets. Palette inspiration: https://tarokenkoubou.com/ . No site logo, font files, photographs or third-party recordings are bundled.

Use only recordings you own or have permission to use. Consult the installed models and codecs for their individual terms. Voice design presets are generated locally and are not representations of specific people.

## Current model and auxiliary services

OmniVoiceコード（k2-fsa/OmniVoice）はApache-2.0、公開モデル重みは提供元モデルカードでCC-BY-NCとされます。音声Codecはeustlb/higgs-audio-v2-tokenizer、翻訳モデルはHelsinki-NLP/opus-mt-ja-en（Apache-2.0）を別途取得します。実際の取得revisionはローカルmanifestへ記録し、各モデルのLICENSE/モデルカードを同梱された取得物から確認してください。モデル・Codec・登録音声はこのソース配布に含めません。

Local ASR uses openai/whisper-large-v3-turbo. Check the downloaded model card and license at the recorded revision. Irodori, its Japanese DACVAE and SilentCipher are no longer installed or used by the application setup. Previously generated local reference WAVs may be retained by their owner; no recordings or weights are bundled in the source ZIP.
