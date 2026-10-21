"""Backend contract v1, shared input validation and provenance."""
import hashlib
import json
from pathlib import Path
from speech.errors import ReferenceNotReady

ROOT = Path(__file__).resolve().parents[2]


class Backend:
    capabilities = {}

    @classmethod
    def validate(cls, reference, language, settings, speed):
        caps = cls.capabilities
        if language not in caps["languages"]:
            raise ValueError("選択した音声モデルはこの言語に対応していません")
        options = caps["settings"]
        if set(settings) - set(options):
            raise ValueError("この音声モデルに対応しない生成設定です")
        effective = {key: spec["default"] for key, spec in options.items()}
        effective.update(settings)
        for key, value in effective.items():
            spec = options[key]
            expected = {"integer": int, "number": (int, float), "boolean": bool, "string": str}[spec["type"]]
            if not isinstance(value, expected) or (spec["type"] in {"integer", "number"} and isinstance(value, bool)):
                raise ValueError("生成設定の型が無効です")
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError("生成設定の値が無効です")
            if isinstance(value, (int, float)):
                import math
                if not math.isfinite(value) or value < spec.get("minimum", value) or value > spec.get("maximum", value):
                    raise ValueError("生成設定の範囲が無効です")
        limits = caps.get("speed")
        import math
        if not math.isfinite(speed) or (limits is None and speed != 1) or (limits and not limits["minimum"] <= speed <= limits["maximum"]):
            raise ValueError("この音声モデルに対応しない話速です")
        ref = caps["reference"]
        # Configuration validation passes None; speech validation always supplies a reference dict.
        if ref["required"] and reference is not None:
            if not reference.get("reference_path"):
                raise ReferenceNotReady("参照音声が必要です")
            if ref["transcript_required"] and not reference.get("reference_transcript", "").strip():
                raise ReferenceNotReady("声の参照区間・文字起こしを保存してください")
            start, end = reference.get("clip_start_ms", 0), reference.get("clip_end_ms")
            if end is None or not ref["min_seconds"] * 1000 <= end - start <= ref["max_seconds"] * 1000:
                raise ReferenceNotReady("選択モデルの参照区間の長さを確認してください")
        return effective

    @classmethod
    def installed(cls, config):
        return (ROOT / config.python_path).is_file() and (ROOT / config.model_path / "model.safetensors").is_file()

    @classmethod
    def identity(cls, config):
        path = ROOT / config.model_path / "model.safetensors"
        manifest_path = ROOT / config.manifest_path
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        # Only TTS assets affect TTS provenance; ASR/translation are independent.
        manifest = {"source_revision": manifest.get("source_revision"), "models": {
            key: value for key, value in manifest.get("models", {}).items() if key in cls.capabilities.get("repositories", [])}}
        import inspect
        files = [Path(__file__), Path(inspect.getfile(cls)), ROOT / "speech/worker.py", ROOT / "speech/audio.py"]
        digest = hashlib.sha256(b"".join(p.read_bytes() for p in files if p.exists())).hexdigest()
        return {"backend": config.backend, "model_path": config.model_path, "model_mtime": path.stat().st_mtime_ns if path.exists() else 0,
                "manifest": manifest, "adapter_sha256": digest, "device": config.device, "precision": config.precision}

    def __init__(self, model_id, config, runtime):
        self.model_id, self.config, self.runtime = model_id, config, runtime

    def load(self):
        raise NotImplementedError

    def prepare(self, reference):
        raise NotImplementedError

    def synthesize(self, request):
        raise NotImplementedError

    def design(self, request):
        raise ValueError("選択モデルは標準音声の新規作成に対応していません")
