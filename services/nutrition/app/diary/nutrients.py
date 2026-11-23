"""Nutrient blocks for diary days and periods: JSON shaping around nutrition_domain.

Takes frozen diary items (as stored) and a day's target set; knows nothing about
authorization or storage.
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from nutrition_domain.nutrient_totals import (
    DAY_NUTRIENTS, ItemFacts, NutrientAverage, NutrientTotal, percent_of_target, total_nutrients,
)
from nutrition_domain.target_method import TargetSet


def item_facts(items: Sequence[dict]) -> list[ItemFacts]:
    """Grams and per-100 g nutrients from frozen items; an unmatched food has none."""
    out = []
    for i in items:
        facts = i["facts"]
        per100 = None if facts is None else {
            k: Decimal(v) for k, v in facts["nutrients_per_100g"].items()}
        out.append(ItemFacts(Decimal(i["grams"]), per100))
    return out


def day_totals(items: Sequence[dict]) -> dict[str, NutrientTotal]:
    return total_nutrients(item_facts(items))


def nutrient_blocks(totals: dict[str, NutrientTotal], targets: TargetSet | None) -> dict:
    blocks = {}
    for nutrient in DAY_NUTRIENTS:
        t = totals[nutrient]
        target = targets.targets.get(nutrient) if targets else None
        pct = percent_of_target(t.known, target)
        blocks[nutrient] = {
            "known": None if t.known is None else str(t.known),
            "items_total": t.items_total,
            "items_uncounted": t.items_uncounted,
            "status": t.status,
            "target": None if target is None else {
                "value": str(target.value), "display_value": target.display_value,
                "unit": target.unit, "kind": target.kind},
            "percent": None if pct is None else str(pct),
        }
    return blocks


def average_json(averages: dict[str, NutrientAverage]) -> dict:
    return {
        n: {
            "average_known": None if a.average_known is None else str(a.average_known),
            "average_percent": None if a.average_percent is None else str(a.average_percent),
            "days_used": a.days_used,
            "left_out": {"open": a.left_out_open, "no_entries": a.left_out_no_entries,
                         "partial": a.left_out_partial},
        }
        for n, a in averages.items()
    }
