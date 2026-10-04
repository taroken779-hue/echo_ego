import asyncio
import hashlib
import io
import json
import html
import logging
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from configuration import load_config, save_config, resolve, data_dir, RuntimeConfig
from store import Store, Preferences

ROOT = Path(__file__).resolve().parent
config = load_config()
store = Store(data_dir())
PRESETS = resolve(config.presets_dir)
CUSTOM = ROOT / "voices"
CACHE = data_dir() / "latents"
DESIGNS = {"calm_male": ("男性・落ち着いた声", "落ち着いた中年男性の声。穏やかで明瞭な標準語。"), "calm_female": ("女性・落ち着いた声", "落ち着いた成人女性の声。穏やかで明瞭な標準語。"), "bright_male": ("男性・明るい声", "若い成人男性の声。明るく親しみやすい標準語。"), "bright_female": ("女性・明るい声", "若い成人女性の声。明るく親しみやすい標準語。")}
DESIGN_DIR = data_dir() / "design-voices"
DESIGN_DIR.mkdir(parents=True, exist_ok=True)
CUSTOM.mkdir(exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)
MODEL = resolve(config.model_path)
state = {"phase": "loading", "message": "モデルを読み込んでいます", "busy": False}
runtime = None
gate = threading.Lock()


def voices():
    items = [{"id": "design:" + key, "name": info[0], "kind": "design"} for key, info in DESIGNS.items()]
    for prefix, folder in [("preset", PRESETS), ("custom", CUSTOM)]:
        for path in sorted(folder.glob("*.wav")):
            items.append({"id": f"{prefix}:{path.stem}", "name": path.stem, "kind": prefix})
    metadata = store.voice_meta()
    for item in items:
        meta = metadata.get(item["id"], {})
        item["name"] = meta.get("name", item["name"])
        item["favorite"] = bool(meta.get("favorite", False))
    return sorted(items, key=lambda v: not v["favorite"])


def resolve_voice(voice):
    kind, _, name = voice.partition(":")
    if kind == "design" and name in DESIGNS:
        return DESIGN_DIR / (name + ".wav")
    if kind not in {"preset", "custom"} or not re.fullmatch(r"[\w-]+", name):
        raise HTTPException(400, "音声を選択してください")
    path = (PRESETS if kind == "preset" else CUSTOM) / (name + ".wav")
    if not path.is_file():
        raise HTTPException(404, "登録音声がありません")
    return path


def latent(path):
    signature = str(path) + str(path.stat().st_mtime_ns) + str(MODEL) + config.codec_repo + "normalize=-16;cap=30"
    dest = CACHE / (hashlib.sha256(signature.encode()).hexdigest() + ".pt")
    if not dest.exists():
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        data = data[:sr * 30].mean(axis=1)
        with torch.inference_mode():
            value = runtime.codec.encode_waveform(torch.from_numpy(data).reshape(1, 1, -1), sample_rate=sr, normalize_db=-16.0, ensure_max=True)
        torch.save(value.squeeze(0).cpu(), dest)
    return str(dest)


def generate(text, voice, steps, speed):
    from irodori_tts.inference_runtime import SamplingRequest
    started = time.perf_counter()
    path = resolve_voice(voice)
    if voice.startswith("design:") and not path.exists():
        name = voice.partition(":")[2]
        designed = runtime.synthesize(SamplingRequest(text="こんにちは。お話できてうれしいです。どうぞよろしくお願いします。", caption=DESIGNS[name][1], no_ref=True, seed=20261004 + list(DESIGNS).index(name), num_steps=4, max_seconds=15), log_fn=logging.info)
        sf.write(path, designed.audio.detach().float().cpu().numpy().squeeze(), designed.sample_rate, subtype="PCM_16")
    ref = latent(path)
    reference_ms = (time.perf_counter() - started) * 1000
    result = runtime.synthesize(SamplingRequest(text=text, ref_latent=ref, num_steps=steps, duration_scale=1 / speed, max_seconds=30.0), log_fn=logging.info)
    samples = result.audio.detach().float().cpu().numpy().squeeze()
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise RuntimeError("合成結果が無効です")
    output = io.BytesIO()
    sf.write(output, samples, result.sample_rate, format="WAV", subtype="PCM_16")
    signal = np.flatnonzero(np.abs(samples) > max(0.001, float(np.max(np.abs(samples))) * 0.02))
    first_ms = float(signal[0]) / result.sample_rate * 1000 if len(signal) else -1
    return output.getvalue(), {
        "X-Synthesis-Ms": f"{(time.perf_counter() - started) * 1000:.1f}",
        "X-Reference-Ms": f"{reference_ms:.1f}",
        "X-First-Signal-Ms": f"{first_ms:.1f}",
        "X-Audio-Duration-Ms": f"{len(samples) / result.sample_rate * 1000:.1f}",
        "X-Generated-At": datetime.now(timezone.utc).isoformat(),
        "Cache-Control": "no-store",
    }


