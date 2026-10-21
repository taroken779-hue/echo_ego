"""Contract tests with a deliberately different backend, never loaded in production."""
import base64
import copy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from unittest.mock import patch
import numpy as np
import soundfile as sf
from configuration import RuntimeConfig, ModelConfig
from store import Store, Preferences
from reading_dictionary import Dictionary
from speech.backends import BACKENDS
from speech.backends.base import Backend
from speech.backends.omnivoice import OmniVoiceBackend
from speech.audio import audio_result
from speech.runtime import RuntimeManager
from speech.service import SpeechService, SpeechRequest, VoiceReference


class AlternativeBackend(Backend):
    capabilities = {"version":1,"label":"Contract alternative","languages":["ja"],"stream":False,
        "reference":{"required":False,"transcript_required":False},"voice_design":False,"speed":None,
        "settings":{"tone":{"type":"string","enum":["neutral","soft"],"default":"neutral"}}}

    @classmethod
    def installed(cls, config):
        return True


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = patch.dict(BACKENDS, {"alternative":AlternativeBackend})
        self.registry.start()
        self.config = RuntimeConfig(models={"alternative":ModelConfig(backend="alternative",label="Alternative"),
            "second":ModelConfig(backend="alternative",label="Second",model_path="runtime/different")},default_model="alternative")
        self.manager = RuntimeManager(self.config)
        self.store = Store(self.temp.name)
        self.store.save_preferences(Preferences(model_id="alternative"))
        self.service = SpeechService(self.store, Dictionary(self.store), self.manager,
            lambda _: self.fail("Reference-free model must not resolve a recording"))
        self.calls = []
        def call(action, payload=None, timeout=180):
            self.calls.append((action,copy.deepcopy(payload)))
            if action == "load": return {}
            return audio_result(np.sin(np.arange(2205)*.03)*.2,22050,time.perf_counter())
        self.patches = [patch.object(worker,"call",side_effect=call) for worker in self.manager.workers.values()]
        for item in self.patches: item.start()

    def tearDown(self):
        self.service.jobs.close()
        self.manager.close()
        for item in self.patches: item.stop()
        self.registry.stop()
        self.temp.cleanup()

    def request(self, **kwargs):
        return SpeechRequest(client_id="contract",request_id=str(time.time_ns()),voice_id="any",text="こんにちは。",**kwargs).model_dump()

    def wait(self, job):
        for _ in range(100):
            value = self.service.jobs.get(job["id"])
            if value["state"] in {"ready","failed"}:return value
            time.sleep(.01)
        self.fail("job timed out")

    def test_reference_free_backend_uses_same_service_and_non_48k_output(self):
        job=self.service.jobs.submit(self.request(),self.service.snapshot)
        self.assertEqual(self.wait(job)["state"],"ready")
        raw,headers=self.service.jobs.audio(job["id"])
        self.assertEqual(sf.info(io.BytesIO(raw)).samplerate,22050)
        self.assertEqual(headers["X-Sample-Rate"],"22050")
        self.assertEqual(self.calls[-1][1]["settings"],{"tone":"neutral"})
        self.assertNotIn("steps",self.calls[-1][1])

    def test_capability_validation_rejects_language_speed_and_unknown_option(self):
        for kwargs in ({"mode":"ja_to_en"},{"speed":1.2},{"engine_settings":{"num_step":16}}, {"engine":"irodori"}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.service.snapshot(self.request(**kwargs))

    def test_alias_conflict_rejected(self):
        with self.assertRaises(ValueError):self.request(engine="alternative",model_id="second")

    def test_snapshot_is_fixed_after_default_and_settings_change(self):
        payload=self.request(engine_settings={"tone":"soft"})
        snap=self.service.snapshot(payload)
        self.store.save_preferences(Preferences(model_id="second"))
        payload["engine_settings"]["tone"]="neutral"
        self.assertEqual((snap["engine"],snap["settings"]),("alternative",{"tone":"soft"}))

    def test_cache_is_separated_by_model_and_effective_settings(self):
        def submit(**kwargs):
            job=self.service.jobs.submit(self.request(use_phrase_cache=True,**kwargs),self.service.snapshot)
            self.assertEqual(self.wait(job)["state"],"ready")
            return self.service.jobs.audio(job["id"])[1]["X-Cached"]
        self.assertEqual(submit(),"0")
        self.assertEqual(submit(),"1")
        self.assertEqual(submit(model_id="second"),"0")
        self.assertEqual(submit(engine_settings={"tone":"soft"}),"0")

    def test_changed_model_fails_before_synthesis(self):
        job=self.service.jobs.submit(self.request(),self.service.snapshot)
        # Use the direct executor deterministically under the shared lock in a separate job service.
        snap=self.service.snapshot(self.request())
        self.wait(job)
        self.config.models["alternative"].model_path="runtime/changed"
        with self.assertRaisesRegex(ValueError,"モデルの版"):
            self.service.execute({"snapshot":snap,"payload":self.request(),"state":"queued","id":"direct","timing":{}})

    def test_tts_switch_does_not_stop_auxiliary(self):
        with patch.object(self.manager.auxiliary,"stop") as stop:
            self.manager.activate("alternative")
            self.manager.activate("second")
            stop.assert_not_called()

    def test_reference_free_preparation_does_not_require_recording(self):
        self.assertFalse(self.service.prepare_voice("builtin:default")["required"])
        self.assertEqual(self.service.preparation_status("builtin:default")["state"],"ready")

    def test_omnivoice_validates_own_constraints(self):
        ref={"reference_path":"voice.wav","reference_transcript":"こんにちは。","clip_start_ms":0,"clip_end_ms":4000}
        self.assertEqual(OmniVoiceBackend.validate(ref,"en",{},1.),{"num_step":32})
        self.assertEqual(OmniVoiceBackend.validate(None,"ja",{"num_step":16},1.),{"num_step":16})
        for changes in ({"reference_transcript":""},{"clip_end_ms":2000}):
            with self.assertRaises(ValueError):OmniVoiceBackend.validate({**ref,**changes},"ja",{},1.)
        for settings in ({"num_step":True},{"num_step":4},{"other":1}):
            with self.assertRaises(ValueError):OmniVoiceBackend.validate(ref,"ja",settings,1.)

    def test_audio_rejects_silent_nonfinite_or_too_long(self):
        for samples in (np.zeros(100),np.array([float('nan')]),np.ones(31001)):
            with self.assertRaises(ValueError):audio_result(samples,1000,time.perf_counter())


class MigrationTests(unittest.TestCase):
    def test_preferences_migration_backups_preserve_history_and_manual_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            old={"japanese_engine":"irodori","omnivoice_steps":16,"history_enabled":True,"voice":"custom:mine"}
            with store.connect() as db:
                db.execute("INSERT INTO settings VALUES (1,?)",(json.dumps(old),))
                db.execute("INSERT INTO history VALUES ('old','2026',?,?)",(json.dumps({"engine":"irodori"}),b"original-wav"))
                db.execute("CREATE TABLE voice_profiles (id TEXT PRIMARY KEY,revision INTEGER,payload TEXT)")
                db.execute("INSERT INTO voice_profiles VALUES ('custom:mine',7,?)",('{"reference_transcript":"manual"}',))
            reopened=Store(folder)
            self.assertEqual(reopened.preferences().model_id,"omnivoice")
            self.assertEqual(reopened.preferences().model_settings["omnivoice"],{"num_step":16})
            backup=Path(folder)/"echo-ego.before-backends.sqlite3"
            initial=backup.read_bytes()
            Store(folder)
            self.assertEqual(backup.read_bytes(),initial)
            self.assertEqual(reopened.history_audio("old"),b"original-wav")
            with reopened.connect() as db:
                self.assertEqual(db.execute("SELECT revision,payload FROM voice_profiles").fetchone()[0],7)
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(json.loads(db.execute("SELECT payload FROM settings").fetchone()[0]),old)

    def test_config_legacy_migration_is_idempotent(self):
        config=RuntimeConfig.model_validate({"device":"cuda","precision":"bf16","presets_dir":"existing","port":8110})
        self.assertEqual(config.models["omnivoice"].precision,"float16")
        self.assertEqual(config.presets_dir,"existing")
        self.assertEqual(RuntimeConfig.model_validate_json(config.model_dump_json()),config)


if __name__ == "__main__":unittest.main()
