"""Real HTTP checks. Requires a server using the isolated validation data folder."""
import argparse
import io
import json
from pathlib import Path
import sys
import time
import uuid
import httpx
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8111")
    args=parser.parse_args()
    client=httpx.Client(base_url=args.base,timeout=300)
    def ok(response):
        response.raise_for_status()
        return response
    info=ok(client.get("/api/config")).json()
    expected=ROOT/".runtime/backend-validation/data"
    if Path(info["diagnostics"]["data_dir"]).resolve() != expected.resolve():
        raise RuntimeError("Use the isolated validation server; refusing to modify ordinary app data")
    evidence={"base":args.base,"checks":[]}
    def check(name, value):
        assert value,name
        evidence["checks"].append(name)
        print(name,flush=True)
    model_id=ok(client.get('/api/preferences')).json()['model_id']
    check("catalog",ok(client.get('/api/v2/models')).json()[model_id]['reference']['transcript_required'])
    check("retired_api",client.post('/api/speech',json={}).status_code==410)
    voice='design:calm_male'
    ref=ok(client.post('/api/v2/voices/'+voice+'/standard-reference')).json()
    check("new_standard_reference",ref['valid_for_model'] and ref['reference_transcript'])
    for style in ['calm_female','bright_male','bright_female']:
        created=ok(client.post('/api/v2/voices/design:'+style+'/standard-reference')).json()
        check("standard_"+style,created['valid_for_model'])
    prefs=ok(client.get('/api/preferences')).json()
    prefs['history_enabled']=True
    ok(client.put('/api/preferences',json=prefs))
    def job(text, mode='ja', cache=False):
        value={'client_id':'backend-validation','request_id':str(uuid.uuid4()),'voice_id':voice,
            'model_id':model_id,'text':text,'mode':mode,'engine_settings':{'num_step':16},'use_phrase_cache':cache}
        started=time.perf_counter()
        submitted=ok(client.post('/api/v2/speech-jobs',json=value)).json()
        for _ in range(1200):
            result=ok(client.get('/api/v2/speech-jobs/'+submitted['id'])).json()
            if result['state'] in {'ready','failed'}:break
            time.sleep(.1)
        assert result['state']=='ready',result
        response=ok(client.get('/api/v2/speech-jobs/'+submitted['id']+'/audio'))
        samples,sr=sf.read(io.BytesIO(response.content))
        assert sr>0 and np.isfinite(samples).all() and np.max(np.abs(samples))>.001
        evidence.setdefault('audio',[]).append({'mode':mode,'cached':response.headers['X-Cached'],
            'http_ms':round((time.perf_counter()-started)*1000,1),'headers':result['headers']})
        return result,response
    ja,audio=job('日本橋で待っています。',cache=True)
    check("japanese_nonzero_wav",bool(audio.content))
    _,cached=job('日本橋で待っています。',cache=True)
    check("phrase_cache_reused",cached.headers['X-Cached']=='1')
    en,_=job('駅で待っています。','ja_to_en')
    check("translation_and_english",bool(en['snapshot']['translated_text']))
    check("private_paths_hidden",'model_path' not in en['snapshot']['model'] and 'reference' not in en['snapshot'])
    item={'id':str(uuid.uuid4()),'text':'日本橋で待っています。','voice':voice,
        'generatedAt':audio.headers['X-Generated-At'],'timing':{},'engine':model_id,'model_identity':ja['snapshot']['model']}
    ok(client.post('/api/history',data={'metadata':json.dumps(item)},files={'file':('test.wav',audio.content,'audio/wav')}))
    check("history_audio_preserved",ok(client.get('/api/history/'+item['id']+'/audio')).content==audio.content)
    ok(client.delete('/api/history/'+item['id']))
    bad={'client_id':'bad','request_id':'bad','voice_id':voice,'text':'test','engine':'irodori'}
    check("retired_model_rejected",client.post('/api/v2/speech-jobs',json=bad).status_code==422)
    check("foreign_origin_rejected",client.get('/api/status',headers={'Origin':'https://example.com'}).status_code==403)
    check("foreign_host_rejected",client.get('/api/status',headers={'Host':'example.com'}).status_code==403)
    uploaded=ok(client.post('/api/voices',files={'file':('generated-test.wav',audio.content,'audio/wav')})).json()
    try:
        check("voice_upload",any(v['id']==uploaded['id'] for v in ok(client.get('/api/status')).json()['voices']))
    finally:
        ok(client.delete('/api/voices/'+uploaded['id']))
    value={'client_id':'cancel','request_id':'cancel','voice_id':voice,'text':'この発話は取り消されます。','model_id':model_id}
    cancelled=ok(client.post('/api/v2/speech-jobs',json=value)).json()
    ok(client.delete('/api/v2/speech-jobs/'+cancelled['id']))
    check("cancelled_audio_unavailable",client.get('/api/v2/speech-jobs/'+cancelled['id']+'/audio').status_code==410)
    out=ROOT/'.runtime/backend-validation/api-evidence.json'
    out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    client.close()
    print(out)


if __name__=='__main__':main()
