"""Bounded FIFO jobs with immutable request identity and cancellation commit barrier."""
from collections import OrderedDict
import copy
import json
import queue
import threading
import time
import uuid


TERMINAL = {"ready", "failed", "cancelled"}


class JobError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class Jobs:
    def __init__(self, execute):
        self.execute = execute
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.items = OrderedDict()
        self.requests = {}
        self.queue = queue.Queue()
        self.closed = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _prune(self):
        now = time.monotonic()
        terminal = [j for j in self.items.values() if j["state"] in TERMINAL]
        total = sum(len(j.get("audio", b"")) for j in terminal)
        remaining = len(terminal)
        for job in terminal:
            if remaining <= 100 and total <= 128*1024*1024 and now-job["accessed"] <= 900:
                continue
            total -= len(job.pop("audio", b""))
            remaining -= 1
            # Expired IDs remain as bounded tombstones; requests are removed with them.
            job["expired"] = True
        for key,value in list(self.items.items()):
            if len(self.items) <= 200:
                break
            if value["state"] in TERMINAL:
                self.items.pop(key)
                self.requests.pop((value["client_id"], value["request_id"]),None)

    def submit(self, payload, snapshot_factory):
        identity = json.dumps(payload,sort_keys=True,ensure_ascii=False)
        key = (payload["client_id"],payload["request_id"])
        with self.lock:
            self._prune()
            if key in self.requests:
                job = self.items[self.requests[key]]
                if job.get("expired"):
                    raise JobError(410,"同じ要求の保持期限が切れました。新しい要求IDで送信してください")
                if job["identity"] != identity:
                    raise JobError(409,"同じ要求IDに異なる内容が送信されました")
                return self.public(job)
            waiting = [j for j in self.items.values() if j["state"] not in TERMINAL]
            if len(waiting)>=32 or sum(j["client_id"]==payload["client_id"] for j in waiting)>=8:
                raise JobError(429,"発話待ちがいっぱいです")
            snapshot = copy.deepcopy(snapshot_factory(payload))
            job = {"id":str(uuid.uuid4()),"client_id":key[0],"request_id":key[1],"identity":identity,
                   "state":"queued","snapshot":snapshot,"timing":{},"created":time.monotonic(),"accessed":time.monotonic(),"payload":copy.deepcopy(payload)}
            self.items[job["id"]] = job
            self.requests[key] = job["id"]
            self.queue.put(job["id"])
            return self.public(job)

    def public(self, job):
        return copy.deepcopy({k:job[k] for k in ("id","state","snapshot","timing","error","headers") if k in job})

    def get(self, key):
        with self.lock:
            self._prune()
            job = self.items.get(key)
            if job is None or job.get("expired"):
                raise JobError(410,"発話結果の保持期限が切れました。新しく送信してください")
            job["accessed"] = time.monotonic()
            return self.public(job)

    def audio(self, key):
        with self.lock:
            self.get(key)
            job = self.items[key]
            if job["state"] in {"failed","cancelled"}:
                raise JobError(410,"この音声は取得できません")
            if job["state"] != "ready":
                raise JobError(409,"音声を生成中です")
            return job["audio"], dict(job["headers"])

    def wait(self, key, after_state, timeout=1.):
        """Return immediately on a state change; no missed completion between GETs."""
        deadline = time.monotonic() + timeout
        with self.changed:
            value = self.get(key)
            while value["state"] == after_state and value["state"] not in TERMINAL and not self.closed:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    break
                self.changed.wait(remaining)
                value = self.get(key)
            return value

    def cancel(self, key):
        with self.lock:
            if key in self.items:
                self.items[key]["state"] = "cancelled"
                self.items[key].pop("audio",None)
                self.changed.notify_all()
        return {"ok":True}

    def cancel_client(self, client_id):
        with self.lock:
            for job in list(self.items.values()):
                if job["client_id"] == client_id:
                    self.cancel(job["id"])
        return {"ok":True}

    def cancel_voice(self, voice_id):
        with self.lock:
            for job in list(self.items.values()):
                if job["snapshot"].get("voice_id") == voice_id:
                    self.cancel(job["id"])

    def update(self, job, state=None, **values):
        with self.lock:
            if job["state"] == "cancelled" or self.closed:
                return False
            if state:
                job["state"] = state
            job.update(values)
            self.changed.notify_all()
            return True

    def commit(self, job, audio, headers, save_cache=None):
        with self.lock:
            if job["state"] == "cancelled" or self.closed:
                return False
            if save_cache:
                save_cache()
            job.update(state="ready",audio=audio,headers=headers)
            self.changed.notify_all()
            return True

    def _loop(self):
        while True:
            key = self.queue.get()
            if key is None:
                return
            with self.lock:
                job = self.items.get(key)
                if job is None or job["state"] == "cancelled":
                    continue
            try:
                self.execute(job)
            except Exception as exc:
                message = str(exc) if isinstance(exc,ValueError) else "音声処理に失敗しました。環境と参照音声を確認してください"
                self.update(job,"failed",error={"code":getattr(exc,"code","invalid_input" if isinstance(exc,ValueError) else "speech_failed"),"message":message if isinstance(exc,ValueError) or hasattr(exc,"code") else "音声処理に失敗しました。環境と参照音声を確認してください","stage":job["state"],"retryable":getattr(exc,"retryable",not isinstance(exc,ValueError))})

    def close(self):
        with self.lock:
            self.closed = True
            self.changed.notify_all()
        self.queue.put(None)
