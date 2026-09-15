"""Nutrition transport boundaries under the G1.6 trusted-actor contract.

The human session arrives via the ``X-Episteck-Delegation`` transport header and is
never a query parameter, body field, or MCP tool argument.
"""
from __future__ import annotations

import importlib
import inspect
import sys

import pytest
from fastapi.testclient import TestClient

SESSION = "delegation-token-test"
DELEGATION_HEADER = "X-Episteck-Delegation"


class FakeService:
    def __init__(self):
        self.calls = []
        self.deny = False

    def get_profile(self, delegation, subject_person_id):
        self.calls.append(("get_profile", delegation, subject_person_id))
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
    for name in ("app.mcp.server", "app.main", "app.deps", "app.session"):
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    mcp_server = importlib.import_module("app.mcp.server")
    session = importlib.import_module("app.session")
    service = FakeService()
    main.svc = service
    mcp_server._svc = service
    session.set_delegation(None)
    return main, mcp_server, service, session


# --------------------------------------------------------------------------
# FastAPI boundary
# --------------------------------------------------------------------------


def test_fastapi_takes_the_session_from_the_header_only(boundary_modules):
    main, _, service, _ = boundary_modules
    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/profile/PSN-SUBJECT", headers={DELEGATION_HEADER: SESSION}
    )
    assert response.status_code == 200
    assert response.json()["context"] == "SYNTHETIC"
    assert service.calls == [("get_profile", SESSION, "PSN-SUBJECT")]


def test_fastapi_ignores_a_query_supplied_actor(boundary_modules):
    """An attacker-supplied actor parameter must have no effect whatsoever."""
    main, _, service, _ = boundary_modules
    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/profile/PSN-SUBJECT",
        params={"actor_person_id": "PSN-VICTIM", "delegation": "forged"},
        headers={DELEGATION_HEADER: SESSION},
    )
    assert response.status_code == 200
    # Only the header session reached the service; the query values were ignored.
    assert service.calls == [("get_profile", SESSION, "PSN-SUBJECT")]


def test_fastapi_without_session_passes_none_and_service_denies(boundary_modules):
    main, _, service, _ = boundary_modules
    service.deny = True
    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/profile/PSN-SUBJECT"
    )
    assert response.status_code == 403
    assert service.calls == [("get_profile", None, "PSN-SUBJECT")]


def test_fastapi_exposes_no_actor_parameter_in_its_schema(boundary_modules):
    """Mechanical guard: the OpenAPI schema must never offer an actor."""
    main, _, _, _ = boundary_modules
    schema = main.app.openapi()
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []) or []:
                assert parameter["name"] != "actor_person_id", f"{method} {path}"


def test_fastapi_authorization_denial_is_403(boundary_modules):
    main, _, service, _ = boundary_modules
    service.deny = True
    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/profile/PSN-SUBJECT", headers={DELEGATION_HEADER: SESSION}
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Home denied"}


def test_legacy_consent_http_mutation_and_read_are_not_exposed(boundary_modules):
    main, _, _, _ = boundary_modules
    client = TestClient(main.app, raise_server_exceptions=False)
    assert client.post("/consent/PSN-SUBJECT").status_code == 404
    assert client.get("/consent/PSN-SUBJECT").status_code == 404


# --------------------------------------------------------------------------
# MCP boundary
# --------------------------------------------------------------------------


def test_mcp_takes_the_session_from_context_not_arguments(boundary_modules):
    _, mcp_server, service, session = boundary_modules
    session.set_delegation(SESSION)
    result = mcp_server.get_nutrition_profile.fn("PSN-SUBJECT")
    assert result["context"] == "SYNTHETIC"
    assert service.calls == [("get_profile", SESSION, "PSN-SUBJECT")]


def test_mcp_tools_expose_no_actor_parameter(boundary_modules):
    """The model cannot even be offered a way to name an actor."""
    _, mcp_server, _, _ = boundary_modules
    forbidden = {"actor_person_id", "actor", "delegation", "token", "session"}
    tool_functions = [
        value.fn
        for value in vars(mcp_server).values()
        if hasattr(value, "fn") and callable(getattr(value, "fn", None))
    ]
    assert tool_functions, "expected MCP tools to be discoverable"
    for function in tool_functions:
        parameters = set(inspect.signature(function).parameters)
        assert not (parameters & forbidden), f"{function.__name__}: {parameters}"


def test_mcp_denial_is_structured_and_does_not_escalate(boundary_modules):
    _, mcp_server, service, session = boundary_modules
    session.set_delegation(SESSION)
    service.deny = True
    result = mcp_server.get_nutrition_profile.fn("PSN-SUBJECT")
    assert result == {
        "allow": False,
        "error": "access_denied",
        "reason": "Home denied",
    }
    assert service.calls == [("get_profile", SESSION, "PSN-SUBJECT")]


def test_mcp_without_session_never_reaches_the_repository(boundary_modules):
    _, mcp_server, service, session = boundary_modules
    session.set_delegation(None)
    service.deny = True
    result = mcp_server.get_nutrition_profile.fn("PSN-SUBJECT")
    assert result["allow"] is False
    # The service was still called, but with no session, so it denies before any read.
    assert service.calls == [("get_profile", None, "PSN-SUBJECT")]
