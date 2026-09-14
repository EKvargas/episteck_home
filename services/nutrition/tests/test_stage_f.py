"""Stage F tests: provider chain, unknown!=zero, provenance, unit norm, consent,
pregnancy targets, menu eval, AI-not-authoritative. Uses a FAKE provider (no network)."""
import tempfile, os
from decimal import Decimal
from app.store.sqlite_repo import SqliteNutritionRepository
from app.service import NutritionService
from app.providers.food_provider import FoodProvider, FoodSearchHit, FoodRecord
from app.providers.chain import ProviderChain
from app.providers.nutrient_map import to_canonical

class FakeUSDA(FoodProvider):
    name = "USDA_FDC"
    def search_food(self, q): return [FoodSearchHit("usda:1", "Egg (fake)")]
    def get_food(self, fid):
        # protein known, iron UNKNOWN (absent), NOT zero
        return FoodRecord("usda:1", "Egg", {"protein_g": Decimal("13"), "energy_kcal": Decimal("143")}, "USDA_FDC:Foundation", "1")
    def get_nutrients(self, fid, qty, unit):
        f=self.get_food(fid).nutrients_per_100g; k=Decimal(str(qty))/Decimal("100"); return {n:v*k for n,v in f.items()}

class FakeOFF(FoodProvider):
    name = "OPEN_FOOD_FACTS"
    def search_food(self, q): return [FoodSearchHit("off:123", "Packaged (fake)")]
    def get_food(self, fid): return FoodRecord("off:123", "Packaged", {"protein_g": Decimal("5")}, "OPEN_FOOD_FACTS", "123")
    def get_nutrients(self, fid, qty, unit):
        f=self.get_food(fid).nutrients_per_100g; k=Decimal(str(qty))/Decimal("100"); return {n:v*k for n,v in f.items()}

def _svc(provider=None):
    fd,p=tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
    return NutritionService(SqliteNutritionRepository(p), provider or ProviderChain([FakeUSDA(), FakeOFF()]))

def test_chain_search_concatenates_both_sources():
    s=_svc(); hits=s.provider.search_food("x")
    provs={h.food_id.split(":")[0] for h in hits}
    assert provs == {"usda","off"}

def test_chain_routes_by_prefix_preserving_source():
    s=_svc()
    assert s.provider.get_food("usda:1").source.startswith("USDA")
    assert s.provider.get_food("off:123").source == "OPEN_FOOD_FACTS"

def test_unknown_nutrient_is_absent_not_zero():
    s=_svc(); rec=s.provider.get_food("usda:1")
    assert "iron_mg" not in rec.nutrients_per_100g   # UNKNOWN, not 0

def test_unit_normalization_g_to_mg_ug():
    assert to_canonical("1","g","mg")==Decimal("1000")
    assert to_canonical("1","g","ug")==Decimal("1000000")
    assert to_canonical("5","MG","mg")==Decimal("5")

def test_unit_normalization_fails_loud_on_unknown_path():
    try: to_canonical("1","g","kcal"); raise AssertionError("should fail")
    except ValueError: pass

def test_consent_required_for_pregnancy_profile():
    s=_svc()
    try:
        s.create_pregnancy_profile("p-real"); raise AssertionError("should require consent")
    except PermissionError: pass
    s.set_consent("p-real","GRANTED")
    prof=s.create_pregnancy_profile("p-real", stage="2nd trimester", preferences="veg")
    assert prof["context"]=="PREGNANCY" and prof["target_source"]=="REFERENCE_TARGET"

def test_pregnancy_targets_have_reference_provenance():
    s=_svc(); s.set_consent("p2","GRANTED")
    prof=s.create_pregnancy_profile("p2")
    d=prof["targets_detail"]
    assert d["folate_ug"]["value"]=="550" and d["folate_ug"]["source_org"].startswith("DGE")
    assert d["iodine_ug"]["value"]=="230"
    assert all(v["provenance"]=="REFERENCE_TARGET" for v in d.values())

def test_gap_v2_marks_unknown_vs_known():
    s=_svc(); s.set_consent("p3","GRANTED"); s.create_pregnancy_profile("p3")
    # eat egg (protein known, iron/folate unknown from this food)
    s.record_actual("p3","2026-09-15",[{"food_id":"usda:1","grams":100}])
    g=s.daily_gap_v2("p3","2026-09-15")
    assert g["protein_g"]["status"]=="KNOWN"
    assert g["iron_mg"]["status"]=="UNKNOWN" and g["iron_mg"]["consumed"] is None

def test_menu_plan_is_proposal_not_medical():
    s=_svc(); s.set_consent("p4","GRANTED"); s.create_pregnancy_profile("p4")
    plan=s.plan_menu("p4",[{"label":"lunch","foods":[{"food_id":"usda:1","grams":150}]}])
    assert plan["status"]=="PROPOSED"
    assert "Not a medical recommendation" in plan["disclaimer"]

def test_ai_change_proposal_not_authoritative():
    s=_svc()
    prop=s.propose_change([{"food_id":"off:123","grams":100}])
    assert prop["provenance"]=="AI_PROPOSAL" and prop["requires_confirmation"] is True
