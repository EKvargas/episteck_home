"""Receivables over a REAL FastMCP HTTP server and over REST: thin adapters, same answers.

Synthetic data only.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.mcp.server import create_mcp
from tests.support import FakeAuthorizer, count_rows, raw_execute, seeded_service
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


ARGS = {
    "finance_receivables": {}, "finance_exchanges": {}, "finance_pending": {},
    "finance_explain": {"ref": "C1"},
    "finance_record_exchange": {"total_usd": "10",
                                "lines": [{"payer": "Familiar A", "usd": "10"}]},
    "finance_record_receipt": {"payer": "Familiar A", "amount": "5", "currency": "USD",
                               "kind": "CASH"},
    "finance_resolve_pending": {"code": "P1", "choice": "yes"},
    "finance_mark_held_cash": {"counterparty": "Familiar A", "amount": "5", "currency": "USD"},
    "finance_correct_exchange": {"exchange_ref": "C1",
                                 "lines": [{"payer": "Familiar A", "usd": "10"}],
                                 "reason": "x"},
    "finance_reallocate": {"receipt_ref": "R1", "allocations": []},
    "finance_forgive": {"target": "Familiar A", "reason": "x"},
    "finance_setup_counterparty": {"label": "Familiar Z", "kind": "PERSON"},
    "finance_record_opening": {"counterparty": "Familiar A", "amount": "5", "currency": "USD",
                               "basis": "APPROXIMATE", "note": "n"},
    "finance_reverse": {"ref": "R1", "reason": "x"},
}
SCENARIOS = {
    "no_header": (lambda: FakeAuthorizer(), False, False),
    "session_invalid": (lambda: FakeAuthorizer(mode="session_invalid"), True, False),
    "unavailable": (lambda: FakeAuthorizer(mode="unavailable"), True, False),
    "denied": (lambda: FakeAuthorizer(allow={"SELF": False}), True, False),
    "non_member": (lambda: FakeAuthorizer(actor="PSN-9"), True, False),
    "feature_off": (lambda: FakeAuthorizer(), True, True),
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_refusal_codes_match_overview_tool_for_every_tool(tmp_path, scenario):
    mk, header, paused = SCENARIOS[scenario]
    env = Env(tmp_path, authorizer=mk())
    overview = _overview(tmp_path, mk())
    if paused:
        raw_execute(env.base, "UPDATE workspace SET status='PAUSED'")
        raw_execute(overview._repo, "UPDATE workspace SET status='PAUSED'")
    url = _serve(create_mcp(overview, env.svc))
    h = {HEADER: DELEG} if header else {}
    expected = _call(url, h, "finance_overview")
    assert expected["ok"] is False
    assert set(ARGS) == set(TOOLS)
    for tool, args in ARGS.items():
        assert _call(url, h, tool, args) == expected, tool
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
    assert dup.status_code == 200 and dup.json()["status"] == "possible_duplicate"
    assert dup.json()["options"] == ["other", "same"]


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
    }
    for kind, body in cases.items():
        r = client.post(f"/commands/{kind}", json=body, headers=h)
        assert r.status_code == 200, (kind, r.status_code, r.json())
        assert r.json()["status"] == "confirmation_required", (kind, r.json())
        done = client.post(f"/pending/{r.json()['code']}/resolve", json={"choice": "yes"},
                           headers=h)
        assert done.status_code == 200 and done.json()["ok"] is True, (kind, done.json())
    held = client.post("/commands/held_cash",
                       json={"counterparty": "Familiar A", "amount": "10", "currency": "USD"},
                       headers={**h, "Idempotency-Key": "h1"})
    assert held.status_code == 200 and held.json()["ok"] is True
    (tmp_path / "d").mkdir()
    denied_env = Env(tmp_path / "d", authorizer=FakeAuthorizer(allow={"SELF": False}))
    denied = _rest(tmp_path / "d", denied_env)
    assert denied.get("/pending", headers=h).status_code == 403
    assert denied.post("/commands/receipt", json={"payer": "Familiar A", "amount": "5", "currency": "USD", "kind": "CASH"}, headers=h).status_code == 403


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_rejected_tool_arguments_never_reach_the_log(tmp_path):
    env = Env(tmp_path)
    mcp = _mcp(env, tmp_path)
    cap = _Capture()
    logger = logging.getLogger("fastmcp.server.server")
    logger.addHandler(cap)
    old = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        url = _serve(mcp)
        h = {HEADER: DELEG}
        _call(url, h, "finance_record_exchange",
              {"total_usd": "120", "lines": [["Familiar A", "120"]]})
        _call(url, h, "finance_record_receipt", {"payer": "Familiar B", "amount": 77.5,
                                                 "currency": "USD", "kind": "CASH"})
    finally:
        logger.removeHandler(cap)
        logger.setLevel(old)
    text = "\n".join(cap.lines)
    assert "finance_record_exchange" in text and "finance_record_receipt" in text
    for secret in ("Familiar A", "Familiar B", "120", "77.5"):
        assert secret not in text


def test_receipt_docstring_never_offers_bank_and_schemas_name_nested_keys(tmp_path):
    env = Env(tmp_path)
    mcp = _mcp(env, tmp_path)
    desc = asyncio.run(mcp.get_tool("finance_record_receipt")).description
    assert "BANK" not in desc and "bank sync" in desc
    forgive = asyncio.run(mcp.get_tool("finance_forgive")).parameters
    assert "reason" in forgive["required"]
    blob = {name: str(asyncio.run(mcp.get_tool(name)).parameters)
            for name in ("finance_record_exchange", "finance_reallocate",
                         "finance_resolve_pending", "finance_correct_exchange")}
    for key in ("ves_reference", "ves_amount", "partner", "date"):
        assert key in blob["finance_record_exchange"]
    for key in ("payer", "usd", "debt_currency", "beneficiary", "eur"):
        assert key in blob["finance_record_exchange"]
        assert key in blob["finance_correct_exchange"]
    assert "exchange" in blob["finance_reallocate"] and "amount" in blob["finance_reallocate"]
    assert "remember" in blob["finance_resolve_pending"]


def test_unknown_nested_key_is_refused_over_mcp_and_rest(tmp_path):
    env = Env(tmp_path)
    url = _serve(_mcp(env, tmp_path))
    h = {HEADER: DELEG}
    bad_ev = {"reference": "REF-SYNTH-0001"}
    out = _call(url, h, "finance_record_exchange",
                {"total_usd": "300", "lines": E1, "evidence": bad_ev})
    assert (out["ok"], out["error"], out["field"]) == (False, "validation_error",
                                                       "evidence.reference")
    assert count_rows(env.base, "pending_item") == 0
    rest = _rest(tmp_path, env)
    r = rest.post("/commands/exchange", json={"total_usd": "300", "lines": E1,
                                              "evidence": bad_ev}, headers=h)
    assert r.status_code == 400 and r.json()["error"] == "validation_error"
    assert r.json()["field"] == "evidence.reference"
    r = rest.post("/commands/exchange", json={"total_usd": "10", "lines": [
        {"payer": "Familiar A", "usd": "10", "amunt": "1"}]}, headers=h)
    assert r.json()["field"] == "lines[0].amunt"
    code = env.svc.propose_receipt(DELEG, "Familiar A", "5", "USD", "CASH")["code"]
    r = rest.post(f"/pending/{code}/resolve",
                  json={"choice": "yes", "details": {"conterparty": "x"}}, headers=h)
    assert r.status_code == 400 and r.json()["field"] == "details.conterparty"
    assert count_rows(env.base, "exchange") == 0


def test_unknown_allocation_key_is_a_validation_error_in_the_service(tmp_path):
    env = Env(tmp_path)
    out = env.svc.propose_exchange(DELEG, "300", E1, {"reference": "x"})
    assert (out["error"], out["field"]) == ("validation_error", "evidence.reference")
    assert out["detail"] == {"reason": "unknown_key"}


def test_rest_shape_errors_carry_detail_and_pending_hides_for_delivery(tmp_path):
    env = Env(tmp_path)
    client = _rest(tmp_path, env)
    h = {HEADER: DELEG}
    r = client.post("/commands/receipt", json={"payer": "x"}, headers=h)
    assert r.status_code == 400 and "detail" in r.json()
    env.svc.propose_receipt(DELEG, "Familiar A", "5", "USD", "CASH")
    shown = client.get("/pending", headers=h).json()
    assert client.get("/pending?for_delivery=true", headers=h).json() == shown
    names = [p.name for route in client.app.routes if getattr(route, "path", "") == "/pending"
             for p in route.dependant.query_params]
    assert "for_delivery" not in names


def test_tool_typeddicts_come_from_typing_extensions():
    # The image runs Python 3.11, where pydantic refuses typing.TypedDict as a tool argument
    # type and the MCP server never starts. Tests on Python 3.12+ would not notice that.
    import re
    from pathlib import Path

    import app

    root = Path(app.__file__).parent
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if re.search(r"^from typing import [^\n]*\bTypedDict\b",
                              p.read_text(encoding="utf-8"), re.M)]
    assert offenders == []
