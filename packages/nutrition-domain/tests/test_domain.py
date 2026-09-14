from decimal import Decimal
import pytest
from nutrition_domain import (
    FoodFact, ConfirmedFoodAmount, calculate_nutrients,
    calculate_meal_nutrients, calculate_daily_intake,
    compare_to_targets, calculate_daily_gap,
    TargetSource, is_authoritative, NutrientTarget, authoritative_targets,
    IntakeKind, IntakeProvenance, is_authoritative_actual,
)

def _yogurt():
    return FoodFact("synthetic-yogurt", {"protein_g": Decimal("10")}, "SYNTHETIC")

# C. deterministic Decimal + migrated behaviour
def test_calculates_confirmed_foods_deterministically():
    totals = calculate_nutrients([ConfirmedFoodAmount(_yogurt(), Decimal("150"))])
    assert totals == {"protein_g": Decimal("15.0")}

def test_rejects_negative_amount():
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate_nutrients([ConfirmedFoodAmount(_yogurt(), Decimal("-1"))])

# D. meal totals
def test_meal_totals_sum_multiple_foods():
    oats = FoodFact("oats", {"protein_g": Decimal("13"), "carb_g": Decimal("68")}, "SYNTHETIC")
    m = calculate_meal_nutrients([
        ConfirmedFoodAmount(_yogurt(), Decimal("200")),
        ConfirmedFoodAmount(oats, Decimal("50")),
    ])
    assert m["protein_g"] == Decimal("26.5")  # 20 + 6.5
    assert m["carb_g"] == Decimal("34.0")

# E. daily totals
def test_daily_intake_sums_meals():
    meal1 = [ConfirmedFoodAmount(_yogurt(), Decimal("100"))]
    meal2 = [ConfirmedFoodAmount(_yogurt(), Decimal("100"))]
    assert calculate_daily_intake([meal1, meal2]) == {"protein_g": Decimal("20.0")}

# F. target comparison
def test_compare_to_targets_gives_remaining_and_pct():
    cmp = compare_to_targets({"protein_g": Decimal("30")}, {"protein_g": Decimal("60")})
    c = cmp["protein_g"]
    assert c.target == Decimal("60") and c.consumed == Decimal("30")
    assert c.remaining == Decimal("30")
    assert c.percentage == Decimal("50")

def test_daily_gap():
    assert calculate_daily_gap({"iron_mg": Decimal("10")}, {"iron_mg": Decimal("27")}) == {"iron_mg": Decimal("17")}

# B. provenance
def test_ai_suggestion_not_authoritative():
    assert is_authoritative(TargetSource.REFERENCE_TARGET) is True
    assert is_authoritative(TargetSource.AI_SUGGESTION) is False

def test_authoritative_targets_excludes_ai():
    ts = [
        NutrientTarget("protein_g", Decimal("60"), TargetSource.PROFESSIONAL_PROVIDED),
        NutrientTarget("iron_mg", Decimal("27"), TargetSource.AI_SUGGESTION),
    ]
    assert authoritative_targets(ts) == {"protein_g": Decimal("60")}

# G. planned vs actual
def test_only_confirmed_actual_is_authoritative():
    assert is_authoritative_actual(IntakeKind.ACTUAL, IntakeProvenance.USER_CONFIRMED) is True
    assert is_authoritative_actual(IntakeKind.ACTUAL, IntakeProvenance.AI_PROPOSAL) is False
    assert is_authoritative_actual(IntakeKind.PLANNED, IntakeProvenance.USER_CONFIRMED) is False
