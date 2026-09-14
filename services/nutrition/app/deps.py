"""Shared singletons: repo, provider, mealie adapter, service."""
from __future__ import annotations
import os
from .store.sqlite_repo import SqliteNutritionRepository
from .providers.synthetic import SyntheticFoodProvider
from .service import NutritionService

_DB = os.environ.get("NUTRITION_DB", "/data/nutrition.sqlite")

def build_service() -> NutritionService:
    repo = SqliteNutritionRepository(_DB)
    provider = SyntheticFoodProvider()
    mealie = None
    if os.environ.get("MEALIE_BASE_URL") and os.environ.get("MEALIE_API_TOKEN"):
        from .mealie.adapter import MealieAdapter
        mealie = MealieAdapter()
    return NutritionService(repo, provider, mealie)
