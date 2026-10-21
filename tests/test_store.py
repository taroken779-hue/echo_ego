import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store import Store, Preferences, Phrase, Reading
from configuration import RuntimeConfig


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def item(self, age=0):
        return {"id": str(uuid.uuid4()), "text": "こんにちは。", "voice": "test", "generatedAt": (datetime.now(timezone.utc)-timedelta(days=age)).isoformat(), "timing": {"total": 1}}

    def test_history_off_blocks_saves_and_clears_audio(self):
        item = self.item()
        with self.assertRaises(ValueError):
            self.store.save_history(item, b"audio")
        self.store.save_preferences(Preferences(history_enabled=True))
        self.store.save_history(item, b"audio")
        self.assertEqual(self.store.history_audio(item["id"]), b"audio")
        self.store.save_preferences(Preferences(history_enabled=False))
        self.assertIsNone(self.store.history_audio(item["id"]))
        self.assertEqual(self.store.histories(), [])

    def test_count_age_and_capacity_are_enforced(self):
        self.store.save_preferences(Preferences(history_enabled=True, history_count=2, history_days=7, history_mb=1))
        old = self.item(age=8)
        self.store.save_history(old, b"a")
        self.assertIsNone(self.store.history_audio(old["id"]))
        ids = []
        for _ in range(3):
            item = self.item(); ids.append(item["id"])
            self.store.save_history(item, b"a" * 600000)
        self.assertIsNone(self.store.history_audio(ids[0]))
        self.assertEqual([r["id"] for r in self.store.histories()], [ids[-1]])
        self.store.save_preferences(Preferences(history_enabled=True, history_count=2, history_mb=10))
        for _ in range(3):
            self.store.save_history(self.item(), b"small")
        self.assertEqual(len(self.store.histories()), 2)

    def test_reopen_restore_delete_and_undo_preserve_timestamp(self):
        self.store.save_preferences(Preferences(history_enabled=True))
        item = self.item(); self.store.save_history(item, b"wav")
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.histories(), [item])
        reopened.delete_history(item["id"])
        self.assertIsNone(reopened.history_audio(item["id"]))
        reopened.save_history(item,b"wav")
        self.assertEqual(reopened.histories()[0]["generatedAt"],item["generatedAt"])

    def test_voice_name_change_keeps_cache_and_delete_removes_it(self):
        self.store.update_voice("custom:one","声A",False)
        self.store.save_cache("key", b"wav", {"X-Generated-At":"timestamp"})
        self.store.update_voice("custom:one","声B",True)
        self.assertEqual(self.store.cache("key"), (b"wav", {"X-Generated-At":"timestamp"}))
        self.assertEqual(self.store.voice_meta()["custom:one"]["name"],"声B")
        self.store.remove_voice("custom:one")
        self.assertIsNone(self.store.cache("key"))

    def test_phrase_cache_bound_and_clear(self):
        for i in range(66):
            self.store.save_cache(str(i),b"audio",{})
        self.assertIsNone(self.store.cache("0"))
        self.assertIsNotNone(self.store.cache("65"))
        self.store.clear_cache()
        self.assertIsNone(self.store.cache("65"))

    def test_config_rejects_unsupported_modes(self):
        for value in [dict(speed=0), dict(phrases=[Phrase(id="a",label="a",text="a")]*2), dict(dictionary=[Reading(surface="a",reading="a")]*2)]:
            with self.assertRaises(ValueError): Preferences(**value)
        with self.assertRaises(ValueError): RuntimeConfig(device="cpu",precision="bf16")
        with self.assertRaises(ValueError): RuntimeConfig(device="web")
        self.assertEqual(RuntimeConfig(device="cpu",precision="fp32").models["omnivoice"].device,"cpu")

if __name__ == "__main__":
    unittest.main()
