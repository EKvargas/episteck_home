from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient


class FakeService:
    def __init__(self):
        self.calls = []
        self.deny = False

    def get_profile(self, actor_person_id, subject_person_id):
        self.calls.append(("get_profile", actor_person_id, subject_person_id))
        if self.deny:
            raise PermissionError("Home denied")
        return {"person_id": subject_person_id, "context": "SYNTHETIC"}


@pytest.fixture
def boundary_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("NUTRITION_DB", str(tmp_path / "nutrition.sqlite"))
    monkeypatch.setenv("FOOD_PROVIDER", "synthetic")
    monkeypatch.setenv("HOME_CONTROL_PLANE_URL", "https://home.invalid")
    monkeypatch.setenv("HOME_API_KEY", "test-key")
    monkeypatch.setenv("HOME_API_SECRET", "test-secret")
    for name in ("app.mcp.server", "app.main", "app.deps"):
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    mcp_server = importlib.import_module("app.mcp.server")
    service = FakeService()
    main.svc = service
    mcp_server._svc = service
    return main, mcp_server, service


def test_fastapi_profile_passes_actor_and_subject(boundary_modules):
    main, _, service = boundary_modules
    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/profile/PSN-SUBJECT", params={"actor_person_id": "PSN-ACTOR"}
    )
    assert response.status_code == 200
    assert response.json()["context"] == "SYNTHETIC"
    assert service.calls == [("get_profile", "PSN-ACTOR", "PSN-SUBJECT")]


def test_fastapi_authorization_denial_is_403(boundary_modules):
    main, _, service = boundary_modules
    service.deny = True
    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/profile/PSN-SUBJECT", params={"actor_person_id": "PSN-ACTOR"}
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Home denied"}


def test_legacy_consent_http_mutation_and_read_are_not_exposed(boundary_modules):
    main, _, _ = boundary_modules
    client = TestClient(main.app, raise_server_exceptions=False)
    assert client.post("/consent/PSN-SUBJECT").status_code == 404
    assert client.get("/consent/PSN-SUBJECT").status_code == 404


def test_mcp_profile_passes_actor_and_subject(boundary_modules):
    _, mcp_server, service = boundary_modules
    result = mcp_server.get_nutrition_profile.fn("PSN-ACTOR", "PSN-SUBJECT")
    assert result["context"] == "SYNTHETIC"
    assert service.calls == [("get_profile", "PSN-ACTOR", "PSN-SUBJECT")]


def test_mcp_denial_is_structured_and_does_not_escalate(boundary_modules):
    _, mcp_server, service = boundary_modules
    service.deny = True
    result = mcp_server.get_nutrition_profile.fn("PSN-ACTOR", "PSN-SUBJECT")
    assert result == {
        "allow": False,
        "error": "access_denied",
        "reason": "Home denied",
    }
    assert service.calls == [("get_profile", "PSN-ACTOR", "PSN-SUBJECT")]
