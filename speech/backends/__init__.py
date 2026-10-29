"""Explicit, trusted backend registry. No inference imports in the controller."""
from speech.backends.omnivoice import OmniVoiceBackend
from speech.backends.qwen3_fast import Qwen3FastBackend

BACKENDS = {"omnivoice": OmniVoiceBackend, "qwen3_fast": Qwen3FastBackend}


def get_backend(name):
    try:
        return BACKENDS[name]
    except KeyError:
        raise ValueError("未対応の音声バックエンドです") from None
