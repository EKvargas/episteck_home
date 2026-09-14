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
