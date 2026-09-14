"""Open Food Facts provider. Secondary source for packaged/barcoded commercial foods.
No API key; requires custom User-Agent. Read rate limits apply. OFF minerals are often
reported in grams per 100g -> normalized to canonical mg/ug. Missing = unknown.
"""
from __future__ import annotations
import os
from decimal import Decimal
import httpx
from .food_provider import FoodProvider, FoodSearchHit, FoodRecord
from .nutrient_map import OFF_KEYS, CANONICAL_UNITS, to_canonical


class OpenFoodFactsProvider(FoodProvider):
    name = "OPEN_FOOD_FACTS"

    def __init__(self, base_url: str | None = None, search_url: str | None = None, user_agent: str | None = None):
        self._base = (base_url or os.environ.get("OFF_BASE_URL", "https://world.openfoodfacts.org")).rstrip("/")
        self._search = (search_url or os.environ.get("OFF_SEARCH_URL", "https://search.openfoodfacts.org")).rstrip("/")
        ua = user_agent or os.environ.get("OFF_USER_AGENT", "EpisteckHome/0.1 (episteck@gmail.com)")
        self._c = httpx.Client(timeout=15.0, headers={"User-Agent": ua})

    def search_food(self, query: str) -> list[FoodSearchHit]:
        # Search-a-licious full-text endpoint
        try:
            r = self._c.get(f"{self._search}/search", params={"q": query, "page_size": 10})
            r.raise_for_status()
            hits = []
            for p in r.json().get("hits", []):
                code = p.get("code")
                if code:
                    hits.append(FoodSearchHit(f"off:{code}", p.get("product_name") or p.get("generic_name") or code))
            return hits
        except Exception:
            return []

    def get_food(self, food_id: str) -> FoodRecord:
        code = food_id.split(":", 1)[1] if food_id.startswith("off:") else food_id
        r = self._c.get(f"{self._base}/api/v3/product/{code}.json")
        r.raise_for_status()
        body = r.json()
        product = body.get("product", {})
        nutr = product.get("nutriments", {})
        nutrients: dict[str, Decimal] = {}
        for off_key, (canon, off_unit) in OFF_KEYS.items():
            val = nutr.get(off_key)
            if val is not None:
                try:
                    nutrients[canon] = to_canonical(val, off_unit, CANONICAL_UNITS[canon])
                except ValueError:
                    continue
        return FoodRecord(f"off:{code}", product.get("product_name") or code, nutrients, self.name, str(code))

    def get_nutrients(self, food_id: str, quantity, unit: str) -> dict:
        if unit not in ("g", "gram", "grams"):
            raise ValueError("OFF provider works in grams")
        rec = self.get_food(food_id)
        factor = Decimal(str(quantity)) / Decimal("100")
        return {n: v * factor for n, v in rec.nutrients_per_100g.items()}
