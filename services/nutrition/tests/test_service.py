"""Service-level tests using SQLite (temp) + synthetic provider. No FastAPI/HTTP needed."""
import tempfile, os
from decimal import Decimal
from app.store.sqlite_repo import SqliteNutritionRepository
from app.providers.synthetic import SyntheticFoodProvider
from app.service import NutritionService
from tests.support import AllowAllAuthorizer

def _svc():
    fd, path = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
    return NutritionService(
        SqliteNutritionRepository(path),
        SyntheticFoodProvider(),
        authorizer=AllowAllAuthorizer(),
    )

def test_profile_crud_and_provenance():
    s = _svc()
    s.upsert_profile("person-syn-1", "person-syn-1", {"context":"GENERAL","targets":{"protein_g":60},"target_source":"USER_CONFIGURED"})
    p = s.get_profile("person-syn-1", "person-syn-1")
    assert p["target_source"] == "USER_CONFIGURED"
    assert p["targets"]["protein_g"] == 60

def test_evaluate_meal_deterministic():
    s = _svc()
    r = s.evaluate_meal([{"food_id":"syn-chicken-breast","grams":200}])
    assert r["protein_g"] == "62"   # 31 * 2

def test_planned_and_actual_distinct():
    s = _svc()
    pl = s.record_planned("p1", "p1","2026-09-14",[{"food_id":"syn-yogurt","grams":100}])
    ac = s.record_actual("p1", "p1","2026-09-14",[{"food_id":"syn-pasta-cooked","grams":100}])
    assert pl["kind"] == "PLANNED" and ac["kind"] == "ACTUAL"
    # daily actual reflects ONLY actual, not planned
    di = s.daily_intake("p1", "p1","2026-09-14")
    assert di.get("carb_g") == "25"   # pasta only

def test_ate_as_planned_copies_without_reentry():
    s = _svc()
    pl = s.record_planned("p2", "p2","2026-09-14",[{"food_id":"syn-chicken-breast","grams":100}])
    ac = s.ate_as_planned("p2", "p2","2026-09-14", pl["id"])
    assert ac["kind"] == "ACTUAL" and ac["provenance"] == "USER_CONFIRMED"
    assert s.daily_intake("p2", "p2","2026-09-14")["protein_g"] == "31"

def test_propose_change_is_proposal_not_fact():
    s = _svc()
    prop = s.propose_change([{"food_id":"syn-pasta-cooked","grams":150}])
    assert prop["provenance"] == "AI_PROPOSAL"
    assert prop["requires_confirmation"] is True

def test_daily_gap():
    s = _svc()
    s.upsert_profile("p3", "p3", {"targets":{"protein_g":60}})
    s.record_actual("p3", "p3","2026-09-14",[{"food_id":"syn-chicken-breast","grams":100}])  # 31
    g = s.daily_gap("p3", "p3","2026-09-14")
    assert g["gap"]["protein_g"] == "29"
    assert g["detail"]["protein_g"]["percentage"].startswith("51.")  # 31/60
