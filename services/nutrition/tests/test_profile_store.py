import json
import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from nutrition_domain.target_method import METHOD_V1

from app.store.profile_sqlite import SqliteProfileStore

EXP = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "n.db")


@pytest.fixture
def store(db):
    return SqliteProfileStore(db)


def build(latest, draft):
    return {"inputs": draft["inputs"], "prev": latest}


def test_append_numbers_versions_per_person(store):
    a = store.append_version("p1", {"x": 1}, "2026-11-23", "PROFILE", "m")
    b = store.append_version("p1", {"x": 2}, "2026-11-24", "MODE", "m")
    c = store.append_version("p2", {"x": 3}, "2026-11-23", "PROFILE", "m")
    assert (a["version"], b["version"], c["version"]) == (1, 2, 1)
    assert [v["version"] for v in store.list_versions("p1")] == [1, 2]
    assert store.latest("p1")["doc"] == {"x": 2}
    assert store.latest("nobody") is None
    assert set(a) == {"version", "valid_from", "origin", "method", "doc", "created_at"}


def test_draft_is_per_person(store):
    d = store.put_draft("p1", {"inputs": {}}, EXP)
    g = store.get_draft("p1", d["id"])
    assert g["id"] == d["id"] and g["version"] is None
    assert g["expires_at"] == "2026-11-24T12:00:00+00:00"
    assert store.get_draft("p2", d["id"]) is None
    with pytest.raises(LookupError):
        store.confirm_draft("p2", d["id"], build, "2026-11-23", "m")


def test_confirm_twice_returns_same_version(store):
    d = store.put_draft("p1", {"inputs": {"a": 1}}, EXP)
    v1, c1 = store.confirm_draft("p1", d["id"], build, "2026-11-23", "m")
    v2, c2 = store.confirm_draft("p1", d["id"], build, "2026-11-23", "m")
    assert (c1, c2) == (True, False) and v1 == v2
    assert v1["origin"] == "PROFILE"
    assert store.get_draft("p1", d["id"])["version"] == v1["version"]


def test_concurrent_confirms_make_one_version(db):
    d = SqliteProfileStore(db).put_draft("p1", {"inputs": {}}, EXP)
    stores = [SqliteProfileStore(db), SqliteProfileStore(db)]
    barrier = threading.Barrier(2)
    out, errs = [], []

    def run(s):
        try:
            barrier.wait()
            out.append(s.confirm_draft("p1", d["id"], build, "2026-11-23", "m"))
        except Exception as e:  # pragma: no cover
            errs.append(e)

    ts = [threading.Thread(target=run, args=(s,)) for s in stores]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and len(out) == 2
    assert out[0][0]["version"] == out[1][0]["version"]
    assert sorted(c for _, c in out) == [False, True]
    assert len(stores[0].list_versions("p1")) == 1


def test_confirm_builds_on_the_latest_version(store):
    d = store.put_draft("p1", {"inputs": {}}, EXP)
    store.append_version("p1", {"mode": "PREGNANCY"}, "2026-11-23", "MODE", "m")
    seen = {}

    def b(latest, draft):
        seen["latest"] = latest
        return {"ok": True}

    v, created = store.confirm_draft("p1", d["id"], b, "2026-11-23", "m")
    assert seen["latest"] == {"mode": "PREGNANCY"}
    assert created and v["version"] == 2


def test_failing_build_leaves_nothing(store):
    d = store.put_draft("p1", {"inputs": {}}, EXP)

    def boom(latest, draft):
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        store.confirm_draft("p1", d["id"], boom, "2026-11-23", "m")
    assert store.list_versions("p1") == []
    assert store.get_draft("p1", d["id"])["version"] is None


def test_migrate_without_legacy_table_returns_zero(store):
    assert store.migrate_legacy("2026-11-23") == 0


def test_migrate_legacy_maps_rows_once(tmp_path):
    db = str(tmp_path / "n.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE profile(person_id TEXT PRIMARY KEY, doc TEXT NOT NULL, updated_at TEXT)")
    rows = {
        "a": {"context": "PREGNANCY", "due_date": "2027-05-15", "explicit_intolerances": "x",
              "targets": {"kcal": "2000"}},
        "b": {"context": "G1_5_SYNTHETIC", "preferences": "p", "due_date": "not-a-date"},
        "c": {"context": "GENERAL", "preferences": "legacy"},
    }
    for k, v in rows.items():
        c.execute("INSERT INTO profile VALUES(?,?,NULL)", (k, json.dumps(v)))
    c.commit()
    c.close()
    store = SqliteProfileStore(db)
    store.append_version("c", {"existing": True}, "2026-11-01", "PROFILE", "m")
    assert store.migrate_legacy("2026-11-23") == 2
    a = store.latest("a")
    assert a["origin"] == "MIGRATED" and a["valid_from"] == "2026-11-23"
    assert a["method"] == METHOD_V1
    assert a["doc"]["inputs"]["mode"] == "PREGNANCY"
    assert a["doc"]["inputs"]["intolerances"] == "x"
    assert a["doc"]["inputs"]["due_date"] == "2027-05-15"
    assert a["doc"]["changed"] == [] and a["doc"]["targets_at_confirmation"] == []
    assert "2000" not in json.dumps(a["doc"])
    assert a["doc"]["inputs"].get("height_cm") is None
    b = store.latest("b")["doc"]["inputs"]
    assert b["mode"] == "GENERAL" and b["preferences"] == "p" and b.get("due_date") is None
    assert store.latest("c")["doc"] == {"existing": True}
    assert store.migrate_legacy("2026-11-24") == 0
    assert len(store.list_versions("a")) == 1
