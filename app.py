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
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from reading_dictionary import Dictionary, Conflict, apply as apply_reading
from speech.runtime import RuntimeManager
from speech.service import SpeechService, SpeechRequest, VoiceReference, AutoReference
from speech.reference import DESIGN_TRANSCRIPT
from speech.jobs import JobError
import base64
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
manager = RuntimeManager(config)
gate = manager.lock
dictionary = Dictionary(store)


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


def ensure_design(voice):
    path = resolve_voice(voice)
    if voice.startswith("design:") and not path.exists():
        name = voice.partition(":")[2]
        with gate:
            manager.activate("irodori")
            result = manager.workers["irodori"].call("synthesize", {
                "text": DESIGN_TRANSCRIPT,
                "design_caption": DESIGNS[name][1], "seed": 20261004 + list(DESIGNS).index(name)})
            path.write_bytes(base64.b64decode(result["audio"]))
    return path


def generate(text, voice, steps, speed):
    path = ensure_design(voice)
    manager.activate("irodori")
    result = manager.workers["irodori"].call("synthesize", {"text":text,"reference_path":str(path),"steps":steps,"speed":speed},timeout=60)
    return base64.b64decode(result["audio"]),result["headers"]


def initialize():
    try:
        with gate:
            prefs = store.preferences()
            engine = prefs.japanese_engine if prefs.mode == "ja" else "omnivoice"
            manager.activate(engine)
            available = {v["id"] for v in voices()}
            voice = store.preferences().voice
            if engine == "irodori":
                generate("こんにちは。",voice if voice in available else "design:calm_male",4,1.)
        state.update(phase="ready",message="準備完了")
    except Exception:
        state.update(phase="error",message="モデルを読み込めません。環境設定を確認してください")


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(asyncio.to_thread(initialize)) if config.preload else None
    if not config.preload:
        state.update(phase="idle", message="設定からモデルを読み込んでください")
    yield
    service.jobs.close()
    manager.close()
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
    return FileResponse(ROOT / "static" / "index.html",headers={"Cache-Control":"no-store"})


@app.get("/api/status")
def status():
    return {"app": "echo-ego-prototype", **state, "model": "Irodori-TTS-v4.1-Small-MF", "precision": config.precision.upper(), "device": config.device, "watermark": bool(manager.status["irodori"].get("watermark")), "steps": 4, "voices": voices()}


class Speech(BaseModel):
    text: str = Field(min_length=1, max_length=160)
    voice: str
    steps: int = Field(default=4)
    speed: float = Field(default=1.0, ge=0.7, le=1.5)
    use_cache: bool = False


def spoken_text(text):
    value = dictionary.get()
    return apply_reading(text,value["entries"],value["revision"])["speech_text"]


def speech_key(payload, text):
    path = resolve_voice(payload.voice)
    voice_version = path.stat().st_mtime_ns if path.exists() else DESIGNS[payload.voice.partition(":")[2]][1]
    identity = [text, payload.voice, voice_version, payload.steps, payload.speed, str(MODEL), MODEL.stat().st_mtime_ns if MODEL.exists() else 0, config.model_dump(), bool(manager.status["irodori"].get("watermark")), "cache-v1"]
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@app.post("/api/speech")
def speak(payload: Speech):
    try:
        text = spoken_text(payload.text.strip())
    except ValueError as exc:
        raise HTTPException(422,str(exc))
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
        service.jobs.cancel_voice(voice_id)
        voice_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        path.unlink()
        with store.connect() as db:
            db.execute("DELETE FROM voice_profiles WHERE id=?",(voice_id,))
        service.preparations.pop(voice_id,None)
        for metadata in (data_dir()/"voice-prompts"/"omnivoice").glob("*.json"):
            owners = json.loads(metadata.read_text(encoding="utf-8"))
            if voice_id in owners:
                owners.remove(voice_id)
                if owners:
                    metadata.write_text(json.dumps(owners),encoding="utf-8")
                else:
                    metadata.with_suffix(".pt").unlink(missing_ok=True)
                    metadata.unlink()
        manager.workers["omnivoice"].stop()
        if manager.active == "omnivoice": manager.active = None
        store.remove_voice(voice_id)
        # Latents hold biometric voice features. Clear them with the recording.
        latent_key = hashlib.sha256((voice_hash + config.model_path + config.codec_repo).encode()).hexdigest()
        (CACHE/(latent_key+".pt")).unlink(missing_ok=True)
    finally:
        gate.release()
    return {"ok": True}


