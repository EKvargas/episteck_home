"""Person reference at login (Task 5)."""
from __future__ import annotations

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from home_bff import sessions
from home_bff.app import create_app
from home_bff.frappe_client import ControlPlaneUnreachable, SessionOpenError
from home_bff.sessions import person_ref, refs_match
from home_bff.store import SessionStore
from tests.test_app import (
    DELEGATION_SECRET,
    FakeClient,
    complete_login,
    login_and_get_state,
    make_settings,
)


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = FakeClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http, store, client


def _callback(http):
    state = login_and_get_state(http)
    return http.get(f"/callback?code=auth-code&state={state}", follow_redirects=False)


def test_person_ref_is_stable_labelled_and_not_the_id():
    ref = person_ref("PSN-00001", "s")
    assert ref == person_ref("PSN-00001", "s") and ref != person_ref("PSN-00002", "s")
    assert ref != person_ref("PSN-00001", "other")
    assert "PSN-00001" not in ref and len(ref) == 64
    assert sessions.PERSON_REF_LABEL == b"episteck-person-ref\x00"


def test_person_ref_rejects_empty_id():
    with pytest.raises(ValueError):
        person_ref("", "s")


def test_refs_match_never_matches_empty():
    assert not refs_match("", "") and not refs_match("a", "") and not refs_match("", "a")
    assert refs_match("a", "a") and not refs_match("a", "b")


def test_login_stores_the_person_ref(ctx):
    http, store, _ = ctx
    complete_login(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    assert session.person_ref == person_ref("PSN-00001", DELEGATION_SECRET)


def test_login_stores_the_person_ref_with_legacy_flag_off(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = FakeClient()
    app = create_app(
        make_settings(runtime_legacy_binding=False), store=store, client=client
    )
    with TestClient(app, base_url="https://bff.invalid") as http:
        complete_login(http)
        session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    assert session.person_ref == person_ref("PSN-00001", DELEGATION_SECRET)


def test_login_with_whoami_unreachable_is_503_and_creates_no_session(ctx, tmp_path):
    http, store, client = ctx
    client.whoami_error = ControlPlaneUnreachable("down")
    response = _callback(http)
    assert response.status_code == 503
    assert response.json() == {"detail": "login could not be completed"}
    assert client.home_session_opens == 0
    assert http.cookies.get(sessions.COOKIE_NAME) is None
    with sqlite3.connect(str(tmp_path / "bff.sqlite")) as db:
        assert db.execute("select count(*) from bff_session").fetchone()[0] == 0


def test_login_with_whoami_refused_is_403(ctx):
    http, _, client = ctx
    client.whoami_error = SessionOpenError("no")
    response = _callback(http)
    assert response.status_code == 403
    assert response.json() == {"detail": "this account is not linked to a Home person"}
    assert client.home_session_opens == 0


@pytest.mark.parametrize("payload", [{"actor_person_id": None}, {"actor_person_id": ""}, {"actor_person_id": 7}, {}])
def test_login_without_person_id_is_403(ctx, payload):
    http, _, client = ctx
    client.whoami_payload = payload
    response = _callback(http)
    assert response.status_code == 403
    assert client.home_session_opens == 0
    assert http.cookies.get(sessions.COOKIE_NAME) is None


def test_ref_and_person_id_never_leave_the_server(ctx, caplog):
    http, _, _ = ctx
    ref = person_ref("PSN-00001", DELEGATION_SECRET)
    with caplog.at_level(logging.DEBUG):
        response = _callback(http)
    assert response.status_code == 303
    assert ref not in response.text and "PSN-00001" not in response.text
    for header in response.headers.raw:
        value = header[1].decode()
        assert ref not in value and "PSN-00001" not in value
    for cookie in http.cookies.jar:
        assert ref not in cookie.value and "PSN-00001" not in cookie.value
    for record in caplog.records:
        text = record.getMessage()
        assert ref not in text and "PSN-00001" not in text
