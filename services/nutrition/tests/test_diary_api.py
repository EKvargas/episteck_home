"""Diary over REST and MCP: round trip, error mapping, tool list."""
from __future__ import annotations

import importlib
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from app.diary.service import DiaryService
from app.providers.synthetic import SyntheticFoodProvider
from app.service import NutritionService
from app.store.diary_sqlite import SqliteDiaryStore
from app.store.sqlite_repo import SqliteNutritionRepository
from tests.support import AllowAllAuthorizer, DenyAllAuthorizer

SESSION = "delegation-token-test"
H = {"X-Episteck-Delegation": SESSION}
PERSON = "PSN-ANA"
NEW_TOOLS = {
    "propose_intake", "confirm_intake", "correct_intake", "void_intake",
    "get_diary_entry", "get_day_summary", "close_day", "set_nutrition_mode",
}
COLA = {"label": "Cola", "food_id": "syn-cola", "amount": 1, "unit": "small_glass"}


class BrokenProvider(SyntheticFoodProvider):
    def get_food(self, food_id):
        raise httpx.ConnectError("down")


@pytest.fixture
def api(monkeypatch, tmp_path):
    db = str(tmp_path / "nutrition.sqlite")
    monkeypatch.setenv("NUTRITION_DB", db)
    monkeypatch.setenv("FOOD_PROVIDER", "synthetic")
    monkeypatch.setenv("HOME_CONTROL_PLANE_URL", "https://home.invalid")
    monkeypatch.setenv("HOME_API_KEY", "test-key")
    monkeypatch.setenv("HOME_API_SECRET", "test-secret")
    for name in ("app.mcp.server", "app.main", "app.deps", "app.session"):
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    server = importlib.import_module("app.mcp.server")

    def build(provider=None, authorizer=None):
        return DiaryService(
            SqliteDiaryStore(db), provider or SyntheticFoodProvider(),
            SqliteNutritionRepository(db), authorizer=authorizer or AllowAllAuthorizer(),
        )

    main.diary = build()
    server._diary = main.diary
    main.svc = NutritionService(SqliteNutritionRepository(db), SyntheticFoodProvider(),
                                authorizer=AllowAllAuthorizer())
    main.build_test_diary = build
    return main, server, TestClient(main.app, raise_server_exceptions=False)


def _today(main):
    return main.diary._today().isoformat()


def test_round_trip_propose_confirm_day(api):
    main, _, client = api
    r = client.post(f"/diary/{PERSON}/drafts", json={"items": [COLA]}, headers=H)
    assert r.status_code == 200
    draft = r.json()
    day = _today(main)
    # a draft never counts
    r = client.get(f"/diary/{PERSON}/days/{day}", headers=H)
    assert r.json()["free_sugars_known_g"] != "15.9"
    r = client.post(f"/diary/{PERSON}/drafts/{draft['draft_id']}/confirm", headers=H)
    assert r.status_code == 200
    entry_id = r.json()["entry"]["id"]
    r = client.get(f"/diary/{PERSON}/days/{day}", headers=H)
    assert r.status_code == 200
    assert r.json()["free_sugars_known_g"] == "15.9"
    assert client.get(f"/diary/{PERSON}/entries/{entry_id}", headers=H).status_code == 200


def test_correct_void_close_and_mode(api):
    main, _, client = api
    d = client.post(f"/diary/{PERSON}/drafts", json={"items": [COLA]}, headers=H).json()
    e = client.post(f"/diary/{PERSON}/drafts/{d['draft_id']}/confirm", headers=H).json()["entry"]["id"]
    r = client.post(f"/diary/{PERSON}/entries/{e}/revisions", json={"items": [COLA]}, headers=H)
    assert r.status_code == 200
    r = client.post(f"/diary/{PERSON}/entries/{e}/void", headers=H)
    assert r.status_code == 200
    r = client.post(f"/diary/{PERSON}/days/{_today(main)}/close", headers=H)
    assert r.status_code == 200
    r = client.put(f"/profile/{PERSON}/mode", json={"mode": "PREGNANCY", "due_date": "2027-03-01"}, headers=H)
    assert r.status_code == 200
    assert r.json()["mode"] == "PREGNANCY"


def test_unknown_draft_and_entry_are_404(api):
    _, _, client = api
    r = client.post(f"/diary/{PERSON}/drafts/nope/confirm", headers=H)
    assert (r.status_code, r.json()) == (404, {"detail": "NOT_FOUND"})
    assert client.get(f"/diary/{PERSON}/entries/nope", headers=H).status_code == 404
    assert client.post(f"/diary/{PERSON}/entries/nope/void", headers=H).status_code == 404


