"""SQLite diary store: drafts, entries, revisions and closed days.

Shares the database file with SqliteNutritionRepository. The REST app and the MCP
server may be separate processes, so atomicity comes from the database
(BEGIN IMMEDIATE plus draft_id UNIQUE), never from a Python lock.
"""
from __future__ import annotations
import json, sqlite3, uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone


def _utc_iso(value: datetime | str) -> str:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class SqliteDiaryStore:
    def __init__(self, path: str):
        self._path = path
        self._init()

    def _conn(self) -> sqlite3.Connection:
        # isolation_level=None: transactions are explicit (BEGIN IMMEDIATE ... COMMIT).
        c = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)
        c.row_factory = sqlite3.Row
        return c

    @contextmanager
    def _tx(self):
        """One connection, one write transaction; rolled back on any error, always closed."""
        with closing(self._conn()) as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")

    def _init(self):
        with closing(self._conn()) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS diary_draft(
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL, doc TEXT NOT NULL,
                expires_at TEXT NOT NULL, entry_id TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS diary_entry(
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL,
                draft_id TEXT UNIQUE NOT NULL, day TEXT NOT NULL,
                consumed_at TEXT NOT NULL, consumed_at_utc TEXT NOT NULL,
                voided INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_diary_entry_day "
                      "ON diary_entry(person_id,day,consumed_at_utc)")
            c.execute("""CREATE TABLE IF NOT EXISTS diary_revision(
                entry_id TEXT NOT NULL, rev INTEGER NOT NULL, doc TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(entry_id, rev))""")
            c.execute("""CREATE TABLE IF NOT EXISTS diary_day(
                person_id TEXT NOT NULL, day TEXT NOT NULL, closed_at TEXT NOT NULL,
                PRIMARY KEY(person_id, day))""")

    # ---- drafts
    def put_draft(self, person_id: str, doc: dict, expires_at: datetime) -> dict:
        did = str(uuid.uuid4())
        with self._tx() as c:
            c.execute("INSERT INTO diary_draft(id,person_id,doc,expires_at) VALUES(?,?,?,?)",
                      (did, person_id, json.dumps(doc), _utc_iso(expires_at)))
        return {**doc, "id": did}

    def get_draft(self, person_id: str, draft_id: str) -> dict | None:
        with closing(self._conn()) as c:
            r = c.execute("SELECT * FROM diary_draft WHERE id=? AND person_id=?",
                          (draft_id, person_id)).fetchone()
        if not r:
            return None
        return {**json.loads(r["doc"]), "id": r["id"], "expires_at": r["expires_at"],
                "entry_id": r["entry_id"]}

    # ---- entries
    @staticmethod
    def _view(c: sqlite3.Connection, e: sqlite3.Row) -> dict:
        r = c.execute("SELECT rev,doc FROM diary_revision WHERE entry_id=? "
                      "ORDER BY rev DESC LIMIT 1", (e["id"],)).fetchone()
        return {**json.loads(r["doc"]), "id": e["id"], "rev": r["rev"],
                "voided": bool(e["voided"]), "day": e["day"],
                "consumed_at": e["consumed_at"], "draft_id": e["draft_id"]}

    @staticmethod
    def _own_entry(c: sqlite3.Connection, person_id: str, entry_id: str) -> sqlite3.Row:
        e = c.execute("SELECT * FROM diary_entry WHERE id=? AND person_id=?",
                      (entry_id, person_id)).fetchone()
        if not e:
            raise LookupError("entry not found")
        return e

    def confirm_draft(self, person_id: str, draft_id: str, entry_doc: dict) -> tuple[dict, bool]:
        with self._tx() as c:
            d = c.execute("SELECT * FROM diary_draft WHERE id=? AND person_id=?",
                          (draft_id, person_id)).fetchone()
            if not d:
                raise LookupError("draft not found")
            existing = c.execute("SELECT * FROM diary_entry WHERE draft_id=?",
                                 (draft_id,)).fetchone()
            if existing:
                return self._view(c, existing), False
            eid = str(uuid.uuid4())
            now = _utc_iso(datetime.now(timezone.utc))
            c.execute("INSERT INTO diary_entry(id,person_id,draft_id,day,consumed_at,"
                      "consumed_at_utc,voided,created_at) VALUES(?,?,?,?,?,?,0,?)",
                      (eid, person_id, draft_id, entry_doc["day"], entry_doc["consumed_at"],
                       _utc_iso(entry_doc["consumed_at"]), now))
            c.execute("INSERT INTO diary_revision(entry_id,rev,doc,created_at) VALUES(?,1,?,?)",
                      (eid, json.dumps(entry_doc), now))
            c.execute("UPDATE diary_draft SET entry_id=? WHERE id=?", (eid, draft_id))
            e = c.execute("SELECT * FROM diary_entry WHERE id=?", (eid,)).fetchone()
            return self._view(c, e), True

    def get_entry(self, person_id: str, entry_id: str) -> dict | None:
        with closing(self._conn()) as c:
            e = c.execute("SELECT * FROM diary_entry WHERE id=? AND person_id=?",
                          (entry_id, person_id)).fetchone()
            return self._view(c, e) if e else None

    def add_revision(self, person_id: str, entry_id: str, doc: dict) -> dict:
        with self._tx() as c:
            e = self._own_entry(c, person_id, entry_id)
            if e["voided"]:
                raise LookupError("entry is voided")
            rev = c.execute("SELECT MAX(rev) FROM diary_revision WHERE entry_id=?",
                            (entry_id,)).fetchone()[0] + 1
            c.execute("INSERT INTO diary_revision(entry_id,rev,doc,created_at) VALUES(?,?,?,?)",
                      (entry_id, rev, json.dumps(doc), _utc_iso(datetime.now(timezone.utc))))
            return self._view(c, e)

    def void_entry(self, person_id: str, entry_id: str) -> dict:
        with self._tx() as c:
            self._own_entry(c, person_id, entry_id)
            c.execute("UPDATE diary_entry SET voided=1 WHERE id=?", (entry_id,))
            e = c.execute("SELECT * FROM diary_entry WHERE id=?", (entry_id,)).fetchone()
            return self._view(c, e)

    def list_entries(self, person_id: str, day: str) -> list[dict]:
        with closing(self._conn()) as c:
            es = c.execute("SELECT * FROM diary_entry WHERE person_id=? AND day=? AND voided=0 "
                           "ORDER BY consumed_at_utc, created_at", (person_id, day)).fetchall()
            return [self._view(c, e) for e in es]

    # ---- days
    def close_day(self, person_id: str, day: str, closed_at: datetime) -> None:
        with self._tx() as c:
            c.execute("INSERT OR IGNORE INTO diary_day(person_id,day,closed_at) VALUES(?,?,?)",
                      (person_id, day, _utc_iso(closed_at)))

    def is_day_closed(self, person_id: str, day: str) -> bool:
        with closing(self._conn()) as c:
            return c.execute("SELECT 1 FROM diary_day WHERE person_id=? AND day=?",
                             (person_id, day)).fetchone() is not None
