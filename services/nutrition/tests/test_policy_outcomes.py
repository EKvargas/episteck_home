"""F3b.2: Nutrition answers 401 / 403 / 503 with fixed bodies and never reads on refusal."""
from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from app.home_control.client import SESSION_INVALID, UNAVAILABLE, AccessDecision
from app.providers.synthetic import SyntheticFoodProvider
from app.service import AccessDenied, NutritionService, PolicyUnavailable, SessionInvalid

SESSION = "delegation-token-outcomes"
HOME_REASON = "no matching active grant (fail closed)"
PROFILE = {"context": "GENERAL", "target_source": "USER_CONFIGURED", "targets": {"energy_kcal": 2000.0}}

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


class SpyRepository:
    def __init__(self, profiles):
        self.profiles = profiles
        self.reads = []

    def get_profile(self, person_id):
        self.reads.append(person_id)
        return self.profiles.get(person_id)


def _service():
    repo = SpyRepository({"PSN-A": PROFILE})
    authorizer = ScriptedAuthorizer(DECISIONS)
    return NutritionService(repo, SyntheticFoodProvider(), authorizer=authorizer), repo, authorizer


@pytest.mark.parametrize(
    "subject, error",
    [("PSN-B", AccessDenied), ("PSN-SESSION", SessionInvalid), ("PSN-DOWN", PolicyUnavailable)],
)
def test_service_refuses_each_non_allow_without_reading(subject, error):
    service, repo, authorizer = _service()
    with pytest.raises(error):
        service.get_profile(SESSION, subject)
    assert repo.reads == []
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
    service, repo, authorizer = _service()
    main.svc = service
    return TestClient(main.app, raise_server_exceptions=False), repo, authorizer


@pytest.mark.parametrize(
    "subject, status, body",
    [
        ("PSN-A", 200, PROFILE),
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
