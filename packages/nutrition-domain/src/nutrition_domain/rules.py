"""Versioned limit rules and pregnancy trimester (spec 6.5-6.11).

Pure and deterministic. A rule is data: new limits are new versions, never edits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class RuleSource:
    title: str
    url: str


@dataclass(frozen=True)
class LimitRule:
    rule_id: str
    version: int
    valid_from: date
    metric: str
    operator: str
    period: str
    value_g: Decimal
    basis: str
    energy_basis_kcal: int
    origin: str
    sources: tuple[RuleSource, ...]
    adaptation: str
    modes: frozenset[str]


FREE_SUGARS_LIMIT_V1 = LimitRule(
    rule_id="free-sugars-daily-max",
    version=1,
    valid_from=date(2026, 11, 18),
    metric="free_sugars_g",
    operator="max",
    period="day",
    value_g=Decimal("50"),
    basis="<10% of energy",
    energy_basis_kcal=2000,
    origin="INSTITUTIONAL_REFERENCE",
    sources=(
        RuleSource(
            "WHO Guideline: Sugars intake for adults and children (2015)",
            "https://www.who.int/publications/i/item/9789241549028",
        ),
        RuleSource(
            "DGE/DAG/DDG: Quantitative Empfehlung zur Zuckerzufuhr in Deutschland (2018)",
            "https://www.dge.de/wissenschaft/stellungnahmen-und-positionspapiere/"
            "stellungnahmen/quantitative-empfehlung-zur-zuckerzufuhr-in-deutschland/",
        ),
        RuleSource(
            "familienplanung.de (BIOEG): Zucker in der Schwangerschaft",
            "https://www.familienplanung.de/schwangerschaft/die-schwangerschaft/"
            "gesundheit-und-ernaehrung/ernaehrung/zucker/",
        ),
    ),
    adaptation="10 % of a standard 2,000 kcal day",
    modes=frozenset({"GENERAL", "PREGNANCY"}),
)

RULES: tuple[LimitRule, ...] = (FREE_SUGARS_LIMIT_V1,)


def effective_limit(on: date, mode: str, rules: Sequence[LimitRule] = RULES) -> LimitRule | None:
    """Rule in force on `on` for `mode`: latest valid_from, then highest version."""
    candidates = [r for r in rules if r.valid_from <= on and mode in r.modes]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.valid_from, r.version))


def trimester(due: date, on: date) -> int | None:
    """Trimester (1-3) from the due date; None before conception. No upper cap."""
    gestational_days = 280 - (due - on).days
    if gestational_days < 0:
        return None
    if gestational_days < 98:
        return 1
    if gestational_days < 196:
        return 2
    return 3
