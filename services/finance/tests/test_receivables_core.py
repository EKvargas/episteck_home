"""Pure receivables core: FX arithmetic, allocation planning, text keys."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from app.receivables.allocation import OpenLine, plan_allocation
from app.receivables.fx import deviation, implied_rate, rate_text, split_largest_remainder
from app.receivables.model import AllocationMethod
from app.receivables.text import description_key, normalize_alias


def test_implied_rate_is_exact():
    assert implied_rate(27600, 30000) == Fraction(23, 25)
    assert rate_text(implied_rate(27600, 30000)) == "0.9200"


def test_implied_rate_rejects_non_positive():
    with pytest.raises(ValueError):
        implied_rate(0, 100)
    with pytest.raises(ValueError):
        implied_rate(100, -1)


def test_rate_text_half_even():
    assert rate_text(Fraction(5, 100000)) == "0.0000"
    assert rate_text(Fraction(15, 100000)) == "0.0002"


def test_split_largest_remainder_sums_exactly_and_is_deterministic():
    assert split_largest_remainder(27600, [12000, 8000, 4000, 6000]) == [11040, 7360, 3680, 5520]
    assert split_largest_remainder(100, [1, 1, 1]) == [34, 33, 33]
    assert sum(split_largest_remainder(1001, [3, 7, 11])) == 1001


def test_split_edge_cases():
    assert split_largest_remainder(0, [1, 2]) == [0, 0]
    for bad in ([], [0, 0], [1, -1]):
        with pytest.raises(ValueError):
            split_largest_remainder(10, bad)


def test_deviation_against_ecb():
    assert deviation(Fraction(23, 25), Decimal("1.0870")) < Fraction(3, 100)
    assert deviation(Fraction(23, 25), Decimal("1.2000")) > Fraction(8, 100)


def test_exact_subset_prefers_oldest_combination():
    lines = [OpenLine("a", 5000, 1), OpenLine("b", 3000, 2), OpenLine("c", 2000, 3), OpenLine("d", 5000, 4)]
    plan = plan_allocation(5000, lines)
    assert plan.method is AllocationMethod.AUTO_EXACT and plan.parts == (("a", 5000),)
    plan = plan_allocation(8000, lines)
    assert plan.parts == (("a", 5000), ("b", 3000))


def test_fifo_with_remainder_when_no_exact_subset():
    plan = plan_allocation(9500, [OpenLine("a", 5000, 1), OpenLine("b", 3000, 2)])
    assert plan.method is AllocationMethod.AUTO_FIFO
    assert plan.parts == (("a", 5000), ("b", 3000)) and plan.remainder_minor == 1500


def test_exact_search_only_over_oldest_limit_lines():
    lines = [OpenLine(f"l{i}", 100, i) for i in range(20)] + [OpenLine("late", 7, 99)]
    assert plan_allocation(7, lines).method is AllocationMethod.AUTO_FIFO


def test_allocation_edges():
    with pytest.raises(ValueError):
        plan_allocation(0, [])
    plan = plan_allocation(500, [])
    assert plan.method is AllocationMethod.AUTO_FIFO and plan.parts == () and plan.remainder_minor == 500


def test_alias_and_description_keys():
    assert normalize_alias("  Mamá ") == normalize_alias("MAMA") == "mama"
    assert description_key("Zelle payment from A B Conf# 7Q2X9 11/14") == "ZELLE PAYMENT FROM A B CONF#"
    assert description_key("ZELLE PAYMENT FROM A B CONF# ABCDEFGHI") == "ZELLE PAYMENT FROM A B CONF#"
    assert description_key("") == ""
    assert description_key("123 4/5 99") == ""
