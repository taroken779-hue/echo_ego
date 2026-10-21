"""Portable runtime configuration. Machine-specific paths are never distributed."""
import json
import os
from pathlib import Path
from pydantic import BaseModel, Field, model_validator, ConfigDict

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("ECHO_EGO_CONFIG", str(ROOT / "config.local.json")))


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: str = "omnivoice"
    label: str = "OmniVoice"
    python_path: str = "runtime/omnivoice/.venv/Scripts/python.exe"
    model_path: str = "runtime/omnivoice/model"
    manifest_path: str = "runtime/omnivoice/manifest.json"
    device: str = "cuda"
    precision: str = "float16"
    defaults: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def supported(self):
        if self.device not in {"cuda", "cpu"} or self.precision not in {"float16", "bfloat16", "float32"}:
            raise ValueError("モデルの実行先・精度が無効です")
        if self.device == "cpu" and self.precision != "float32":
            raise ValueError("CPUではfloat32を選択してください")
        return self


class RuntimeConfig(BaseModel):
    schema_version: int = 3
    models: dict[str, ModelConfig] = Field(default_factory=lambda: {"omnivoice": ModelConfig()})
    default_model: str = "omnivoice"
    auxiliary_python: str = "runtime/omnivoice/.venv/Scripts/python.exe"
    auxiliary_manifest: str = "runtime/omnivoice/manifest.json"
    translation_model: str = "runtime/omnivoice/translation"
    asr_model: str = "runtime/omnivoice/asr"
    python_path: str = "runtime/app/.venv/Scripts/python.exe"
    presets_dir: str = "presets"
    port: int = Field(default=8100, ge=1024, le=65535)
    offline: bool = True
    preload: bool = True

    @model_validator(mode="before")
    @classmethod
    def migrate(cls, value):
        if not isinstance(value, dict) or "models" in value:
            return value
        value = dict(value)
        device = value.get("device", "cuda")
        # Validate old CPU/precision combinations before retiring the old fields.
        if device not in {"cuda", "cpu"} or (device == "cpu" and value.get("precision", "fp32") != "fp32"):
            raise ValueError("旧設定の実行先・精度が無効です")
        value["models"] = {"omnivoice": {"backend": "omnivoice", "label": "OmniVoice", "device": device,
            "precision": "float32" if device == "cpu" else "float16",
            "python_path": value.pop("omnivoice_python", "runtime/omnivoice/.venv/Scripts/python.exe"),
            "model_path": value.pop("omnivoice_model", "runtime/omnivoice/model")}}
        value["schema_version"] = 3
        return value

    @model_validator(mode="after")
    def supported(self):
        import re
        if self.default_model not in self.models or any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) for key in self.models):
            raise ValueError("音声モデル構成が無効です")
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