def initialize():
    global runtime
    try:
        if runtime is not None:
            runtime = None
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey
        if not MODEL.is_file():
            raise RuntimeError("MFモデルがありません。scripts/download_model.pyを実行してください")
        runtime = InferenceRuntime.from_key(RuntimeKey(checkpoint=str(MODEL), codec_repo=config.codec_repo, model_device=config.device, codec_device=config.device, model_precision=config.precision, codec_precision=config.codec_precision, compile_model=config.compile_model))
        if runtime.model_cfg.flow_parameterization != "meanflow":
            raise RuntimeError("MFモデルとして認識されませんでした")
        state.update(phase="warming", message="最初の音声を生成して準備しています")
        with gate:
            available = {v["id"] for v in voices()}
            voice = store.preferences().voice
            generate("こんにちは。", voice if voice in available else "design:calm_male", 4, 1.0)
        state.update(phase="ready", message="準備完了")
    except Exception as exc:
        logging.exception("Initialization failed")
        state.update(phase="error", message=str(exc))


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(asyncio.to_thread(initialize)) if config.preload else None
    if not config.preload:
        state.update(phase="idle", message="設定からモデルを読み込んでください")
    yield
    # GPU推論はプロセス終了で解放。稼働中の準備タスクをキャンセルして誤表示しない。
    if task and task.done():
        await task


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def local_only(request: Request, call_next):
    if request.headers.get("host") not in {f"127.0.0.1:{config.port}", f"localhost:{config.port}"}:
        return JSONResponse({"detail": "ローカルURLから開いてください"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in {f"http://127.0.0.1:{config.port}", f"http://localhost:{config.port}"}:
        return JSONResponse({"detail": "外部ページからのアクセスは許可していません"}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status():
    return {"app": "echo-ego-prototype", **state, "model": "Irodori-TTS-v4.1-Small-MF", "precision": config.precision.upper(), "device": config.device, "watermark": bool(runtime and runtime.watermarker.ready), "steps": 4, "voices": voices()}


class Speech(BaseModel):
    text: str = Field(min_length=1, max_length=160)
    voice: str
    steps: int = Field(default=4)
    speed: float = Field(default=1.0, ge=0.7, le=1.5)
    use_cache: bool = False


def spoken_text(text):
    readings = sorted(store.preferences().dictionary, key=lambda r: -len(r.surface))
    if not readings:
        return text
    mapping = {r.surface: r.reading for r in readings}
    return re.sub("|".join(re.escape(r.surface) for r in readings), lambda match: mapping[match[0]], text)


def speech_key(payload, text):
    path = resolve_voice(payload.voice)
    voice_version = path.stat().st_mtime_ns if path.exists() else DESIGNS[payload.voice.partition(":")[2]][1]
    identity = [text, payload.voice, voice_version, payload.steps, payload.speed, str(MODEL), MODEL.stat().st_mtime_ns if MODEL.exists() else 0, config.model_dump(), bool(runtime and runtime.watermarker.ready), "cache-v1"]
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@app.post("/api/speech")
def speak(payload: Speech):
    text = spoken_text(payload.text.strip())
    if len(text) > 320:
        raise HTTPException(400, "読み辞書の適用後の文が長すぎます")
    if not re.search(r"[\w\u3040-\u30ff\u3400-\u9fff]", text):
        raise HTTPException(400, "読み上げる文字を入力してください")
    resolve_voice(payload.voice)
    if payload.steps not in {4, 6, 8}:
        raise HTTPException(400, "ステップ数が無効です")
    key = speech_key(payload, text) if payload.use_cache else None
    cached = store.cache(key) if key else None
    if cached:
        audio, headers = cached
        return Response(audio, media_type="audio/wav", headers={**headers, "X-Cached": "1"})
    if state["phase"] != "ready":
        raise HTTPException(503, state["message"])
    if not gate.acquire(blocking=False):
        raise HTTPException(409, "前の音声を生成中です。少し待って再送してください")
    state["busy"] = True
    try:
        audio, headers = generate(text, payload.voice, payload.steps, payload.speed)
        if key:
            # Designed reference is created on first generation; key must use its new version.
            store.save_cache(speech_key(payload, text), audio, headers)
        headers["X-Cached"] = "0"
        return Response(audio, media_type="audio/wav", headers=headers)
    except HTTPException:
        raise
    except Exception:
        logging.exception("Synthesis failed")
        raise HTTPException(500, "音声生成に失敗しました。ログを確認してください")
    finally:
        state["busy"] = False
        gate.release()


@app.post("/api/voices")
async def upload(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() != ".wav":
        raise HTTPException(400, "WAV音声を選択してください")
    raw = await file.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(400, "20MB以内のWAVを選択してください")
    try:
        data, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    except Exception:
        raise HTTPException(400, "WAVを読み込めませんでした")
    if not 1 <= len(data) / sr <= 30 or not np.isfinite(data).all() or np.max(np.abs(data)) < 0.001:
        raise HTTPException(400, "1〜30秒の、声が入ったWAVを選択してください")
    name = "my_voice_" + uuid.uuid4().hex[:8]
    sf.write(CUSTOM / (name + ".wav"), data.mean(axis=1), sr, subtype="PCM_16")
    store.update_voice("custom:" + name, "自分の声 " + datetime.now().strftime("%m/%d %H:%M"), False)
    return {"id": "custom:" + name, "name": name}


class VoiceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    favorite: bool = False


@app.patch("/api/voices/{voice_id}")
def update_voice(voice_id: str, payload: VoiceUpdate):
    resolve_voice(voice_id)
    if not payload.name.strip():
        raise HTTPException(400, "名前を入力してください")
    store.update_voice(voice_id, payload.name.strip(), payload.favorite)
    return {"ok": True}


@app.get("/api/voices/{voice_id}/audio")
def reference_audio(voice_id: str):
    path = resolve_voice(voice_id)
    if not path.exists():
        raise HTTPException(404, "プリセットは最初の発話時に作成されます")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.delete("/api/voices/{voice_id}")
def delete_voice(voice_id: str):
    path = resolve_voice(voice_id)
    if not voice_id.startswith("custom:"):
        raise HTTPException(400, "削除できるのは登録した声だけです")
    if not gate.acquire(False):
        raise HTTPException(409, "生成完了後に削除してください")
    try:
        path.unlink()
        store.remove_voice(voice_id)
        # Latents hold biometric voice features. Clear them with the recording.
        for item in CACHE.glob("*.pt"):
            item.unlink()
    finally:
        gate.release()
    return {"ok": True}


@app.get("/api/preferences")
def preferences():
    return store.preferences()


@app.put("/api/preferences")
def save_preferences(payload: Preferences):
    if payload.dictionary != store.preferences().dictionary:
        store.clear_cache()
    store.save_preferences(payload)
    return payload


class HistoryItem(BaseModel):
    id: uuid.UUID
    text: str = Field(min_length=1, max_length=160)
    voice: str = Field(max_length=100)
    generatedAt: datetime
    timing: dict[str, float]


@app.get("/api/history")
def history_list():
    return store.histories()


@app.post("/api/history")
async def history_save(metadata: str = Form(...), file: UploadFile = File(...)):
    try:
        item = HistoryItem.model_validate_json(metadata)
        if item.generatedAt.tzinfo is None or any(not np.isfinite(v) or v < 0 for v in item.timing.values()):
            raise ValueError("履歴の日時・計測値が不正です")
        raw = await file.read(10 * 1024 * 1024 + 1)
        info = sf.info(io.BytesIO(raw))
        if len(raw) > 10 * 1024 * 1024 or not 0 < info.duration <= 31 or info.format != "WAV":
            raise ValueError("履歴の音声が不正です")
        data = item.model_dump(mode="json")
        data["generatedAt"] = item.generatedAt.astimezone(timezone.utc).isoformat()
        store.save_history(data, raw)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/api/history/{item_id}/audio")
def history_audio(item_id: uuid.UUID):
    audio = store.history_audio(str(item_id))
    if audio is None:
        raise HTTPException(404, "履歴の音声がありません")
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.delete("/api/history")
def clear_history():
    store.delete_history()
    return {"ok": True}


@app.delete("/api/history/{item_id}")
def delete_history(item_id: uuid.UUID):
    store.delete_history(str(item_id))
    return {"ok": True}


@app.delete("/api/cache")
def clear_phrase_cache():
    store.clear_cache()
    return {"ok": True}


@app.get("/api/config")
def runtime_config():
    return {"config": config.model_dump(), "saved": load_config().model_dump(), "diagnostics": {"cuda": torch.cuda.is_available(), "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None, "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1) if torch.cuda.is_available() else 0, "model_exists": MODEL.is_file(), "source_exists": resolve(config.source_path).is_dir(), "data_dir": str(data_dir())}}


@app.put("/api/config")
def update_runtime_config(payload: RuntimeConfig):
    save_config(payload)
    return {"ok": True, "message": "設定を保存しました。stop.batで終了してstart.batで起動すると反映されます。"}


@app.post("/api/runtime/load")
def load_runtime():
    if state["phase"] not in {"idle", "error"}:
        raise HTTPException(409, "モデルは読み込み中か準備済みです")
    state.update(phase="loading", message="モデルを読み込んでいます")
    threading.Thread(target=initialize, daemon=True).start()
    return {"ok": True}


@app.post("/api/shutdown")
def shutdown():
    import signal
    threading.Timer(.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"ok": True}


MANUALS = {"user": "USER_GUIDE.md", "setup": "SETUP.md", "release": "DISTRIBUTION.md"}


@app.get("/api/manual/{name}")
def manual(name: str):
    if name not in MANUALS:
        raise HTTPException(404, "マニュアルがありません")
    # Escape all Markdown text; no script or remote HTML is accepted.
    lines = (ROOT / "docs" / MANUALS[name]).read_text(encoding="utf-8").splitlines()
    result = []
    for line in lines:
        safe = html.escape(line)
        safe = re.sub(r"\[([^\]]+)\]\((https://[^\s)]+)\)", r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', safe)
        if line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 4)
            result.append(f"<h{level}>{safe[level:].strip()}</h{level}>")
        elif line.startswith("- "):
            result.append("<p class='manual-bullet'>• " + safe[2:] + "</p>")
        elif line.strip():
            result.append("<p>" + safe + "</p>")
    return {"html": "\n".join(result)}
