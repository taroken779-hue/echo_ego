import base64
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from reading_dictionary import apply, safe_text
from speech.jobs import Jobs, JobError
from speech.reference import DESIGN_TRANSCRIPT


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1,max_length=64,pattern=r"^[\w-]+$")
    request_id: str = Field(min_length=1,max_length=64,pattern=r"^[\w-]+$")
    mode: Literal["ja","ja_to_en"] = "ja"
    engine: Literal["irodori","omnivoice"] | None = None
    voice_id: str = Field(min_length=1,max_length=100)
    text: str = Field(min_length=1,max_length=160)
    speed: float = Field(default=1,ge=.7,le=1.5)
    engine_settings: dict = Field(default_factory=dict)
    use_phrase_cache: bool = False
    audition: bool = False
    draft_entries: list[dict] | None = Field(default=None,max_length=100)


class VoiceReference(BaseModel):
    reference_transcript: str = Field(min_length=1,max_length=500)
    reference_language: Literal["ja","en"] = "ja"
    clip_start_ms: int = Field(default=0,ge=0,le=27000)
    clip_end_ms: int = Field(ge=3000,le=30000)
    wav_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AutoReference(BaseModel):
    reference_language: Literal["ja", "en"] = "ja"
    clip_start_ms: int | None = Field(default=None, ge=0, le=27000)
    clip_end_ms: int | None = Field(default=None, ge=3000, le=30000)


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
            if path.is_file() and 3 <= sf.info(path).duration <= 10:
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
        if not 3000 <= value.clip_end_ms-value.clip_start_ms <= 10000 or value.clip_end_ms > info.duration*1000+1:
            raise ValueError("録音内の3〜10秒の区間と、その区間に合う文字起こしを指定してください")
        safe_text(value.reference_transcript)
        value = value.model_copy(update={"wav_sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM voice_profiles WHERE id=?",(voice,)).fetchone()
            db.execute("INSERT OR REPLACE INTO voice_profiles VALUES (?,?,?)",(voice,row[0]+1 if row else 1,value.model_dump_json()))
        return self.profile(voice)

    def transcribe_reference(self, voice, value):
        path = self.resolve_voice(voice)
        if not path.is_file():
            raise ValueError("録音がありません")
        ref = {"reference_path":str(path),"wav_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
        if (value.clip_start_ms is None) != (value.clip_end_ms is None):
            raise ValueError("開始と終了を両方指定してください")
        payload = {"reference_path":ref["reference_path"],"wav_sha256":ref["wav_sha256"],**value.model_dump()}
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
                    result = self.manager.workers["omnivoice"].call("transcribe-reference",payload,timeout=300)
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

    def prepare_voice(self, voice):
        ref = self.reference(voice)
        if not ref["reference_transcript"]:
            raise ValueError("参照音声の文字起こしを保存してください")
        version = self.manager.identity("omnivoice")
        key = hashlib.sha256(json.dumps([ref,version],sort_keys=True).encode()).hexdigest()
        with self.preparation_lock:
            old = self.preparations.get(voice,{})
            if old.get("key")==key and old.get("state") in {"preparing","ready"}:
                return dict(old)
            item = {"state":"preparing","key":key,"voice_revision":ref["revision"]}
            self.preparations[voice] = item
        def run():
            try:
                with self.manager.lock:
                    self.manager.activate("omnivoice")
                    self.manager.workers["omnivoice"].call("prepare-voice",ref,timeout=120)
                    self.manager.workers["omnivoice"].call("synthesize",{
                        **ref,"text":"こんにちは。" if ref["reference_language"]=="ja" else "Hello.",
                        "language":ref["reference_language"],"steps":16,"speed":1.},timeout=60)
                item.update(state="ready")
            except Exception:
                item.update(state="failed",message="声を準備できませんでした。環境・区間・文字起こしを確認してください")
        threading.Thread(target=run,daemon=True).start()
        return dict(item)

    def snapshot(self,p):
        prefs = self.store.preferences()
        engine = p["engine"] or (prefs.japanese_engine if p["mode"]=="ja" else "omnivoice")
        if p["mode"]=="ja_to_en" and engine!="omnivoice":
            raise ValueError("英語モードにはOmniVoiceを選択してください")
        if not self.manager.installed(engine):
            raise JobError(503,"音声エンジンが未導入です。セットアップを実行してください")
        settings = p["engine_settings"]
        field = "steps" if engine=="irodori" else "num_step"
        if set(settings)-{field}:
            raise ValueError("音声エンジンの生成設定が無効です")
        steps = settings.get(field,prefs.steps if engine=="irodori" else prefs.omnivoice_steps)
        if type(steps) is not int or steps not in ({4,6,8} if engine=="irodori" else {16,32}):
            raise ValueError("生成ステップ数が無効です")
        safe_text(p["text"])
        ref = self.reference(p["voice_id"])
        if engine=="omnivoice" and not ref["reference_transcript"]:
            raise JobError(503,"声の管理でOmniVoice用の参照区間・文字起こしを保存し、準備してください")
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
                "reading_revision":reading["dictionary_revision"],"applied_entries":reading["applied_entries"],"steps":steps}

    def public_job(self,job):
        # Internal verified paths/transcripts stay in the controller/worker boundary.
        value = dict(job)
        value["snapshot"] = {k:v for k,v in job["snapshot"].items() if k not in {"reference","model_identity"}}
        identity = job["snapshot"]["model_identity"]
        value["snapshot"]["model"] = {"engine":identity["engine"],"model_mtime":identity.get("model_mtime"),
                                      "manifest":identity.get("manifest",{}),"precision":self.manager.config.precision if identity["engine"]=="irodori" else ("fp16" if self.manager.config.device=="cuda" else "fp32"),
                                      "source_revision":identity.get("source_revision"),"worker_sha256":identity.get("worker_sha256")}
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
                # Translation is CPU-only in the isolated OmniVoice process.
                translated = self.manager.workers["omnivoice"].call("translate",{"text":snap["original_text"]},timeout=60)["text"]
                safe_text(translated)
                with self.jobs.lock:
                    if job["state"]=="cancelled":
                        return
                    snap.update(translated_text=translated,speech_text=translated)
                    job["timing"]["translation_ms"] = (time.perf_counter()-start)*1000
            key = hashlib.sha256(json.dumps([snap,p["speed"],"speech-v2"],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
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
            result = self.manager.workers[snap["engine"]].call("synthesize",{
                **snap["reference"],"text":snap["speech_text"],"language":snap["target_language"],"steps":snap["steps"],"speed":p["speed"]},timeout=60)
            audio,headers = base64.b64decode(result["audio"]),{**result["headers"],"X-Cached":"0"}
            job["timing"]["processing_ms"] = (time.perf_counter()-start)*1000
            self.jobs.commit(job,audio,headers, (lambda:self.store.save_cache(key,audio,headers)) if p["use_phrase_cache"] else None)
