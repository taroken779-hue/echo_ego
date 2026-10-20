"""Portable runtime configuration. Machine-specific paths are never distributed."""
import json
import os
from pathlib import Path
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.local.json"


class RuntimeConfig(BaseModel):
    schema_version: int = 2
    omnivoice_python: str = "runtime/omnivoice/.venv/Scripts/python.exe"
    omnivoice_model: str = "runtime/omnivoice/model"
    translation_model: str = "runtime/omnivoice/translation"
    asr_model: str = "runtime/omnivoice/asr"
    python_path: str = ".venv/Scripts/python.exe"
    source_path: str = "runtime/Irodori-TTS"
    model_path: str = "runtime/models/MF/model.safetensors"
    codec_repo: str = "Aratako/Semantic-DACVAE-Japanese-32dim"
    presets_dir: str = "presets"
    hf_home: str = "runtime/hf-cache"
    device: str = "cuda"
    precision: str = "bf16"
    codec_precision: str = "fp32"
    compile_model: bool = False
    port: int = Field(default=8100, ge=1024, le=65535)
    offline: bool = True
    preload: bool = True

    @model_validator(mode="after")
    def supported(self):
        if self.device not in {"cuda", "cpu"}:
            raise ValueError("device must be cuda or cpu")
        if self.precision not in {"fp32", "bf16"} or self.codec_precision not in {"fp32", "bf16"}:
            raise ValueError("precision must be fp32 or bf16")
        if self.device == "cpu" and (self.precision != "fp32" or self.codec_precision != "fp32"):
            raise ValueError("CPUではFP32を選択してください")
        return self


def resolve(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def load_config():
    return RuntimeConfig.model_validate_json(CONFIG_PATH.read_text(encoding="utf-8-sig")) if CONFIG_PATH.exists() else RuntimeConfig()


def save_config(config):
    if CONFIG_PATH.exists() and not CONFIG_PATH.with_suffix(".v1-backup.json").exists():
        CONFIG_PATH.with_suffix(".v1-backup.json").write_bytes(CONFIG_PATH.read_bytes())
    temp = CONFIG_PATH.with_suffix(".tmp")
    temp.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temp, CONFIG_PATH)


def data_dir():
    return Path(os.environ.get("ECHO_EGO_DATA_DIR", str(ROOT / "data"))).resolve()
