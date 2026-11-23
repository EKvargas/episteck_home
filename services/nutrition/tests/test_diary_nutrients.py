from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.diary.service import DiaryService, InvalidField
from app.profile.service import ProfileService
from app.providers.synthetic import SyntheticFoodProvider
from app.store.diary_sqlite import SqliteDiaryStore
from app.store.profile_sqlite import SqliteProfileStore
from tests.support import AllowAllAuthorizer

SESSION = "delegation-token"
P = "PSN-NUTR"
CHICKEN = {"label": "Pollo", "food_id": "syn-chicken-breast", "amount": 200, "unit": "g", "stated": True}
COLA = {"label": "Cola", "food_id": "syn-cola", "amount": 1, "unit": "small_glass"}
ERICK_WIRE = {"birth_date": "1986-03-10", "sex": "MALE", "height_cm": "180", "weight_kg": "82",
              "activity_pal": "1.6", "training_sessions_per_week": 3, "goal": "PERFORMANCE"}
ANA_REST = {"birth_date": "1992-06-01", "height_cm": "165", "pre_pregnancy_weight_kg": "58",
            "activity_pal": "1.4", "training_sessions_per_week": 0}


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "n.sqlite")
    clock = Clock(datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc))
    auth = AllowAllAuthorizer()
    profiles = ProfileService(SqliteProfileStore(db), authorizer=auth, clock=clock)
    svc = DiaryService(SqliteDiaryStore(db), SyntheticFoodProvider(), profiles,
                       authorizer=auth, clock=clock)
    return svc, profiles, auth, clock


def _log(svc, items, consumed_at):
    d = svc.propose_intake(SESSION, P, items, consumed_at)
    return svc.confirm_intake(SESSION, P, d["draft_id"])


def _onboard(profiles, wire):
    d = profiles.propose_profile(SESSION, P, wire)
    return profiles.confirm_profile(SESSION, P, d["draft_id"])


def test_day_nutrients_from_frozen_facts(env):
    svc = env[0]
    _log(svc, [CHICKEN], "2026-11-23T08:00")
    day = svc.get_day_summary(SESSION, P, "2026-11-23")
    assert day["nutrients"]["energy_kcal"]["known"] == "330.0"
    assert day["nutrients"]["protein_g"]["known"] == "62.0"
    assert day["nutrients"]["energy_kcal"]["target"] is None and day["profile_version"] is None


def test_food_without_a_value_makes_the_nutrient_partial_never_zero(env):
    svc = env[0]
    _log(svc, [CHICKEN, COLA], "2026-11-23T08:00")
    e = svc.get_day_summary(SESSION, P, "2026-11-23")["nutrients"]["energy_kcal"]
    assert (e["known"], e["status"], e["items_uncounted"]) == ("330.0", "PARTIAL", 1)
    _log(svc, [COLA], "2026-11-22T20:00")
    e = svc.get_day_summary(SESSION, P, "2026-11-22")["nutrients"]["energy_kcal"]
    assert e["known"] is None and e["items_uncounted"] == 1


def test_day_compares_with_targets_once_onboarded(env):
    svc, profiles = env[0], env[1]
    _log(svc, [CHICKEN], "2026-11-21T12:00")
    _onboard(profiles, ERICK_WIRE)
    day = svc.get_day_summary(SESSION, P, "2026-11-21")
    e = day["nutrients"]["energy_kcal"]
    assert e["target"]["display_value"] == "3150"  # the first version reaches back
    assert e["percent"] is not None and e["known"] is not None
    assert day["profile_version"] == 1


def test_set_mode_creates_a_mode_version(env):
    svc, profiles = env[0], env[1]
    r = svc.set_mode(SESSION, P, "PREGNANCY", "2027-05-15")
    assert r["version"] == 1 and profiles.inputs_on(P, date(2026, 11, 23)).mode == "PREGNANCY"


def test_period_defaults_to_the_last_seven_days(env):
    p = env[0].get_period_summary(SESSION, P)
    assert (p["start"], p["end"]) == ("2026-11-17", "2026-11-23") and len(p["days"]) == 7


@pytest.mark.parametrize("start,end,field", [
    ("2026-10-01", "2026-11-23", "start"), ("2026-11-23", "2026-11-22", "start"),
    ("2026-11-20", "2026-11-24", "end"), ("20261120", None, "start")])
def test_period_bounds(env, start, end, field):
    with pytest.raises(InvalidField) as e:
        env[0].get_period_summary(SESSION, P, start, end)
    assert e.value.field == field


def test_period_one_home_request(env):
    svc, auth = env[0], env[2]
    before = auth.home_calls
    p = svc.get_period_summary(SESSION, P, "2026-10-24", "2026-11-23")
    assert len(p["days"]) == 31 and auth.home_calls == before + 1


def test_period_uses_each_days_targets_across_a_change(env):
    svc, profiles, _, clock = env

    def at(day):
        clock.now = datetime.fromisoformat(f"{day}T10:00:00+00:00")

    at("2027-02-18")
    svc.set_mode(SESSION, P, "PREGNANCY", "2027-05-15")
    _onboard(profiles, ANA_REST)
    for day in ("2027-02-18", "2027-02-19", "2027-02-20"):
        at(day)
        if day == "2027-02-19":
            _onboard(profiles, {"pre_pregnancy_weight_kg": "60"})
        target = profiles.targets_on(P, date.fromisoformat(day)).targets["energy_kcal"]
        grams = (target.value / Decimal("1.65")).quantize(Decimal("0.01"))
        _log(svc, [{**CHICKEN, "amount": str(grams)}], f"{day}T08:00")
        svc.close_day(SESSION, P, day)
    at("2027-02-21")
    p = svc.get_period_summary(SESSION, P, "2027-02-18", "2027-02-20")
    assert [d["nutrients"]["energy_kcal"]["target"]["value"] for d in p["days"]] == [
        "2042.4", "2070.4", "2320.4"]
    assert [d["nutrients"]["energy_kcal"]["percent"] for d in p["days"]] == ["100"] * 3
    assert [d["profile_version"] for d in p["days"]] == [2, 3, 3]
    avg = p["averages"]["energy_kcal"]
    assert avg["average_percent"] == "100" and avg["days_used"] == 3


def test_period_without_profile_says_so(env):
    assert env[0].get_period_summary(SESSION, P)["has_profile"] is False
