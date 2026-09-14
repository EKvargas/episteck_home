"""Episteck Home — canonical Nutrition domain (pure Python, no Frappe/HTTP/LLM)."""
from .calculator import (
    FoodFact, ConfirmedFoodAmount, calculate_nutrients,
    calculate_meal_nutrients, calculate_daily_intake,
    compare_to_targets, calculate_daily_gap, NutrientComparison,
)
from .provenance import TargetSource, is_authoritative, AUTHORITATIVE_SOURCES
from .intake import IntakeKind, IntakeSource, IntakeStatus, IntakeProvenance, is_authoritative_actual
from .targets import NutrientTarget, authoritative_targets

__all__ = [
    "FoodFact", "ConfirmedFoodAmount", "calculate_nutrients",
    "calculate_meal_nutrients", "calculate_daily_intake",
    "compare_to_targets", "calculate_daily_gap", "NutrientComparison",
    "TargetSource", "is_authoritative", "AUTHORITATIVE_SOURCES",
    "IntakeKind", "IntakeSource", "IntakeStatus", "IntakeProvenance", "is_authoritative_actual",
    "NutrientTarget", "authoritative_targets",
]
