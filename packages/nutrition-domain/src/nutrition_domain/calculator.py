"""Deterministic nutrient arithmetic over already-confirmed food facts.

Canonical implementation for Episteck Home. Dataset lookup and AI proposal are
intentionally OUTSIDE this module: callers provide source-labelled food facts and
confirmed amounts. No LLM, no dataset download, no persistence, no clinical target
judgement lives here. All arithmetic uses Decimal.

Migrated from EKvargas/episteck @ 2193382 (apps/episteck_home/.../nutrition/calculator.py)
and extended with meal/daily/compare/gap helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class FoodFact:
    """A source-labelled nutrient fact per 100g. `source` records provenance."""
    food_reference: str
    nutrients_per_100g: dict[str, Decimal]
    source: str


@dataclass(frozen=True)
class ConfirmedFoodAmount:
    """A confirmed (human-accepted) amount of a food fact, in grams."""
    fact: FoodFact
    grams: Decimal


def calculate_nutrients(items: Iterable[ConfirmedFoodAmount]) -> dict[str, Decimal]:
    """Sum nutrient totals from confirmed food amounts. No targets, no AI."""
    totals: dict[str, Decimal] = {}
    for item in items:
        if item.grams < 0:
            raise ValueError("Food amount cannot be negative")
        factor = item.grams / Decimal("100")
        for nutrient, value in item.fact.nutrients_per_100g.items():
            totals[nutrient] = totals.get(nutrient, Decimal("0")) + value * factor
    return totals


# --- meal / daily aggregation -------------------------------------------------

def calculate_meal_nutrients(items: Iterable[ConfirmedFoodAmount]) -> dict[str, Decimal]:
    """A meal is a set of confirmed food amounts. Alias of calculate_nutrients
    kept as a distinct name so callers express intent."""
    return calculate_nutrients(items)


def calculate_daily_intake(meals: Iterable[Iterable[ConfirmedFoodAmount]]) -> dict[str, Decimal]:
    """Sum several meals into a daily total, deterministically."""
    totals: dict[str, Decimal] = {}
    for meal in meals:
        for nutrient, value in calculate_meal_nutrients(meal).items():
            totals[nutrient] = totals.get(nutrient, Decimal("0")) + value
    return totals


# --- target comparison / gap --------------------------------------------------

@dataclass(frozen=True)
class NutrientComparison:
    nutrient: str
    target: Decimal
    consumed: Decimal

    @property
    def remaining(self) -> Decimal:
        """Positive = still to consume; negative = over target."""
        return self.target - self.consumed

    @property
    def percentage(self) -> Decimal:
        """Consumed as a percentage of target (0 target -> Decimal('0'))."""
        if self.target == 0:
            return Decimal("0")
        return (self.consumed / self.target) * Decimal("100")


def compare_to_targets(
    consumed: dict[str, Decimal], targets: dict[str, Decimal]
) -> dict[str, NutrientComparison]:
    """Per-nutrient comparison. Covers every nutrient present in either map."""
    result: dict[str, NutrientComparison] = {}
    for nutrient in set(consumed) | set(targets):
        result[nutrient] = NutrientComparison(
            nutrient=nutrient,
            target=targets.get(nutrient, Decimal("0")),
            consumed=consumed.get(nutrient, Decimal("0")),
        )
    return result


def calculate_daily_gap(
    consumed: dict[str, Decimal], targets: dict[str, Decimal]
) -> dict[str, Decimal]:
    """Remaining amount per targeted nutrient (target - consumed, clamped at >=0
    is NOT applied: a negative gap signals an exceedance and is meaningful)."""
    return {n: targets[n] - consumed.get(n, Decimal("0")) for n in targets}
