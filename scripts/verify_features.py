"""Local GPU/API verification; creates disposable fixtures and restores preferences."""
import io
import json
import sys
import time
import uuid
from pathlib import Path
import httpx
import numpy as np
import soundfile as sf

root = Path(__file__).resolve().parents[1]
client = httpx.Client(base_url="http://127.0.0.1:8100", timeout=120)
original = client.get("/api/preferences").json()
voice_id = None
history_id = str(uuid.uuid4())
results = []

def ok(response):
    response.raise_for_status()
    return response

def put_preferences(value):
    current = client.get("/api/preferences")
    return client.put("/api/preferences", json=value, headers={"If-Match":current.headers["ETag"]})


try:
    deadline = time.monotonic() + 180
    while client.get("/api/status").json()["phase"] != "ready":
        if time.monotonic() > deadline: raise RuntimeError("Runtime did not become ready")
        time.sleep(1)
    assert client.get("/api/status").json()["watermark"], "Audio watermark must be available"
    for name in ["user", "setup", "release"]:
        assert "<h1>" in ok(client.get("/api/manual/" + name)).json()["html"]
    prefs = dict(original, history_enabled=True, dictionary=[{"surface":"Echo Ego", "reading":"エコーエゴ"}])
    ok(put_preferences(prefs))
    payload = {"text":"Echo Egoです。", "voice":"design:calm_male", "steps":4,"speed":1,"use_cache":True}
    first_timestamp = None
    for index in range(2):
        started = time.perf_counter(); response = ok(client.post("/api/speech", json=payload)); elapsed = (time.perf_counter()-started)*1000
        samples,rate = sf.read(io.BytesIO(response.content))
        assert rate == 48000 and len(samples)>rate*.1 and np.max(np.abs(samples))>.001
        assert response.headers["X-Cached"] == str(index)
        if index == 0: first_timestamp = response.headers["X-Generated-At"]
        assert response.headers["X-Generated-At"] == first_timestamp
        results.append({"cached":bool(index),"http_ms":round(elapsed,1),"synthesis_ms":float(response.headers["X-Synthesis-Ms"])})
    metadata = {"id":history_id,"text":payload["text"],"voice":"設計した声", "generatedAt":first_timestamp,"timing":{"total":100,"synthesis":100,"received":100}}
    ok(client.post("/api/history",data={"metadata":json.dumps(metadata)},files={"file":("fixture.wav",response.content,"audio/wav")}))
    assert any(item["id"]==history_id for item in ok(client.get("/api/history")).json())
    assert ok(client.get(f"/api/history/{history_id}/audio")).content == response.content
    ok(client.delete("/api/history/" + history_id))
    assert client.get(f"/api/history/{history_id}/audio").status_code == 404
    upload = ok(client.post("/api/voices",files={"file":("fixture.wav",response.content,"audio/wav")})).json(); voice_id = upload["id"]
    ok(client.patch("/api/voices/"+voice_id,json={"name":"検証用の声", "favorite":True}))
    found = next(v for v in client.get("/api/status").json()["voices"] if v["id"]==voice_id)
    assert found["name"]=="検証用の声" and found["favorite"]
    assert len(ok(client.get("/api/voices/"+voice_id+"/audio")).content)>1000
    ok(client.delete("/api/voices/"+voice_id)); voice_id=None
    changed = dict(prefs,dictionary=[{"surface":"Echo Ego","reading":"エコー エゴ"}])
    ok(put_preferences(changed))
    response=ok(client.post("/api/speech",json=payload)); assert response.headers["X-Cached"]=="0"
    invalid = dict(payload,steps=5)
    assert client.post("/api/speech",json=invalid).status_code==400
    assert client.get("/api/status",headers={"Origin":"https://example.com"}).status_code==403
    assert client.get("/api/status",headers={"Host":"example.com"}).status_code==403
    print(json.dumps(results,ensure_ascii=False,indent=2))
    print("Real GPU synthesis, designed preset, cache, pronunciation, history, voice management and local-origin checks passed.")
finally:
    if voice_id: client.delete("/api/voices/"+voice_id)
    client.delete("/api/history/"+history_id)
    put_preferences(original)
    (root/".runtime"/"features-verification.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
