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
        python = ROOT / (self.config.python_path if self.kind == "irodori" else self.config.omnivoice_python)
        if not python.is_file():
            raise ValueError("専用環境がありません。セットアップを実行してください")
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
            raise RuntimeError("音声ワーカーの開始がタイムアウトしました") from None
        if not line:
            self.stop()
            raise RuntimeError("音声ワーカーを開始できませんでした")
        self.url = f"http://127.0.0.1:{int(line)}"

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
            raise RuntimeError("音声処理に失敗しました。モデル・参照音声と専用環境を確認してください") from None
        except Exception:
            self.stop()
            raise RuntimeError("音声処理に失敗しました。モデル・参照音声と専用環境を確認してください") from None

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
        self.workers = {kind: Worker(kind, config) for kind in ("irodori", "omnivoice")}
        self.active = None
        self.status = {kind: {"phase": "idle", "message": "未読込"} for kind in self.workers}
        atexit.register(self.close)

    def activate(self, engine):
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

    def installed(self, engine):
        if engine == "irodori":
            return (ROOT / self.config.model_path).is_file()
        return (ROOT / self.config.omnivoice_python).is_file() and (ROOT / self.config.omnivoice_model / "model.safetensors").is_file()

    def identity(self, engine):
        path = ROOT / (self.config.model_path if engine == "irodori" else self.config.omnivoice_model + "/model.safetensors")
        manifest = ROOT / "runtime/omnivoice/manifest.json"
        source_head = ROOT / self.config.source_path / ".git/HEAD"
        return {"engine": engine, "model_mtime": path.stat().st_mtime_ns if path.exists() else 0,
                "worker_sha256":hashlib.sha256((ROOT/"speech/worker.py").read_bytes()).hexdigest(),
                "source_revision":source_head.read_text().strip() if engine=="irodori" and source_head.exists() else None,
                "manifest": json.loads(manifest.read_text(encoding="utf-8")) if engine == "omnivoice" and manifest.exists() else {},
                "config": self.config.model_dump()}
