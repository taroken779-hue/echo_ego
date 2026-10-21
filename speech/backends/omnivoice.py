"""OmniVoice implementation; its dependencies are imported only in its worker."""
import hashlib
import json
import os
from pathlib import Path
import time
from configuration import data_dir
from speech.backends.base import Backend, ROOT
from speech.audio import audio_result


class OmniVoiceBackend(Backend):
    capabilities = {
        "version": 1, "label": "OmniVoice", "languages": ["ja", "en"], "stream": False,
        "repositories": ["k2-fsa/OmniVoice", "eustlb/higgs-audio-v2-tokenizer"],
        "reference": {"required": True, "transcript_required": True, "min_seconds": 3, "max_seconds": 10},
        "voice_design": True, "speed": {"minimum": .7, "maximum": 1.5},
        "settings": {"num_step": {"type": "integer", "enum": [16, 32], "default": 32, "label": "生成ステップ"}}}

    def __init__(self, *args):
        super().__init__(*args)
        self.model = None
        self.prompts = {}

    def load(self):
        import torch
        torch.set_num_threads(4)
        if self.model is None:
            from omnivoice import OmniVoice
            self.model = OmniVoice.from_pretrained(str(ROOT / self.config.model_path), device_map=self.config.device,
                dtype=getattr(torch, self.config.precision), attn_implementation="sdpa")
        cuda = torch.cuda.is_available()
        return {"hardware": {"cuda": cuda, "gpu": torch.cuda.get_device_name(0) if cuda else None,
            "vram_gb": round(torch.cuda.get_device_properties(0).total_memory/1024**3, 1) if cuda else 0}}

    def prepare(self, p):
        self.load()
        import soundfile as sf
        import numpy as np
        import torch
        self.validate(p, p.get("reference_language", "ja"), {}, 1.)
        path = Path(p["reference_path"]).resolve()
        allowed = [ROOT / "voices", data_dir() / "design-voices", ROOT / self.runtime.presets_dir]
        if not any(path.is_relative_to(folder.resolve()) for folder in allowed):
            raise ValueError("参照音声の場所が無効です")
        content = path.read_bytes()
        version = hashlib.sha256(content).hexdigest()
        if p.get("wav_sha256") and version != p["wav_sha256"]:
            raise ValueError("参照音声が変更されました。再送してください")
        values, sr = sf.read(path, dtype="float32", always_2d=True)
        start, end = p.get("clip_start_ms", 0), p["clip_end_ms"]
        if start < 0 or end > len(values)*1000/sr+1:
            raise ValueError("参照区間が録音の範囲外です")
        values = values[int(start*sr/1000):int(end*sr/1000)].mean(axis=1)
        if not 3 <= len(values)/sr <= 10 or not np.isfinite(values).all() or np.max(np.abs(values)) < .001:
            raise ValueError("OmniVoiceの参照区間は声を含む3〜10秒にしてください")
        key = hashlib.sha256(content + json.dumps([p["reference_transcript"], start, end, self.identity(self.config), "prompt-v2"], sort_keys=True).encode()).hexdigest()
        folder = data_dir() / "voice-prompts" / self.model_id
        folder.mkdir(parents=True, exist_ok=True)
        if key not in self.prompts:
            from omnivoice import VoiceClonePrompt
            dest = folder / (key + ".pt")
            if dest.exists():
                prompt = VoiceClonePrompt.load(str(dest))
            else:
                prompt = self.model.create_voice_clone_prompt(ref_audio=(torch.from_numpy(values).unsqueeze(0),sr), ref_text=p["reference_transcript"])
                temp = dest.with_suffix(".tmp")
                prompt.save(str(temp))
                os.replace(temp, dest)
            self.prompts[key] = prompt
        if p.get("voice_id"):
            metadata = folder / (key + ".json")
            owners = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else []
            if p["voice_id"] not in owners:
                owners.append(p["voice_id"])
                metadata.write_text(json.dumps(owners), encoding="utf-8")
        return {"key": key, "wav_sha256": version}

    def synthesize(self, p):
        settings = self.validate(p, p["language"], p["settings"], p["speed"])
        self.load()
        started = time.perf_counter()
        ref = self.prepare(p)
        reference_ms = (time.perf_counter()-started)*1000
        prompt = self.prompts[ref["key"]]
        duration = self.model._estimate_target_tokens(p["text"], prompt.ref_text, prompt.ref_audio_tokens.shape[-1],p["speed"]) / self.model.audio_tokenizer.config.frame_rate
        if duration > 30 or len(self.model.text_tokenizer.encode(p["text"])) > 2048:
            raise ValueError("発話文が長すぎます。短く分けて入力してください")
        values = self.model.generate(text=p["text"], language=p["language"], voice_clone_prompt=prompt,
            **settings, speed=p["speed"], normalize_text=False)[0]
        return audio_result(values, int(self.model.sampling_rate), started, reference_ms)

    def design(self, p):
        self.load()
        import torch
        started = time.perf_counter()
        # Native voice-design vocabulary in the pinned upstream implementation.
        instructions = {"calm_male": "male, middle-aged, low pitch", "calm_female": "female, middle-aged, moderate pitch",
            "bright_male": "male, young adult, moderate pitch", "bright_female": "female, young adult, high pitch"}
        with torch.random.fork_rng(devices=[torch.cuda.current_device()] if self.config.device == "cuda" else []):
            torch.manual_seed(p["seed"])
            values = self.model.generate(text=p["text"], language="ja", instruct=instructions[p["style"]], num_step=32, normalize_text=False)[0]
        return audio_result(values, int(self.model.sampling_rate), started)
