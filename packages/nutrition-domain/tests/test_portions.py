from decimal import Decimal

import pytest

from nutrition_domain.portions import (
    PORTION_TABLE_VERSION, PRESETS_ML, Conversion, ConversionMethod, PortionError, to_grams,
)

D = Decimal


def test_presets_exact():
    assert PRESETS_ML == {"small_glass": D("150"), "glass": D("200"), "large_glass": D("300"),
                          "cup": D("250"), "can": D("330"), "tablespoon": D("15"), "teaspoon": D("5")}


def test_preset_uses_assumed_density():
    c = to_grams(D("1"), "small_glass", stated=False)
    assert (c.grams, c.method) == (D("150"), ConversionMethod.PRESET) and "1.0 g/ml" in c.detail
    assert c.table_version == PORTION_TABLE_VERSION


def test_two_glasses():
    assert to_grams(D("2"), "glass", stated=False).grams == D("400")


def test_source_density():
    c = to_grams(D("1"), "can", stated=False, density_g_per_ml=D("1.04"))
    assert c.grams == D("343.20")
    assert "1.04 g/ml" in c.detail and "food" in c.detail


def test_preset_ignores_stated():
    assert to_grams(D("1"), "glass", stated=True).method is ConversionMethod.PRESET


def test_stated_ml():
    assert to_grams(D("330"), "ml", stated=True).method is ConversionMethod.USER_STATED


def test_ml_uses_density():
    assert to_grams(D("100"), "ml", stated=True, density_g_per_ml=D("1.5")).grams == D("150.0")


def test_guessed_grams():
    assert to_grams(D("150"), "g", stated=False).method is ConversionMethod.AGENT_ESTIMATE


def test_source_serving():
    c = to_grams(D("2"), "serving", stated=False, serving_g=D("125"))
    assert (c.grams, c.method) == (D("250"), ConversionMethod.SOURCE_SERVING)


def test_serving_falls_back_to_estimate():
    c = to_grams(D("1"), "serving", stated=False, grams_estimate=D("90"))
    assert (c.grams, c.method) == (D("90"), ConversionMethod.AGENT_ESTIMATE)


def test_serving_needs_something():
    with pytest.raises(PortionError):
        to_grams(D("1"), "serving", stated=False)


def test_slices_need_estimate():
    c = to_grams(D("2"), "slice", stated=False, grams_estimate=D("60"))
    assert (c.grams, c.method) == (D("60"), ConversionMethod.AGENT_ESTIMATE)
    with pytest.raises(PortionError):
        to_grams(D("2"), "slice", stated=False)


@pytest.mark.parametrize("amount,unit", [(D("0"), "g"), (D("-1"), "ml"), (D("1"), "bucket")])
def test_rejects(amount, unit):
    with pytest.raises(PortionError):
        to_grams(amount, unit, stated=True)


@pytest.mark.parametrize("unit", ["piece", "serving"])
def test_rejects_non_positive_estimate(unit):
    with pytest.raises(PortionError):
        to_grams(D("1"), unit, stated=False, grams_estimate=D("0"))
