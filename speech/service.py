import base64
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from reading_dictionary import apply, safe_text
from speech.jobs import Jobs, JobError
from speech.errors import ReferenceNotReady
from speech.reference import DESIGN_TRANSCRIPT


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1,max_length=64,pattern=r"^[\w-]+$")
    request_id: str = Field(min_length=1,max_length=64,pattern=r"^[\w-]+$")
    mode: Literal["ja","ja_to_en"] = "ja"
    engine: str | None = None
    model_id: str | None = None
    voice_id: str = Field(min_length=1,max_length=100)
    text: str = Field(min_length=1,max_length=160)
    speed: float = Field(default=1,gt=0,le=3)
    engine_settings: dict = Field(default_factory=dict)
    use_phrase_cache: bool = False
    audition: bool = False
    draft_entries: list[dict] | None = Field(default=None,max_length=100)

    @model_validator(mode="after")
    def aliases(self):
        if self.engine and self.model_id and self.engine != self.model_id:
            raise ValueError("engineとmodel_idが一致しません")
        return self


class VoiceReference(BaseModel):
    reference_transcript: str = Field(default="",max_length=500)
    reference_language: Literal["ja","en"] = "ja"
    clip_start_ms: int = Field(default=0,ge=0,le=29999)
    clip_end_ms: int = Field(ge=1,le=30000)
    wav_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AutoReference(BaseModel):
    reference_language: Literal["ja", "en"] = "ja"
    clip_start_ms: int | None = Field(default=None, ge=0, le=29999)
    clip_end_ms: int | None = Field(default=None, ge=1, le=30000)


