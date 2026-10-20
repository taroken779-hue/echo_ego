import tempfile
import unittest
from store import Store, Preferences, Reading
from reading_dictionary import Dictionary, Conflict, apply, validate_entries


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def entry(self,surface,reading,**kwargs):
        return {"surface":surface,"reading":reading,**kwargs}

    def test_longest_nonrecursive_and_original(self):
        entries = validate_entries([self.entry("日本","にほん"),self.entry("日本橋","にほんばし"),self.entry("橋","はし"),self.entry("はし","ばし")])
        result = apply("日本橋と橋と日本",entries,3)
        self.assertEqual(result["speech_text"],"にほんばしとはしとにほん")
        self.assertEqual(result["original_text"],"日本橋と橋と日本")
        self.assertEqual(len(result["applied_entries"]),3)

    def test_scope_disabled_and_english(self):
        entries=validate_entries([self.entry("明日","あす",match_mode="whole_text"),self.entry("今日","きょう",enabled=False)])
        self.assertEqual(apply("明日",entries)["speech_text"],"あす")
        self.assertEqual(apply("明日。今日",entries)["speech_text"],"明日。今日")
        self.assertEqual(apply("明日",entries,1,"ja_to_en")["speech_text"],"明日")
        self.assertIsNone(apply("明日",entries,1,"ja_to_en")["dictionary_revision"])

    def test_whole_text_wins_over_same_surface(self):
        entries=validate_entries([self.entry("明日","あした"),self.entry("明日","あす",match_mode="whole_text")])
        self.assertEqual(apply("明日",entries)["speech_text"],"あす")

    def test_invalid_new_rules_and_nfc_conflicts(self):
        for entries in [[self.entry("a","英語")],[self.entry("a","abc")],[self.entry("[a]","えー")],
                        [self.entry("ガ","が"),self.entry("ガ","が")],[self.entry("a","あ",id="same"),self.entry("b","びー",id="same")]]:
            with self.assertRaises(ValueError):validate_entries(entries)

    def test_legacy_values_preserved_but_new_reading_validated(self):
        self.store.save_preferences(Preferences(dictionary=[Reading(surface="AI",reading="artificial intelligence")]))
        dictionary=Dictionary(self.store)
        current=dictionary.get()
        self.assertEqual(current["entries"][0]["reading"],"artificial intelligence")
        dictionary.update(current["entries"],current["revision"])
        current=dictionary.get();current["entries"][0]["reading"]="different English"
        with self.assertRaises(ValueError):dictionary.update(current["entries"],current["revision"])

    def test_revision_conflict_is_atomic_and_reopen_preserves_ids(self):
        dictionary=Dictionary(self.store)
        saved=dictionary.update([self.entry("日本橋","にほんばし")],1)
        with self.assertRaises(Conflict):dictionary.update([],1)
        self.assertEqual(Dictionary(Store(self.temp.name)).get(),saved)

    def test_expansion_limit_and_control_tokens(self):
        entries=validate_entries([self.entry("a","あ"*80)])
        with self.assertRaises(ValueError):apply("a"*5,entries)
        with self.assertRaises(ValueError):apply("[laughter]",[])


if __name__=="__main__":unittest.main()