@app.get("/api/preferences")
def preferences():
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = store.preferences().model_dump()
        result["dictionary"] = dictionary.projection(dictionary.get(db))
        return JSONResponse(result,headers={"ETag":dictionary.etag()})


@app.put("/api/preferences")
def save_preferences(payload: Preferences, request: Request):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = dictionary.get(db)
        incoming = [r.model_dump() for r in payload.dictionary]
        if incoming != dictionary.projection(current):
            etag = request.headers.get("if-match")
            if etag is None: raise HTTPException(428,"設定を再読み込みしてから辞書を保存してください")
            if etag != dictionary.etag(): raise HTTPException(412,"設定が別の画面で更新されました")
            old = {e["surface"]:e for e in current["entries"] if e["match_mode"]=="substring"}
            entries = [{**old.get(r["surface"],{}),**r} for r in incoming]
            entries += [e for e in current["entries"] if e["match_mode"]=="whole_text"]
            try: dictionary.update(entries,current["revision"],db)
            except ValueError as exc: raise HTTPException(422,str(exc))
        db.execute("INSERT OR REPLACE INTO settings VALUES (1,?)",(payload.model_dump_json(),))
        if not payload.history_enabled: db.execute("DELETE FROM history")
    store.prune()
    result = payload.model_dump()
    result["dictionary"] = dictionary.projection(dictionary.get())
    return JSONResponse(result,headers={"ETag":dictionary.etag()})


class HistoryItem(BaseModel):
    id: uuid.UUID
    text: str = Field(min_length=1, max_length=160)
    voice: str = Field(max_length=100)
    generatedAt: datetime
    timing: dict[str, float]
    speech_text: str | None = Field(default=None,max_length=640)
    translated_text: str | None = Field(default=None,max_length=640)
    engine: str | None = None
    reading_revision: int | None = None
    model_identity: dict | None = None
    voice_revision: int | None = None


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
    hardware = next((value["hardware"] for value in manager.status.values() if value.get("hardware")), {"cuda":False,"gpu":None,"vram_gb":0})
    return {"config":config.model_dump(),"saved":load_config().model_dump(),"diagnostics":{**hardware,"model_exists":MODEL.is_file(),"source_exists":resolve(config.source_path).is_dir(),"data_dir":str(data_dir())}}


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
    service.jobs.close()
    manager.close()
    threading.Timer(.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"ok": True}


MANUALS = {"user": "USER_GUIDE.md", "setup": "SETUP.md", "release": "DISTRIBUTION.md", "omni": "OMNIVOICE_GUIDE.md", "discord": "DISCORD_GUIDE.md"}


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


service = SpeechService(store,dictionary,manager,resolve_voice)


@app.exception_handler(JobError)
async def job_error(request, exc):
    return JSONResponse({"detail":str(exc)},status_code=exc.status)


@app.get("/api/v2/engines")
def engines():
    return {kind:{**manager.status[kind],"installed":manager.installed(kind),"languages":["ja"] if kind=="irodori" else ["ja","en"],"stream":False} for kind in manager.workers}


@app.get("/api/v2/reading-dictionary")
def get_dictionary():
    return dictionary.get()


class DictionaryUpdate(BaseModel):
    expected_revision: int
    entries: list[dict] = Field(max_length=100)


