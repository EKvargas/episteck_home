"""Money is integer minor units + ISO currency. Never float, never silent rounding."""
from __future__ import annotations

import pytest

from app.money import UnknownCurrency, format_minor, parse_amount


def test_parses_a_decimal_string_to_minor_units():
    assert parse_amount("1234.50", "EUR") == 123450


def test_negative_amount_keeps_its_sign():
    assert parse_amount("-0.05", "USD") == -5


def test_integer_string_is_whole_units():
    assert parse_amount("7", "EUR") == 700


def test_zero_exponent_currency_has_no_minor_unit():
    assert parse_amount("1500", "JPY") == 1500


def test_locale_formatted_amount_is_rejected_not_guessed():
    with pytest.raises(ValueError):
        parse_amount("1,234.50", "EUR")


def test_unknown_currency_is_a_hard_error():
    with pytest.raises(UnknownCurrency):
        parse_amount("1.00", "XXZ")


def test_float_input_is_rejected():
    with pytest.raises(TypeError):
        parse_amount(12.5, "EUR")  # type: ignore[arg-type]


def test_more_decimals_than_the_exponent_is_rejected_not_rounded():
    with pytest.raises(ValueError):
        parse_amount("1.005", "EUR")


def test_trailing_zero_decimals_beyond_exponent_are_accepted():
    assert parse_amount("1.500", "EUR") == 150


def test_format_minor_round_trips():
    assert format_minor(123450, "EUR") == "1234.50"
    assert format_minor(-5, "USD") == "-0.05"
    assert format_minor(1500, "JPY") == "1500"
