"""Private loopback inference worker. Launched and authenticated by runtime.py."""
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from configuration import RuntimeConfig, data_dir

CONFIG = RuntimeConfig.model_validate_json(os.environ["ECHO_WORKER_CONFIG"])
ENGINE = sys.argv[1]
TOKEN = os.environ["ECHO_WORKER_TOKEN"]
model = None
translator = None
prompts = {}


def load():
    global model
    if model is not None:
        return loaded_info()
    import torch
    torch.set_num_threads(4)
    if ENGINE == "irodori":
        sys.path.insert(0, str(ROOT / CONFIG.source_path))
        os.environ["HF_HOME"] = str(ROOT / CONFIG.hf_home)
        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey
        model = InferenceRuntime.from_key(RuntimeKey(checkpoint=str(ROOT / CONFIG.model_path), codec_repo=CONFIG.codec_repo,
                model_device=CONFIG.device, codec_device=CONFIG.device, model_precision=CONFIG.precision,
                codec_precision=CONFIG.codec_precision, compile_model=CONFIG.compile_model))
        return loaded_info()
    from omnivoice import OmniVoice
    model = OmniVoice.from_pretrained(str(ROOT / CONFIG.omnivoice_model), device_map=CONFIG.device,
                dtype=torch.float16 if CONFIG.device == "cuda" else torch.float32, attn_implementation="sdpa")
    return loaded_info()


def loaded_info():
    import torch
    cuda = torch.cuda.is_available()
    return {"watermark": bool(model.watermarker.ready) if ENGINE == "irodori" else False,
            "hardware":{"cuda":cuda,"gpu":torch.cuda.get_device_name(0) if cuda else None,
                        "vram_gb":round(torch.cuda.get_device_properties(0).total_memory/1024**3,1) if cuda else 0}}


def audio_result(samples, sr, started, reference_ms=0):
    import numpy as np
    import soundfile as sf
    values = np.asarray(samples, dtype=np.float32).squeeze()
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or len(values) / sr > 30:
        raise ValueError("合成音声の形式または長さが不正です（30秒以内）")
    peak = float(np.max(np.abs(values)))
    signal = np.flatnonzero(np.abs(values) > max(.001, peak * .02))
    if not len(signal):
        raise ValueError("合成音声に声がありません")
    out = io.BytesIO()
    sf.write(out, values, sr, format="WAV", subtype="PCM_16")
    return {"audio": base64.b64encode(out.getvalue()).decode(), "headers": {
        "X-Synthesis-Ms": f"{(time.perf_counter()-started)*1000:.1f}", "X-Reference-Ms": f"{reference_ms:.1f}",
        "X-First-Signal-Ms": f"{signal[0]/sr*1000:.1f}", "X-Audio-Duration-Ms": f"{len(values)/sr*1000:.1f}",
        "X-Generated-At": datetime.now(timezone.utc).isoformat(), "Cache-Control": "no-store"}}


