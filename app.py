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
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Query
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from reading_dictionary import Dictionary, Conflict, apply as apply_reading
from speech.runtime import RuntimeManager
from speech.service import SpeechService, SpeechRequest, VoiceReference, AutoReference
from speech.reference import DESIGN_TRANSCRIPT
from speech.jobs import JobError
from speech.errors import BackendFailure
import base64
from configuration import load_config, save_config, resolve, data_dir, RuntimeConfig
from store import Store, Preferences

ROOT = Path(__file__).resolve().parent
config = load_config()
store = Store(data_dir(), default_model=config.default_model)
PRESETS = resolve(config.presets_dir)
CUSTOM = ROOT / "voices"
DESIGNS = {"calm_male": ("男性・落ち着いた声", "落ち着いた中年男性の声。穏やかで明瞭な標準語。"), "calm_female": ("女性・落ち着いた声", "落ち着いた成人女性の声。穏やかで明瞭な標準語。"), "bright_male": ("男性・明るい声", "若い成人男性の声。明るく親しみやすい標準語。"), "bright_female": ("女性・明るい声", "若い成人女性の声。明るく親しみやすい標準語。")}
DESIGN_DIR = data_dir() / "design-voices"
DESIGN_DIR.mkdir(parents=True, exist_ok=True)
CUSTOM.mkdir(exist_ok=True)
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


def ensure_design(voice, model_id=None):
    path = resolve_voice(voice)
    if voice.startswith("design:") and not path.exists():
        name = voice.partition(":")[2]
        with gate:
            model_id = model_id or store.preferences().model_id
            if not manager.capabilities(model_id)["voice_design"]:
                raise ValueError("選択モデルは標準音声の新規作成に対応していません。録音を登録してください")
            manager.activate(model_id)
            result = manager.call(model_id, "design", {
                "text": DESIGN_TRANSCRIPT,
                "style": name, "seed": 20261004 + list(DESIGNS).index(name)})
            raw = base64.b64decode(result["audio"])
            duration = sf.info(io.BytesIO(raw)).duration
            limits = manager.capabilities(model_id)["reference"]
            if not limits.get("min_seconds", 0) <= duration <= limits.get("max_seconds", 30):
                raise ValueError("標準音声が参照時間の条件を満たしません。再実行するか録音を登録してください")
            temp = path.with_suffix(".tmp")
            temp.write_bytes(raw)
            os.replace(temp, path)
    return path


def initialize():
    try:
        with gate:
            prefs = store.preferences()
            manager.activate(prefs.model_id)
        # Reuse the explicit preparation path; never create/replace a user's reference.
        # Missing references must not prevent the model, settings or manuals from opening.
        try:
            service.prepare_voice(prefs.voice, prefs.model_id)
        except (ValueError, HTTPException):
            pass
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
    model_id = store.preferences().model_id
    model = manager.model(model_id)
    return {"app": "echo-ego-prototype", **state, "model": model.label, "model_id":model_id,
        "precision":model.precision, "device":model.device, "voices":voices()}


@app.post("/api/speech")
def retired_speech():
    raise HTTPException(410, "旧発話APIは廃止しました。/api/v2/speech-jobsを使用してください")


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
        path.unlink()
        with store.connect() as db:
            db.execute("DELETE FROM voice_profiles WHERE id=?",(voice_id,))
        for key in list(service.preparations):
            if key.endswith(":" + voice_id): service.preparations.pop(key, None)
        for metadata in (data_dir()/"voice-prompts").glob("*/*.json"):
            owners = json.loads(metadata.read_text(encoding="utf-8"))
            if voice_id in owners:
                owners.remove(voice_id)
                if owners:
                    metadata.write_text(json.dumps(owners),encoding="utf-8")
                else:
                    metadata.with_suffix(".pt").unlink(missing_ok=True)
                    metadata.unlink()
        for model_id, worker in manager.workers.items():
            worker.stop()
            manager.status[model_id] = {"phase":"idle", "message":"未読込"}
        manager.active = None
        store.remove_voice(voice_id)
        # Old Irodori features contain biometric data; clear derived legacy features.
        for latent in (data_dir()/"latents").glob("*.pt"):
            latent.unlink()
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
    try:
        manager.model(payload.model_id)
        for model_id, settings in payload.model_settings.items():
            if model_id not in config.models: continue
            caps = manager.capabilities(model_id)
            manager.validate(model_id, None, caps["languages"][0], settings, payload.speed if model_id==payload.model_id else 1.)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
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
    translation_identity: dict | None = None
    generation_settings: dict | None = None


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
    return {"config":config.model_dump(),"saved":load_config().model_dump(),"diagnostics":{**hardware,"model_exists":manager.installed(store.preferences().model_id),"data_dir":str(data_dir())}}


