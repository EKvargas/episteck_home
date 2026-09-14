"""Shared singletons: repo, provider (chain or synthetic), mealie adapter, service."""
from __future__ import annotations
import os
from .store.sqlite_repo import SqliteNutritionRepository
from .providers.synthetic import SyntheticFoodProvider
from .service import NutritionService

_DB = os.environ.get("NUTRITION_DB", "/data/nutrition.sqlite")


def _build_provider():
    # If real providers are configured (USDA key present), use the chain; else synthetic.
    mode = os.environ.get("FOOD_PROVIDER", "auto")
    if mode == "synthetic":
        return SyntheticFoodProvider()
    if os.environ.get("USDA_API_KEY") or os.environ.get("OFF_BASE_URL") or mode == "chain":
        from .providers.usda import UsdaFoodProvider
        from .providers.openfoodfacts import OpenFoodFactsProvider
        from .providers.chain import ProviderChain
        return ProviderChain([UsdaFoodProvider(), OpenFoodFactsProvider()])
    return SyntheticFoodProvider()


def build_service() -> NutritionService:
    repo = SqliteNutritionRepository(_DB)
    provider = _build_provider()
    mealie = None
    if os.environ.get("MEALIE_BASE_URL") and os.environ.get("MEALIE_API_TOKEN"):
        from .mealie.adapter import MealieAdapter
        mealie = MealieAdapter()
    return NutritionService(repo, provider, mealie)
