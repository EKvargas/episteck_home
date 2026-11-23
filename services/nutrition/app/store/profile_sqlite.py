"""SQLite store for versioned personal profiles and profile drafts.

Shares the database file with SqliteNutritionRepository (legacy `profile` table) and
SqliteDiaryStore. Atomicity comes from BEGIN IMMEDIATE, never from a Python lock.
"""
from __future__ import annotations
import json, sqlite3, uuid
from collections.abc import Callable
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone

from nutrition_domain.profile import ProfileInputs, inputs_to_doc
from nutrition_domain.profile_versions import ORIGINS


def _utc_iso(value: datetime | str) -> str:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


class SqliteProfileStore:
    def __init__(self, path: str):
        self._path = path
        self._init()

    def _conn(self) -> sqlite3.Connection:
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
            c.execute("""CREATE TABLE IF NOT EXISTS profile_version(
                person_id TEXT NOT NULL, version INTEGER NOT NULL, valid_from TEXT NOT NULL,
                origin TEXT NOT NULL, method TEXT NOT NULL, doc TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(person_id, version))""")
            c.execute("""CREATE TABLE IF NOT EXISTS profile_draft(
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL, doc TEXT NOT NULL,
                expires_at TEXT NOT NULL, version INTEGER)""")

    # ---- versions
    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {"version": r["version"], "valid_from": r["valid_from"], "origin": r["origin"],
                "method": r["method"], "doc": json.loads(r["doc"]), "created_at": r["created_at"]}

    @staticmethod
    def _latest(c: sqlite3.Connection, person_id: str) -> sqlite3.Row | None:
        return c.execute("SELECT * FROM profile_version WHERE person_id=? "
                         "ORDER BY version DESC LIMIT 1", (person_id,)).fetchone()

    def _append(self, c: sqlite3.Connection, person_id: str, doc: dict, valid_from: str,
                origin: str, method: str) -> dict:
        if origin not in ORIGINS:
            raise ValueError("unknown origin")
        n = c.execute("SELECT COALESCE(MAX(version),0) FROM profile_version WHERE person_id=?",
                      (person_id,)).fetchone()[0] + 1
        c.execute("INSERT INTO profile_version(person_id,version,valid_from,origin,method,doc,"
                  "created_at) VALUES(?,?,?,?,?,?,?)",
                  (person_id, n, valid_from, origin, method, json.dumps(doc),
                   _utc_iso(datetime.now(timezone.utc))))
        return self._row(c.execute("SELECT * FROM profile_version WHERE person_id=? AND version=?",
                                   (person_id, n)).fetchone())

    def list_versions(self, person_id: str) -> list[dict]:
        with closing(self._conn()) as c:
            return [self._row(r) for r in c.execute(
                "SELECT * FROM profile_version WHERE person_id=? ORDER BY version", (person_id,))]

    def latest(self, person_id: str) -> dict | None:
        with closing(self._conn()) as c:
            r = self._latest(c, person_id)
            return self._row(r) if r else None

    def append_version(self, person_id: str, doc: dict, valid_from: str, origin: str,
                       method: str) -> dict:
        with self._tx() as c:
            return self._append(c, person_id, doc, valid_from, origin, method)

    # ---- drafts
    def put_draft(self, person_id: str, doc: dict, expires_at: datetime) -> dict:
        did = str(uuid.uuid4())
        with self._tx() as c:
            c.execute("INSERT INTO profile_draft(id,person_id,doc,expires_at) VALUES(?,?,?,?)",
                      (did, person_id, json.dumps(doc), _utc_iso(expires_at)))
        return {**doc, "id": did}

    def get_draft(self, person_id: str, draft_id: str) -> dict | None:
        with closing(self._conn()) as c:
            r = c.execute("SELECT * FROM profile_draft WHERE id=? AND person_id=?",
                          (draft_id, person_id)).fetchone()
        if not r:
            return None
        return {**json.loads(r["doc"]), "id": r["id"], "expires_at": r["expires_at"],
                "version": r["version"]}

    def confirm_draft(self, person_id: str, draft_id: str,
                      build: Callable[[dict | None, dict], dict],
                      valid_from: str, method: str) -> tuple[dict, bool]:
        with self._tx() as c:
            d = c.execute("SELECT * FROM profile_draft WHERE id=? AND person_id=?",
                          (draft_id, person_id)).fetchone()
            if not d:
                raise LookupError("draft not found")
            if d["version"] is not None:
                r = c.execute("SELECT * FROM profile_version WHERE person_id=? AND version=?",
                              (person_id, d["version"])).fetchone()
                return self._row(r), False
            latest = self._latest(c, person_id)
            new_doc = build(json.loads(latest["doc"]) if latest else None, json.loads(d["doc"]))
            row = self._append(c, person_id, new_doc, valid_from, "PROFILE", method)
            c.execute("UPDATE profile_draft SET version=? WHERE id=?", (row["version"], draft_id))
            return row, True

    # ---- legacy migration
    def migrate_legacy(self, today: str) -> int:
        with closing(self._conn()) as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile'"
                             ).fetchone():
                return 0
            legacy = c.execute("SELECT person_id, doc FROM profile").fetchall()
        migrated = 0
        for row in legacy:
            try:
                old = json.loads(row["doc"])
            except (TypeError, ValueError):
                continue
            if not isinstance(old, dict):
                continue
            due = None
            if isinstance(old.get("due_date"), str):
                try:
                    due = date.fromisoformat(old["due_date"])
                except ValueError:
                    due = None
            inputs = ProfileInputs(
                mode="PREGNANCY" if old.get("context") == "PREGNANCY" else "GENERAL",
                due_date=due,
                preferences=_text(old.get("preferences")),
                dislikes=_text(old.get("dislikes")),
                intolerances=_text(old.get("intolerances")) or _text(old.get("explicit_intolerances")),
            )
            doc = {"inputs": inputs_to_doc(inputs), "changed": [], "targets_at_confirmation": []}
            with self._tx() as c:
                if self._latest(c, row["person_id"]) is not None:
                    continue
                self._append(c, row["person_id"], doc, today, "MIGRATED", "legacy")
                migrated += 1
        return migrated
