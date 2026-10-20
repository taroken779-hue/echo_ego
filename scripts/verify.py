"""実GPU合成を含む確認。合成時間と実際に聞こえる時間を区別する。"""
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
import numpy as np
import soundfile as sf

root = Path(__file__).resolve().parents[1]
base = "http://127.0.0.1:8100"

def request(path, payload=None):
    raw = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    return urllib.request.urlopen(urllib.request.Request(base + path, raw, {"Content-Type": "application/json"}), timeout=120)

deadline = time.monotonic() + 180
while True:
    with request("/api/status") as response:
        status = json.load(response)
    if status["phase"] == "ready":
        break
    if status["phase"] == "error" or time.monotonic() > deadline:
        raise RuntimeError(status)
    time.sleep(1)

for overrides in [{"text": "……"}, {"voice": "custom:missing"}, {"steps": 99}]:
    payload = {"text": "こんにちは。", "voice": "preset:age_middle_male", "steps": 4, **overrides}
    try:
        request("/api/speech", payload)
        raise AssertionError("Invalid input accepted")
    except urllib.error.HTTPError as error:
        assert error.code in (400, 404), error.code

results = []
for index, text in enumerate(["こんにちは。", "こんにちは。", "こんにちは。", "今日はいい天気ですね。", "ありがとうございます。"]):
    started = time.perf_counter()
    with request("/api/speech", {"text": text, "voice": "preset:age_middle_male", "steps": 4, "speed": 1}) as response:
        audio = response.read()
        headers = response.headers
    elapsed = (time.perf_counter() - started) * 1000
    data, rate = sf.read(io.BytesIO(audio))
    assert rate == 48000 and len(data) > rate * 0.1 and np.isfinite(data).all() and np.max(np.abs(data)) > 0.005
    (root / ".runtime" / f"sample-{index + 1}.wav").write_bytes(audio)
    row = {"text": text, "http_ms": round(elapsed, 1), "synthesis_ms": float(headers["X-Synthesis-Ms"]), "first_signal_ms": float(headers["X-First-Signal-Ms"]), "audio_seconds": round(len(data) / rate, 2)}
    results.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
(root / ".runtime" / "benchmark.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("Invalid input checks and 5 real GPU syntheses passed.", flush=True)
