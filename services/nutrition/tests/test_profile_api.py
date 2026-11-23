"""Profile drafts and period summaries over REST and MCP."""
from __future__ import annotations

import asyncio

from tests.test_diary_api import COLA, H, PERSON, SESSION, _tool, api  # noqa: F401

P = PERSON
WIRE = {"birth_date": "1986-03-10", "sex": "MALE", "height_cm": "180", "weight_kg": "82",
        "activity_pal": "1.6", "training_sessions_per_week": 3, "goal": "PERFORMANCE"}


class _Session:
    """Supply the delegated session the way the transport seam would."""

    def __enter__(self):
        import app.session as session_module
        self.module = session_module
        self.original = session_module.get_http_headers
        session_module.get_http_headers = lambda: {
            session_module.DELEGATION_HEADER.lower(): SESSION}

    def __exit__(self, *exc):
        self.module.get_http_headers = self.original


def _onboard_through_mcp(api, wire=WIRE):
    _, server, _ = api
    with _Session():
        draft = _tool(server, "propose_profile")(P, wire)
        return _tool(server, "confirm_profile")(P, draft["draft_id"])


def test_get_profile_404_until_onboarded_then_view(api):
    _, _, client = api
    r = client.get(f"/profile/{P}", headers=H)
    assert (r.status_code, r.json()) == (404, {"detail": "no profile"})
    _onboard_through_mcp(api)
    body = client.get(f"/profile/{P}", headers=H).json()
    assert body["context"] == "GENERAL" and body["targets"]["energy_kcal"] == "3150.0"
    assert body["target_source"] == "REFERENCE_TARGET"
    assert body["target_set"]["method"] == "episteck-targets-1"
    assert "targets_flat" not in body
    assert all(isinstance(v, str) for v in body["targets"].values())
    assert body["onboarded"] is True


def test_get_profile_with_only_a_mode_version_is_not_onboarded(api):
    _, server, client = api
    assert client.put(f"/profile/{P}/mode", json={"mode": "GENERAL"}, headers=H).status_code == 200
    body = client.get(f"/profile/{P}", headers=H).json()
    assert body["origin"] == "MODE" and body["onboarded"] is False
    with _Session():
        assert _tool(server, "get_nutrition_profile")(P)["onboarded"] is False


def test_period_route(api):
    _, _, client = api
    r = client.get(f"/diary/{P}/period", headers=H)
    assert r.status_code == 200 and len(r.json()["days"]) == 7
    r = client.get(f"/diary/{P}/period", params={"start": "2026-01-01", "end": "2026-02-09"},
                   headers=H)
    assert (r.status_code, r.json()) == (400, {"detail": {"error": "INVALID_ITEM", "field": "start"}})


def test_profile_invalid_maps_to_invalid_field(api):
    _, server, _ = api
    with _Session():
        out = _tool(server, "propose_profile")(P, {**WIRE, "height_cm": "10"})
    assert out == {"error": "INVALID_FIELD", "field": "height_cm", "reason": "OUT_OF_RANGE"}
    # REST: the same mapper over the shared profile service
    main = api[0]
    import pytest
    from fastapi import HTTPException
    from nutrition_domain.profile import ProfileInvalid

    def boom():
        raise ProfileInvalid("height_cm", "out of range")

    with pytest.raises(HTTPException) as caught:
        main._diary_call(boom)
    assert (caught.value.status_code, caught.value.detail) == (
        400, {"error": "INVALID_FIELD", "field": "height_cm", "reason": "INVALID"})

    def under_19():
        raise ProfileInvalid("birth_date", reason="UNDER_19")

    with pytest.raises(HTTPException) as caught:
        main._diary_call(under_19)
    assert caught.value.detail == {"error": "INVALID_FIELD", "field": "birth_date", "reason": "UNDER_19"}


def test_mcp_propose_goal_in_pregnancy_says_why(api):
    _, server, _ = api
    with _Session():
        assert _tool(server, "set_nutrition_mode")(P, "PREGNANCY", "2027-05-15")["version"] == 1
        out = _tool(server, "propose_profile")(P, {"goal": "MAINTAIN"})
    assert out == {"error": "INVALID_FIELD", "field": "goal", "reason": "NOT_ALLOWED_IN_MODE"}


def test_mcp_propose_confirm_round_trip(api):
    _, server, _ = api
    with _Session():
        draft = _tool(server, "propose_profile")(P, WIRE)
        assert draft["draft_id"] and draft["targets_after"]["method"] == "episteck-targets-1"
        assert _tool(server, "get_nutrition_profile")(P) == {"error": "no profile"}
        done = _tool(server, "confirm_profile")(P, draft["draft_id"])
        assert done["created"] is True
        view = _tool(server, "get_nutrition_profile")(P)
        assert view["version"] == 1 and view["targets"]["method"] == "episteck-targets-1"
        assert "targets_flat" in view
        assert _tool(server, "get_pregnancy_profile")(P)["version"] == 1
        assert _tool(server, "confirm_profile")(P, "nope") == {"error": "NOT_FOUND"}
        period = _tool(server, "get_period_summary")(P)
        assert len(period["days"]) == 7 and period["has_profile"] is True
        assert _tool(server, "get_period_summary")(P, "2026-01-01", "2026-02-09") == {
            "error": "INVALID_ITEM", "field": "start"}


def test_new_tool_descriptions_guide_the_agent(api):
    _, server, _ = api
    tools = {t.name: (t.description or "") for t in asyncio.run(server.mcp.list_tools())}
    text = tools["propose_profile"]
    for needle in ("birth_date", "sex", "height_cm", "weight_kg", "weight_measured_on",
                   "activity_pal", "1.4", "1.8", "2.0", "training_sessions_per_week",
                   "training_note", "goal", "pre_pregnancy_weight_kg", "preferences",
                   "dislikes", "intolerances", "targets_after", "¿Lo guardo? (sí / corrige)",
                   "set_nutrition_mode", "decimal comma"):
        assert needle in text, needle
    assert "confirm_profile" in text
    assert "Never add up nutrients yourself" in tools["get_period_summary"]
    assert "has_profile" in tools["get_period_summary"] and "onboarded" in tools["get_period_summary"]
    for name in ("get_nutrition_profile", "get_pregnancy_profile"):
        assert '"onboarded": false' in tools[name] and "onboarding" in tools[name], name


def test_day_summary_description_covers_the_nutrient_block(api):
    _, server, _ = api
    tools = {t.name: (t.description or "") for t in asyncio.run(server.mcp.list_tools())}
    text = tools["get_day_summary"]
    for needle in ("profile_version", "nutrients", "known", "null", "never 0", "items_uncounted",
                   "status", "target", "without a profile", "percent"):
        assert needle in text, needle
    low = text.lower()
    assert "delegation" not in low and "token" not in low
    for name in ("propose_profile", "confirm_profile", "get_period_summary"):
        low = tools[name].lower()
        assert "delegation" not in low and "token" not in low, name
