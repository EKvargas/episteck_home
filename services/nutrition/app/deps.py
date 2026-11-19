"""Shared singletons: repo, provider (chain or synthetic), mealie adapter, service."""
from __future__ import annotations
import os
from .store.sqlite_repo import SqliteNutritionRepository
from .providers.synthetic import SyntheticFoodProvider
from .service import NutritionService
from .home_control.client import HomeControlPlaneClient

_DB = os.environ.get("NUTRITION_DB", "/data/nutrition.sqlite")


def build_home_authorizer() -> HomeControlPlaneClient:
    """Build lazily so importing the module never reads or exposes credentials."""
    return HomeControlPlaneClient.from_env()


def _build_provider():
    # If real providers are configured (USDA key present), use the chain; else synthetic.
    mode = os.environ.get("FOOD_PROVIDER", "auto")
    if mode == "synthetic":
        return SyntheticFoodProvider()
    bls_db = os.environ.get("BLS_DB")
    if bls_db and os.path.exists(bls_db):
        # BLS alone justifies the chain, even without a USDA key.
        from .providers.bls import BlsFoodProvider
        from .providers.usda import UsdaFoodProvider
        from .providers.openfoodfacts import OpenFoodFactsProvider
        from .providers.chain import ProviderChain
        return ProviderChain([BlsFoodProvider(bls_db), OpenFoodFactsProvider(), UsdaFoodProvider()])
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
    return NutritionService(repo, provider, mealie, authorizer=build_home_authorizer())


def build_diary_service():
    """Build the diary service. A bad DIARY_TZ fails here, at startup."""
    from zoneinfo import ZoneInfo

    from .diary.service import DiaryService
    from .store.diary_sqlite import SqliteDiaryStore

    tz = os.environ.get("DIARY_TZ", "Europe/Berlin")
    ZoneInfo(tz)
    return DiaryService(
        SqliteDiaryStore(_DB),
        _build_provider(),
        SqliteNutritionRepository(_DB),
        authorizer=build_home_authorizer(),
        tz=tz,
    )