def test_expired_draft_is_409(api):
    main, _, client = api
    d = client.post(f"/diary/{PERSON}/drafts", json={"items": [COLA]}, headers=H).json()
    from datetime import datetime, timedelta, timezone
    main.diary._clock = lambda: datetime.now(timezone.utc) + timedelta(hours=25)
    r = client.post(f"/diary/{PERSON}/drafts/{d['draft_id']}/confirm", headers=H)
    assert (r.status_code, r.json()) == (409, {"detail": "DRAFT_EXPIRED"})


def test_invalid_item_is_400(api):
    _, _, client = api
    bad = {"label": "Cola", "food_id": "syn-cola", "amount": 1, "unit": "bucket"}
    r = client.post(f"/diary/{PERSON}/drafts", json={"items": [bad]}, headers=H)
    assert (r.status_code, r.json()) == (400, {"detail": "INVALID_ITEM"})
    assert client.get(f"/diary/{PERSON}/days/not-a-date", headers=H).status_code == 400


def test_body_failing_schema_stays_422(api):
    _, _, client = api
    r = client.post(f"/diary/{PERSON}/drafts", json={"nope": 1}, headers=H)
    assert r.status_code == 422


def test_provider_down_is_503(api):
    main, _, client = api
    main.diary = main.build_test_diary(provider=BrokenProvider())
    r = client.post(f"/diary/{PERSON}/drafts", json={"items": [COLA]}, headers=H)
    assert (r.status_code, r.json()) == (503, {"detail": "PROVIDER_UNAVAILABLE"})


def test_missing_session_is_401_and_denial_403(api):
    main, _, client = api
    r = client.get(f"/diary/{PERSON}/days/2026-11-19")
    assert (r.status_code, r.json()) == (401, {"detail": "SESSION_INVALID"})
    main.diary = main.build_test_diary(authorizer=DenyAllAuthorizer())
    r = client.get(f"/diary/{PERSON}/days/2026-11-19", headers=H)
    assert (r.status_code, r.json()) == (403, {"detail": "ACCESS_DENIED"})


def _tool(server, name):
    tool = getattr(server, name)
    return getattr(tool, "fn", tool)


def test_mcp_exposes_the_eight_diary_tools(api):
    _, server, _ = api
    for name in NEW_TOOLS:
        assert callable(_tool(server, name))
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    assert NEW_TOOLS <= {t.name for t in tools}


def test_mcp_unknown_draft_returns_error_code(api):
    _, server, _ = api
    import app.session as session_module
    original = session_module.get_http_headers
    session_module.get_http_headers = lambda: {session_module.DELEGATION_HEADER.lower(): SESSION}
    try:
        assert _tool(server, "confirm_intake")(PERSON, "nope") == {"error": "NOT_FOUND"}
        out = _tool(server, "propose_intake")(PERSON, [COLA])
        assert out["items"]
    finally:
        session_module.get_http_headers = original


def test_put_profile_without_context_keeps_mode_set_by_set_mode(api):
    """R25: a PUT that sends only targets must not silently undo set_mode."""
    _, _, client = api
    r = client.put(f"/profile/{PERSON}/mode", json={"mode": "PREGNANCY", "due_date": "2027-03-01"}, headers=H)
    assert r.status_code == 200
    r = client.put(f"/profile/{PERSON}", json={"targets": {"protein_g": 70}}, headers=H)
    assert r.status_code == 200
    stored = client.get(f"/profile/{PERSON}", headers=H).json()
    assert stored["context"] == "PREGNANCY" and stored["due_date"] == "2027-03-01"
    assert stored["targets"] == {"protein_g": 70}
    # an explicit GENERAL is a deliberate switch and clears the due date
    client.put(f"/profile/{PERSON}", json={"context": "GENERAL"}, headers=H)
    stored = client.get(f"/profile/{PERSON}", headers=H).json()
    assert stored["context"] == "GENERAL" and stored["due_date"] is None


def test_put_profile_for_a_new_person_defaults_to_general(api):
    _, _, client = api
    client.put("/profile/PSN-NEW", json={"targets": {}}, headers=H)
    assert client.get("/profile/PSN-NEW", headers=H).json()["context"] == "GENERAL"
