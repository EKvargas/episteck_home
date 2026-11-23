"""Shared singletons: provider (chain or synthetic), mealie adapter, services."""
from __future__ import annotations
import logging
import os
from collections.abc import Callable
from decimal import Decimal
from .providers.synthetic import SyntheticFoodProvider
from .service import NutritionService
from .home_control.client import HomeControlPlaneClient

_DB = os.environ.get("NUTRITION_DB", "/data/nutrition.sqlite")
_log = logging.getLogger(__name__)
_WARNED_MISSING_BLS: set[str] = set()  # the service and the diary both build a provider


def build_home_authorizer() -> HomeControlPlaneClient:
    """Build lazily so importing the module never reads or exposes credentials."""
    return HomeControlPlaneClient.from_env()


def _build_provider():
    # If real providers are configured (USDA key present), use the chain; else synthetic.
    mode = os.environ.get("FOOD_PROVIDER", "auto")
    if mode == "synthetic":
        return SyntheticFoodProvider()
    bls_db = os.environ.get("BLS_DB")
    if bls_db and not os.path.exists(bls_db) and bls_db not in _WARNED_MISSING_BLS:
        _WARNED_MISSING_BLS.add(bls_db)
        _log.warning("BLS_DB is set but the file is missing (%s); BLS lookups are disabled", bls_db)
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


def targets_today_from(profile) -> Callable[[str], dict[str, Decimal]]:
    """The person's targets in force today (nutrient -> Decimal), or {} when none.

    Uses the profile service's internal helpers, which do not authorize: the menu
    operation calling it has already made its one Home request.
    """
    def targets_today(person: str) -> dict[str, Decimal]:
        target_set = profile.targets_on(person, profile.today())
        if target_set is None:
            return {}
        return {nutrient: target.value for nutrient, target in target_set.targets.items()}

    return targets_today


def build_service(profile=None) -> NutritionService:
    """Build the meal and menu service.

    Pass the entry point's own ProfileService so both share one instance.
    """
    profiles = profile if profile is not None else build_profile_service()
    provider = _build_provider()
    mealie = None
    if os.environ.get("MEALIE_BASE_URL") and os.environ.get("MEALIE_API_TOKEN"):
        from .mealie.adapter import MealieAdapter
        mealie = MealieAdapter()
    return NutritionService(
        provider, mealie, authorizer=build_home_authorizer(),
        targets_today=targets_today_from(profiles),
    )


def build_diary_service(profile=None):
    """Build the diary service. A bad DIARY_TZ fails here, at startup.

    Pass the entry point's own ProfileService so both share one instance.
    """
    from zoneinfo import ZoneInfo

    from .diary.service import DiaryService
    from .store.diary_sqlite import SqliteDiaryStore

    tz = os.environ.get("DIARY_TZ", "Europe/Berlin")
    ZoneInfo(tz)
    return DiaryService(
        SqliteDiaryStore(_DB),
        _build_provider(),
        profile if profile is not None else build_profile_service(),
        authorizer=build_home_authorizer(),
        tz=tz,
    )


def build_profile_service():
    """Build the profile service and migrate legacy profiles once. A bad DIARY_TZ fails here."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from .profile.service import ProfileService
    from .store.profile_sqlite import SqliteProfileStore

    tz = os.environ.get("DIARY_TZ", "Europe/Berlin")
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    store = SqliteProfileStore(_DB)
    store.migrate_legacy(today)
    return ProfileService(store, authorizer=build_home_authorizer(), tz=tz)
