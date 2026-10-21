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
            if action=="transcribe-reference":
                return {"reference_transcript":"自動認識の下書きです。","reference_language":payload["reference_language"],
                        "clip_start_ms":payload.get("clip_start_ms") or 0,"clip_end_ms":payload.get("clip_end_ms") or 4000,
                        "wav_sha256":payload["wav_sha256"]}
            if action=="synthesize":
                out=io.BytesIO();sf.write(out,np.sin(np.arange(2400)*.1)*.2,24000,format="WAV")
                return {"audio":base64.b64encode(out.getvalue()).decode(),"headers":{"X-Synthesis-Ms":"1","X-Generated-At":"2026-10-19T00:00:00Z"}}
            return {}
        cls.patches=[patch.object(cls.app.manager,"installed",return_value=True),patch.object(cls.app.manager,"identity",side_effect=lambda engine:{"engine":engine}),
                     patch.object(cls.app.manager,"activate",return_value={}),patch.object(cls.app.manager.workers["omnivoice"],"call",side_effect=fake_call),patch.object(cls.app.manager.auxiliary,"call",side_effect=fake_call)]
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

    def test_04_auto_draft_preserves_profile_and_checks_audio_identity(self):
        import hashlib
        original=self.app.service.profile('custom:test')
        with patch.object(self.app,'resolve_voice',return_value=self.path):
            r=self.client.post('/api/v2/voices/custom:test/auto-reference',json={'reference_language':'en','clip_start_ms':500,'clip_end_ms':3500})
            self.assertEqual(r.status_code,202,r.text)
            for _ in range(100):
                result=self.client.get('/api/v2/voices/custom:test/auto-reference').json()
                if result['state']!='transcribing':break
                time.sleep(.01)
            self.assertEqual(result['state'],'ready',result)
            draft=result['reference']
            self.assertEqual((draft['clip_start_ms'],draft['clip_end_ms'],draft['reference_language']),(500,3500,'en'))
            self.assertEqual(self.app.service.profile('custom:test'),original)
            draft['wav_sha256']='0'*64
            self.assertEqual(self.client.put('/api/v2/voices/custom:test/reference',json=draft).status_code,422)
            self.assertEqual(self.app.service.profile('custom:test'),original)
            draft['wav_sha256']=hashlib.sha256(self.path.read_bytes()).hexdigest()
            self.assertEqual(self.client.put('/api/v2/voices/custom:test/reference',json=draft).status_code,200)
            self.assertEqual(self.app.service.profile('custom:test')['reference_transcript'],draft['reference_transcript'])
            self.assertEqual(self.client.post('/api/v2/voices/custom:test/auto-reference',json={'clip_start_ms':0}).status_code,422)

    def test_05_standard_defaults_never_override_saved_settings(self):
        from speech.reference import DESIGN_TRANSCRIPT
        ref=self.app.service.profile('design:calm_male')
        self.assertEqual(ref['reference_transcript'],DESIGN_TRANSCRIPT)
        self.assertEqual(ref['clip_end_ms'],4000)
        from speech.service import VoiceReference
        saved=VoiceReference(reference_transcript='手動の設定を保持します。',clip_start_ms=0,clip_end_ms=3000)
        self.app.service.save_profile('design:calm_male',saved)
        self.assertEqual(self.app.service.profile('design:calm_male')['reference_transcript'],saved.reference_transcript)

    def test_06_changed_recording_and_competing_transcription(self):
        from speech.service import AutoReference
        from speech.jobs import JobError
        self.app.service.transcriptions['custom:busy']={'state':'transcribing','key':'other'}
        try:
            with self.assertRaises(JobError) as error:
                self.app.service.transcribe_reference('custom:busy',AutoReference())
            self.assertEqual(error.exception.status,409)
        finally:
            self.app.service.transcriptions.pop('custom:busy')
        original=self.path.read_bytes()
        try:
            sf.write(self.path,np.sin(np.arange(24000*4)*.06)*.1,24000)
            with self.assertRaisesRegex(ValueError,'録音が変更'):
                self.app.service.reference('custom:test')
            with patch.object(self.app,'resolve_voice',return_value=self.path):
                self.assertTrue(self.client.get('/api/v2/voices/custom:test/reference').json()['reference_audio_changed'])
        finally:
            self.path.write_bytes(original)

    def test_07_catalog_retired_api_and_invalid_model(self):
        models=self.client.get('/api/v2/models').json()
        self.assertEqual(set(models),{'omnivoice'})
        self.assertTrue(models['omnivoice']['reference']['transcript_required'])
        self.assertEqual(self.client.post('/api/speech',json={}).status_code,410)
        bad={'client_id':'bad-model','request_id':'missing','voice_id':'custom:test','text':'こんにちは。','model_id':'missing'}
        self.assertEqual(self.client.post('/api/v2/speech-jobs',json=bad).status_code,422)

    def test_08_missing_reference_is_explicit_and_does_not_fallback(self):
        from speech.service import VoiceReference
        self.app.service.save_profile('custom:empty',VoiceReference(
            clip_start_ms=0,clip_end_ms=4000,reference_transcript=''))
        bad={'client_id':'missing-ref','request_id':'empty','voice_id':'custom:empty','text':'こんにちは。','model_id':'omnivoice'}
        before=len(self.calls)
        self.assertEqual(self.client.post('/api/v2/speech-jobs',json=bad).status_code,503)
        self.assertEqual(len(self.calls),before)

    def test_09_reference_validation_is_bound_to_requested_model(self):
        from configuration import ModelConfig
        from speech.backends.omnivoice import OmniVoiceBackend
        with patch.dict(self.app.config.models,{'comparison':ModelConfig()}), patch.dict(self.app.manager.backends,{'comparison':OmniVoiceBackend}), patch.object(self.app,'resolve_voice',return_value=self.path):
            ref=self.client.get('/api/v2/voices/custom:test/reference?model_id=comparison').json()
            self.assertEqual(ref['model_id'],'comparison')
            self.assertTrue(ref['valid_for_model'])
            self.assertEqual(self.client.get('/api/v2/voices/custom:test/reference?model_id=missing').status_code,422)

    def test_10_history_retains_translation_and_generation_provenance(self):
        import json, uuid
        prefs=self.app.store.preferences()
        self.app.store.save_preferences(prefs.model_copy(update={'history_enabled':True}))
        metadata={'id':str(uuid.uuid4()),'text':'履歴の確認です。','voice':'test',
            'generatedAt':'2026-10-22T00:00:00Z','timing':{},
            'translation_identity':{'revision':'translation-test'},'generation_settings':{'num_step':16}}
        try:
            response=self.client.post('/api/history',data={'metadata':json.dumps(metadata)},files={'file':('test.wav',self.path.read_bytes(),'audio/wav')})
            self.assertEqual(response.status_code,200,response.text)
            stored=next(item for item in self.client.get('/api/history').json() if item['id']==metadata['id'])
            self.assertEqual(stored['translation_identity'],metadata['translation_identity'])
            self.assertEqual(stored['generation_settings'],metadata['generation_settings'])
        finally:
            self.app.store.delete_history(metadata['id'])
            self.app.store.save_preferences(prefs)

    def test_11_long_poll_is_bounded_and_initialization_preserves_voice_choice(self):
        self.assertEqual(self.client.get('/api/v2/speech-jobs/missing?after_state=queued&wait_ms=1001').status_code,422)
        prefs=self.app.store.preferences()
        with patch.object(self.app.service,'prepare_voice',return_value={'state':'preparing'}) as prepare:
            self.app.initialize()
            prepare.assert_called_once_with(prefs.voice,prefs.model_id)
        with patch.object(self.app.service,'prepare_voice',side_effect=ValueError('reference missing')):
            self.app.initialize()
            self.assertEqual(self.app.state['phase'],'ready')


if __name__=='__main__':unittest.main()
