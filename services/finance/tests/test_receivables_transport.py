"""Receivables over a REAL FastMCP HTTP server and over REST: thin adapters, same answers.

Synthetic data only.
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.mcp.server import create_mcp
from tests.support import FakeAuthorizer, count_rows, seeded_service
from tests.test_receivables_service import DELEG, E1, EVIDENCE, Env

HEADER = "X-Episteck-Delegation"
FORBIDDEN = {"actor", "workspace", "workspace_id", "account", "token", "sql", "delegation"}
TOOLS = {
    "finance_receivables": {"counterparty"},
    "finance_exchanges": {"status", "since"},
    "finance_pending": {"for_delivery"},
    "finance_explain": {"ref"},
    "finance_record_exchange": {"total_usd", "lines", "evidence", "delivered_on"},
    "finance_record_receipt": {"payer", "amount", "currency", "kind", "received_on",
                               "description"},
    "finance_resolve_pending": {"code", "choice", "details"},
    "finance_mark_held_cash": {"counterparty", "amount", "currency"},
    "finance_correct_exchange": {"exchange_ref", "lines", "reason"},
    "finance_reallocate": {"receipt_ref", "allocations"},
    "finance_forgive": {"target", "amount", "reason"},
    "finance_setup_counterparty": {"label", "kind", "aliases", "pay_currency", "settles_to"},
    "finance_record_opening": {"counterparty", "amount", "currency", "basis", "note"},
    "finance_reverse": {"ref", "reason"},
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(mcp):
    port = _free_port()
    threading.Thread(
        target=lambda: mcp.run(transport="http", host="127.0.0.1", port=port), daemon=True
    ).start()
    for _ in range(80):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover
        pytest.fail("FastMCP server did not start")
    return f"http://127.0.0.1:{port}/mcp"


def _call(url, headers, tool, args=None):
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    async def run():
        async with Client(StreamableHttpTransport(url, headers=headers)) as client:
            result = await client.call_tool(tool, args or {}, raise_on_error=False)
            return result.data

    return asyncio.run(run())


def _overview(tmp_path, authorizer=None):
    d = tmp_path / f"ov{len(list(tmp_path.glob('ov*')))}"
    d.mkdir()
    return seeded_service(d, authorizer)[0]


def _mcp(env, tmp_path, authorizer=None):
    return create_mcp(_overview(tmp_path, authorizer), env.svc)


def _rest(tmp_path, env):
    return TestClient(create_app(_overview(tmp_path), receivables=env.svc))


def _env_with_debts(tmp_path):
    env = Env(tmp_path)
    env.yes(env.svc.propose_exchange(DELEG, "300", E1, EVIDENCE))
    return env


def test_every_tool_is_registered_with_no_forbidden_parameter(tmp_path):
    env = Env(tmp_path)
    mcp = _mcp(env, tmp_path)
    for name, params in TOOLS.items():
        tool = asyncio.run(mcp.get_tool(name))
        props = set(tool.parameters.get("properties", {}))
        assert props == params, name
        assert FORBIDDEN.isdisjoint(props)
        assert tool.description and len(tool.description) < 600
    for name in ("finance_record_exchange", "finance_record_receipt",
                 "finance_resolve_pending"):
        assert "owner" in asyncio.run(mcp.get_tool(name)).description


def test_mcp_and_rest_return_identical_receivables(tmp_path):
    env = _env_with_debts(tmp_path)
    url = _serve(_mcp(env, tmp_path))
    rest = _rest(tmp_path, env)
    h = {HEADER: DELEG}
    for tool, path, args in (
            ("finance_receivables", "/receivables", {}),
            ("finance_receivables", "/receivables?counterparty=Familiar%20A",
             {"counterparty": "Familiar A"}),
            ("finance_exchanges", "/exchanges", {}),
            ("finance_pending", "/pending", {})):
        got = rest.get(path, headers=h)
        assert got.status_code == 200
        assert _call(url, h, tool, args) == got.json()


def test_mcp_two_phase_exchange_over_http_with_header_delegation(tmp_path):
    env = Env(tmp_path)
    url = _serve(_mcp(env, tmp_path))
    h = {HEADER: DELEG}
    out = _call(url, h, "finance_record_exchange",
                {"total_usd": "300", "lines": E1, "evidence": EVIDENCE})
    assert out["status"] == "confirmation_required" and out["code"] == "P1"
    assert count_rows(env.base, "exchange") == 0
    done = _call(url, h, "finance_resolve_pending", {"code": "P1", "choice": "yes"})
    assert done["ok"] is True and done["exchange_ref"] == "C1"
    assert count_rows(env.base, "exchange") == 1
    assert env.authz.calls[0][0] == DELEG


def test_rest_resolve_requires_delegation_header(tmp_path):
    env = Env(tmp_path)
    out = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH")
    client = _rest(tmp_path, env)
    before = len(env.authz.calls)
    r = client.post(f"/pending/{out['code']}/resolve", json={"choice": "yes"})
    assert r.status_code == 401 and r.json() == {"detail": "SESSION_INVALID"}
    assert len(env.authz.calls) == before
    ok = client.post(f"/pending/{out['code']}/resolve", json={"choice": "yes"},
                     headers={HEADER: DELEG})
    assert ok.status_code == 200 and ok.json()["receipt_ref"] == "R1"


@pytest.mark.parametrize("scenario", ["no_header", "denied", "unavailable"])
def test_refusal_codes_match_overview_tool(tmp_path, scenario):
    def mk():
        return {"no_header": FakeAuthorizer(),
                "denied": FakeAuthorizer(allow={"SELF": False}),
                "unavailable": FakeAuthorizer(mode="unavailable")}[scenario]

    env = Env(tmp_path, authorizer=mk())
    url = _serve(_mcp(env, tmp_path, mk()))
    h = {} if scenario == "no_header" else {HEADER: DELEG}
    expected = _call(url, h, "finance_overview")
    assert expected["ok"] is False
    for tool, args in (("finance_receivables", {}), ("finance_pending", {}),
                       ("finance_record_receipt", {"payer": "Familiar A", "amount": "5",
                                                   "currency": "USD", "kind": "CASH"}),
                       ("finance_resolve_pending", {"code": "P1", "choice": "yes"})):
        assert _call(url, h, tool, args) == expected
    assert count_rows(env.base, "pending_item") == 0


def test_unexpected_error_is_internal_error_without_details(tmp_path, monkeypatch):
    env = Env(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("Familiar A owes 99")
    monkeypatch.setattr(env.svc, "exchanges", boom)
    url = _serve(_mcp(env, tmp_path))
    assert _call(url, {HEADER: DELEG}, "finance_exchanges") == {
        "ok": False, "error": "internal_error"}
    r = _rest(tmp_path, env).get("/exchanges", headers={HEADER: DELEG})
    assert r.status_code == 500 and r.json() == {"ok": False, "error": "internal_error"}


def test_rest_commands_idempotency_key_and_status_mapping(tmp_path):
    env = Env(tmp_path)
    client = _rest(tmp_path, env)
    h = {HEADER: DELEG}
    body = {"payer": "Familiar A", "amount": "50", "currency": "USD", "kind": "CASH"}
    first = client.post("/commands/receipt", json=body, headers={**h, "Idempotency-Key": "k1"})
    assert first.status_code == 200 and first.json()["status"] == "confirmation_required"
    again = client.post("/commands/receipt", json=body, headers={**h, "Idempotency-Key": "k1"})
    assert again.json() == first.json()
    clash = client.post("/commands/receipt", json={**body, "amount": "60"},
                        headers={**h, "Idempotency-Key": "k1"})
    assert clash.status_code == 409 and clash.json()["error"] == "idempotency_conflict"
    bad = client.post("/commands/receipt", json={**body, "amount": "1e3"}, headers=h)
    assert bad.status_code == 400 and bad.json()["error"] == "validation_error"
    amb = client.post("/commands/receipt", json={**body, "payer": "Nadie"}, headers=h)
    assert amb.status_code == 400 and amb.json()["ok"] is False
    assert client.post("/commands/receipt", json={"payer": "Familiar A"},
                       headers=h).status_code == 400
    assert client.post("/commands/receipt", json={**body, "actor": "x"},
                       headers=h).status_code == 400
    assert client.post("/commands/nonsense", json={}, headers=h).status_code == 404
    assert client.post("/commands/receipt", content=b"[1]",
                       headers={**h, "Content-Type": "application/json"}).status_code == 400
    code = first.json()["code"]
    assert client.post(f"/pending/{code}/resolve", json={"choice": "yes"},
                       headers=h).status_code == 200
    stale = client.post(f"/pending/{code}/resolve", json={"choice": "cancel"}, headers=h)
    assert stale.status_code == 409 and stale.json()["error"] == "already_resolved"
    unknown = client.post("/pending/P99/resolve", json={"choice": "yes"}, headers=h)
    assert unknown.status_code == 400 and unknown.json()["error"] == "unknown_pending"
    dup = client.post("/commands/receipt", json=body, headers=h)
    assert dup.json()["status"] == "possible_duplicate"


def test_rest_remaining_command_types_and_refusal_statuses(tmp_path):
    env = _env_with_debts(tmp_path)
    client = _rest(tmp_path, env)
    h = {HEADER: DELEG}
    cases = {
        "exchange": {"total_usd": "10", "lines": [{"payer": "Familiar A", "usd": "10"}]},
        "correction": {"exchange_ref": "C1", "lines": E1, "reason": "x"},
        "forgive": {"target": "Familiar A", "reason": "x"},
        "opening": {"counterparty": "Familiar A", "amount": "10", "currency": "USD",
                    "basis": "APPROXIMATE", "note": "n"},
        "counterparty": {"label": "Familiar Z", "kind": "PERSON", "aliases": []},
        "reverse": {"ref": "C1", "reason": "x"},
        "reallocate": {"receipt_ref": "R1", "allocations": []},
    }
    for kind, body in cases.items():
        r = client.post(f"/commands/{kind}", json=body, headers=h)
        assert r.status_code in (200, 400), (kind, r.status_code, r.json())
        assert r.json().get("status") == "confirmation_required" or r.json()["ok"] is False
    held = client.post("/commands/held_cash",
                       json={"counterparty": "Familiar A", "amount": "10", "currency": "USD"},
                       headers={**h, "Idempotency-Key": "h1"})
    assert held.status_code == 200 and held.json()["ok"] is True
    (tmp_path / "d").mkdir()
    denied_env = Env(tmp_path / "d", authorizer=FakeAuthorizer(allow={"SELF": False}))
    denied = _rest(tmp_path / "d", denied_env)
    assert denied.get("/pending", headers=h).status_code == 403
    assert denied.post("/commands/receipt", json={"payer": "Familiar A", "amount": "5", "currency": "USD", "kind": "CASH"}, headers=h).status_code == 403
