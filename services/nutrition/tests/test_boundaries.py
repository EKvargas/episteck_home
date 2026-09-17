"""Nutrition transport boundaries under the G1.6 trusted-actor contract.

The human session arrives via the ``X-Episteck-Delegation`` transport header and is
never a query parameter, body field, or MCP tool argument.
"""
from __future__ import annotations

import importlib
import inspect
import sys
from contextlib import contextmanager

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
    return main, mcp_server, service, session


def _tool(mcp_server, name):
    """The underlying function for an MCP tool, across fastmcp versions.

    fastmcp 2.x wraps a decorated tool in a FunctionTool exposing ``.fn``; the pinned
    4.0.3 returns the plain function. Reaching only for ``.fn`` silently finds nothing
    on 4.0.3, which is how an assertion becomes vacuous instead of failing.
    """
    tool = getattr(mcp_server, name)
    return getattr(tool, "fn", tool)


@contextmanager
def _delegated_request(token: str | None):
    """Drive the MCP seam the way the transport does: through request headers.

    The fixture used to call ``session.set_delegation(...)``. That setter is gone —
    nothing in production ever called it, which is precisely why the binding was
    broken — so these tests now substitute the header map the seam reads. The
    end-to-end proof over a real HTTP server lives in ``test_transport_binding.py``.
    """
    import app.session as session_module

    headers = {} if token is None else {session_module.DELEGATION_HEADER.lower(): token}
    original = session_module.get_http_headers
    session_module.get_http_headers = lambda: headers
    try:
        yield
    finally:
        session_module.get_http_headers = original


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
    _, mcp_server, service, _ = boundary_modules
    with _delegated_request(SESSION):
        result = _tool(mcp_server, "get_nutrition_profile")("PSN-SUBJECT")
    assert result["context"] == "SYNTHETIC"
    assert service.calls == [("get_profile", SESSION, "PSN-SUBJECT")]


def test_mcp_tools_expose_no_actor_parameter(boundary_modules):
    """The model cannot even be offered a way to name an actor."""
    _, mcp_server, _, _ = boundary_modules
    forbidden = {"actor_person_id", "actor", "delegation", "token", "session"}
    tool_functions = [
        fn
        for name, value in vars(mcp_server).items()
        if not name.startswith("_")
        and (fn := getattr(value, "fn", value if inspect.isfunction(value) else None))
        is not None
        and callable(fn)
        and getattr(fn, "__module__", None) == mcp_server.__name__
    ]
    assert tool_functions, "expected MCP tools to be discoverable"
    # The tool set is ~13; a couple would mean the discovery above quietly broke and
    # the assertion stopped covering anything.
    assert len(tool_functions) >= 10, f"only found {len(tool_functions)} tools"
    for function in tool_functions:
        parameters = set(inspect.signature(function).parameters)
        assert not (parameters & forbidden), f"{function.__name__}: {parameters}"


def test_mcp_denial_is_structured_and_does_not_escalate(boundary_modules):
    _, mcp_server, service, _ = boundary_modules
    service.deny = True
    with _delegated_request(SESSION):
        result = _tool(mcp_server, "get_nutrition_profile")("PSN-SUBJECT")
    assert result == {
        "allow": False,
        "error": "access_denied",
        "reason": "Home denied",
    }
    assert service.calls == [("get_profile", SESSION, "PSN-SUBJECT")]


def test_mcp_without_session_never_reaches_the_repository(boundary_modules):
    _, mcp_server, service, _ = boundary_modules
    service.deny = True
    with _delegated_request(None):
        result = _tool(mcp_server, "get_nutrition_profile")("PSN-SUBJECT")
    assert result["allow"] is False
    # The service was still called, but with no session, so it denies before any read.
    assert service.calls == [("get_profile", None, "PSN-SUBJECT")]
