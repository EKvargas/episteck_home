"""Nutrition service core — wires domain + provider + store + Mealie. Deterministic:
all nutrient numbers come from nutrition_domain, never from an LLM. AI-derived intake
is always a PROPOSAL until user-confirmed.
"""
from __future__ import annotations
from decimal import Decimal
from nutrition_domain import (
    FoodFact, ConfirmedFoodAmount, calculate_meal_nutrients, calculate_daily_intake,
    compare_to_targets, calculate_daily_gap,
    IntakeKind, IntakeProvenance,
)
from .providers.food_provider import FoodProvider
from .store.repository import NutritionRepository
from .reference.pregnancy_targets import pregnancy_targets_map, pregnancy_targets_detailed


class NutritionService:
    def __init__(self, repo: NutritionRepository, provider: FoodProvider, mealie=None):
        self.repo = repo
        self.provider = provider
        self.mealie = mealie

    # --- profile ---
    def get_profile(self, person_id: str):
        return self.repo.get_profile(person_id)

    def upsert_profile(self, person_id: str, profile: dict):
        return self.repo.upsert_profile(person_id, profile)

    # --- deterministic evaluation ---
    def _to_confirmed(self, foods: list[dict]) -> list[ConfirmedFoodAmount]:
        out = []
        for f in foods:
            rec = self.provider.get_food(f["food_id"])
            out.append(ConfirmedFoodAmount(
                FoodFact(rec.food_id, rec.nutrients_per_100g, rec.source),
                Decimal(str(f["grams"]))))
        return out

    def evaluate_meal(self, foods: list[dict]) -> dict:
        totals = calculate_meal_nutrients(self._to_confirmed(foods))
        return {k: str(v) for k, v in totals.items()}

    def daily_intake(self, person_id: str, date: str) -> dict:
        records = self.repo.list_intake(person_id, date, kind=IntakeKind.ACTUAL.value)
        meals = [self._to_confirmed(r["foods"]) for r in records if r.get("foods")]
        totals = calculate_daily_intake(meals)
        return {k: str(v) for k, v in totals.items()}

    def daily_gap(self, person_id: str, date: str) -> dict:
        prof = self.repo.get_profile(person_id) or {}
        targets = {k: Decimal(str(v)) for k, v in (prof.get("targets") or {}).items()}
        consumed = {k: Decimal(v) for k, v in self.daily_intake(person_id, date).items()}
        gap = calculate_daily_gap(consumed, targets)
        cmp = compare_to_targets(consumed, targets)
        return {
            "targets": {k: str(v) for k, v in targets.items()},
            "consumed": {k: str(v) for k, v in consumed.items()},
            "gap": {k: str(v) for k, v in gap.items()},
            "detail": {k: {"target": str(c.target), "consumed": str(c.consumed),
                           "remaining": str(c.remaining), "percentage": str(c.percentage)}
                       for k, c in cmp.items()},
        }

    # --- planned vs actual ---
    def record_planned(self, person_id: str, date: str, foods: list[dict], ref: str | None = None):
        return self.repo.add_intake(person_id, {
            "date": date, "kind": IntakeKind.PLANNED.value, "foods": foods,
            "planned_meal_reference": ref, "provenance": IntakeProvenance.USER_CONFIRMED.value})

    def record_actual(self, person_id: str, date: str, foods: list[dict],
                      provenance: str = IntakeProvenance.USER_CONFIRMED.value, ref: str | None = None):
        return self.repo.add_intake(person_id, {
            "date": date, "kind": IntakeKind.ACTUAL.value, "foods": foods,
            "planned_meal_reference": ref, "provenance": provenance})

    def ate_as_planned(self, person_id: str, date: str, planned_id: str):
        """Copy a PLANNED record into an ACTUAL USER_CONFIRMED one. No re-entry."""
        planned = [r for r in self.repo.list_intake(person_id, date, IntakeKind.PLANNED.value)
                   if r["id"] == planned_id]
        if not planned:
            raise KeyError("planned record not found")
        p = planned[0]
        return self.record_actual(person_id, date, p["foods"],
                                  provenance=IntakeProvenance.USER_CONFIRMED.value,
                                  ref=p.get("planned_meal_reference") or planned_id)

    def propose_change(self, foods: list[dict]) -> dict:
        """AI/NL change returns a PROPOSAL (not authoritative). Caller must confirm
        before it becomes actual intake."""
        return {"provenance": IntakeProvenance.AI_PROPOSAL.value,
                "foods": foods, "nutrients": self.evaluate_meal(foods),
                "requires_confirmation": True}

    # --- consent ---
    def set_consent(self, person_id: str, state: str = "GRANTED", note: str = ""):
        return self.repo.set_consent(person_id, "NUTRITION", state, note)

    def get_consent(self, person_id: str):
        return self.repo.get_consent(person_id)

    def _require_consent(self, person_id: str):
        if not self.repo.has_consent(person_id, "NUTRITION"):
            raise PermissionError(f"no NUTRITION consent for {person_id}")

    # --- pregnancy profile with authoritative reference targets ---
    def create_pregnancy_profile(self, person_id: str, *, stage: str | None = None,
                                 preferences: str = "", dislikes: str = "",
                                 intolerances: str = "", avoided_foods: str = "",
                                 user_goals: dict | None = None):
        """Create a PREGNANCY-context profile whose targets come from DGE/EFSA reference
        values (provenance REFERENCE_TARGET). Requires consent. Only explicit facts stored."""
        self._require_consent(person_id)
        profile = {
            "context": "PREGNANCY",
            "pregnancy_stage": stage,
            "preferences": preferences,
            "dislikes": dislikes,
            "explicit_intolerances": intolerances,
            "avoided_foods": avoided_foods,
            "user_goals": user_goals or {},
            "targets": {n: str(v) for n, v in pregnancy_targets_map().items()},
            "targets_detail": pregnancy_targets_detailed(),
            "target_source": "REFERENCE_TARGET",
        }
        return self.repo.upsert_profile(person_id, profile)

    def daily_gap_v2(self, person_id: str, date: str) -> dict:
        """Like daily_gap but distinguishes UNKNOWN (no data for a targeted nutrient) from
        a genuine zero-consumed. A nutrient is 'unavailable' if NO consumed food reported it."""
        from decimal import Decimal
        prof = self.repo.get_profile(person_id) or {}
        targets = {k: Decimal(str(v)) for k, v in (prof.get("targets") or {}).items()}
        records = self.repo.list_intake(person_id, date, kind="ACTUAL")
        # which nutrients were actually reported by any consumed food?
        reported = set()
        for r in records:
            for f in r.get("foods", []):
                try:
                    rec = self.provider.get_food(f["food_id"])
                    reported |= set(rec.nutrients_per_100g.keys())
                except Exception:
                    continue
        consumed = {k: Decimal(v) for k, v in self.daily_intake(person_id, date).items()}
        out = {}
        for n, tgt in targets.items():
            if n not in reported:
                out[n] = {"target": str(tgt), "consumed": None, "remaining": None,
                          "percentage": None, "status": "UNKNOWN"}
            else:
                c = consumed.get(n, Decimal("0"))
                out[n] = {"target": str(tgt), "consumed": str(c), "remaining": str(tgt - c),
                          "percentage": str((c/tgt*100) if tgt else Decimal("0")), "status": "KNOWN"}
        return out

    # --- menu planning (deterministic evaluation; NOT medical optimization) ---
    def plan_menu(self, person_id: str, candidate_meals: list[dict]) -> dict:
        """candidate_meals = [{"label": str, "foods": [{food_id,grams}]}]. Evaluates each meal
        and the day total against targets deterministically. Returns a PLAN with gaps, framed
        as constructed against configured reference targets — NOT a medical optimum."""
        from decimal import Decimal
        prof = self.repo.get_profile(person_id) or {}
        targets = {k: Decimal(str(v)) for k, v in (prof.get("targets") or {}).items()}
        day_meals = []
        for m in candidate_meals:
            day_meals.append(self._to_confirmed(m["foods"]))
        from nutrition_domain import calculate_daily_intake, calculate_daily_gap
        total = calculate_daily_intake(day_meals)
        gap = calculate_daily_gap(total, targets)
        return {
            "person_id": person_id,
            "meals": [{"label": m["label"], "foods": m["foods"]} for m in candidate_meals],
            "day_total": {k: str(v) for k, v in total.items()},
            "gap_vs_reference": {k: str(v) for k, v in gap.items()},
            "disclaimer": "Plan constructed against configured DGE/EFSA reference targets and "
                          "stated preferences. Not a medical recommendation.",
            "status": "PROPOSED",
        }
