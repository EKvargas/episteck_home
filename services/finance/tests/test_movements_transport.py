"""Movements tools over a REAL FastMCP HTTP server and over REST (synthetic data only)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.mcp.server import create_mcp
from app.service import FinanceService
from tests.support import FakeAuthorizer, raw_execute
from tests.test_movements_service import DELEG, NOW, Env
from tests.test_receivables_transport import HEADER, _call, _serve

PARAMS = {
    "finance_movements": {"text", "amount", "account", "direction", "since", "until", "limit"},
    "finance_summary": {"period"},
}
DOCS = {
    "finance_movements": (
        "Search bank movements of the visible accounts by text, amount, account, direction "
        "(in or out) and dates (YYYY-MM-DD, default the last 90 days). Each line says what it "
        "is for Finance. Accounts without descriptions are found by amount and date only. "
        "Every figure you state must come from this tool's result."),
    "finance_summary": (
        "Own income, own spending (family help included and broken down by person) and net "
        "per currency for a month (YYYY-MM, default this month) or a year (YYYY), with what "
        "was set aside and whether the data is complete. Every figure you state must come "
        "from this tool's result."),
}


def _env(tmp_path, authorizer=None):
    env = Env(tmp_path, authorizer)
    env.add("acc-a", -2500, env.ago(2), "Tienda")
    overview = FinanceService(env.base, env.authz, "ws-1", clock=lambda: NOW)
    return env, overview


def test_mcp_tools_have_exactly_these_parameters(tmp_path):
    env, overview = _env(tmp_path)
    mcp = create_mcp(overview, movements=env.svc)
    for name, params in PARAMS.items():
        tool = asyncio.run(mcp.get_tool(name))
        assert set(tool.parameters.get("properties", {})) == params
        assert " ".join(tool.description.split()) == DOCS[name]


def test_mcp_refusal_is_typed(tmp_path):
    env, overview = _env(tmp_path, FakeAuthorizer(mode="session_invalid"))
    url = _serve(create_mcp(overview, movements=env.svc))
    for tool in PARAMS:
        assert _call(url, {HEADER: DELEG}, tool) == {"ok": False, "error": "session_invalid"}
        assert _call(url, {}, tool) == {"ok": False, "error": "session_invalid"}


def test_mcp_unexpected_error_is_internal_error(tmp_path, monkeypatch, caplog):
    env, overview = _env(tmp_path)
    monkeypatch.setattr(env.svc, "_load", lambda *a: (_ for _ in ()).throw(RuntimeError("secret 12.34")))
    url = _serve(create_mcp(overview, movements=env.svc))
    assert _call(url, {HEADER: DELEG}, "finance_summary") == {"ok": False, "error": "internal_error"}
    assert "secret" not in caplog.text and "12.34" not in caplog.text


def _rest(tmp_path, authorizer=None, paused=False):
    env, overview = _env(tmp_path, authorizer)
    if paused:
        raw_execute(env.base, "UPDATE workspace SET status='PAUSED'")
    return env, TestClient(create_app(overview, movements=env.svc))


@pytest.mark.parametrize("path", ["/movements", "/summary"])
@pytest.mark.parametrize("name,authorizer,paused,status", [
    ("no_header", None, False, 401),
    ("session_invalid", FakeAuthorizer(mode="session_invalid"), False, 401),
    ("unavailable", FakeAuthorizer(mode="unavailable"), False, 503),
    ("denied", FakeAuthorizer(allow={"SELF": False}), False, 403),
    ("feature_off", None, True, 409),
])
def test_rest_maps_refusals(tmp_path, path, name, authorizer, paused, status):
    _env_, client = _rest(tmp_path, authorizer, paused)
    headers = {} if name == "no_header" else {HEADER: DELEG}
    assert client.get(path, headers=headers).status_code == status


def test_rest_maps_domain_errors_and_internal_errors(tmp_path, monkeypatch):
    env, client = _rest(tmp_path)
    h = {HEADER: DELEG}
    bad = client.get("/summary", params={"period": "2099-01"}, headers=h)
    assert bad.status_code == 400 and bad.json() == {"ok": False, "error": "bad_period"}
    limit = client.get("/movements", params={"limit": "many"}, headers=h)
    assert limit.status_code == 400 and limit.json()["error"] == "bad_limit"
    unknown = client.get("/movements", params={"account": "nowhere"}, headers=h)
    assert unknown.status_code == 400 and unknown.json()["error"] == "unknown_account"
    monkeypatch.setattr(env.svc, "_load", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    boom = client.get("/summary", headers=h)
    assert boom.status_code == 500 and boom.json() == {"ok": False, "error": "internal_error"}


def test_rest_summary_ok_and_same_answer_as_mcp(tmp_path):
    env, overview = _env(tmp_path)
    client = TestClient(create_app(overview, movements=env.svc))
    h = {HEADER: DELEG}
    summary = client.get("/summary", headers=h)
    assert summary.status_code == 200
    body = summary.json()
    assert body["ok"] is True and body["period"] == "2026-11"
    eur = next(c for c in body["currencies"] if c["currency"] == "EUR")
    assert eur["spending"]["bank"]["amount_minor"] == 2500
    found = client.get("/movements", params={"text": "tienda", "limit": "5"}, headers=h)
    assert found.status_code == 200 and found.json()["total_matches"] == 1
    url = _serve(create_mcp(overview, movements=env.svc))
    assert _call(url, h, "finance_summary") == body
    assert _call(url, h, "finance_movements", {"text": "tienda", "limit": 5}) == found.json()
