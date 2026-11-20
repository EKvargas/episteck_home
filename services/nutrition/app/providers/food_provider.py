"""Food/nutrient provider abstraction. Real datasets (BLS/USDA/Open Food Facts)
are NOT chosen here — they need a license/key decision. Stage E ships only a
synthetic provider. Swapping providers must not touch business logic.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


class FoodNotFound(KeyError):
    """The provider does not know this food id (a caller mistake, not an outage)."""


@dataclass(frozen=True)
class FoodSearchHit:
    food_id: str
    name: str


@dataclass(frozen=True)
class FoodRecord:
    food_id: str
    name: str
    nutrients_per_100g: dict[str, Decimal]
    source: str            # provider label -> becomes FoodFact.source (provenance)
    provider_version: str
    category: str | None = None
    serving_g: Decimal | None = None
    density_g_per_ml: Decimal | None = None


class FoodProvider(ABC):
    @abstractmethod
    def search_food(self, query: str) -> list[FoodSearchHit]: ...

    @abstractmethod
    def get_food(self, food_id: str) -> FoodRecord: ...

    @abstractmethod
    def get_nutrients(self, food_id: str, quantity: Decimal, unit: str) -> dict[str, Decimal]: ...
