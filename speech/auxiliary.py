"""CPU auxiliary services, independent of the selected TTS backend."""
import hashlib
from pathlib import Path
from configuration import data_dir
from speech.reference import select_clip
ROOT = Path(__file__).resolve().parents[1]

class Auxiliary:
    def __init__(self, config):
        self.config = config
        self.translator = None

    def transcribe_reference(self, p):
        # ASR stays on CPU and is released after use. Never download during a request.
        import gc
        import soundfile as sf
        import torch
        import torchaudio
        from transformers import pipeline
        torch.set_num_threads(4)
        path = Path(p["reference_path"]).resolve()
        allowed = [ROOT / "voices", data_dir() / "design-voices", ROOT / self.config.presets_dir]
        if not any(path.is_relative_to(folder.resolve()) for folder in allowed):
            raise ValueError("参照音声の場所が無効です")
        if hashlib.sha256(path.read_bytes()).hexdigest() != p["wav_sha256"]:
            raise ValueError("録音が変更されました。やり直してください")
        asr_path = ROOT / self.config.asr_model
        if not (asr_path / "model.safetensors").is_file():
            raise ValueError("自動文字起こしモデルがありません。setup_omnivoice.batを実行してください")
        values, sr = sf.read(path, dtype="float32", always_2d=True)
        clip, start, end = select_clip(values, sr, p.get("clip_start_ms"), p.get("clip_end_ms"),
            p.get("min_seconds", 3), p.get("max_seconds", 10))
        if sr != 16000:
            clip = torchaudio.functional.resample(torch.from_numpy(clip), sr, 16000).numpy()
        pipe = pipeline("automatic-speech-recognition", model=str(asr_path), device="cpu", dtype=torch.float32)
        try:
            result = pipe({"array":clip,"sampling_rate":16000},
                          generate_kwargs={"language":p["reference_language"],"task":"transcribe"})
            text = result["text"].strip()
            if not text:
                raise ValueError("文字起こしできませんでした。区間を変えてください")
            return {"reference_transcript":text,"reference_language":p["reference_language"],
                    "clip_start_ms":start,"clip_end_ms":end,"wav_sha256":p["wav_sha256"]}
        finally:
            del pipe
            gc.collect()


    def translate(self, p):
        if self.translator is None:
            from transformers import MarianMTModel, MarianTokenizer
            path = str(ROOT / self.config.translation_model)
            self.translator = (MarianTokenizer.from_pretrained(path, local_files_only=True), MarianMTModel.from_pretrained(path, local_files_only=True).eval())
        import torch
        tokenizer, translation_model = self.translator
        encoded = tokenizer(p["text"],return_tensors="pt",truncation=False)
        if encoded.input_ids.shape[-1] > 480:
            raise ValueError("翻訳する文が長すぎます")
        with torch.inference_mode():
            output = translation_model.generate(**encoded,max_new_tokens=256,num_beams=1)
        # Reject incomplete generation rather than speaking a truncated sentence.
        if int(output[0,-1]) != tokenizer.eos_token_id:
            raise ValueError("翻訳が完了しませんでした。文を短くしてください")
        text = tokenizer.decode(output[0],skip_special_tokens=True).strip()
        if not text or len(text)>640:
            raise ValueError("翻訳結果が空か長すぎます")
        return {"text":text}
