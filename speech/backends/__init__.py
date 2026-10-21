"""Explicit, trusted backend registry. No inference imports in the controller."""
from speech.backends.omnivoice import OmniVoiceBackend

BACKENDS = {"omnivoice": OmniVoiceBackend}


def get_backend(name):
    try:
        return BACKENDS[name]
    except KeyError:
        raise ValueError("未対応の音声バックエンドです") from None
