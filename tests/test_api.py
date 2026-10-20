"""HTTP contracts use fake inference, isolated SQLite, and synthetic in-memory WAV."""
import base64
import importlib
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        with patch.dict(os.environ,{"ECHO_EGO_DATA_DIR":cls.temp.name}):
            cls.app=importlib.import_module("app")
        cls.app.config.preload=False
        cls.client=TestClient(cls.app.app,base_url="http://127.0.0.1:8100")
        cls.path=Path(cls.temp.name)/"reference.wav"
        sf.write(cls.path,np.sin(np.arange(24000*4)*.03)*.2,24000)
        cls.app.service.resolve_voice=lambda _:cls.path
        cls.calls=[]
        def fake_call(action,payload=None,timeout=180):
            cls.calls.append((action,payload))
            if action=="translate":return {"text":"I am waiting at Nihonbashi."}
            if action=="synthesize":
                out=io.BytesIO();sf.write(out,np.sin(np.arange(2400)*.1)*.2,24000,format="WAV")
                return {"audio":base64.b64encode(out.getvalue()).decode(),"headers":{"X-Synthesis-Ms":"1","X-Generated-At":"2026-10-19T00:00:00Z"}}
            return {}
        cls.patches=[patch.object(cls.app.manager,"installed",return_value=True),patch.object(cls.app.manager,"identity",side_effect=lambda engine:{"engine":engine}),
                     patch.object(cls.app.manager,"activate",return_value={}),patch.object(cls.app.manager.workers["omnivoice"],"call",side_effect=fake_call),patch.object(cls.app.manager.workers["irodori"],"call",side_effect=fake_call)]
        for item in cls.patches:item.start()
    @classmethod
    def tearDownClass(cls):
        cls.app.service.jobs.close();cls.app.manager.close();cls.client.close()
        for item in cls.patches:item.stop()
        cls.temp.cleanup()
    def test_01_dictionary_preview_revision_and_legacy_etag(self):
        r=self.client.get('/api/v2/reading-dictionary');self.assertEqual(r.status_code,200)
        revision=r.json()['revision']
        result=self.client.put('/api/v2/reading-dictionary',json={"expected_revision":revision,"entries":[{"surface":"日本橋","reading":"にほんばし"}]})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.client.put('/api/v2/reading-dictionary',json={"expected_revision":revision,"entries":[]}).status_code,409)
        r=self.client.post('/api/v2/reading-preview',json={"text":"日本橋で待っています。"})
        self.assertEqual(r.json()['speech_text'],"にほんばしで待っています。")
        pref=self.client.get('/api/preferences');value=pref.json();value['dictionary']=[]
        self.assertEqual(self.client.put('/api/preferences',json=value).status_code,428)
        self.assertEqual(self.client.put('/api/preferences',json=value,headers={'If-Match':'"wrong"'}).status_code,412)
        self.assertEqual(self.client.put('/api/preferences',json=value,headers={'If-Match':pref.headers['etag']}).status_code,200)
    def test_02_voice_reference_and_english_does_not_use_reading(self):
        # The reference transcript is explicitly supplied, never inferred from the voice ID.
        r=self.client.put('/api/v2/voices/custom:test/reference',json={'reference_transcript':'こんにちは。テストです。','reference_language':'ja','clip_start_ms':0,'clip_end_ms':4000})
        self.assertEqual(r.status_code,200,r.text)
        value={'client_id':'api-test','request_id':'one','voice_id':'custom:test','text':'日本橋で待っています。','mode':'ja_to_en','engine':'omnivoice'}
        r=self.client.post('/api/v2/speech-jobs',json=value);self.assertEqual(r.status_code,202,r.text)
        job=r.json();self.assertNotIn('reference',job['snapshot'])
        self.assertEqual(self.client.post('/api/v2/speech-jobs',json=value).json()['id'],job['id'])
        for _ in range(100):
            job=self.client.get('/api/v2/speech-jobs/'+job['id']).json()
            if job['state'] in {'ready','failed'}:break
            time.sleep(.01)
        self.assertEqual(job['state'],'ready',job)
        self.assertEqual(job['snapshot']['translated_text'],'I am waiting at Nihonbashi.')
        translations=[p for action,p in self.calls if action=='translate']
        self.assertEqual(translations[-1]['text'],value['text'])
        self.assertEqual(self.client.get('/api/v2/speech-jobs/'+job['id']+'/audio').headers['content-type'],'audio/wav')
        self.client.delete('/api/v2/speech-jobs/'+job['id'])
        self.assertEqual(self.client.get('/api/v2/speech-jobs/'+job['id']+'/audio').status_code,410)
    def test_03_validation_and_origin(self):
        self.assertEqual(self.client.get('/api/v2/engines',headers={'Origin':'https://example.com'}).status_code,403)
        self.assertEqual(self.client.post('/api/v2/reading-preview',json={'text':'[laughter]'}).status_code,422)
        self.assertEqual(self.client.post('/api/v2/speech-jobs',json={'client_id':'t','request_id':'bad','voice_id':'custom:test','text':'test','mode':'ja_to_en','engine':'irodori'}).status_code,422)


if __name__=='__main__':unittest.main()
