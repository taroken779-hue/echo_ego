"""Owned subprocess clients; one inference task at a time across both engines."""
import atexit
import json
import os
from pathlib import Path
import secrets
import hashlib
import subprocess
import threading
import time
import urllib.request
import urllib.error
import queue
import socket
from speech.backends import get_backend
from speech.errors import BackendFailure

ROOT = Path(__file__).resolve().parents[1]


class Worker:
    def __init__(self, kind, config):
        self.kind, self.config = kind, config
        self.process = None
        self.token = secrets.token_urlsafe(32)
        self.url = None

    def start(self):
        if self.process and self.process.poll() is None:
            return
        env = os.environ.copy()
        env.update(ECHO_WORKER_TOKEN=self.token, ECHO_WORKER_CONFIG=self.config.model_dump_json(),
                   HF_HUB_OFFLINE="1" if self.config.offline else "0", TRANSFORMERS_OFFLINE="1" if self.config.offline else "0",
                   HF_HUB_DISABLE_TELEMETRY="1", PYTHONUTF8="1", TOKENIZERS_PARALLELISM="false")
        python = ROOT / (self.config.auxiliary_python if self.kind == "auxiliary" else self.config.models[self.kind].python_path)
        if not python.is_file():
            raise BackendFailure("not_installed", "専用環境がありません。セットアップを実行してください", False)
        self.process = subprocess.Popen([str(python), str(ROOT / "speech" / "worker.py"), self.kind],
                                        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # The worker prints only its bound loopback port, before importing inference libraries.
        result = queue.Queue()
        threading.Thread(target=lambda:result.put(self.process.stdout.readline()),daemon=True).start()
        try:
            line = result.get(timeout=15)
        except queue.Empty:
            self.stop()
            raise BackendFailure("timeout", "音声ワーカーの開始がタイムアウトしました") from None
        if not line:
            self.stop()
            raise BackendFailure("worker_failed", "音声ワーカーを開始できませんでした")
        self.url = f"http://127.0.0.1:{int(line)}"
        # Never retain inference stdout (which may contain text), but prevent pipe backpressure.
        output = self.process.stdout
        def drain():
            try:
                while output.read(4096):
                    pass
            except (ValueError, OSError, AttributeError):
                pass
        threading.Thread(target=drain, daemon=True).start()

    def call(self, action, payload=None, timeout=180):
        self.start()
        req = urllib.request.Request(self.url + "/" + action, data=json.dumps(payload or {}, ensure_ascii=False).encode(),
                                     headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                error = json.load(exc)
            except Exception:
                error = {}
            if error.get("error") == "invalid_input":
                raise ValueError(error["message"]) from None
            self.stop()
            code = "out_of_memory" if error.get("error") == "OutOfMemoryError" else "worker_failed"
            raise BackendFailure(code, "音声処理に失敗しました。モデル・参照音声と専用環境を確認してください") from None
        except (TimeoutError, socket.timeout):
            self.stop()
            raise BackendFailure("timeout", "音声処理がタイムアウトしました") from None
        except Exception:
            self.stop()
            raise BackendFailure("worker_failed", "音声処理に失敗しました。モデル・参照音声と専用環境を確認してください") from None

    def stop(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process.stdout.close()
            self.process = None


class RuntimeManager:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.backends = {key: get_backend(value.backend) for key, value in config.models.items()}
        self.workers = {kind: Worker(kind, config) for kind in config.models}
        self.auxiliary = Worker("auxiliary", config)
        self.active = None
        self.status = {kind: {"phase": "idle", "message": "未読込"} for kind in self.workers}
        atexit.register(self.close)

    def activate(self, engine):
        self.model(engine)
        if self.active != engine:
            if self.active:
                self.workers[self.active].stop()
                self.status[self.active] = {"phase": "idle", "message": "待機中"}
            self.active = None
        self.status[engine] = {"phase": "loading", "message": "モデルを読み込んでいます"}
        try:
            result = self.workers[engine].call("load")
            self.active = engine
            self.status[engine] = {"phase": "ready", "message": "準備完了", **result}
            return result
        except Exception:
            self.status[engine] = {"phase": "error", "message": "モデルを読み込めません。セットアップを確認してください"}
            raise

    def close(self):
        for worker in self.workers.values():
            worker.stop()
        self.auxiliary.stop()

    def installed(self, engine):
        return self.backends[engine].installed(self.model(engine))

    def identity(self, engine):
        return {"engine": engine, **self.backends[engine].identity(self.model(engine))}

    def model(self, model_id):
        if model_id not in self.config.models:
            raise ValueError("この音声モデルは未登録または廃止済みです")
        return self.config.models[model_id]

    def capabilities(self, model_id):
        self.model(model_id)
        return self.backends[model_id].capabilities

    def validate(self, model_id, reference, language, settings, speed):
        model = self.model(model_id)
        return self.backends[model_id].validate(reference, language, {**model.defaults, **settings}, speed)

    def auxiliary_identity(self, task):
        repository, path = (("Helsinki-NLP/opus-mt-ja-en", self.config.translation_model) if task == "translate"
            else ("openai/whisper-large-v3-turbo", self.config.asr_model))
        manifest = ROOT / self.config.auxiliary_manifest
        values = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        return {"path": path, "revision": values.get("models", {}).get(repository),
            "adapter_sha256": hashlib.sha256((ROOT / "speech/auxiliary.py").read_bytes()).hexdigest()}

    def call(self, model_id, action, payload=None, timeout=180):
        self.model(model_id)
        return self.workers[model_id].call(action, payload, timeout)
