"""COMPAT SHIM. The canonical Nutrition calculator now lives in the
`nutrition_domain` package (packages/nutrition-domain). This module re-exports it
so the dormant Frappe app keeps working without a second implementation.

Single source of truth: nutrition_domain.calculator
"""
from nutrition_domain.calculator import (  # noqa: F401
    FoodFact, ConfirmedFoodAmount, calculate_nutrients,
    calculate_meal_nutrients, calculate_daily_intake,
    compare_to_targets, calculate_daily_gap, NutrientComparison,
)
