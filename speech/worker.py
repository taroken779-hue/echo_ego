"""Authenticated owned worker, dispatching through backend contract v1."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys
import time
import traceback
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from configuration import RuntimeConfig
from speech.backends import get_backend
from speech.auxiliary import Auxiliary
CONFIG = RuntimeConfig.model_validate_json(os.environ["ECHO_WORKER_CONFIG"])
ENGINE = sys.argv[1]
TOKEN = os.environ["ECHO_WORKER_TOKEN"]
backend = None if ENGINE == "auxiliary" else get_backend(CONFIG.models[ENGINE].backend)(ENGINE, CONFIG.models[ENGINE], CONFIG)
auxiliary = Auxiliary(CONFIG) if ENGINE == "auxiliary" else None


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
            if backend is not None:
                actions = {"load": lambda: backend.load(), "synthesize": lambda: backend.synthesize(payload),
                    "prepare-voice": lambda: backend.prepare(payload), "design": lambda: backend.design(payload),
                    "health": lambda: {"running": True}}
            else:
                actions = {"translate": lambda: auxiliary.translate(payload),
                    "transcribe-reference": lambda: auxiliary.transcribe_reference(payload)}
            if action not in actions:
                raise ValueError("未対応の操作です")
            result = actions[action]()
            raw = json.dumps(result,ensure_ascii=False).encode()
            self.send_response(200)
        except Exception as exc:
            # Frame locations and exception type only: never persist speech text or transcripts.
            folder = ROOT / ".runtime"
            folder.mkdir(exist_ok=True)
            frames = [(f.filename,f.lineno,f.name) for f in traceback.extract_tb(exc.__traceback__)]
            with (folder / (ENGINE+"-errors.jsonl")).open("a",encoding="utf-8") as handle:
                handle.write(json.dumps({"type":type(exc).__name__,"frames":frames})+"\n")
            own_validation = isinstance(exc,ValueError) and bool(frames) and Path(frames[-1][0]).resolve().is_relative_to(ROOT / "speech")
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