@app.put("/api/v2/reading-dictionary")
def put_dictionary(value: DictionaryUpdate):
    try: return dictionary.update(value.entries,value.expected_revision)
    except Conflict as exc: raise HTTPException(409,str(exc))
    except ValueError as exc: raise HTTPException(422,str(exc))


class ReadingPreview(BaseModel):
    text: str = Field(min_length=1,max_length=160)
    mode: str = Field(default="ja",pattern="^(ja|ja_to_en)$")
    use_dictionary: bool = True
    draft_entries: list[dict] | None = Field(default=None,max_length=100)


@app.post("/api/v2/reading-preview")
def preview_reading(value: ReadingPreview):
    from reading_dictionary import validate_entries
    current = dictionary.get()
    try:
        entries = validate_entries(value.draft_entries,current["entries"]) if value.draft_entries is not None else current["entries"]
        return apply_reading(value.text,entries,None if value.draft_entries is not None else current["revision"],value.mode,value.use_dictionary)
    except ValueError as exc: raise HTTPException(422,str(exc))


@app.post("/api/v2/speech-jobs",status_code=202)
def create_job(value: SpeechRequest):
    try: return service.public_job(service.jobs.submit(value.model_dump(),service.snapshot))
    except ValueError as exc:
        if isinstance(exc,JobError): raise
        raise HTTPException(422,str(exc))


@app.get("/api/v2/speech-jobs/{job_id}")
def get_job(job_id: str):
    return service.public_job(service.jobs.get(job_id))


@app.get("/api/v2/speech-jobs/{job_id}/audio")
def job_audio(job_id: str):
    audio,headers = service.jobs.audio(job_id)
    return Response(audio,media_type="audio/wav",headers=headers)


@app.delete("/api/v2/speech-jobs/{job_id}")
def cancel_job(job_id: str):
    return service.jobs.cancel(job_id)


@app.post("/api/v2/clients/{client_id}/cancel")
def cancel_client(client_id: str):
    return service.jobs.cancel_client(client_id)


@app.get("/api/v2/voices/{voice_id}/reference")
def voice_reference(voice_id: str):
    path = resolve_voice(voice_id)
    profile = service.profile(voice_id)
    changed = bool(profile.get("wav_sha256") and path.exists() and
                   profile["wav_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest())
    return {**profile,"duration_seconds":sf.info(path).duration if path.exists() else None,
            "reference_audio_changed":changed}


@app.put("/api/v2/voices/{voice_id}/reference")
def save_reference(voice_id: str,value: VoiceReference):
    try: return service.save_profile(voice_id,value)
    except ValueError as exc: raise HTTPException(422,str(exc))


@app.post("/api/v2/voices/{voice_id}/auto-reference",status_code=202)
def auto_reference(voice_id: str,value: AutoReference):
    try:
        ensure_design(voice_id)
        return service.transcribe_reference(voice_id,value)
    except ValueError as exc:
        if isinstance(exc,JobError): raise
        raise HTTPException(422,str(exc))


@app.get("/api/v2/voices/{voice_id}/auto-reference")
def auto_reference_status(voice_id: str):
    resolve_voice(voice_id)
    return service.transcriptions.get(voice_id,{"state":"idle"})


@app.post("/api/v2/voices/{voice_id}/standard-reference")
def standard_reference(voice_id: str):
    if voice_id not in {"design:"+name for name in DESIGNS}:
        raise HTTPException(400,"標準の声を選択してください")
    ensure_design(voice_id)
    return voice_reference(voice_id)


@app.post("/api/v2/voices/{voice_id}/prepare",status_code=202)
def prepare_reference(voice_id: str):
    try: return service.prepare_voice(voice_id)
    except ValueError as exc:
        if isinstance(exc,JobError): raise
        raise HTTPException(422,str(exc))


@app.get("/api/v2/voices/{voice_id}/preparation")
def reference_status(voice_id: str):
    resolve_voice(voice_id)
    return service.preparations.get(voice_id,{"state":"unprepared"})
