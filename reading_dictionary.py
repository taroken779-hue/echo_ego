"""Versioned, non-recursive Japanese pronunciation rules. No inference dependencies."""
import hashlib
import json
import re
import unicodedata
import uuid
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal


class Conflict(ValueError):
    pass


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=64)
    surface: str = Field(min_length=1, max_length=40)
    reading: str = Field(min_length=1, max_length=80)
    match_mode: Literal["substring", "whole_text"] = "substring"
    enabled: bool = True
    note: str = Field(default="", max_length=100)


def normalized(text):
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def safe_text(text):
    if any(c in "[]<>" or (unicodedata.category(c).startswith("C") and c not in "\n\t") for c in text):
        raise ValueError("制御記号 [ ] < > や制御文字は発話に使えません")
    if not re.search(r"\w", text):
        raise ValueError("読み上げる文字を入力してください")
    return text


def validate_entries(entries, previous=()):
    if len(entries) > 100:
        raise ValueError("読み辞書は100件までです")
    old = {e["id"]: e for e in previous}
    result, seen = [], set()
    ids = set()
    for raw in entries:
        entry = Entry.model_validate(raw).model_dump()
        for key in ("surface", "reading"):
            entry[key] = normalized(entry[key])
            if not entry[key].strip() or any(unicodedata.category(c).startswith("C") or c in "[]<>" for c in entry[key]):
                raise ValueError("単語と読みには空欄・改行・制御記号を使えません")
        key = (entry["surface"], entry["match_mode"])
        if key in seen or entry["id"] in ids:
            raise ValueError("読み辞書の単語・適用範囲またはIDが重複しています")
        seen.add(key)
        ids.add(entry["id"])
        unchanged = old.get(entry["id"], {}).get("reading") == entry["reading"]
        if not unchanged and (not re.fullmatch(r"[ぁ-ゖァ-ヺゝゞヽヾー・、。！？!? ,．]+", entry["reading"]) or not re.search(r"[ぁ-ゖァ-ヺ]", entry["reading"])):
            raise ValueError("読みはひらがな・カタカナで入力してください")
        result.append(entry)
    return result


def apply(text, entries, revision=None, mode="ja", use_dictionary=True):
    output, counts = [], {}
    source = normalized(text)
    ordered = sorted(enumerate(entries), key=lambda pair: (-len(pair[1]["surface"]), pair[1].get("match_mode") != "whole_text", pair[0]))
    index = 0
    while index < len(source):
        found = None
        if mode == "ja" and use_dictionary:
            for _, entry in ordered:
                if not entry.get("enabled", True):
                    continue
                word = entry["surface"]
                if entry.get("match_mode") == "whole_text" and source != word:
                    continue
                if source.startswith(word, index):
                    found = entry
                    break
        if found:
            output.append(found["reading"])
            index += len(found["surface"])
            counts[found["id"]] = counts.get(found["id"], 0) + 1
        else:
            output.append(source[index])
            index += 1
    speech = "".join(output)
    if len(speech) > (320 if mode == "ja" else 640):
        raise ValueError("読み辞書の適用後の文が長すぎます")
    safe_text(speech)
    return {"dictionary_revision": revision if mode == "ja" else None, "original_text": text,
            "speech_text": speech, "applied_entries": [dict(entry_id=e["id"], surface=e["surface"], reading=e["reading"], count=counts[e["id"]]) for e in entries if e["id"] in counts],
            "warnings": [] if mode == "ja" else ["英語モードには日本語読み辞書を適用しません"]}


class Dictionary:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            exists = db.execute("SELECT name FROM sqlite_master WHERE name='reading_dictionary'").fetchone()
            if not exists:
                # Preserve the original settings as a recoverable migration record.
                row = db.execute("SELECT payload FROM settings WHERE id=1").fetchone()
                old = json.loads(row[0]) if row else {}
                db.execute("CREATE TABLE reading_dictionary (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL, migration_backup TEXT NOT NULL)")
                entries, seen = [], set()
                for i, value in enumerate(old.get("dictionary", [])):
                    item = Entry(surface=normalized(value["surface"]), reading=normalized(value["reading"]), id=f"migrated-{i}").model_dump()
                    key = item["surface"]
                    if key not in seen:
                        entries.append(item)
                        seen.add(key)
                db.execute("INSERT INTO reading_dictionary VALUES (1,1,?,?)", (json.dumps(entries, ensure_ascii=False), json.dumps(old, ensure_ascii=False)))

    def get(self, db=None):
        if db is None:
            with self.store.connect() as connection:
                return self.get(connection)
        row = db.execute("SELECT revision,payload FROM reading_dictionary WHERE id=1").fetchone()
        return {"schema_version": 2, "revision": row[0], "entries": json.loads(row[1])}

    def update(self, entries, expected, db=None):
        if db is None:
            with self.store.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                return self.update(entries, expected, connection)
        current = self.get(db)
        if current["revision"] != expected:
            raise Conflict("辞書が別の画面で更新されました。再読み込みしてください")
        entries = validate_entries(entries, current["entries"])
        revision = expected + 1
        db.execute("UPDATE reading_dictionary SET revision=?,payload=? WHERE id=1", (revision, json.dumps(entries, ensure_ascii=False)))
        return {"schema_version": 2, "revision": revision, "entries": entries}

    @staticmethod
    def projection(value):
        return [{"surface": e["surface"], "reading": e["reading"]} for e in value["entries"] if e["match_mode"] == "substring"]

    def etag(self):
        # Whole preferences ETag protects legacy read/modify/write clients too.
        content = self.store.preferences().model_dump_json() + json.dumps(self.get(), sort_keys=True)
        return '"' + hashlib.sha256(content.encode()).hexdigest() + '"'