def prepare(p):
    load()
    import soundfile as sf
    import numpy as np
    import torch
    path = Path(p["reference_path"]).resolve()
    # Only the controller supplies this path; still restrict it to configured voice roots.
    allowed = [ROOT / "voices", data_dir() / "design-voices", ROOT / CONFIG.presets_dir]
    if not any(path.is_relative_to(folder.resolve()) for folder in allowed):
        raise ValueError("参照音声の場所が無効です")
    content = path.read_bytes()
    version = hashlib.sha256(content).hexdigest()
    if p.get("wav_sha256") and version != p["wav_sha256"]:
        raise ValueError("参照音声が変更されました。再送してください")
    if ENGINE == "irodori":
        signature = hashlib.sha256((version + CONFIG.model_path + CONFIG.codec_repo).encode()).hexdigest()
        dest = data_dir() / "latents" / (signature + ".pt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            values, sr = sf.read(path, dtype="float32", always_2d=True)
            values = values[:sr*30].mean(axis=1)
            with torch.inference_mode():
                latent = model.codec.encode_waveform(torch.from_numpy(values).reshape(1,1,-1), sample_rate=sr, normalize_db=-16., ensure_max=True)
            torch.save(latent.squeeze(0).cpu(), dest)
        return {"key": str(dest), "wav_sha256": version}
    transcript = p.get("reference_transcript", "").strip()
    if not transcript:
        raise ValueError("OmniVoice用に参照音声の文字起こしを保存してください")
    values, sr = sf.read(path, dtype="float32", always_2d=True)
    start, end = p.get("clip_start_ms", 0), p.get("clip_end_ms")
    stop = int(end*sr/1000) if end is not None else min(len(values), sr*10)
    values = values[int(start*sr/1000):stop].mean(axis=1)
    if not 3 <= len(values)/sr <= 10 or not np.isfinite(values).all() or np.max(np.abs(values)) < .001:
        raise ValueError("OmniVoiceの参照区間は声を含む3〜10秒にしてください")
    manifest = (ROOT / "runtime/omnivoice/manifest.json").read_bytes()
    key = hashlib.sha256(content + json.dumps([transcript,start,end,hashlib.sha256(manifest).hexdigest(),"prompt-v1"],ensure_ascii=False).encode()).hexdigest()
    if key not in prompts:
        from omnivoice import VoiceClonePrompt
        folder = data_dir() / "voice-prompts" / "omnivoice"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / (key + ".pt")
        if dest.exists():
            prompt = VoiceClonePrompt.load(str(dest))
        else:
            prompt = model.create_voice_clone_prompt(ref_audio=(torch.from_numpy(values).unsqueeze(0),sr), ref_text=transcript)
            temp = dest.with_suffix(".tmp")
            prompt.save(str(temp))
            os.replace(temp, dest)
        prompts[key] = prompt
    if p.get("voice_id"):
        metadata = data_dir()/"voice-prompts"/"omnivoice"/(key+".json")
        owners = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else []
        if p["voice_id"] not in owners:
            owners.append(p["voice_id"])
            metadata.write_text(json.dumps(owners),encoding="utf-8")
    return {"key": key, "wav_sha256": version}


def synthesize(p):
    load()
    import soundfile as sf
    started = time.perf_counter()
    if p.get("design_caption"):
        from irodori_tts.inference_runtime import SamplingRequest
        result = model.synthesize(SamplingRequest(text=p["text"], caption=p["design_caption"], no_ref=True, seed=p["seed"], num_steps=4,max_seconds=15), log_fn=lambda _: None)
        return audio_result(result.audio.detach().float().cpu().numpy(),result.sample_rate,started)
    ref = prepare(p)
    reference_ms = (time.perf_counter()-started)*1000
    if ENGINE == "irodori":
        from irodori_tts.inference_runtime import SamplingRequest
        result = model.synthesize(SamplingRequest(text=p["text"],ref_latent=ref["key"],num_steps=p["steps"],duration_scale=1/p["speed"],max_seconds=30),log_fn=lambda _: None)
        return audio_result(result.audio.detach().float().cpu().numpy(),result.sample_rate,started,reference_ms)
    prompt = prompts[ref["key"]]
    # Use the same duration estimator as generation, before allocating target tensors.
    duration = model._estimate_target_tokens(p["text"], prompt.ref_text, prompt.ref_audio_tokens.shape[-1],p["speed"]) / model.audio_tokenizer.config.frame_rate
    if duration > 30:
        raise ValueError("音声が30秒を超える見込みです。短く分けて入力してください")
    if len(model.text_tokenizer.encode(p["text"])) > 2048:
        raise ValueError("発話文がモデルの入力上限を超えています")
    values = model.generate(text=p["text"], language=p["language"], voice_clone_prompt=prompt,
            num_step=p["steps"], speed=p["speed"], normalize_text=False)[0]
    return audio_result(values,model.sampling_rate,started,reference_ms)


def translate(p):
    global translator
    if translator is None:
        from transformers import MarianMTModel, MarianTokenizer
        path = str(ROOT / CONFIG.translation_model)
        translator = (MarianTokenizer.from_pretrained(path, local_files_only=True), MarianMTModel.from_pretrained(path, local_files_only=True).eval())
    import torch
    tokenizer, translation_model = translator
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length","0"))
            if size > 100000:
                raise ValueError("要求が大きすぎます")
            payload = json.loads(self.rfile.read(size))
            action = self.path.strip("/")
            result = {"load":lambda:load(),"synthesize":lambda:synthesize(payload),"prepare-voice":lambda:prepare(payload),
                      "translate":lambda:translate(payload),"health":lambda:{"loaded":model is not None}}[action]()
            raw = json.dumps(result,ensure_ascii=False).encode()
            self.send_response(200)
        except Exception as exc:
            # Frame locations and exception type only: never persist speech text or transcripts.
            folder = ROOT / ".runtime"
            folder.mkdir(exist_ok=True)
            frames = [(f.filename,f.lineno,f.name) for f in traceback.extract_tb(exc.__traceback__)]
            with (folder / (ENGINE+"-errors.jsonl")).open("a",encoding="utf-8") as handle:
                handle.write(json.dumps({"type":type(exc).__name__,"frames":frames})+"\n")
            own_validation = isinstance(exc,ValueError) and bool(frames) and Path(frames[-1][0]).resolve() == Path(__file__).resolve()
            error = {"error":"invalid_input","message":str(exc)} if own_validation else {"error":type(exc).__name__}
            raw = json.dumps(error,ensure_ascii=False).encode()
            self.send_response(422 if own_validation else 500)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1",0),Handler)
    print(server.server_port,flush=True)
    # Do not leave orphan inference processes after the controller exits/crashes.
    import threading
    parent = os.getppid()
    def watch_parent():
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32",use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p,ctypes.c_ulong]
            handle = kernel.OpenProcess(0x100000,False,parent)
            if handle:
                kernel.WaitForSingleObject(handle,0xFFFFFFFF)
                os._exit(0)
        else:
            while os.getppid() == parent:
                time.sleep(1)
            os._exit(0)
    threading.Thread(target=watch_parent,daemon=True).start()
    server.serve_forever()
