"""Tiny local synthetic food provider for Stage E validation only. NO real data."""
from __future__ import annotations
from decimal import Decimal
from .food_provider import FoodProvider, FoodSearchHit, FoodRecord

_DATA = {
    "syn-chicken-breast": ("Chicken breast (synthetic)", {"protein_g": Decimal("31"), "fat_g": Decimal("3.6"), "energy_kcal": Decimal("165")}),
    "syn-broccoli":       ("Broccoli (synthetic)",       {"protein_g": Decimal("2.8"), "carb_g": Decimal("7"), "iron_mg": Decimal("0.7"), "energy_kcal": Decimal("34")}),
    "syn-pasta-cooked":   ("Pasta, cooked (synthetic)",  {"protein_g": Decimal("5"), "carb_g": Decimal("25"), "energy_kcal": Decimal("131")}),
    "syn-olive-oil":      ("Olive oil (synthetic)",      {"fat_g": Decimal("100"), "energy_kcal": Decimal("884")}),
    "syn-yogurt":         ("Yogurt, plain (synthetic)",  {"protein_g": Decimal("10"), "fat_g": Decimal("5"), "energy_kcal": Decimal("97")}),
    "syn-cola":           ("Cola (synthetic)",           {"sugars_total_g": Decimal("10.6")}),
    "syn-orange-juice":   ("Orange juice (synthetic)",   {"sugars_total_g": Decimal("8.4")}),
    "syn-apple":          ("Apple (synthetic)",          {"sugars_total_g": Decimal("10.3")}),
    "syn-bread":          ("Bread (synthetic)",          {"sugars_total_g": Decimal("3.0")}),
}
# Open Food Facts style category tags, only for the foods that have one.
_CATEGORY = {
    "syn-cola": "en:sodas",
    "syn-orange-juice": "en:fruit-juices",
    "syn-apple": "en:fresh-fruits",
}
_SOURCE = "SYNTHETIC"
_VERSION = "stage-e-1"


class SyntheticFoodProvider(FoodProvider):
    def search_food(self, query: str) -> list[FoodSearchHit]:
        q = query.lower()
        return [FoodSearchHit(fid, name) for fid, (name, _) in _DATA.items() if q in name.lower() or q in fid]

    def get_food(self, food_id: str) -> FoodRecord:
        if food_id not in _DATA:
            raise KeyError(f"unknown food_id {food_id!r}")
        name, nutrients = _DATA[food_id]
        return FoodRecord(food_id, name, nutrients, _SOURCE, _VERSION,
                          category=_CATEGORY.get(food_id))

    def get_nutrients(self, food_id: str, quantity, unit: str) -> dict:
        from decimal import Decimal as D
        if unit not in ("g", "gram", "grams"):
            raise ValueError(f"synthetic provider only supports grams, got {unit!r}")
        rec = self.get_food(food_id)
        factor = D(str(quantity)) / D("100")
        return {n: v * factor for n, v in rec.nutrients_per_100g.items()}
