"""Explicit local GPU smoke test using a synthetic reference; no private voice copying."""
import base64
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from configuration import load_config, data_dir
from speech.runtime import RuntimeManager


def main():
    manager=RuntimeManager(load_config())
    path=data_dir()/"design-voices"/"verification-reference.wav"
    path.parent.mkdir(parents=True,exist_ok=True)
    transcript="こんにちは。今日はいい天気ですね。これから一緒に公園へ散歩に行きましょう。"
    evidence={}
    try:
        with manager.lock:
            manager.activate("omnivoice")
            ref=manager.call("omnivoice","design",{"text":transcript,"style":"calm_male","seed":20261019})
            path.write_bytes(base64.b64decode(ref["audio"]))
            import soundfile as sf
            duration=sf.info(path).duration
            print("Synthetic reference duration",duration,flush=True)
            if not 3<=duration<=10:raise RuntimeError("Synthetic reference must fit 3-10 seconds")
            reference={"reference_path":str(path),"reference_transcript":transcript,"reference_language":"ja","clip_start_ms":0,"clip_end_ms":round(duration*1000)}
            manager.activate("omnivoice")
            evidence["prepare"]=manager.workers["omnivoice"].call("prepare-voice",reference,timeout=120)
            for lang,text in [("ja","にほんばしで待っています。"),("en","Hello. I will be waiting for you at the station.")]:
                result=manager.workers["omnivoice"].call("synthesize",{**reference,"text":text,"language":lang,"settings":{"num_step":16},"speed":1.},timeout=60)
                target=ROOT/".runtime"/("omnivoice-smoke-"+lang+".wav")
                target.write_bytes(base64.b64decode(result["audio"]))
                evidence[lang]=result["headers"]
                print(lang,result["headers"],flush=True)
            evidence["asr"]=manager.auxiliary.call("transcribe-reference",{**reference,"wav_sha256":__import__("hashlib").sha256(path.read_bytes()).hexdigest()},timeout=300)
            evidence["translation"]=manager.auxiliary.call("translate",{"text":"駅で待っています。"},timeout=60)
            print("translation",evidence["translation"],flush=True)
        (ROOT/".runtime/omnivoice-smoke.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    finally:
        manager.close()
        path.unlink(missing_ok=True)


if __name__=="__main__":main()
