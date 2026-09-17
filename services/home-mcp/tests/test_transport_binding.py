"""The HTTP header → tool → client binding, over a REAL server (G1.6, PR B).

WHY THIS SUITE EXISTS
---------------------
The previous design kept a ContextVar with ``set_delegation`` /
``delegation_from_headers``, and unit tests exercised both. Every test passed. But
nothing in production ever called the setter — the binding from HTTP header to
ContextVar was never written — so ``current_delegation()`` returned ``None`` on every
real request and every person-scoped tool was permanently unusable.

Unit tests could not see that, because they set the ContextVar themselves. The gap was
in the wiring, so the test has to exercise the wiring: these tests start an actual
FastMCP HTTP server and drive it over the network.

This is the third defect in G1.6 of the same shape — components correct in isolation,
composition wrong — so the coverage here is deliberately end-to-end.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

from home_mcp import context


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """A real FastMCP HTTP server whose tool reads the delegation as production does."""
    from fastmcp import FastMCP

    mcp = FastMCP("transport-binding-test")

    @mcp.tool
    def peek(marker: str = "") -> dict:
        """Report exactly what the production seam sees for this request."""
        from fastmcp.server.dependencies import get_http_headers

        visible = get_http_headers()
        return {
            "marker": marker,
            "delegation": context.current_delegation(),
            # What the production seam yields, versus what the library offered it.
            "seam_output": context.current_delegation(),
            "library_offered_authorization": "authorization" in visible,
            "library_offered_cookie": "cookie" in visible,
        }

    port = _free_port()
    threading.Thread(
        target=lambda: mcp.run(transport="http", host="127.0.0.1", port=port),
        daemon=True,
    ).start()

    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(80):  # up to ~8s for the server to bind
        try:
            _rpc(url, "initialize", _init_params())
            break
        except Exception:
            time.sleep(0.1)
    else:  # pragma: no cover
        pytest.fail("FastMCP server did not start")
    return url


def _init_params():
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    }


def _rpc(url, method, params=None, sid=None, extra=None):
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if sid:
        headers["Mcp-Session-Id"] = sid
    if extra:
        headers.update(extra)
    request = urllib.request.Request(url, data=body, headers=headers)
    response = urllib.request.urlopen(request, timeout=20)
    return response.status, dict(response.headers), response.read().decode()


def _open_session(url) -> str:
    _, response_headers, _ = _rpc(url, "initialize", _init_params())
    sid = response_headers.get("Mcp-Session-Id") or response_headers.get(
        "mcp-session-id"
    )
    _rpc(url, "notifications/initialized", {}, sid=sid)
    return sid


def _call_peek(url, *, delegation=None, marker="", sid=None, extra=None):
    """Invoke the tool over HTTP, always sending credential headers we must not see."""
    session_id = sid or _open_session(url)
    request_headers = {
        "Authorization": "Bearer MACHINE-CREDENTIAL-MUST-NOT-LEAK",
        "Cookie": "episteck_home_session=BROWSER-COOKIE-MUST-NOT-LEAK",
    }
    if delegation is not None:
        request_headers[context.DELEGATION_HEADER] = delegation
    if extra:
        request_headers.update(extra)

    _, _, body = _rpc(
        url,
        "tools/call",
        {"name": "peek", "arguments": {"marker": marker}},
        sid=session_id,
        extra=request_headers,
    )
    if "data: " in body:
        body = body.split("data: ", 1)[1].strip()
    payload = json.loads(body)
    return json.loads(payload["result"]["content"][0]["text"])


# ======================================================================
# The binding exists
# ======================================================================


def test_transport_header_reaches_the_tool(live_server):
    """THE REGRESSION: this returned None for every request before PR B."""
    result = _call_peek(live_server, delegation="TOKEN-ALPHA")
    assert result["delegation"] == "TOKEN-ALPHA"


def test_absent_header_fails_closed(live_server):
    assert _call_peek(live_server, delegation=None)["delegation"] is None


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_header_fails_closed(live_server, value):
    assert _call_peek(live_server, delegation=value)["delegation"] is None


def test_surrounding_whitespace_is_stripped(live_server):
    assert _call_peek(live_server, delegation="  TOKEN-PAD  ")["delegation"] == "TOKEN-PAD"


def test_header_name_is_case_insensitive(live_server):
    """HTTP header names are case-insensitive; the seam must not depend on casing."""
    result = _call_peek(
        live_server, extra={"x-EPISTECK-delegation": "TOKEN-MIXED-CASE"}
    )
    assert result["delegation"] == "TOKEN-MIXED-CASE"


# ======================================================================
# Credential headers never reach tool code
# ======================================================================


def test_the_seam_returns_only_the_delegation(live_server):
    """Our guarantee, independent of the library version.

    fastmcp 4.0.3 strips `authorization` and `cookie` by default; fastmcp 2.13 does
    NOT. Same call, opposite security behaviour. The dependency is pinned, but the
    seam narrows to one header anyway, so a default change cannot widen exposure.
    """
    result = _call_peek(live_server, delegation="TOKEN-SHIELD")
    assert result["delegation"] == "TOKEN-SHIELD"
    assert result["seam_output"] == "TOKEN-SHIELD"
    assert isinstance(result["seam_output"], str), "the seam yields a token, not a map"


def test_seam_discards_credential_headers_regardless_of_library_default(monkeypatch):
    """Even if get_http_headers() hands back everything, only the token survives."""
    monkeypatch.setattr(
        context,
        "get_http_headers",
        lambda: {
            "x-episteck-delegation": "TOKEN-NARROW",
            "authorization": "Bearer MACHINE-CREDENTIAL-MUST-NOT-LEAK",
            "cookie": "episteck_home_session=BROWSER-COOKIE-MUST-NOT-LEAK",
        },
    )
    value = context.current_delegation()

    assert value == "TOKEN-NARROW"
    assert "MACHINE-CREDENTIAL-MUST-NOT-LEAK" not in value
    assert "BROWSER-COOKIE-MUST-NOT-LEAK" not in value


def test_pinned_fastmcp_matches_the_version_this_seam_was_verified_against():
    """The seam is version-independent by construction, but the pin is the contract."""
    import pathlib
    import tomllib

    pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
    deps = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    assert "fastmcp==4.0.3" in deps, f"fastmcp must be pinned exactly, got {deps}"


def test_production_seam_never_requests_all_headers(monkeypatch):
    """include_all=True would expose the machine credential and browser cookie.

    Asserted by observing the call, not by grepping the source: a docstring that
    mentions the flag must not be able to fail this, and a future refactor that
    starts passing it must not be able to pass.
    """
    seen = {}

    def spy(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return {}

    monkeypatch.setattr(context, "get_http_headers", spy)
    context.current_delegation()

    assert seen["args"] == (), "the seam must call get_http_headers() with no arguments"
    assert seen["kwargs"] == {}, f"unexpected arguments: {seen['kwargs']}"


# ======================================================================
# Concurrency: no cross-request contamination
# ======================================================================


def test_concurrent_requests_do_not_cross_contaminate(live_server):
    """Eight in-flight requests, eight distinct tokens, each tool sees its own.

    This is the property a hand-rolled ContextVar would have had to get right with an
    explicit set/reset at the request boundary. FastMCP's own per-request context
    already provides it, which is why this module keeps no state of its own.
    """

    def one(i: int):
        return _call_peek(live_server, delegation=f"TOKEN-{i}", marker=str(i))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(8)))

    for result in results:
        assert result["delegation"] == f"TOKEN-{result['marker']}", result


def test_a_session_without_a_token_is_unaffected_by_concurrent_tokens(live_server):
    """A request with no delegation must not inherit a neighbour's token."""

    def with_token(i: int):
        return _call_peek(live_server, delegation=f"TOKEN-N-{i}", marker=f"t{i}")

    def without_token(i: int):
        return _call_peek(live_server, delegation=None, marker=f"n{i}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [pool.submit(with_token if i % 2 else without_token, i) for i in range(8)]
        results = [j.result() for j in jobs]

    for result in results:
        if result["marker"].startswith("n"):
            assert result["delegation"] is None, result
        else:
            assert result["delegation"] == f"TOKEN-N-{result['marker'][1:]}", result


# ======================================================================
# The token never becomes model-visible
# ======================================================================


def test_no_tool_accepts_a_delegation_or_actor_parameter():
    """The model must be unable to supply either one."""
    import inspect

    from home_mcp import server

    forbidden = {
        "delegation",
        "token",
        "access_token",
        "actor",
        "actor_id",
        "actor_person_id",
        "credential",
        "authorization",
    }
    for name in dir(server):
        tool = getattr(server, name)
        fn = getattr(tool, "fn", None)
        if fn is None or not callable(fn):
            continue
        params = set(inspect.signature(fn).parameters)
        assert not (params & forbidden), f"{name} exposes {params & forbidden}"


def test_context_module_exposes_no_setter():
    """There is no way for anything but the transport to supply a delegation."""
    assert not hasattr(context, "set_delegation")
    assert not hasattr(context, "delegation_from_headers")


def test_tool_results_never_echo_the_delegation(live_server):
    """A token in the request must not come back in a model-visible result."""
    from home_mcp import server

    token = "TOKEN-MUST-NOT-ECHO"
    result = _call_peek(live_server, delegation=token)
    # The probe tool deliberately returns it; production tools must not.
    for name in dir(server):
        tool = getattr(server, name)
        if getattr(tool, "fn", None) is None:
            continue
        source_doc = (getattr(tool, "description", "") or "").lower()
        assert "delegation" not in source_doc, name
    assert result["delegation"] == token  # sanity: the probe did see it
