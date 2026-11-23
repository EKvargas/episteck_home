import re
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from nutrition_domain.profile import Goal, ProfileInputs, Sex
from nutrition_domain.reference_values import GENERAL_REFERENCE, PREGNANCY_REFERENCE
from nutrition_domain.target_method import (
    METHOD_V1,
    resting_energy_kcal,
    targets_for_day,
    total_pal,
)

ERICK = ProfileInputs(birth_date=date(1986, 3, 10), sex=Sex.MALE, height_cm=D("180"), weight_kg=D("82"),
                      activity_pal=D("1.6"), training_sessions_per_week=3, goal=Goal.PERFORMANCE)
ANA = ProfileInputs(mode="PREGNANCY", due_date=date(2027, 5, 15), birth_date=date(1992, 6, 1),
                    height_cm=D("165"), pre_pregnancy_weight_kg=D("58"), activity_pal=D("1.4"),
                    training_sessions_per_week=0)


def test_method_id():
    assert METHOD_V1 == "episteck-targets-1"


def test_resting_energy_mifflin_st_jeor():
    assert resting_energy_kcal(Sex.MALE, D("82"), D("180"), 40) == D("1750")
    assert resting_energy_kcal(Sex.FEMALE, D("58"), D("165"), 34) == D("1280.25")


def test_worked_example_general():
    t = targets_for_day(ERICK, date(2026, 11, 23)).targets
    assert t["energy_kcal"].value == D("3150.0") and t["energy_kcal"].display_value == "3150"
    assert t["energy_kcal"].kind == "ABOUT"
    assert t["protein_g"].value == D("131.2") and t["protein_g"].display_value == "131"
    assert t["protein_g"].kind == "MIN"
    assert t["fat_g"].value == D("105.0")
    assert t["fiber_g"].value == D("30") and t["fiber_g"].kind == "MIN"
    assert t["free_sugars_g"].value == D("50") and t["free_sugars_g"].kind == "MAX"


def test_pregnancy_second_trimester():
    t = targets_for_day(ANA, date(2026, 11, 23)).targets          # gestational day 107
    assert t["energy_kcal"].value == D("2042.4") and t["energy_kcal"].display_value == "2050"
    assert t["protein_g"].value == D("52.2")


def test_third_trimester_steps_up_by_itself():
    before = targets_for_day(ANA, date(2027, 2, 19)).targets       # day 195, trimester 2
    after = targets_for_day(ANA, date(2027, 2, 20)).targets        # day 196, trimester 3
    assert after["energy_kcal"].value - before["energy_kcal"].value == D("250.0")
    assert after["energy_kcal"].display_value == "2300" and after["protein_g"].value == D("58.0")


def test_pregnancy_has_no_fixed_energy_or_protein_rows():
    assert "energy_kcal" not in PREGNANCY_REFERENCE and "protein_g" not in PREGNANCY_REFERENCE


def test_pregnancy_ignores_sex_and_goal_and_uses_pre_pregnancy_weight():
    s = targets_for_day(replace(ANA, weight_kg=D("90"), sex=Sex.FEMALE), date(2026, 11, 23))
    assert s.targets["energy_kcal"].value == D("2042.4")


def test_before_conception_has_no_energy_supplement():
    t = targets_for_day(ANA, date(2026, 6, 1)).targets            # before day 0
    assert t["energy_kcal"].value == D("1792.4") and t["protein_g"].value == D("46.4")


@pytest.mark.parametrize("goal,factor", [(Goal.MAINTAIN, "1.00"), (None, "1.00"),
                                         (Goal.BUILD_MUSCLE, "1.10"), (Goal.LOSE_FAT, "0.85")])
def test_goal_factor(goal, factor):
    t = targets_for_day(replace(ERICK, goal=goal), date(2026, 11, 23)).targets
    assert t["energy_kcal"].value == (D("3150") * D(factor)).quantize(D("0.1"))


@pytest.mark.parametrize("sessions,pal", [(None, "1.6"), (0, "1.6"), (2, "1.7"), (4, "1.8"), (6, "1.9")])
def test_training_add_on(sessions, pal):
    assert total_pal(D("1.6"), sessions) == D(pal)


def test_protein_without_training_is_age_dependent():
    calm = replace(ERICK, training_sessions_per_week=0, goal=Goal.MAINTAIN)
    assert targets_for_day(calm, date(2026, 11, 23)).targets["protein_g"].value == D("65.6")
    older = replace(calm, birth_date=date(1960, 1, 1))
    assert targets_for_day(older, date(2026, 11, 23)).targets["protein_g"].value == D("82.0")


def test_missing_inputs_leave_targets_out_and_name_the_fields():
    s = targets_for_day(ProfileInputs(weight_kg=D("82")), date(2026, 11, 23))
    assert "energy_kcal" not in s.targets and "fat_g" not in s.targets
    assert set(s.missing["energy_kcal"]) == {"birth_date", "sex", "height_cm", "activity_pal"}
    assert "fiber_g" in s.targets and "free_sugars_g" in s.targets
    assert s.missing["protein_g"] == ("birth_date",)


def test_general_micronutrients_by_sex_and_band():
    t = targets_for_day(ERICK, date(2026, 11, 23)).targets
    assert t["calcium_mg"].value == D("1000") and t["iron_mg"].value == D("11")
    f = targets_for_day(replace(ERICK, sex=Sex.FEMALE), date(2026, 11, 23)).targets
    assert f["iron_mg"].value == D("16") and f["selenium_ug"].value == D("60")


def test_general_reference_covers_every_band_and_nutrient():
    nutrients = {"calcium_mg", "iron_mg", "folate_ug", "vitamin_b12_ug", "vitamin_d_ug",
                 "iodine_ug", "zinc_mg", "selenium_ug"}
    for sex in Sex:
        for band in ("19-24", "25-50", "51-64", "65+"):
            assert set(GENERAL_REFERENCE[(sex, band)]) == nutrients


def test_every_target_names_its_source():
    for s in (targets_for_day(ERICK, date(2026, 11, 23)), targets_for_day(ANA, date(2026, 11, 23))):
        assert all(t.source_org and t.source_ref and t.explanation for t in s.targets.values())


def test_spanish_explanations_use_a_decimal_comma():
    calm = replace(ERICK, training_sessions_per_week=0, goal=Goal.MAINTAIN)
    sets = [targets_for_day(ERICK, date(2026, 11, 23)), targets_for_day(calm, date(2026, 11, 23)),
            targets_for_day(ANA, date(2026, 6, 1)), targets_for_day(ANA, date(2026, 11, 23)),
            targets_for_day(ANA, date(2027, 2, 20))]
    for s in sets:
        for t in s.targets.values():
            assert not re.search(r"\d\.\d", t.explanation), (t.nutrient, t.explanation)
    t = sets[0].targets
    assert "4,0 µg" in t["vitamin_b12_ug"].explanation and t["vitamin_b12_ug"].display_value == "4.0"
    assert "0,8 g" in sets[1].targets["protein_g"].explanation
    assert "0,9 g" in sets[3].targets["protein_g"].explanation
    assert "4,5 µg" in sets[3].targets["vitamin_b12_ug"].explanation
    assert sets[3].targets["vitamin_b12_ug"].value == D("4.5")


def test_unknown_method_is_refused():
    with pytest.raises(ValueError):
        targets_for_day(ERICK, date(2026, 11, 23), "episteck-targets-0")
