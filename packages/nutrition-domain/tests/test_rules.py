from dataclasses import replace
from datetime import date
from decimal import Decimal

from nutrition_domain.rules import FREE_SUGARS_LIMIT_V1, RULES, effective_limit, trimester


def test_rule_v1_values():
    r = FREE_SUGARS_LIMIT_V1
    assert (r.rule_id, r.version, r.valid_from) == ("free-sugars-daily-max", 1, date(2026, 11, 18))
    assert (r.metric, r.operator, r.period, r.value_g) == ("free_sugars_g", "max", "day", Decimal("50"))
    assert (r.basis, r.energy_basis_kcal, r.origin) == ("<10% of energy", 2000, "INSTITUTIONAL_REFERENCE")
    assert r.modes == frozenset({"GENERAL", "PREGNANCY"}) and len(r.sources) == 3
    assert r.adaptation == "10 % of a standard 2,000 kcal day"
    assert RULES == (FREE_SUGARS_LIMIT_V1,)
    assert [s.title for s in r.sources] == [
        "WHO Guideline: Sugars intake for adults and children (2015)",
        "DGE/DAG/DDG: Quantitative Empfehlung zur Zuckerzufuhr in Deutschland (2018)",
        "familienplanung.de (BIOEG): Zucker in der Schwangerschaft",
    ]
    assert all(s.url.startswith("https://") for s in r.sources)


def test_effective_limit_respects_dates_and_versions():
    v2 = replace(FREE_SUGARS_LIMIT_V1, version=2, valid_from=date(2027, 1, 1), value_g=Decimal("45"))
    assert effective_limit(date(2026, 11, 17), "PREGNANCY") is None
    assert effective_limit(date(2026, 12, 31), "PREGNANCY", [FREE_SUGARS_LIMIT_V1, v2]).version == 1
    assert effective_limit(date(2027, 1, 2), "GENERAL", [FREE_SUGARS_LIMIT_V1, v2]).version == 2


def test_effective_limit_unknown_mode_and_tie():
    assert effective_limit(date(2026, 12, 1), "OTHER") is None
    b = replace(FREE_SUGARS_LIMIT_V1, version=3, value_g=Decimal("40"))
    assert effective_limit(date(2026, 12, 1), "GENERAL", [b, FREE_SUGARS_LIMIT_V1]).version == 3


def test_trimester():
    due = date(2027, 5, 20)
    assert trimester(due, date(2026, 11, 18)) == 1   # 13+6
    assert trimester(due, date(2026, 11, 19)) == 2   # 14+0
    assert trimester(due, date(2027, 2, 24)) == 2    # 27+6
    assert trimester(due, date(2027, 2, 25)) == 3    # 28+0
    assert trimester(due, date(2026, 6, 1)) is None  # before pregnancy


def test_trimester_past_due_stays_3():
    assert trimester(date(2027, 5, 20), date(2027, 7, 1)) == 3
