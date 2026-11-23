"""NutritionService: meal evaluation and menu planning (synthetic provider, temp SQLite)."""
from datetime import datetime, timezone
from decimal import Decimal

from app import deps
from app.profile.service import ProfileService
from app.providers.synthetic import SyntheticFoodProvider
from app.service import NutritionService
from app.store.profile_sqlite import SqliteProfileStore
from tests.support import AllowAllAuthorizer

S = "delegation-token"
# Task 2 worked example: energy target 3150 kcal on 2026-11-23.
ERICK_WIRE = {"birth_date": "1986-03-10", "sex": "MALE", "height_cm": "180", "weight_kg": "82",
              "activity_pal": "1.6", "training_sessions_per_week": 3, "goal": "PERFORMANCE"}
LUNCH = [{"label": "lunch", "foods": [{"food_id": "syn-chicken-breast", "grams": 200}]}]


def _svc():
    return NutritionService(
        SyntheticFoodProvider(),
        authorizer=AllowAllAuthorizer(),
        targets_today=lambda person: {},
    )


def test_evaluate_meal_deterministic():
    s = _svc()
    r = s.evaluate_meal([{"food_id":"syn-chicken-breast","grams":200}])
    assert r["protein_g"] == "62"   # 31 * 2

def test_propose_change_is_proposal_not_fact():
    s = _svc()
    prop = s.propose_change([{"food_id":"syn-pasta-cooked","grams":150}])
    assert prop["provenance"] == "AI_PROPOSAL"
    assert prop["requires_confirmation"] is True


def test_plan_menu_uses_todays_targets(tmp_path, monkeypatch):
    """The service deps builds compares the menu with the targets in force today."""
    clock = lambda: datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)  # noqa: E731
    profiles = ProfileService(SqliteProfileStore(str(tmp_path / "n.sqlite")),
                              authorizer=AllowAllAuthorizer(), clock=clock)
    draft = profiles.propose_profile(S, "PSN-E", ERICK_WIRE)["draft_id"]
    profiles.confirm_profile(S, "PSN-E", draft)
    monkeypatch.setenv("FOOD_PROVIDER", "synthetic")
    monkeypatch.setattr(deps, "build_home_authorizer", AllowAllAuthorizer)

    svc = deps.build_service(profiles)
    plan = svc.plan_menu(S, "PSN-E", LUNCH)

    assert Decimal(plan["day_total"]["energy_kcal"]) == Decimal("330")   # 165 kcal/100 g * 2
    assert (Decimal(plan["gap_vs_reference"]["energy_kcal"])
            == Decimal("3150") - Decimal(plan["day_total"]["energy_kcal"]))
    # A person without a profile has no targets; none is guessed.
    assert svc.plan_menu(S, "PSN-NONE", LUNCH)["gap_vs_reference"] == {}
