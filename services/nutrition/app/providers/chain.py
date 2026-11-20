"""Provider chain behind the FoodProvider ABC. BLS (when configured), OFF and USDA.

- search_food: queries providers in order; each hit keeps its provider prefix (usda:/off:)
  so results are never source-ambiguous. Results are CONCATENATED, not merged.
- get_food/get_nutrients: routed to the owning provider by the id prefix.
- No silent merging of conflicting nutrient values: each FoodRecord carries ONE source.
"""
from __future__ import annotations
from decimal import Decimal
from .food_provider import FoodNotFound, FoodProvider, FoodSearchHit, FoodRecord


class ProviderChain(FoodProvider):
    def __init__(self, providers: list[FoodProvider]):
        # ordered: primary first
        self._providers = providers
        self._by_prefix = {}
        for p in providers:
            # infer prefix from a sample id scheme
            self._by_prefix[getattr(p, "name", p.__class__.__name__)] = p

    def _route(self, food_id: str) -> FoodProvider:
        prefix = food_id.split(":", 1)[0]
        mapping = {"usda": "USDA_FDC", "off": "OPEN_FOOD_FACTS", "bls": "BLS"}
        want = mapping.get(prefix)
        for p in self._providers:
            if getattr(p, "name", None) == want:
                return p
        raise FoodNotFound(f"no provider for id {food_id!r}")

    def search_food(self, query: str) -> list[FoodSearchHit]:
        results: list[FoodSearchHit] = []
        for p in self._providers:
            try:
                results.extend(p.search_food(query))
            except Exception:
                continue  # a provider being down must not break the chain
        return results

    def get_food(self, food_id: str) -> FoodRecord:
        return self._route(food_id).get_food(food_id)

    def get_nutrients(self, food_id: str, quantity, unit: str) -> dict:
        return self._route(food_id).get_nutrients(food_id, quantity, unit)
