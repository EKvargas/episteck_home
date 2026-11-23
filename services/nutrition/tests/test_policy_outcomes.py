"""F3b.2: Nutrition answers 401 / 403 / 503 with fixed bodies and never reads on refusal."""
from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from app.home_control.client import SESSION_INVALID, UNAVAILABLE, AccessDecision
from app.profile.service import ProfileService
from app.store.profile_sqlite import SqliteProfileStore
from tests.support import AllowAllAuthorizer
from app.service import AccessDenied, PolicyUnavailable, SessionInvalid

SESSION = "delegation-token-outcomes"
HOME_REASON = "no matching active grant (fail closed)"
WIRE = {"birth_date": "1986-03-10", "sex": "MALE", "height_cm": "180", "weight_kg": "82",
        "activity_pal": "1.6"}

DECISIONS = {
    "PSN-A": AccessDecision(True, "grant NUTRITION/VIEW"),
    "PSN-EMPTY": AccessDecision(True, "self-access"),
    "PSN-B": AccessDecision(False, HOME_REASON),
    "PSN-SESSION": AccessDecision(False, "authorization indeterminate (fail closed)", SESSION_INVALID),
    "PSN-DOWN": AccessDecision(False, "authorization indeterminate (fail closed)", UNAVAILABLE),
}


class ScriptedAuthorizer:
    """A fixed decision per subject; records every Home call."""

    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def check_access(self, subject, domain, action, delegation=None):
        self.calls.append((subject, domain, action, delegation))
        return self.decisions[subject]

    def check_access_many(self, subject, requirements, delegation=None):
        self.calls.append((subject, tuple(requirements), delegation))
        return self.decisions[subject]


class SpyProfileStore(SqliteProfileStore):
    def __init__(self, path):
        super().__init__(path)
        self.reads = []

    def list_versions(self, person_id):
        self.reads.append(person_id)
        return super().list_versions(person_id)


def _service(tmp_path):
    store = SpyProfileStore(str(tmp_path / "outcomes.sqlite"))
    authorizer = ScriptedAuthorizer(DECISIONS)
    return ProfileService(store, authorizer=authorizer), store, authorizer


@pytest.mark.parametrize(
    "subject, error",
    [("PSN-B", AccessDenied), ("PSN-SESSION", SessionInvalid), ("PSN-DOWN", PolicyUnavailable)],
)
def test_service_refuses_each_non_allow_without_reading(tmp_path, subject, error):
    service, store, authorizer = _service(tmp_path)
    with pytest.raises(error):
        service.get_profile_view(SESSION, subject)
    assert store.reads == []
    assert len(authorizer.calls) == 1


def test_refusals_remain_permission_errors_for_the_mcp_boundary():
    assert issubclass(AccessDenied, PermissionError)
    assert issubclass(SessionInvalid, PermissionError)
    assert issubclass(PolicyUnavailable, PermissionError)


@pytest.fixture
def http(monkeypatch, tmp_path):
    monkeypatch.setenv("NUTRITION_DB", str(tmp_path / "nutrition.sqlite"))
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    store = SpyProfileStore(str(tmp_path / "nutrition.sqlite"))
    seeding = ProfileService(store, authorizer=AllowAllAuthorizer())
    draft = seeding.propose_profile("seed", "PSN-A", WIRE)["draft_id"]
    seeding.confirm_profile("seed", "PSN-A", draft)
    store.reads.clear()
    authorizer = ScriptedAuthorizer(DECISIONS)
    main.profile = ProfileService(store, authorizer=authorizer)
    return TestClient(main.app, raise_server_exceptions=False), store, authorizer


@pytest.mark.parametrize(
    "subject, status, body",
    [
        ("PSN-A", 200, None),
        ("PSN-EMPTY", 404, {"detail": "no profile"}),
        ("PSN-B", 403, {"detail": "ACCESS_DENIED"}),
        ("PSN-SESSION", 401, {"detail": "SESSION_INVALID"}),
        ("PSN-DOWN", 503, {"detail": "SERVICE_UNAVAILABLE"}),
    ],
)
def test_profile_route_contract(http, subject, status, body):
    client, repo, authorizer = http
    response = client.get(f"/profile/{subject}", headers={"X-Episteck-Delegation": SESSION})
    assert response.status_code == status
    if body is None:  # the view: flat Hub keys plus the structured set
        found = response.json()
        assert found["context"] == "GENERAL" and found["target_source"] == "REFERENCE_TARGET"
        assert found["targets"]["energy_kcal"] and "targets_flat" not in found
        assert found["target_set"]["method"] == "episteck-targets-1"
    else:
        assert response.json() == body
    assert HOME_REASON not in response.text
    assert "indeterminate" not in response.text
    assert repo.reads == ([subject] if status in (200, 404) else [])
    assert len(authorizer.calls) == 1


def test_cross_subject_denial_does_not_leak_or_read(http):
    client, repo, _ = http
    assert client.get("/profile/PSN-A", headers={"X-Episteck-Delegation": SESSION}).status_code == 200
    denied = client.get("/profile/PSN-B", headers={"X-Episteck-Delegation": SESSION})
    assert denied.status_code == 403
    assert denied.json() == {"detail": "ACCESS_DENIED"}
    assert repo.reads == ["PSN-A"]


def test_unusable_delegation_answers_401_not_500_with_the_real_client(http):
    import httpx

    from app import main
    from app.home_control.client import HomeControlPlaneClient

    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"message": {"allow": True, "reason": "x"}})

    real = HomeControlPlaneClient(
        "https://home.episteck.com", "k", "s", transport=httpx.MockTransport(handler)
    )
    client, repo, _ = http
    main.profile = ProfileService(repo, authorizer=real)
    main.app.dependency_overrides[main.human_session] = lambda: "tok\u00e9n\u2603"
    try:
        response = client.get("/profile/PSN-A")
    finally:
        main.app.dependency_overrides.pop(main.human_session, None)
    assert response.status_code == 401
    assert response.json() == {"detail": "SESSION_INVALID"}
    assert sent == []
    assert repo.reads == []
