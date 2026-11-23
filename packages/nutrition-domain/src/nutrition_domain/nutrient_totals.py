"""Nutrient totals for a diary day and averages over a period. Missing is unknown, never zero."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .day_summary import DayStatus
from .target_method import Target, TargetSet

DAY_NUTRIENTS = (
    "energy_kcal", "protein_g", "fat_g", "carb_g", "fiber_g", "calcium_mg", "iron_mg",
    "folate_ug", "vitamin_b12_ug", "vitamin_d_ug", "iodine_ug", "zinc_mg", "selenium_ug",
    "choline_mg", "dha_g",
)

_TENTH = Decimal("0.1")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class ItemFacts:
    grams: Decimal
    nutrients_per_100g: Mapping[str, Decimal] | None  # None = no food match


@dataclass(frozen=True)
class NutrientTotal:
    nutrient: str
    known: Decimal | None
    items_total: int
    items_uncounted: int

    @property
    def status(self) -> str:
        if self.items_total == 0:
            return "NONE"
        return "PARTIAL" if self.items_uncounted > 0 else "KNOWN"


@dataclass(frozen=True)
class DayRow:
    day: date
    day_status: DayStatus
    totals: dict[str, NutrientTotal]
    targets: TargetSet | None


@dataclass(frozen=True)
class NutrientAverage:
    nutrient: str
    average_known: Decimal | None
    average_percent: Decimal | None
    days_used: int
    left_out_open: int
    left_out_no_entries: int
    left_out_partial: int


def total_nutrients(items: Sequence[ItemFacts]) -> dict[str, NutrientTotal]:
    result: dict[str, NutrientTotal] = {}
    for nutrient in DAY_NUTRIENTS:
        total = Decimal(0)
        counted = 0
        for item in items:
            facts = item.nutrients_per_100g
            if facts is not None and nutrient in facts:
                total += item.grams * facts[nutrient] / _HUNDRED
                counted += 1
        known = total.quantize(_TENTH, rounding=ROUND_HALF_UP) if counted else None
        result[nutrient] = NutrientTotal(nutrient, known, len(items), len(items) - counted)
    return result


def percent_of_target(known: Decimal | None, target: Target | None) -> Decimal | None:
    if known is None or target is None or target.value == 0:
        return None
    return (known * _HUNDRED / target.value).quantize(_ONE, rounding=ROUND_HALF_UP)


def average_period(rows: Sequence[DayRow]) -> dict[str, NutrientAverage]:
    result: dict[str, NutrientAverage] = {}
    for nutrient in DAY_NUTRIENTS:
        knowns: list[Decimal] = []
        percents: list[Decimal] = []
        left_open = left_none = left_partial = 0
        for row in rows:
            total = row.totals[nutrient]
            if row.day_status == DayStatus.OPEN:
                left_open += 1
            elif row.day_status == DayStatus.NO_ENTRIES or total.status == "NONE":
                left_none += 1
            elif total.status == "PARTIAL":
                left_partial += 1
            else:
                knowns.append(total.known)  # type: ignore[arg-type]
                target = row.targets.targets.get(nutrient) if row.targets else None
                pct = percent_of_target(total.known, target)
                if pct is not None:
                    percents.append(pct)
        average_known = (
            (sum(knowns, Decimal(0)) / len(knowns)).quantize(_TENTH, rounding=ROUND_HALF_UP)
            if knowns else None
        )
        average_percent = (
            (sum(percents, Decimal(0)) / len(percents)).quantize(_ONE, rounding=ROUND_HALF_UP)
            if percents else None
        )
        result[nutrient] = NutrientAverage(
            nutrient, average_known, average_percent, len(knowns), left_open, left_none, left_partial
        )
    return result
