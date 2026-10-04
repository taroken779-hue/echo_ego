"""SQLite storage for preferences, voice labels, bounded audio history and phrases."""
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pydantic import BaseModel, Field, model_validator


class Phrase(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    text: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=32)


class Reading(BaseModel):
    surface: str = Field(min_length=1, max_length=40)
    reading: str = Field(min_length=1, max_length=80)


class Preferences(BaseModel):
    voice: str = "design:calm_male"
    speed: float = Field(default=1, ge=.7, le=1.5)
    steps: int = Field(default=4, ge=4, le=8)
    volume: float = Field(default=.8, ge=0, le=1)
    output_device: str = ""
    history_enabled: bool = False
    history_count: int = Field(default=50, ge=1, le=500)
    history_days: int = Field(default=7, ge=1, le=365)
    history_mb: int = Field(default=100, ge=1, le=1000)
    phrases: list[Phrase] = Field(default_factory=lambda: [Phrase(id="yes", label="はい、わかりました", text="はい、わかりました。"), Phrase(id="thanks", label="ありがとうございます", text="ありがとうございます。"), Phrase(id="wait", label="少し待ってください", text="少し待ってください。")], max_length=9)
    dictionary: list[Reading] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_options(self):
        if self.steps not in {4, 6, 8}:
            raise ValueError("ステップは4・6・8を選択してください")
        if len({p.id for p in self.phrases}) != len(self.phrases):
            raise ValueError("定型句IDが重複しています")
        if len({r.surface for r in self.dictionary}) != len(self.dictionary):
            raise ValueError("読み辞書の単語が重複しています")
        return self


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "echo-ego.sqlite3"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS voices (id TEXT PRIMARY KEY, name TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL, audio BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS cache (id TEXT PRIMARY KEY, used_at REAL NOT NULL, headers TEXT NOT NULL, audio BLOB NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def preferences(self):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM settings WHERE id=1").fetchone()
        return Preferences.model_validate_json(row[0]) if row else Preferences()

    def save_preferences(self, prefs):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (1, ?)", (prefs.model_dump_json(),))
            if not prefs.history_enabled:
                db.execute("DELETE FROM history")
        self.prune(prefs)

    def voice_meta(self):
        with self.connect() as db:
            return {r["id"]: dict(r) for r in db.execute("SELECT * FROM voices")}

    def update_voice(self, voice_id, name, favorite):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO voices VALUES (?, ?, ?)", (voice_id, name, int(favorite)))

    def remove_voice(self, voice_id):
        with self.connect() as db:
            db.execute("DELETE FROM voices WHERE id=?", (voice_id,))
            db.execute("DELETE FROM cache")

    def prune(self, prefs=None):
        prefs = prefs or self.preferences()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=prefs.history_days)).isoformat()
        with self.connect() as db:
            db.execute("DELETE FROM history WHERE created_at < ?", (cutoff,))
            rows = db.execute("SELECT id, length(audio) size FROM history ORDER BY created_at DESC, rowid DESC").fetchall()
            size = 0
            for index, row in enumerate(rows):
                size += row["size"]
                if index >= prefs.history_count or size > prefs.history_mb * 1024 * 1024:
                    db.execute("DELETE FROM history WHERE id=?", (row["id"],))

    def save_history(self, item, audio):
        with self.connect() as db:
            # Check inside the write transaction so turning storage off cannot race a save.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM settings WHERE id=1").fetchone()
            if not row or not Preferences.model_validate_json(row[0]).history_enabled:
                raise ValueError("履歴の保存はオフです")
            db.execute("INSERT OR REPLACE INTO history VALUES (?, ?, ?, ?)", (item["id"], item["generatedAt"], json.dumps(item, ensure_ascii=False), audio))
        self.prune()

    def histories(self):
        self.prune()
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM history ORDER BY created_at DESC, rowid DESC")]

    def history_audio(self, item_id):
        with self.connect() as db:
            row = db.execute("SELECT audio FROM history WHERE id=?", (item_id,)).fetchone()
        return bytes(row[0]) if row else None

    def delete_history(self, item_id=None):
        with self.connect() as db:
            if item_id is None:
                db.execute("DELETE FROM history")
            else:
                db.execute("DELETE FROM history WHERE id=?", (item_id,))

    def cache(self, key):
        with self.connect() as db:
            row = db.execute("SELECT audio, headers FROM cache WHERE id=?", (key,)).fetchone()
            if row:
                db.execute("UPDATE cache SET used_at=? WHERE id=?", (time.time(), key))
                return bytes(row[0]), json.loads(row[1])
        return None

    def save_cache(self, key, audio, headers):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)", (key, time.time(), json.dumps(headers), audio))
            rows = db.execute("SELECT id, length(audio) size FROM cache ORDER BY used_at DESC").fetchall()
            size = 0
            for index, row in enumerate(rows):
                size += row["size"]
                if index >= 64 or size > 50 * 1024 * 1024:
                    db.execute("DELETE FROM cache WHERE id=?", (row["id"],))

    def clear_cache(self):
        with self.connect() as db:
            db.execute("DELETE FROM cache")
