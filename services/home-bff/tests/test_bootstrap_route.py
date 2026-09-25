"""GET /bootstrap: cookie-only auth, one CP call, strict mapping (§6, §7)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from home_bff import sessions
from home_bff.app import create_app
from home_bff.frappe_client import UpstreamMalformed, UpstreamRefused, UpstreamUnavailable
from home_bff.store import SessionStore

from tests.test_app import FakeClient, make_settings  # noqa: E402


class BootstrapFakeClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.bootstrap_payload = {
            "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
            "circles": [{"circle_id": "CIR-00001", "display_name": "Family"}],
            "care": [
                {
                    "person_id": "PSN-00007",
                    "display_name": "Ana",
                    "relationship_type": "CAREGIVER",
                }
            ],
        }
        self.bootstrap_error: Exception | None = None
        self.bootstrap_calls: list[tuple[str, str]] = []

    def get_home_bootstrap(self, access_token, session_id):
        self.bootstrap_calls.append((access_token, session_id))
        if self.bootstrap_error:
            raise self.bootstrap_error
        return self.bootstrap_payload


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = BootstrapFakeClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http, store, client


def _log_in(http) -> str:
    """Drive a real login+callback so the store has a genuine session + tokens."""
    from urllib.parse import parse_qs, urlparse

    http.get("/login", follow_redirects=False)
    login_response = http.get("/login", follow_redirects=False)
    query = parse_qs(urlparse(login_response.headers["location"]).query)
    state = query["state"][0]
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 303, response.text
    return http.cookies.get(sessions.COOKIE_NAME)


# ------------------------------------------------------------------- BFF-7


def test_bff7_missing_cookie_is_session_required(ctx):
    http, _, _ = ctx
    response = http.get("/bootstrap")
    assert response.status_code == 401
    assert response.json() == {"error": "SESSION_REQUIRED"}


def test_bff7_unknown_session_is_session_invalid(ctx):
    http, _, _ = ctx
    http.cookies.set(sessions.COOKIE_NAME, "not-a-real-session", domain="bff.invalid")
    response = http.get("/bootstrap")
    assert response.status_code == 401
    assert response.json() == {"error": "SESSION_INVALID"}


def test_bff7_expired_session_is_session_invalid(ctx):
    import sqlite3
    import time

    http, store, _ = ctx
    _log_in(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)
    with sqlite3.connect(store._path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, raw),
        )
    response = http.get("/bootstrap")
    assert response.status_code == 401
    assert response.json() == {"error": "SESSION_INVALID"}


# ------------------------------------------------------------------- BFF-8 / BFF-9


def test_bff8_uses_the_sessions_own_token_and_home_session_id(ctx):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))

    response = http.get("/bootstrap")

    assert response.status_code == 200
    assert client.bootstrap_calls == [(session.access_token, session.home_session_id)]


def test_bff8_query_actor_hint_is_ignored(ctx):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    client.bootstrap_calls.clear()

    http.get("/bootstrap?person_id=PSN-99999")
    http.get("/bootstrap?actor=PSN-99999")

    assert client.bootstrap_calls == [
        (session.access_token, session.home_session_id),
        (session.access_token, session.home_session_id),
    ]


def test_bff8_actor_header_is_ignored(ctx):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    client.bootstrap_calls.clear()

    http.get("/bootstrap", headers={"X-Actor-ID": "PSN-99999"})

    assert client.bootstrap_calls == [(session.access_token, session.home_session_id)]


def test_bff8_body_is_ignored(ctx):
    """Even sending a body on a GET must not change which session is used."""
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    client.bootstrap_calls.clear()

    http.request("GET", "/bootstrap", content=b'{"person_id": "PSN-99999"}')

    assert client.bootstrap_calls == [(session.access_token, session.home_session_id)]


def test_bff9_route_declares_no_actor_parameters():
    """The FastAPI route signature itself must not accept an actor input."""
    import inspect

    from home_bff.app import create_app

    app = create_app(make_settings(), store=SessionStore(":memory:invalid-guard"), client=None) \
        if False else None  # placeholder guard, real introspection below

    from home_bff import app as app_module

    source = inspect.getsource(app_module)
    bootstrap_section = source[source.index('@app.get("/bootstrap")'):]
    bootstrap_section = bootstrap_section[: bootstrap_section.index("\n\n    @app.")]
    for forbidden in ("person_id", "actor", "subject_person_id", "actor_person_id"):
        assert forbidden not in bootstrap_section


# ------------------------------------------------------------------- BFF-10


@pytest.mark.parametrize("exc", [UpstreamRefused("nope")])
def test_bff10_cp_refusal_is_session_invalid_and_leaves_store_unchanged(ctx, exc):
    http, store, client = ctx
    _log_in(http)
    session_id = http.cookies.get(sessions.COOKIE_NAME)
    client.bootstrap_error = exc

    response = http.get("/bootstrap")

    assert response.status_code == 401
    assert response.json() == {"error": "SESSION_INVALID"}
    assert store.get_session(session_id) is not None
    from home_bff.runtime import RUNTIME_ID

    assert store.resolve_runtime(RUNTIME_ID) is not None


# ------------------------------------------------------------------- BFF-11


@pytest.mark.parametrize(
    "exc",
    [
        UpstreamUnavailable("connect error"),
        UpstreamUnavailable("timeout"),
        UpstreamUnavailable("HTTP 404"),
        UpstreamUnavailable("HTTP 417"),
        UpstreamUnavailable("HTTP 429"),
        UpstreamUnavailable("HTTP 500"),
    ],
)
def test_bff11_cp_unavailable_is_service_unavailable(ctx, exc):
    http, store, client = ctx
    _log_in(http)
    client.bootstrap_error = exc

    response = http.get("/bootstrap")

    assert response.status_code == 503
    assert response.json() == {"error": "SERVICE_UNAVAILABLE"}


# ------------------------------------------------------------------- BFF-16


def test_bff16_logout_then_bootstrap_is_401(ctx):
    http, _, _ = ctx
    _log_in(http)
    http.post("/logout")
    response = http.get("/bootstrap")
    assert response.status_code == 401


# ------------------------------------------------------------------- BFF-17


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_bff17_non_get_methods_are_405(ctx, method):
    http, _, _ = ctx
    _log_in(http)
    response = getattr(http, method)("/bootstrap")
    assert response.status_code == 405


# ------------------------------------------------------------------- BFF-18


def test_bff18_bootstrap_has_no_store_cache_control(ctx):
    http, _, _ = ctx
    _log_in(http)
    response = http.get("/bootstrap")
    assert response.headers["cache-control"] == "no-store"


# ------------------------------------------------------------------- BFF-12


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"viewer": {"person_id": "PSN-00001"}, "circles": [], "care": []},  # missing display_name
        {"viewer": {"person_id": "PSN-1", "display_name": "X"}, "circles": [], "care": []},  # bad id
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [],
            "care": [
                {
                    "person_id": "PSN-00007",
                    "display_name": "Ana",
                    "relationship_type": "FRIEND",
                }
            ],
        },  # unknown enum
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [{"circle_id": "PSN-00007", "display_name": "Not a circle"}],
            "care": [],
        },  # circle id in personId namespace
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [],
            "care": [
                {
                    "person_id": "PSN-00001",
                    "display_name": "X",
                    "relationship_type": "CAREGIVER",
                }
            ],
        },  # care subject == viewer
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [],
            "care": [
                {
                    "person_id": "PSN-00007",
                    "display_name": "Ana",
                    "relationship_type": "CAREGIVER",
                },
                {
                    "person_id": "PSN-00007",
                    "display_name": "Ana",
                    "relationship_type": "GUARDIAN",
                },
            ],
        },  # duplicate
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [
                {"circle_id": f"CIR-{i:05d}", "display_name": "C"} for i in range(51)
            ],
            "care": [],
        },  # over bound
    ],
    ids=[
        "missing-field",
        "bad-id-format",
        "unknown-enum",
        "circle-id-in-person-namespace",
        "care-subject-equals-viewer",
        "duplicate-care-subject",
        "over-bound-circles",
    ],
)
def test_bff12_every_malformed_shape_is_invalid_response_never_partial(ctx, bad_payload):
    http, _, client = ctx
    _log_in(http)
    client.bootstrap_payload = bad_payload

    response = http.get("/bootstrap")

    assert response.status_code == 502
    assert response.json() == {"error": "INVALID_RESPONSE"}


def test_bff12_non_dict_care_entry_is_invalid_response(ctx):
    http, _, client = ctx
    _log_in(http)
    client.bootstrap_payload = {
        "viewer": {"person_id": "PSN-00001", "display_name": "X"},
        "circles": [],
        "care": ["not-a-dict"],
    }
    response = http.get("/bootstrap")
    assert response.status_code == 502
    assert response.json() == {"error": "INVALID_RESPONSE"}


# ------------------------------------------------------------------- BFF-13


def test_bff13_extra_access_and_external_ref_fields_are_dropped(ctx):
    http, _, client = ctx
    _log_in(http)
    client.bootstrap_payload = {
        "viewer": {
            "person_id": "PSN-00001",
            "display_name": "Erick",
            "external_ref": "leak-me-not",
        },
        "circles": [],
        "care": [],
        "access": {"nutrition": ["VIEW"]},
        "grants": ["should-not-appear"],
    }
    response = http.get("/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert "access" not in body
    assert "grants" not in body
    assert "external_ref" not in body["viewer"]
    import json

    text = json.dumps(body)
    assert "leak-me-not" not in text
    assert "should-not-appear" not in text


# ------------------------------------------------------------------- BFF-14


def test_bff14_response_bytes_contain_no_secrets(ctx):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    response = http.get("/bootstrap")

    assert session.access_token not in response.text
    assert session.home_session_id not in response.text
    assert http.cookies.get(sessions.COOKIE_NAME) not in response.text
    assert "client_secret" not in response.text
    assert "super-secret" not in response.text


# ------------------------------------------------------------------- BFF-15


def test_bff15_logs_across_bootstrap_failure_paths_contain_no_secrets(ctx, caplog):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))

    with caplog.at_level("DEBUG"):
        client.bootstrap_error = UpstreamRefused("refused")
        http.get("/bootstrap")

        client.bootstrap_error = UpstreamUnavailable("down")
        http.get("/bootstrap")

        client.bootstrap_error = None
        client.bootstrap_payload = {"viewer": {}, "circles": [], "care": []}
        http.get("/bootstrap")

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert session.access_token not in log_text
    assert session.home_session_id not in log_text
    assert http.cookies.get(sessions.COOKIE_NAME) not in log_text
    assert "super-secret" not in log_text
    assert "PSN-" not in log_text
