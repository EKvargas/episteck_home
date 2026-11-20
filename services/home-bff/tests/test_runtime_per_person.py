"""/runtime per person (Task 6): each person sees, grants and revokes only their own agents.

The owner (PSN-00001) may grant home-agent-primary; Ana (PSN-00002) may grant
home-agent-ana. Ana must never see the owner's expiry or last use, and must never be
able to revoke the owner's grant, not even while Home is down.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from home_bff import csrf, runtime_page, sessions
from home_bff.app import create_app
from home_bff.frappe_client import AccessRefused, SessionOpenError
from home_bff.runtime import PRIMARY_GRANT_AUDIENCES, PRIMARY_RUNTIME_ID
from home_bff.sessions import person_ref
from home_bff.store import SessionStore, StoreUnavailableError
from tests.test_app import DELEGATION_SECRET, make_settings
from tests.test_runtime_routes import ORIGIN, GrantClient, login

ANA_RUNTIME = "home-agent-ana"
OWNER = "PSN-00001"
ANA = "PSN-00002"
REF_OWNER = person_ref(OWNER, DELEGATION_SECRET)
REF_ANA = person_ref(ANA, DELEGATION_SECRET)
DAY = 86400


class PersonClient(GrantClient):
    """Home as the owner or Ana sees it: who logs in, and which agents they may grant.

    ``grantable`` None simulates Home unreachable; an exception instance is raised.
    """

    def __init__(self):
        super().__init__()
        self.grantable: list[str] | None | Exception = [PRIMARY_RUNTIME_ID]
        self.grantable_calls = 0

    def list_grantable_runtimes(self, access_token):
        self.grantable_calls += 1
        if isinstance(self.grantable, Exception):
            raise self.grantable
        return self.grantable


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = PersonClient()
    settings = make_settings(
        runtime_ids=(PRIMARY_RUNTIME_ID, ANA_RUNTIME), runtime_legacy_binding=False
    )
    app = create_app(settings, store=store, client=client)
    with TestClient(app, base_url=ORIGIN) as http:
        yield http, store, client


def as_owner(http, client) -> str:
    client.whoami_payload = {"actor_person_id": OWNER}
    client.grantable = [PRIMARY_RUNTIME_ID]
    return login(http)


def as_ana(http, client) -> str:
    client.whoami_payload = {"actor_person_id": ANA}
    client.grantable = [ANA_RUNTIME]
    return login(http)


def send(http, path, cookie, **fields):
    data = {"csrf": csrf.token_for(cookie, DELEGATION_SECRET), **fields}
    return http.post(path, data=data, headers={"Origin": ORIGIN}, follow_redirects=False)


def owner_grant(store, home_session_id="HDS-OWNER", *, grantor=REF_OWNER):
    return store.put_runtime_grant(
        PRIMARY_RUNTIME_ID, home_session_id, PRIMARY_GRANT_AUDIENCES,
        ttl_seconds=30 * DAY, grantor_ref=grantor,
    )


def ana_grant(store, home_session_id="HDS-ANA"):
    return store.put_runtime_grant(
        ANA_RUNTIME, home_session_id, {"home-control-plane"},
        ttl_seconds=10 * DAY, grantor_ref=REF_ANA,
    )


def date_of(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%d/%m/%Y")


# ------------------------------------------------------------------ the page


def test_ana_sees_only_her_agent_and_nothing_of_the_owners_grant(ctx):
    http, store, client = ctx
    grant = owner_grant(store)
    store.touch_runtime_grant(PRIMARY_RUNTIME_ID)
    expiry = date_of(grant.expires_at)
    as_ana(http, client)
    # The spec's link names her agent; the query never selects what is shown.
    for url in ("/runtime", "/runtime?agent=home-agent-ana", "/runtime?agent=home-agent-primary"):
        page = http.get(url)
        assert page.status_code == 200
        assert "home-agent-ana" in page.text
        assert "home-agent-primary" not in page.text
        assert expiry not in page.text
        assert "puede actuar" not in page.text
        assert "Último uso" not in page.text
        assert REF_ANA not in page.text and REF_OWNER not in page.text


def test_ana_never_sees_the_owners_grant_even_if_home_lists_his_agent(ctx):
    http, store, client = ctx
    grant = owner_grant(store)
    as_ana(http, client)
    client.grantable = [PRIMARY_RUNTIME_ID, ANA_RUNTIME, "home-agent-other"]
    page = http.get("/runtime").text
    assert PRIMARY_RUNTIME_ID in page and ANA_RUNTIME in page
    assert "home-agent-other" not in page  # listed by Home but not run by this BFF
    assert date_of(grant.expires_at) not in page
    assert "puede actuar" not in page


def test_home_down_page_shows_only_her_stored_grants(ctx):
    http, store, client = ctx
    owners = owner_grant(store)
    ana_grant(store)
    as_ana(http, client)
    client.grantable = None
    page = http.get("/runtime")
    assert page.status_code == 200
    assert "Home no responde. Solo se muestran los permisos que ya diste." in page.text
    assert ANA_RUNTIME in page.text
    assert "puede actuar" in page.text  # her own grant
    assert PRIMARY_RUNTIME_ID not in page.text
    assert date_of(owners.expires_at) not in page.text


def test_access_refused_on_the_page_asks_for_a_fresh_login(ctx):
    http, _, client = ctx
    as_owner(http, client)
    client.grantable = AccessRefused("Control Plane refused the session (HTTP 401)")
    response = http.get("/runtime", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/runtime"


def test_page_without_any_grantable_agent_says_so(ctx):
    http, _, client = ctx
    as_owner(http, client)
    client.grantable = []
    page = http.get("/runtime")
    assert page.status_code == 200
    assert "Esta cuenta no tiene ningún asistente que autorizar." in page.text
    assert "/runtime/grant" not in page.text
    assert "/runtime/revoke" not in page.text
    assert 'action="/logout/all"' in page.text


def test_page_escapes_the_agent_id():
    hostile = '"><script>alert(1)</script>'
    html = runtime_page.render(
        csrf_token="tok", agents=[runtime_page.AgentView(hostile, None)], now=0
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ----------------------------------------------------------------- grant


def test_ana_grants_her_agent_with_the_control_plane_only(ctx):
    http, store, client = ctx
    cookie = as_ana(http, client)
    response = send(http, "/runtime/grant", cookie, agent=ANA_RUNTIME)
    assert response.status_code == 303
    assert response.headers["location"] == "/runtime"
    assert client.open_calls[-1][1] == "home-agent-ana"
    grant = store.resolve_runtime_grant(ANA_RUNTIME)
    assert grant.allowed_audiences == {"home-control-plane"}
    assert grant.grantor_ref == REF_ANA
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) is None


def test_unknown_agent_is_400_without_calling_home(ctx):
    http, store, client = ctx
    cookie = as_owner(http, client)
    for agent in ("home-agent-other", "", [ANA_RUNTIME, PRIMARY_RUNTIME_ID]):
        for path in ("/runtime/grant", "/runtime/revoke"):
            response = send(http, path, cookie, agent=agent)
            assert response.status_code == 400
            assert response.json() == {"detail": "unknown agent"}
    assert client.open_calls == [] and client.close_calls == []
    assert client.grantable_calls == 0


def test_session_without_person_ref_must_log_in_again_to_grant(ctx):
    http, store, client = ctx
    old = store.create_session(
        home_session_id="HDS-OLD", access_token="at-old", refresh_token=None, person_ref=""
    )
    http.cookies.set(sessions.COOKIE_NAME, old.session_id, domain="bff.invalid")
    response = send(http, "/runtime/grant", old.session_id)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/runtime"
    assert client.open_calls == []
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) is None


def test_grant_never_replaces_another_persons_live_grant(ctx):
    http, store, client = ctx
    before = owner_grant(store)
    cookie = as_ana(http, client)
    client.grantable = [PRIMARY_RUNTIME_ID]  # Home misconfigured: lets Ana grant his agent
    response = send(http, "/runtime/grant", cookie, agent=PRIMARY_RUNTIME_ID)
    assert response.status_code == 409
    assert "Este asistente ya tiene el permiso de otra persona." in response.text
    assert client.open_calls == []
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) == before
    assert date_of(before.expires_at) not in response.text


def test_grant_check_store_failure_is_503_without_calling_home(ctx, monkeypatch):
    http, store, client = ctx
    cookie = as_ana(http, client)
    real = store.resolve_runtime_grant
    failures = []

    def fail_once(runtime_id):
        if not failures:
            failures.append(runtime_id)
            raise StoreUnavailableError("runtime store unavailable")
        return real(runtime_id)

    monkeypatch.setattr(store, "resolve_runtime_grant", fail_once)
    response = send(http, "/runtime/grant", cookie, agent=ANA_RUNTIME)
    assert response.status_code == 503
    assert "No se pudo guardar el permiso. Intentalo de nuevo." in response.text
    assert failures == [ANA_RUNTIME]
    assert client.open_calls == []
    assert real(ANA_RUNTIME) is None


def test_owner_regrant_replaces_a_legacy_row(ctx):
    http, store, client = ctx
    owner_grant(store, "HDS-LEGACY", grantor="")
    cookie = as_owner(http, client)
    response = send(http, "/runtime/grant", cookie, agent=PRIMARY_RUNTIME_ID)
    assert response.status_code == 303
    assert response.headers["location"] == "/runtime"
    grant = store.resolve_runtime_grant(PRIMARY_RUNTIME_ID)
    assert grant.grantor_ref == REF_OWNER
    assert grant.home_session_id == "HDS-GRANT-SECRET"


def test_home_refusal_for_the_wrong_person_stores_nothing(ctx):
    http, store, client = ctx
    cookie = as_ana(http, client)
    client.open_error = SessionOpenError()
    response = send(http, "/runtime/grant", cookie, agent=PRIMARY_RUNTIME_ID)
    assert response.status_code == 403
    assert "Esta cuenta no puede conceder el permiso." in response.text
    assert client.open_calls[-1][1] == PRIMARY_RUNTIME_ID
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) is None
    # The error page still shows only her own agents.
    assert ANA_RUNTIME in response.text and PRIMARY_RUNTIME_ID not in response.text


# ---------------------------------------------------------------- revoke


def test_ana_cannot_touch_the_owners_grant(ctx):
    http, store, client = ctx
    before = owner_grant(store)
    cookie = as_ana(http, client)
    response = send(http, "/runtime/revoke", cookie, agent=PRIMARY_RUNTIME_ID)
    assert response.status_code == 303
    assert client.close_calls == []
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) == before


def test_home_down_ana_revoke_removes_only_her_row(ctx):
    http, store, client = ctx
    before = owner_grant(store)
    ana_grant(store)
    cookie = as_ana(http, client)
    client.close_result = None
    response = send(http, "/runtime/revoke", cookie, agent=ANA_RUNTIME)
    assert response.status_code == 303
    assert client.close_calls == [("at-1", "HDS-ANA")]
    assert store.resolve_runtime_grant(ANA_RUNTIME) is None
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) == before


def test_revoke_keeps_a_grant_replaced_while_home_was_asked(ctx):
    http, store, client = ctx
    ana_grant(store, "HDS-OLD")
    cookie = as_ana(http, client)

    def close_while_regranted(access_token, home_session_id):
        client.close_calls.append((access_token, home_session_id))
        ana_grant(store, "HDS-NEW")  # a fresh grant lands while Home is asked
        return True

    client.close_runtime_grant = close_while_regranted
    assert send(http, "/runtime/revoke", cookie, agent=ANA_RUNTIME).status_code == 303
    assert client.close_calls == [("at-1", "HDS-OLD")]
    assert store.resolve_runtime_grant(ANA_RUNTIME).home_session_id == "HDS-NEW"


def test_legacy_row_is_shown_and_revoked_by_nobody(ctx):
    http, store, client = ctx
    before = owner_grant(store, "HDS-LEGACY", grantor="")
    cookie = as_owner(http, client)
    page = http.get("/runtime").text
    assert "no tiene permiso" in page
    assert "puede actuar" not in page
    response = send(http, "/runtime/revoke", cookie, agent=PRIMARY_RUNTIME_ID)
    assert response.status_code == 303
    assert client.close_calls == []
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) == before
    everywhere = send(http, "/logout/all", cookie)
    assert everywhere.json() == {"status": "logged out", "runtime_grant": "none"}
    assert client.close_calls == []
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) == before


# --------------------------------------------------------- log out everywhere


def test_home_down_logout_all_by_ana_keeps_the_owners_grant(ctx):
    http, store, client = ctx
    before = owner_grant(store)
    ana_grant(store)
    cookie = as_ana(http, client)
    client.close_result = None
    response = send(http, "/logout/all", cookie)
    assert response.status_code == 200
    assert response.json() == {"status": "logged out", "runtime_grant": "revoked"}
    assert client.close_calls == [("at-1", "HDS-ANA")]  # Home asked about hers only
    assert store.resolve_runtime_grant(ANA_RUNTIME) is None
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) == before
    assert store.get_session(cookie) is None


# ------------------------------------------- sessions from before person references


def ref_less_session(http, store):
    """A browser session created before the deploy: it has no person reference."""
    old = store.create_session(
        home_session_id="HDS-OLD", access_token="at-old", refresh_token=None, person_ref=""
    )
    http.cookies.set(sessions.COOKIE_NAME, old.session_id, domain="bff.invalid")
    return old.session_id


def test_empty_ref_session_page_asks_for_login(ctx):
    http, store, client = ctx
    owner_grant(store)
    ref_less_session(http, store)
    response = http.get("/runtime", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/runtime"
    assert client.grantable_calls == 0


def test_empty_ref_session_revoke_asks_for_login(ctx):
    http, store, client = ctx
    before = owner_grant(store)
    cookie = ref_less_session(http, store)
    response = send(http, "/runtime/revoke", cookie, agent=PRIMARY_RUNTIME_ID)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/runtime"
    assert client.close_calls == []
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) == before


def test_empty_ref_session_logout_all_asks_for_login(ctx):
    http, store, client = ctx
    before = owner_grant(store)
    cookie = ref_less_session(http, store)
    response = send(http, "/logout/all", cookie)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/runtime"
    assert client.close_calls == [] and client.revoked == []
    assert store.resolve_runtime_grant(PRIMARY_RUNTIME_ID) == before
    assert store.get_session(cookie) is not None


def test_race_lost_after_home_opened_closes_the_home_grant(ctx):
    http, store, client = ctx
    cookie = as_ana(http, client)
    original_open = client.open_runtime_grant

    def open_then_other_person_wins(access_token, runtime_id, ttl_days):
        home_id = original_open(access_token, runtime_id, ttl_days)
        # Between the pre-check and the claim, the owner's live grant lands.
        store.put_runtime_grant(
            runtime_id, "HDS-OWNER", {"home-control-plane"},
            ttl_seconds=30 * DAY, grantor_ref=REF_OWNER,
        )
        return home_id

    client.open_runtime_grant = open_then_other_person_wins
    response = send(http, "/runtime/grant", cookie, agent=ANA_RUNTIME)
    assert response.status_code == 409
    assert "Este asistente ya tiene el permiso de otra persona." in response.text
    assert [call[1] for call in client.close_calls] == ["HDS-GRANT-SECRET"]
    row = store.resolve_runtime_grant(ANA_RUNTIME)
    assert row.home_session_id == "HDS-OWNER" and row.grantor_ref == REF_OWNER