class SpeechService:
    def __init__(self, store, dictionary, manager, resolve_voice):
        self.store, self.dictionary, self.manager, self.resolve_voice = store,dictionary,manager,resolve_voice
        self.preparations = {}
        self.preparation_lock = threading.Lock()
        self.transcriptions = {}
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS voice_profiles (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)")
        self.jobs = Jobs(self.execute)

    def profile(self, voice):
        with self.store.connect() as db:
            row = db.execute("SELECT revision,payload FROM voice_profiles WHERE id=?",(voice,)).fetchone()
        if row:
            return {"revision":row[0],**json.loads(row[1])}
        # Full generated utterance only: never pair the full text with a truncated WAV.
        if voice.startswith("design:"):
            import soundfile as sf
            path = self.resolve_voice(voice)
            if path.is_file() and 0 < sf.info(path).duration <= 30:
                return {"revision":0,"reference_transcript":DESIGN_TRANSCRIPT,"reference_language":"ja",
                        "clip_start_ms":0,"clip_end_ms":int(sf.info(path).duration*1000),
                        "wav_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"source":"standard"}
        return {"revision":0,"reference_transcript":"","reference_language":"ja","clip_start_ms":0,"clip_end_ms":None}

    def save_profile(self, voice, value):
        import soundfile as sf
        path = self.resolve_voice(voice)
        info = sf.info(path)
        if value.wav_sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != value.wav_sha256:
            raise ValueError("録音が変更されました。自動入力をやり直してください")
        if not 0 <= value.clip_start_ms < value.clip_end_ms <= info.duration*1000+1:
            raise ValueError("参照区間は録音の範囲内で指定してください")
        if value.reference_transcript:
            safe_text(value.reference_transcript)
        value = value.model_copy(update={"wav_sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM voice_profiles WHERE id=?",(voice,)).fetchone()
            db.execute("INSERT OR REPLACE INTO voice_profiles VALUES (?,?,?)",(voice,row[0]+1 if row else 1,value.model_dump_json()))
        return self.profile(voice)

    def transcribe_reference(self, voice, value, model_id=None):
        path = self.resolve_voice(voice)
        if not path.is_file():
            raise ValueError("録音がありません")
        ref = {"reference_path":str(path),"wav_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
        if (value.clip_start_ms is None) != (value.clip_end_ms is None):
            raise ValueError("開始と終了を両方指定してください")
        limits = self.manager.capabilities(model_id or self.store.preferences().model_id)["reference"]
        payload = {"reference_path":ref["reference_path"],"wav_sha256":ref["wav_sha256"],**value.model_dump(),
            "min_seconds":limits.get("min_seconds",1),"max_seconds":limits.get("max_seconds",30),
            "asr_identity":self.manager.auxiliary_identity("transcribe")}
        key = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        with self.preparation_lock:
            old = self.transcriptions.get(voice,{})
            if old.get("state") == "transcribing":
                if old.get("key") != key:
                    raise JobError(409,"この声は別の区間で文字起こし中です。完了してから実行してください")
                return dict(old)
            # Bound request work across voices; shared TTS execution lock is still used.
            if any(item.get("state") == "transcribing" for item in self.transcriptions.values()):
                raise JobError(429,"別の声を自動入力中です。完了してから実行してください")
            item = {"state":"transcribing","key":key}
            self.transcriptions[voice] = item
        def run():
            try:
                with self.manager.lock:
                    if payload["asr_identity"] != self.manager.auxiliary_identity("transcribe"):
                        raise ValueError("文字起こしモデルの版が変わりました。再実行してください")
                    result = self.manager.auxiliary.call("transcribe-reference",payload,timeout=300)
                    if hashlib.sha256(path.read_bytes()).hexdigest() != payload["wav_sha256"]:
                        raise ValueError("録音が変更されました。自動入力をやり直してください")
                    # Validate the returned draft without writing it into the saved profile.
                    draft = VoiceReference.model_validate(result).model_dump()
                    safe_text(draft["reference_transcript"])
                item.update(state="ready",reference=draft)
            except Exception as exc:
                message = str(exc) if isinstance(exc,ValueError) else "自動文字起こしに失敗しました。モデルの導入・録音を確認して再実行してください"
                item.update(state="failed",message=message)
        threading.Thread(target=run,daemon=True).start()
        return dict(item)

    def reference(self, voice):
        path = self.resolve_voice(voice)
        if not path.exists():
            raise JobError(503,"この声は未作成です。声の管理で試聴してから準備してください")
        profile = self.profile(voice)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if profile.get("wav_sha256") and profile["wav_sha256"] != digest:
            raise ValueError("録音が変更されました。参照設定を作り直してください")
        return {**profile,"voice_id":voice,"reference_path":str(path),"wav_sha256":digest}

    def prepare_voice(self, voice, model_id=None):
        model_id = model_id or self.store.preferences().model_id
        if not self.manager.capabilities(model_id)["reference"]["required"]:
            return {"state":"ready", "model_id":model_id,"required":False}
        ref = self.reference(voice)
        language = ref["reference_language"]
        settings = self.manager.validate(model_id, ref, language, {}, 1.)
        version = self.manager.identity(model_id)
        key = hashlib.sha256(json.dumps([ref,version],sort_keys=True).encode()).hexdigest()
        preparation_id = model_id + ":" + voice
        with self.preparation_lock:
            old = self.preparations.get(preparation_id,{})
            if old.get("key")==key and old.get("state") in {"preparing","ready"}:
                return dict(old)
            item = {"state":"preparing","key":key,"voice_revision":ref["revision"],"model_id":model_id}
            self.preparations[preparation_id] = item
        def run():
            try:
                with self.manager.lock:
                    if self.manager.identity(model_id) != version:
                        raise ValueError("モデルが変更されました")
                    self.manager.activate(model_id)
                    self.manager.call(model_id,"prepare-voice",ref,timeout=120)
                    self.manager.call(model_id,"synthesize",{
                        **ref,"text":"こんにちは。" if ref["reference_language"]=="ja" else "Hello.",
                        "language":language,"settings":settings,"speed":1.},timeout=60)
                item.update(state="ready")
            except Exception:
                item.update(state="failed",message="声を準備できませんでした。環境・区間・文字起こしを確認してください")
        threading.Thread(target=run,daemon=True).start()
        return dict(item)

    def preparation_status(self, voice, model_id=None):
        model_id = model_id or self.store.preferences().model_id
        self.manager.model(model_id)
        if not self.manager.capabilities(model_id)["reference"]["required"]:
            return {"state":"ready", "model_id":model_id,"required":False}
        item = self.preparations.get(model_id + ":" + voice, {"state":"unprepared"})
        if item.get("state") == "ready":
            ref = self.reference(voice)
            key = hashlib.sha256(json.dumps([ref,self.manager.identity(model_id)],sort_keys=True).encode()).hexdigest()
            if key != item.get("key"):
                return {"state":"unprepared", "model_id":model_id}
        return dict(item)

    def snapshot(self,p):
        prefs = self.store.preferences()
        engine = p.get("model_id") or p.get("engine") or prefs.model_id
        self.manager.model(engine)
        if not self.manager.installed(engine):
            raise JobError(503,"音声エンジンが未導入です。セットアップを実行してください")
        safe_text(p["text"])
        ref = self.reference(p["voice_id"]) if self.manager.capabilities(engine)["reference"]["required"] else {"voice_id":p["voice_id"],"revision":0}
        language = "ja" if p["mode"] == "ja" else "en"
        try:
            settings = self.manager.validate(engine, ref, language, {**prefs.model_settings.get(engine,{}), **p["engine_settings"]}, p["speed"])
        except ReferenceNotReady as exc:
            raise JobError(503,str(exc)) from None
        dictionary = self.dictionary.get()
        entries = dictionary["entries"]
        if p.get("draft_entries") is not None:
            from reading_dictionary import validate_entries
            if not p["audition"] or p["mode"] != "ja" or p["use_phrase_cache"]:
                raise ValueError("未保存の読みは日本語の試聴にだけ指定できます")
            entries = validate_entries(p["draft_entries"],entries)
        if p["audition"] and p["use_phrase_cache"]:
            raise ValueError("試聴は定型句キャッシュへ保存できません")
        reading = apply(p["text"],entries,None if p.get("draft_entries") is not None else dictionary["revision"],p["mode"])
        return {"engine":engine,"model_identity":self.manager.identity(engine),"voice_id":p["voice_id"],"voice_revision":ref["revision"],
                "reference":ref,"original_text":p["text"],"translated_text":None,
                "speech_text":reading["speech_text"] if p["mode"]=="ja" else None,"target_language":"ja" if p["mode"]=="ja" else "en",
                "reading_revision":reading["dictionary_revision"],"applied_entries":reading["applied_entries"],"settings":settings,
                "translation_identity":self.manager.auxiliary_identity("translate") if language=="en" else None}

    def public_job(self,job):
        # Internal verified paths/transcripts stay in the controller/worker boundary.
        value = dict(job)
        value["snapshot"] = {k:v for k,v in job["snapshot"].items() if k not in {"reference","model_identity"}}
        identity = job["snapshot"]["model_identity"]
        value["snapshot"]["model"] = {key:value for key,value in identity.items() if key != "model_path"}
        value["snapshot"]["translation_identity"] = {key:value for key,value in (job["snapshot"].get("translation_identity") or {}).items() if key != "path"}
        return value

    def execute(self,job):
        snap,p = job["snapshot"],job["payload"]
        start = time.perf_counter()
        with self.manager.lock:
            if not self.jobs.update(job,"waiting_engine"):
                return
            if snap["model_identity"] != self.manager.identity(snap["engine"]):
                raise ValueError("モデルの版が変わりました。新しく送信してください")
            if snap["target_language"]=="en":
                self.jobs.update(job,"translating")
                if snap["translation_identity"] != self.manager.auxiliary_identity("translate"):
                    raise ValueError("翻訳モデルの版が変わりました。新しく送信してください")
                translated = self.manager.auxiliary.call("translate",{"text":snap["original_text"]},timeout=60)["text"]
                safe_text(translated)
                with self.jobs.lock:
                    if job["state"]=="cancelled":
                        return
                    snap.update(translated_text=translated,speech_text=translated)
                    job["timing"]["translation_ms"] = (time.perf_counter()-start)*1000
            key = hashlib.sha256(json.dumps([snap,p["speed"],"speech-backend-v1"],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            cached = self.store.cache(key) if p["use_phrase_cache"] else None
            if cached:
                audio,headers = cached
                self.jobs.commit(job,audio,{**headers,"X-Cached":"1"})
                return
            if not self.jobs.update(job,"waiting_engine"):
                return
            self.manager.activate(snap["engine"])
            if not self.jobs.update(job,"synthesizing"):
                return
            result = self.manager.call(snap["engine"],"synthesize",{
                **snap["reference"],"text":snap["speech_text"],"language":snap["target_language"],"settings":snap["settings"],"speed":p["speed"]},timeout=60)
            audio,headers = base64.b64decode(result["audio"]),{**result["headers"],"X-Cached":"0"}
            job["timing"]["processing_ms"] = (time.perf_counter()-start)*1000
            self.jobs.commit(job,audio,headers, (lambda:self.store.save_cache(key,audio,headers)) if p["use_phrase_cache"] else None)
