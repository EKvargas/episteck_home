import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from app.store.diary_sqlite import SqliteDiaryStore

EXP = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "n.db")


@pytest.fixture
def store(db):
    return SqliteDiaryStore(db)


def entry_doc(consumed="2026-11-18T12:00:00+01:00", day="2026-11-18", items=None):
    return {"day": day, "consumed_at": consumed, "items": items or [{"food": "apple"}]}


def rows(db, sql, args=()):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def test_confirm_twice_returns_same_entry(store):
    d = store.put_draft("p1", {"items": []}, EXP)
    e1, c1 = store.confirm_draft("p1", d["id"], entry_doc())
    e2, c2 = store.confirm_draft("p1", d["id"], entry_doc())
    assert c1 is True and c2 is False
    assert e1["id"] == e2["id"]


def test_concurrent_confirms_create_one_entry(db):
    s0 = SqliteDiaryStore(db)
    d = s0.put_draft("p1", {"items": []}, EXP)
    stores = [SqliteDiaryStore(db), SqliteDiaryStore(db)]
    barrier = threading.Barrier(2)
    out, errs = [], []

    def run(s):
        try:
            barrier.wait()
            out.append(s.confirm_draft("p1", d["id"], entry_doc()))
        except Exception as e:  # pragma: no cover
            errs.append(e)

    ts = [threading.Thread(target=run, args=(s,)) for s in stores]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    assert len(out) == 2
    assert out[0][0]["id"] == out[1][0]["id"]
    assert sorted(c for _, c in out) == [False, True]
    assert rows(db, "SELECT COUNT(*) FROM diary_entry WHERE draft_id=?", (d["id"],)) == [(1,)]
    assert rows(db, "SELECT COUNT(*) FROM diary_revision") == [(1,)]


def test_other_persons_draft_is_invisible(store):
    d = store.put_draft("p1", {"items": []}, EXP)
    assert store.get_draft("p2", d["id"]) is None
    with pytest.raises(LookupError):
        store.confirm_draft("p2", d["id"], entry_doc())
    with pytest.raises(LookupError):
        store.confirm_draft("p1", "nope", entry_doc())


def test_get_draft_fields(store):
    d = store.put_draft("p1", {"items": [1]}, EXP)
    g = store.get_draft("p1", d["id"])
    assert g["id"] == d["id"] and g["items"] == [1]
    assert g["expires_at"] == "2026-11-19T12:00:00+00:00"
    assert g["entry_id"] is None
    e, _ = store.confirm_draft("p1", d["id"], entry_doc())
    assert store.get_draft("p1", d["id"])["entry_id"] == e["id"]
    assert store.get_draft("p1", "unknown") is None


def test_revision_and_void(store):
    d = store.put_draft("p1", {}, EXP)
    e, _ = store.confirm_draft("p1", d["id"], entry_doc())
    assert e["rev"] == 1 and e["voided"] is False
    r = store.add_revision("p1", e["id"], {"items": [{"food": "pear"}]})
    assert r["rev"] == 2 and r["items"] == [{"food": "pear"}]
    assert r["day"] == "2026-11-18" and r["draft_id"] == d["id"]
    assert store.list_entries("p1", "2026-11-18")[0]["rev"] == 2
    v = store.void_entry("p1", e["id"])
    assert v["voided"] is True and v["rev"] == 2
    assert store.list_entries("p1", "2026-11-18") == []
    assert store.get_entry("p1", e["id"])["voided"] is True
    assert rows(store._path, "SELECT COUNT(*) FROM diary_revision") == [(2,)]


def test_void_is_idempotent_and_revise_voided_fails(store):
    d = store.put_draft("p1", {}, EXP)
    e, _ = store.confirm_draft("p1", d["id"], entry_doc())
    v1 = store.void_entry("p1", e["id"])
    v2 = store.void_entry("p1", e["id"])
    assert v1 == v2 and v2["voided"] is True
    with pytest.raises(LookupError):
        store.add_revision("p1", e["id"], {"items": []})


def test_other_persons_entry(store):
    d = store.put_draft("p1", {}, EXP)
    e, _ = store.confirm_draft("p1", d["id"], entry_doc())
    assert store.get_entry("p2", e["id"]) is None
    with pytest.raises(LookupError):
        store.add_revision("p2", e["id"], {"items": []})
    with pytest.raises(LookupError):
        store.void_entry("p2", e["id"])
    assert store.list_entries("p2", "2026-11-18") == []
    with pytest.raises(LookupError):
        store.void_entry("p1", "missing")


def test_close_day(store):
    assert store.is_day_closed("p1", "2026-11-18") is False
    store.close_day("p1", "2026-11-18", datetime(2026, 11, 18, 20, tzinfo=timezone.utc))
    store.close_day("p1", "2026-11-18", datetime(2026, 11, 19, 20, tzinfo=timezone.utc))
    assert store.is_day_closed("p1", "2026-11-18") is True
    assert store.is_day_closed("p2", "2026-11-18") is False
    assert store.is_day_closed("p1", "2026-11-19") is False
    assert rows(store._path, "SELECT closed_at FROM diary_day") == [("2026-11-18T20:00:00+00:00",)]


def test_entries_ordered_by_consumed_at(store):
    # string order: A (22:45Z) < B (23:30+01:00); time order: B (22:30Z) < A (22:45Z)
    a = "2026-11-18T22:45:00Z"
    b = "2026-11-18T23:30:00+01:00"
    ids = {}
    for name, ts in (("a", a), ("b", b)):
        d = store.put_draft("p1", {}, EXP)
        e, _ = store.confirm_draft("p1", d["id"], entry_doc(consumed=ts))
        ids[name] = e["id"]
    got = [x["id"] for x in store.list_entries("p1", "2026-11-18")]
    assert got == [ids["b"], ids["a"]]
    assert store.list_entries("p1", "2026-11-18")[0]["consumed_at"] == b
