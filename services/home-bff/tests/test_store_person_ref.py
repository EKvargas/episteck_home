import sqlite3
import time

from home_bff import store as store_module
from home_bff.store import SessionStore


def _pre_plan_schema() -> str:
    schema = store_module._SCHEMA
    stripped = schema.replace(
        "    person_ref           TEXT NOT NULL DEFAULT '',\n", ""
    ).replace("    grantor_ref        TEXT NOT NULL DEFAULT '',\n", "")
    assert "person_ref" not in stripped and "grantor_ref" not in stripped
    return stripped


def _make_pre_plan_file(path: str) -> None:
    now = int(time.time())
    db = sqlite3.connect(path)
    db.executescript(_pre_plan_schema())
    db.execute(
        "INSERT INTO bff_session (session_id, home_session_id, access_token,"
        " refresh_token, created_at, expires_at) VALUES ('S1','H1','tok',NULL,?,?)",
        (now, now + 600),
    )
    db.execute(
        "INSERT INTO runtime_grant (runtime_id, home_session_id, allowed_audiences,"
        " granted_at, expires_at, last_mint_at) VALUES"
        " ('home-agent-primary','HDS-0','home-control-plane',?,?,NULL)",
        (now, now + 600),
    )
    db.commit()
    db.close()


def test_old_store_file_gains_both_columns_with_empty_defaults(tmp_path):
    path = str(tmp_path / "old.db")
    _make_pre_plan_file(path)
    store = SessionStore(path)
    session = store.get_session("S1")
    grant = store.resolve_runtime_grant("home-agent-primary")
    assert session is not None and session.person_ref == ""
    assert grant is not None and grant.grantor_ref == ""


def test_session_and_grant_round_trip_their_refs(tmp_path):
    store = SessionStore(str(tmp_path / "s.db"))
    session = store.create_session(
        home_session_id="H1", access_token="t", refresh_token=None, person_ref="ref-a"
    )
    assert session.person_ref == "ref-a"
    assert store.get_session(session.session_id).person_ref == "ref-a"
    claimed, _ = store.create_session_and_claim_runtime(
        home_session_id="H2",
        access_token="t",
        refresh_token=None,
        runtime_id="home-agent-ana",
        person_ref="ref-b",
    )
    assert claimed.person_ref == "ref-b"
    assert store.get_session(claimed.session_id).person_ref == "ref-b"
    grant = store.put_runtime_grant(
        "home-agent-ana", "HDS-1", {"home-control-plane"}, ttl_seconds=60,
        grantor_ref="ref-b",
    )
    assert grant.grantor_ref == "ref-b"
    assert store.resolve_runtime_grant("home-agent-ana").grantor_ref == "ref-b"


def test_list_grants_for_returns_only_live_rows_of_that_person(tmp_path):
    store = SessionStore(str(tmp_path / "s.db"))
    aud = {"home-control-plane"}
    store.put_runtime_grant("home-agent-primary", "H1", aud, ttl_seconds=60, grantor_ref="A")
    store.put_runtime_grant("home-agent-ana", "H2", aud, ttl_seconds=60, grantor_ref="B")
    store.put_runtime_grant("x", "H3", aud, ttl_seconds=60, grantor_ref="B")
    store.put_runtime_grant("y", "H4", aud, ttl_seconds=60)
    with store._mutation() as db:
        db.execute("UPDATE runtime_grant SET expires_at = ? WHERE runtime_id = 'x'",
                   (int(time.time()) - 1,))
    assert [g.runtime_id for g in store.list_runtime_grants_for("B")] == ["home-agent-ana"]
    assert store.list_runtime_grants_for("") == []


def test_conditional_delete_keeps_a_newer_grant(tmp_path):
    store = SessionStore(str(tmp_path / "s.db"))
    aud = {"home-control-plane"}
    store.put_runtime_grant("home-agent-ana", "HDS-1", aud, ttl_seconds=60, grantor_ref="B")
    store.put_runtime_grant("home-agent-ana", "HDS-2", aud, ttl_seconds=60, grantor_ref="B")
    assert store.delete_runtime_grant("home-agent-ana", home_session_id="HDS-1") is False
    assert store.resolve_runtime_grant("home-agent-ana").home_session_id == "HDS-2"
    assert store.delete_runtime_grant("home-agent-ana", home_session_id="HDS-2") is True
    assert store.resolve_runtime_grant("home-agent-ana") is None


def test_unconditional_delete_still_works(tmp_path):
    store = SessionStore(str(tmp_path / "s.db"))
    store.put_runtime_grant("home-agent-ana", "HDS-1", {"home-control-plane"}, ttl_seconds=60)
    assert store.delete_runtime_grant("home-agent-ana") is True
    assert store.delete_runtime_grant("home-agent-ana") is False


def test_two_processes_migrating_the_same_file_both_succeed(tmp_path):
    path = str(tmp_path / "old.db")
    _make_pre_plan_file(path)
    SessionStore(path)
    second = SessionStore(path)
    assert second.get_session("S1").person_ref == ""
