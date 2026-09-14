"""USDA FoodData Central provider. Primary source for generic whole foods.
Per-100g nutrients normalized to canonical units. Missing nutrient = absent (unknown),
never zero. source label preserves provenance incl fdcId + dataType.
"""
from __future__ import annotations
import os
from decimal import Decimal
import httpx
from .food_provider import FoodProvider, FoodSearchHit, FoodRecord
from .nutrient_map import USDA_BY_NUMBER, CANONICAL_UNITS, to_canonical


class UsdaFoodProvider(FoodProvider):
    name = "USDA_FDC"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._key = api_key or os.environ.get("USDA_API_KEY", "DEMO_KEY")
        self._base = (base_url or os.environ.get("USDA_BASE_URL", "https://api.nal.usda.gov/fdc/v1")).rstrip("/")
        self._c = httpx.Client(timeout=15.0)

    def search_food(self, query: str) -> list[FoodSearchHit]:
        r = self._c.post(f"{self._base}/foods/search", params={"api_key": self._key},
                         json={"query": query, "pageSize": 10,
                               "dataType": ["Foundation", "SR Legacy", "Survey (FNDDS)"]})
        r.raise_for_status()
        hits = []
        for f in r.json().get("foods", []):
            hits.append(FoodSearchHit(f"usda:{f['fdcId']}", f.get("description", "")))
        return hits

    def get_food(self, food_id: str) -> FoodRecord:
        fdc = food_id.split(":", 1)[1] if food_id.startswith("usda:") else food_id
        r = self._c.get(f"{self._base}/food/{fdc}", params={"api_key": self._key})
        r.raise_for_status()
        data = r.json()
        nutrients: dict[str, Decimal] = {}
        for fn in data.get("foodNutrients", []):
            num = str((fn.get("nutrient") or {}).get("number", ""))
            amount = fn.get("amount")
            if num in USDA_BY_NUMBER and amount is not None:
                canon, usda_unit = USDA_BY_NUMBER[num]
                try:
                    nutrients[canon] = to_canonical(amount, usda_unit, CANONICAL_UNITS[canon])
                except ValueError:
                    continue  # unknown conversion -> leave nutrient UNKNOWN (absent)
        return FoodRecord(f"usda:{fdc}", data.get("description", ""), nutrients,
                          f"{self.name}:{data.get('dataType','?')}", str(fdc))

    def get_nutrients(self, food_id: str, quantity, unit: str) -> dict:
        if unit not in ("g", "gram", "grams"):
            raise ValueError("USDA provider works in grams")
        rec = self.get_food(food_id)
        factor = Decimal(str(quantity)) / Decimal("100")
        return {n: v * factor for n, v in rec.nutrients_per_100g.items()}
