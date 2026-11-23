from datetime import date
from decimal import Decimal as D

from nutrition_domain.day_summary import DayStatus
from nutrition_domain.nutrient_totals import (
    DAY_NUTRIENTS,
    DayRow,
    ItemFacts,
    NutrientTotal,
    average_free_sugars,
    average_period,
    percent_of_target,
    total_nutrients,
)
from nutrition_domain.target_method import Target, TargetSet

COMPLETE, OPEN, NO_ENTRIES = DayStatus.COMPLETE, DayStatus.OPEN, DayStatus.NO_ENTRIES

BREAD = ItemFacts(D("100"), {"energy_kcal": D("250"), "protein_g": D("9")})
EGG = ItemFacts(D("120"), {"energy_kcal": D("155"), "protein_g": D("13"), "fat_g": D("11")})
UNMATCHED = ItemFacts(D("150"), None)


def _target(nutrient, value):
    return Target(nutrient, D(value), value, "kcal", "goal", "org", "ref", "why")


def _row(day, status, energy=None, target=None, partial=False):
    if status == NO_ENTRIES:
        totals = total_nutrients([])
    else:
        item = ItemFacts(D("100"), {"energy_kcal": D(energy)}) if energy is not None else UNMATCHED
        items = [item, UNMATCHED] if partial else [item]
        totals = total_nutrients(items)
    targets = {"energy_kcal": _target("energy_kcal", target)} if target is not None else {}
    ts = TargetSet("episteck-targets-1", date.fromisoformat(day), targets, {})
    return DayRow(date.fromisoformat(day), status, totals, ts)


def test_known_sum_per_nutrient():
    t = total_nutrients([BREAD, EGG])
    assert set(t) == set(DAY_NUTRIENTS)
    assert t["energy_kcal"].known == D("436.0") and t["energy_kcal"].status == "KNOWN"
    assert t["fat_g"].known == D("13.2") and t["fat_g"].items_uncounted == 1 and t["fat_g"].status == "PARTIAL"


def test_unknown_is_never_zero():
    t = total_nutrients([UNMATCHED])
    assert t["energy_kcal"].known is None and t["energy_kcal"].items_uncounted == 1
    assert total_nutrients([])["energy_kcal"].known is None and total_nutrients([])["energy_kcal"].status == "NONE"


def test_unmatched_item_makes_the_day_partial_not_lower():
    t = total_nutrients([BREAD, UNMATCHED])
    assert t["energy_kcal"].known == D("250.0") and t["energy_kcal"].status == "PARTIAL"


def test_percent_of_target():
    assert percent_of_target(D("1640"), _target("energy_kcal", "2800")) == D("59")
    assert percent_of_target(None, _target("energy_kcal", "2800")) is None
    assert percent_of_target(D("10"), None) is None


def test_average_uses_only_complete_fully_known_days():
    rows = [_row("2026-11-20", COMPLETE, energy="2510", target="2800"),
            _row("2026-11-21", COMPLETE, energy="2240", target="2800"),
            _row("2026-11-22", OPEN, energy="1640", target="2800"),
            _row("2026-11-23", NO_ENTRIES),
            _row("2026-11-19", COMPLETE, energy="2000", target="2800", partial=True)]
    a = average_period(rows)["energy_kcal"]
    assert a.average_known == D("2375.0") and a.average_percent == D("85")
    assert (a.days_used, a.left_out_open, a.left_out_no_entries, a.left_out_partial) == (2, 1, 1, 1)


def test_average_percent_uses_each_days_own_target():
    rows = [_row("2026-11-20", COMPLETE, energy="2800", target="2800"),
            _row("2026-11-21", COMPLETE, energy="2800", target="3500")]
    assert average_period(rows)["energy_kcal"].average_percent == D("90")


def test_no_usable_days_gives_none():
    a = average_period([_row("2026-11-22", OPEN, energy="1640", target="2800")])["energy_kcal"]
    assert a.average_known is None and a.average_percent is None and a.days_used == 0


def test_complete_day_without_items_counts_as_no_entries():
    row = DayRow(date(2026, 11, 20), COMPLETE, total_nutrients([]), None)
    a = average_period([row])["energy_kcal"]
    assert a.left_out_no_entries == 1 and a.days_used == 0


def test_average_without_any_target_has_no_percent():
    a = average_period([_row("2026-11-20", COMPLETE, energy="2000")])["energy_kcal"]
    assert a.average_known == D("2000.0") and a.average_percent is None


def _sugar_row(day, status, known, items, uncounted, limit="50"):
    sugars = NutrientTotal("free_sugars_g", None if known is None else D(known), items, uncounted)
    return DayRow(date.fromisoformat(day), status, total_nutrients([]), None, sugars,
                  None if limit is None else D(limit))


def test_free_sugar_average_uses_complete_known_days_against_each_days_limit():
    rows = [_sugar_row("2026-11-20", COMPLETE, "25.0", 1, 0),
            _sugar_row("2026-11-21", COMPLETE, "40.0", 1, 0, limit="40"),
            _sugar_row("2026-11-22", COMPLETE, "10.0", 2, 1),
            _sugar_row("2026-11-23", OPEN, "5.0", 1, 0),
            _sugar_row("2026-11-24", NO_ENTRIES, None, 0, 0)]
    a = average_free_sugars(rows)
    assert a.nutrient == "free_sugars_g"
    assert a.average_known == D("32.5") and a.average_percent == D("75")  # (50 % + 100 %) / 2
    assert (a.days_used, a.left_out_open, a.left_out_no_entries, a.left_out_partial) == (2, 1, 1, 1)


def test_free_sugar_percent_without_a_limit_is_unknown():
    a = average_free_sugars([_sugar_row("2026-11-20", COMPLETE, "25.0", 1, 0, limit=None)])
    assert a.average_known == D("25.0") and a.average_percent is None


def test_total_status_property():
    assert NutrientTotal("x", None, 0, 0).status == "NONE"
