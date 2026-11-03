# Third-party components

Echo Ego's LICENSE covers its own application source. Models, upstream software and user recordings retain their own terms. This source distribution does not bundle model weights or third-party recordings.

- PyTorch and Python ecosystem packages: installed into separate application, CPU auxiliary and backend environments from requirements.txt, requirements-auxiliary.txt and the optional requirements-omnivoice.lock.txt; their licenses remain applicable.
- Echo Ego icons and gear decoration are original SVG assets. Palette inspiration: https://tarokenkoubou.com/ . No site logo, font files, photographs or third-party recordings are bundled.

Use only recordings you own or have permission to use. Consult the installed models and codecs for their individual terms. Voice design presets are generated locally and are not representations of specific people.

## Current model and auxiliary services

OmniVoiceコード（k2-fsa/OmniVoice）はApache-2.0、公開モデル重みは提供元モデルカードでCC-BY-NCとされます。音声Codecはeustlb/higgs-audio-v2-tokenizer、翻訳モデルはHelsinki-NLP/opus-mt-ja-en（Apache-2.0）を別途取得します。実際の取得revisionはローカルmanifestへ記録し、各モデルのLICENSE/モデルカードを同梱された取得物から確認してください。モデル・Codec・登録音声はこのソース配布に含めません。

Local ASR uses openai/whisper-large-v3-turbo. Check the downloaded model card and license at the recorded revision. Irodori, its Japanese DACVAE and SilentCipher are no longer installed or used by the application setup. Previously generated local reference WAVs may be retained by their owner; no recordings or weights are bundled in the source ZIP.

## Default Qwen3 backend and independent auxiliary services

The default setup installs Qwen3 TTS with a separate CPU environment for Helsinki-NLP/opus-mt-ja-en translation and openai/whisper-large-v3-turbo transcription under runtime/auxiliary. It does not download the OmniVoice model, its source repository or its audio codec. OmniVoice remains an optional installation via setup_omnivoice.bat. Legacy assets are retained during upgrades.

Qwen/Qwen3-TTS-12Hz-0.6B-Base is downloaded separately at revision 5d83992436eae1d760afd27aff78a71d676296fc. Its model card and license remain applicable: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base .

Low-latency inference uses the third-party faster-qwen3-tts 0.5.4 (MIT; Copyright 2026 Andres Marafioti), qwen-tts-hf 0.1.1.post1, Transformers 5.15.1 and PyTorch 2.10.0+cu128 in an isolated environment. This is not the unmodified official Qwen inference pipeline. Consult the installed distributions for their respective licenses. No weights, reference recordings, generated audio or Python environments are included in the source archive.
