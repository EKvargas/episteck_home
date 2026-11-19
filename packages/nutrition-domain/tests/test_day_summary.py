from datetime import date
from decimal import Decimal

from nutrition_domain.day_summary import DayStatus, SugarStatus, summarize_day
from nutrition_domain.rules import FREE_SUGARS_LIMIT_V1

D = date(2026, 11, 20)


def test_empty_day_is_never_zero():
    s = summarize_day(D, [], closed=True, limit=FREE_SUGARS_LIMIT_V1)
    assert (s.day_status, s.sugar_status, s.free_sugars_known_g) == (DayStatus.NO_ENTRIES, SugarStatus.NONE, None)
    assert s.limit is FREE_SUGARS_LIMIT_V1
    assert summarize_day(D, [], closed=False, limit=None).day_status == DayStatus.NO_ENTRIES


def test_partial_day():
    s = summarize_day(D, [Decimal("17"), Decimal("0"), None], closed=False, limit=None)
    assert (s.free_sugars_known_g, s.items_total, s.items_uncounted) == (Decimal("17"), 3, 1)
    assert (s.sugar_status, s.day_status) == (SugarStatus.PARTIAL, DayStatus.OPEN)


def test_complete_known_day():
    s = summarize_day(D, [Decimal("17"), Decimal("15")], closed=True, limit=None)
    assert (s.free_sugars_known_g, s.sugar_status, s.day_status) == (Decimal("32"), SugarStatus.KNOWN, DayStatus.COMPLETE)


def test_all_unknown_is_none_not_zero():
    for items in ([None], [None, None]):
        s = summarize_day(D, items, closed=False, limit=None)
        assert s.free_sugars_known_g is None
        assert s.sugar_status == SugarStatus.PARTIAL
        assert (s.items_total, s.items_uncounted) == (len(items), len(items))


def test_known_zero_is_known():
    s = summarize_day(D, [Decimal("0")], closed=False, limit=None)
    assert (s.free_sugars_known_g, s.sugar_status) == (Decimal("0"), SugarStatus.KNOWN)
