"""SQLite implementation of NutritionRepository. Data file lives under the mounted
/srv/episteck/services/nutrition/data (persistent). person_id is an external stable
reference (future Episteck Core identity) — this service does NOT own identity.
"""
from __future__ import annotations
import json, sqlite3, uuid, threading
from .repository import NutritionRepository


class SqliteNutritionRepository(NutritionRepository):
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._init()

    def _conn(self):
        c = sqlite3.connect(self._path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._lock, self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS profile(
                person_id TEXT PRIMARY KEY, doc TEXT NOT NULL, updated_at TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS intake(
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL, date TEXT NOT NULL,
                kind TEXT NOT NULL, doc TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_intake ON intake(person_id,date,kind)")

    def upsert_profile(self, person_id: str, profile: dict) -> dict:
        import datetime
        doc = json.dumps(profile)
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO profile(person_id,doc,updated_at) VALUES(?,?,datetime('now')) "
                      "ON CONFLICT(person_id) DO UPDATE SET doc=excluded.doc, updated_at=excluded.updated_at",
                      (person_id, doc))
        return self.get_profile(person_id)

    def get_profile(self, person_id: str) -> dict | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT doc FROM profile WHERE person_id=?", (person_id,)).fetchone()
        return json.loads(r["doc"]) if r else None

    def add_intake(self, person_id: str, record: dict) -> dict:
        rid = record.get("id") or str(uuid.uuid4())
        record = {**record, "id": rid, "person_id": person_id}
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO intake(id,person_id,date,kind,doc) VALUES(?,?,?,?,?)",
                      (rid, person_id, record["date"], record["kind"], json.dumps(record)))
        return record

    def list_intake(self, person_id: str, date: str, kind: str | None = None) -> list[dict]:
        q = "SELECT doc FROM intake WHERE person_id=? AND date=?"
        args = [person_id, date]
        if kind:
            q += " AND kind=?"; args.append(kind)
        with self._lock, self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [json.loads(r["doc"]) for r in rows]
