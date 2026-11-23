import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from nutrition_domain.profile import (
    ACTIVITY_LEVELS, CHANGEABLE_FIELDS, Goal, ProfileInputs, ProfileInvalid, Sex,
    age_on, apply_changes, inputs_from_doc, inputs_to_doc, parse_changes, validate_inputs,
)

D = Decimal
TODAY = date(2026, 11, 23)


def test_age_on_counts_birthdays():
    assert age_on(date(1986, 3, 10), TODAY) == 40
    assert age_on(date(1986, 11, 24), TODAY) == 39


def test_parse_accepts_decimal_comma():
    assert parse_changes({"weight_kg": "82,5"})["weight_kg"] == Decimal("82.5")


def test_parse_types_and_rejects_unknown_keys():
    c = parse_changes({"birth_date": "1986-03-10", "sex": "MALE", "activity_pal": 1.6,
                       "training_sessions_per_week": 3, "goal": "PERFORMANCE", "intolerances": None})
    assert c["birth_date"] == date(1986, 3, 10) and c["sex"] is Sex.MALE
    assert c["activity_pal"] == Decimal("1.6") and c["goal"] is Goal.PERFORMANCE
    assert c["intolerances"] is None
    with pytest.raises(ProfileInvalid) as e:
        parse_changes({"mode": "PREGNANCY"})
    assert e.value.field == "mode"


@pytest.mark.parametrize("key,value", [
    ("weight_kg", True), ("weight_kg", "abc"), ("weight_kg", "1,2,3"), ("weight_kg", "NaN"),
    ("weight_kg", float("inf")), ("weight_kg", "1e999999"), ("weight_kg", 10**4000),
    ("weight_kg", 1e300), ("weight_kg", Decimal("1e999999")), ("weight_kg", "1_0"),
    ("training_sessions_per_week", "1e999999"), ("training_sessions_per_week", 10**4000), ("training_sessions_per_week", True),
    ("training_sessions_per_week", 2.5), ("birth_date", "10.03.1986"), ("sex", "OTHER"),
    ("training_note", "x" * 121), ("preferences", "x" * 501), ("dislikes", 5),
])
def test_parse_rejects_bad_values(key, value):
    with pytest.raises(ProfileInvalid) as e:
        parse_changes({key: value})
    assert e.value.field == key


def test_parse_strips_text_and_empty_becomes_none():
    c = parse_changes({"preferences": "  pasta  ", "dislikes": "   "})
    assert c == {"preferences": "pasta", "dislikes": None}


def test_error_never_carries_value():
    with pytest.raises(ProfileInvalid) as e:
        parse_changes({"weight_kg": "secret-value"})
    assert "secret-value" not in str(e.value)


def test_apply_carries_over_and_clears():
    cur = ProfileInputs(height_cm=Decimal("180"), intolerances="lactosa")
    new = apply_changes(cur, {"weight_kg": Decimal("82"), "intolerances": None})
    assert new.height_cm == Decimal("180") and new.weight_kg == Decimal("82") and new.intolerances is None
    assert apply_changes(None, {"height_cm": D("170")}).height_cm == D("170")


def test_apply_rejects_unchangeable_field():
    with pytest.raises(ProfileInvalid) as e:
        apply_changes(None, {"mode": "PREGNANCY"})
    assert e.value.field == "mode"


def test_constants():
    assert ACTIVITY_LEVELS == (D("1.4"), D("1.6"), D("1.8"), D("2.0"))
    assert "mode" not in CHANGEABLE_FIELDS and len(CHANGEABLE_FIELDS) == 13


@pytest.mark.parametrize("field,value", [
    ("birth_date", date(2008, 1, 1)), ("birth_date", date(1920, 1, 1)),
    ("height_cm", Decimal("119")), ("height_cm", Decimal("231")),
    ("weight_kg", Decimal("29")), ("weight_kg", Decimal("251")),
    ("weight_measured_on", date(2026, 11, 24)), ("weight_measured_on", date(2026, 8, 24)),
    ("activity_pal", Decimal("1.5")), ("training_sessions_per_week", 15),
    ("training_sessions_per_week", -1), ("mode", "OTHER"),
])
def test_validation_ranges(field, value):
    with pytest.raises(ProfileInvalid) as e:
        validate_inputs(replace(ProfileInputs(), **{field: value}), TODAY)
    assert e.value.field == field


def test_boundaries_valid():
    validate_inputs(ProfileInputs(birth_date=date(2007, 11, 23), height_cm=D("120"), weight_kg=D("30"),
                                  activity_pal=D("2.0"), training_sessions_per_week=14), TODAY)


def test_measured_exactly_90_days_ago_is_valid():
    validate_inputs(ProfileInputs(weight_kg=Decimal("82"), weight_measured_on=date(2026, 8, 25)), TODAY)


@pytest.mark.parametrize("inputs,field", [
    (ProfileInputs(mode="PREGNANCY", goal=Goal.LOSE_FAT), "goal"),
    (ProfileInputs(mode="PREGNANCY", sex=Sex.MALE), "sex"),
    (ProfileInputs(pre_pregnancy_weight_kg=Decimal("58")), "pre_pregnancy_weight_kg"),
    (ProfileInputs(due_date=date(2027, 5, 15)), "due_date"),
    (ProfileInputs(mode="PREGNANCY", pre_pregnancy_weight_kg=Decimal("29")), "pre_pregnancy_weight_kg"),
])
def test_pregnancy_rules(inputs, field):
    with pytest.raises(ProfileInvalid) as e:
        validate_inputs(inputs, TODAY)
    assert e.value.field == field


def test_pregnancy_valid():
    validate_inputs(ProfileInputs(mode="PREGNANCY", sex=Sex.FEMALE, due_date=date(2027, 5, 15),
                                  pre_pregnancy_weight_kg=D("58")), TODAY)


def test_doc_round_trip():
    p = ProfileInputs(birth_date=date(1986, 3, 10), sex=Sex.MALE, weight_kg=Decimal("82.5"), goal=Goal.MAINTAIN)
    assert inputs_from_doc(json.loads(json.dumps(inputs_to_doc(p)))) == p


def test_doc_round_trip_full():
    p = ProfileInputs(birth_date=date(1990, 1, 2), sex=Sex.FEMALE, height_cm=D("165"), weight_kg=D("60"),
                      weight_measured_on=date(2026, 11, 1), activity_pal=D("1.6"),
                      training_sessions_per_week=2, training_note="yoga", pre_pregnancy_weight_kg=D("58"),
                      preferences="a", dislikes="b", intolerances="c", mode="PREGNANCY",
                      due_date=date(2027, 5, 15))
    assert inputs_from_doc(json.loads(json.dumps(inputs_to_doc(p)))) == p
    assert inputs_from_doc({}) == ProfileInputs()
