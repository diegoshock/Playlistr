"""Local state. Credentials are encrypted with a key stored outside the database."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet


class Store:
    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "playlistr.db"
        key = self.directory / "credentials.key"
        if not key.exists():
            try:
                fd = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artists(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, mbid TEXT,
                    status TEXT NOT NULL DEFAULT 'pending', genres TEXT NOT NULL DEFAULT '[]',
                    evidence TEXT NOT NULL DEFAULT '[]', candidates TEXT NOT NULL DEFAULT '[]',
                    checked_at TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS songs(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL,
                    album TEXT NOT NULL, duration INTEGER NOT NULL, year INTEGER,
                    library_genre TEXT);
                CREATE TABLE IF NOT EXISTS song_artists(
                    song_id TEXT REFERENCES songs(id) ON DELETE CASCADE,
                    artist_id TEXT REFERENCES artists(id) ON DELETE CASCADE,
                    PRIMARY KEY(song_id,artist_id));
                CREATE INDEX IF NOT EXISTS song_artists_artist ON song_artists(artist_id);
                CREATE TABLE IF NOT EXISTS playlists(
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, remote_id TEXT NOT NULL,
                    song_count INTEGER NOT NULL, filters TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def setting(self, key, default=None):
        with self.db() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def credentials(self):
        data = self.setting("navidrome")
        if data:
            data["password"] = self.cipher.decrypt(data["password"].encode()).decode()
        return data

    def save_credentials(self, data):
        data = dict(data)
        data["password"] = self.cipher.encrypt(data["password"].encode()).decode()
        self.set_setting("navidrome", data)

    def artists(self):
        with self.db() as db:
            rows = db.execute("""SELECT a.*, COUNT(sa.song_id) AS song_count
                FROM artists a LEFT JOIN song_artists sa ON a.id=sa.artist_id
                GROUP BY a.id ORDER BY a.name COLLATE NOCASE""").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("genres", "evidence", "candidates"):
                item[key] = json.loads(item[key])
            result.append(item)
        return result
