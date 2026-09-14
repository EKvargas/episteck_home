"""Nutrient targets carry provenance. AI suggestions are excluded from authoritative targets."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from .provenance import TargetSource, is_authoritative


@dataclass(frozen=True)
class NutrientTarget:
    nutrient: str
    amount: Decimal
    source: TargetSource

    @property
    def authoritative(self) -> bool:
        return is_authoritative(self.source)


def authoritative_targets(targets: list[NutrientTarget]) -> dict[str, Decimal]:
    return {t.nutrient: t.amount for t in targets if t.authoritative}