@app.put("/api/config")
def update_runtime_config(payload: RuntimeConfig):
    try:
        for key, model in payload.models.items():
            from speech.backends import get_backend
            backend = get_backend(model.backend)
            backend.validate(None, backend.capabilities["languages"][0], model.defaults, 1.)
        if store.preferences().model_id not in payload.models:
            raise ValueError("選択中の音声モデルは削除できません")
    except ValueError as exc:
        raise HTTPException(422,str(exc))
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


@app.exception_handler(BackendFailure)
async def backend_error(request, exc):
    return JSONResponse({"detail":str(exc),"code":exc.code},status_code=503)


@app.get("/api/v2/models")
@app.get("/api/v2/engines")
def engines():
    return {key:{**manager.status[key],"installed":manager.installed(key),
        **manager.capabilities(key), "label":model.label, "device":model.device,
        "defaults":model.defaults} for key,model in config.models.items()}


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
def get_job(job_id: str, after_state: str | None = Query(default=None,max_length=32), wait_ms: int = Query(default=0,ge=0,le=1000)):
    value = service.jobs.wait(job_id,after_state,wait_ms/1000) if after_state and wait_ms else service.jobs.get(job_id)
    return service.public_job(value)


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
def voice_reference(voice_id: str, model_id: str | None = None):
    path = resolve_voice(voice_id)
    profile = service.profile(voice_id)
    changed = bool(profile.get("wav_sha256") and path.exists() and
                   profile["wav_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest())
    model_id = model_id or store.preferences().model_id
    try: manager.model(model_id)
    except ValueError as exc: raise HTTPException(422,str(exc))
    message = ""
    valid = False
    try:
        if changed: raise ValueError("録音が変更されています。参照設定を作り直してください")
        if not path.exists(): raise ValueError("この声は未作成です")
        manager.validate(model_id, {**profile,"reference_path":str(path)}, profile["reference_language"], {}, 1.)
        valid = True
    except ValueError as exc:
        message = str(exc)
    return {**profile,"duration_seconds":sf.info(path).duration if path.exists() else None,
            "reference_audio_changed":changed,"valid_for_model":valid,"model_id":model_id,"validation_message":message}


@app.put("/api/v2/voices/{voice_id}/reference")
def save_reference(voice_id: str,value: VoiceReference):
    try: return service.save_profile(voice_id,value)
    except ValueError as exc: raise HTTPException(422,str(exc))


@app.post("/api/v2/voices/{voice_id}/auto-reference",status_code=202)
def auto_reference(voice_id: str,value: AutoReference,model_id: str | None = None):
    try:
        ensure_design(voice_id,model_id)
        return service.transcribe_reference(voice_id,value,model_id)
    except ValueError as exc:
        if isinstance(exc,JobError): raise
        raise HTTPException(422,str(exc))


@app.get("/api/v2/voices/{voice_id}/auto-reference")
def auto_reference_status(voice_id: str):
    resolve_voice(voice_id)
    return service.transcriptions.get(voice_id,{"state":"idle"})


@app.post("/api/v2/voices/{voice_id}/standard-reference")
def standard_reference(voice_id: str,model_id: str | None = None):
    if voice_id not in {"design:"+name for name in DESIGNS}:
        raise HTTPException(400,"標準の声を選択してください")
    try:
        ensure_design(voice_id,model_id)
        return voice_reference(voice_id,model_id)
    except ValueError as exc:
        raise HTTPException(422,str(exc))


@app.post("/api/v2/voices/{voice_id}/prepare",status_code=202)
def prepare_reference(voice_id: str, model_id: str | None = None):
    try: return service.prepare_voice(voice_id, model_id)
    except ValueError as exc:
        if isinstance(exc,JobError): raise
        raise HTTPException(422,str(exc))


@app.get("/api/v2/voices/{voice_id}/preparation")
def reference_status(voice_id: str, model_id: str | None = None):
    try: return service.preparation_status(voice_id, model_id)
    except ValueError as exc: raise HTTPException(422,str(exc))
