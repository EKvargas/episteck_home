from decimal import Decimal

from episteck_home.nutrition.calculator import ConfirmedFoodAmount, FoodFact, calculate_nutrients


def test_calculates_confirmed_foods_deterministically():
    yogurt = FoodFact("synthetic-yogurt", {"protein_g": Decimal("10")}, "SYNTHETIC")
    totals = calculate_nutrients([ConfirmedFoodAmount(yogurt, Decimal("150"))])
    assert totals == {"protein_g": Decimal("15.0")}


def test_rejects_negative_amount():
    food = FoodFact("synthetic-food", {}, "SYNTHETIC")
    try:
        calculate_nutrients([ConfirmedFoodAmount(food, Decimal("-1"))])
    except ValueError as error:
        assert str(error) == "Food amount cannot be negative"
    else:
        raise AssertionError("negative amount must be rejected")
