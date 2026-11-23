# Nutrition profile · Plan 1: Nutrition backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give svc-nutrition versioned personal profiles, targets calculated from named sources (method v1), profile drafts confirmed by the person, nutrient totals for days and periods against each day's targets, and retire the pre-diary intake paths.

**Architecture:** Pure rules (profile inputs and validation, target method v1, nutrient totals, period averages, which version is in force on a day) go in `packages/nutrition-domain`. svc-nutrition gets a SQLite profile store (versions and drafts) in the existing database file, a `ProfileService` beside `DiaryService`, nutrient blocks in the day summary, a period summary, and new REST and MCP entry points. Every person-sensitive operation still makes exactly one Home request.

**Tech Stack:** Python 3.11, Decimal arithmetic, SQLite (stdlib), FastAPI, fastmcp 4.0.3 (pinned), pytest.

**Spec:** `docs/superpowers/specs/2026-11-23-nutrition-profile-onboarding-design.md` (sections 6.2–6.7, 6.11, 6.12, 7). This is plan 1 of 3. Plan 2 covers the shared nutrition skill for both agents, Ultron's evening check-in and the install scripts (spec 6.8, 6.9). Plan 3 covers the Hub's Perfil, Hoy and Días views and the profile contract change (spec 6.10). Ana's rollout stage B6 (spec 6.9, track 0) is an operator procedure in `docs/runbooks/nutrition-r1-rollout.md` and needs no code.

## Global Constraints

- Run every test from the repo root with `PYTHONPATH="packages/nutrition-domain/src;services/nutrition"` (Windows; `:` on Linux) and `python -m pytest -q -p no:cacheprovider <path>`, using `C:\AIProjects\episteck-delivery-workspace\.venvs\nutrition-r1\Scripts\python.exe`. Abbreviated below as `PT <path>`.
- All nutrient and body maths uses `Decimal`; wire numbers are converted with `Decimal(str(x))`. API output renders Decimals as strings.
- Missing is unknown, never zero. A nutrient no item can count is `null`, never `"0"`. A target whose inputs are missing is absent and listed under `missing`, never guessed.
- Each person-sensitive operation makes exactly **one** Home request: `check_access` for one action, `check_access_many` for several. Reads ask `VIEW`; `propose_profile`, `confirm_profile` and `set_mode` ask `UPDATE` + `VIEW`.
- No tool or route takes an actor; the delegation comes from transport only. `tests/test_boundaries.py` keeps passing.
- Diary and profile dates are local dates in `DIARY_TZ` (default `Europe/Berlin`). A profile version is valid from the local date it was confirmed.
- Profile drafts expire after **24 hours**, like diary drafts.
- Target method id `episteck-targets-1`. A published method is never edited; a change is a new method id.
- The free-sugar rule `free-sugars-daily-max` v1 (≤ 50 g/day) is unchanged and still chosen by `effective_limit()`.
- Validation ranges: age 19 to 100 on the day of confirmation; height 120 to 230 cm; weight and weight before pregnancy 30 to 250 kg; weight measured not in the future and at most 90 days ago; activity one of 1.4, 1.6, 1.8, 2.0; training 0 to 14 sessions a week.
- Period summaries cover at most **31 days**; the default is the last 7 days ending today.
- `GET /profile/{person_id}` keeps the keys `context`, `target_source` and a flat `targets` map (nutrient → numeric string), because the deployed Hub (`profile-contract.ts`) reads exactly those until plan 3 ships. A missing profile still answers `404 {"detail": "no profile"}`.
- Logs carry ids, versions and statuses only, never body values, food text or targets.
- No new service, container or dependency. Do not change the `fastmcp==4.0.3` pin.

## Review Focus

- **Ana's due date arrives before her profile.** Rollout B6 makes a MODE version with no body data; days logged between B6 and her onboarding get targets from her first onboarded version (Task 4 test `test_first_profile_version_reaches_back_over_mode_only_versions`).
- **A typo fixed the same day as onboarding** reaches back with it; one fixed the next day does not (Task 4 tests `test_same_day_correction_reaches_back` and `test_next_day_correction_starts_that_day`).
- **The bot sends "sí" twice at once** for one profile draft: exactly one new version exists afterwards (Task 4 test `test_concurrent_confirms_make_one_version`).
- **A Spanish decimal comma** ("82,5") from a voice note is read as 82.5, not rejected (Task 1 test `test_parse_accepts_decimal_comma`).
- **A period that crosses a weight change and the start of the third trimester:** each day is compared with its own targets, and averages are the mean of per-day percentages (Task 6 test `test_period_uses_each_days_targets_across_a_change`).

---

### Task 1: Profile inputs and validation

**Files:**
- Create: `packages/nutrition-domain/src/nutrition_domain/profile.py`
- Test: `packages/nutrition-domain/tests/test_profile.py`

**Interfaces:**
- Produces:
  - `class Sex(str, Enum)`: `MALE`, `FEMALE`. `class Goal(str, Enum)`: `MAINTAIN`, `LOSE_FAT`, `BUILD_MUSCLE`, `PERFORMANCE`.
  - `ACTIVITY_LEVELS: tuple[Decimal, ...] = (Decimal("1.4"), Decimal("1.6"), Decimal("1.8"), Decimal("2.0"))`
  - `CHANGEABLE_FIELDS: tuple[str, ...]` = `birth_date, sex, height_cm, weight_kg, weight_measured_on, activity_pal, training_sessions_per_week, training_note, goal, pre_pregnancy_weight_kg, preferences, dislikes, intolerances` (mode and due date change only through `set_nutrition_mode`).
  - `@dataclass(frozen=True) class ProfileInputs`: those fields, all `None` by default (`birth_date: date | None`, `sex: Sex | None`, `height_cm: Decimal | None`, `weight_kg: Decimal | None`, `weight_measured_on: date | None`, `activity_pal: Decimal | None`, `training_sessions_per_week: int | None`, `training_note: str | None`, `goal: Goal | None`, `pre_pregnancy_weight_kg: Decimal | None`, `preferences/dislikes/intolerances: str | None`), plus `mode: str = "GENERAL"` and `due_date: date | None = None`.
  - `class ProfileInvalid(ValueError)`: `__init__(self, field: str, message: str | None = None)`, attribute `field`. Carries the field name only, never the value.
  - `age_on(birth_date: date, on: date) -> int`
  - `parse_changes(raw: dict) -> dict[str, object]`: wire → typed values; unknown key → `ProfileInvalid(key)`; `None` is kept (it clears the field).
  - `apply_changes(current: ProfileInputs | None, changes: dict[str, object]) -> ProfileInputs`
  - `validate_inputs(inputs: ProfileInputs, today: date) -> None`
  - `inputs_to_doc(inputs: ProfileInputs) -> dict` and `inputs_from_doc(doc: dict) -> ProfileInputs`: JSON-safe round trip (Decimals as strings, dates ISO, enums by value).

- [ ] **Step 1: Write the failing tests**

```python
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
    with pytest.raises(ProfileInvalid) as e: parse_changes({"mode": "PREGNANCY"})
    assert e.value.field == "mode"

def test_apply_carries_over_and_clears():
    cur = ProfileInputs(height_cm=Decimal("180"), intolerances="lactosa")
    new = apply_changes(cur, {"weight_kg": Decimal("82"), "intolerances": None})
    assert new.height_cm == Decimal("180") and new.weight_kg == Decimal("82") and new.intolerances is None

@pytest.mark.parametrize("field,value", [
    ("birth_date", date(2008, 1, 1)), ("birth_date", date(1920, 1, 1)),
    ("height_cm", Decimal("119")), ("height_cm", Decimal("231")),
    ("weight_kg", Decimal("29")), ("weight_kg", Decimal("251")),
    ("weight_measured_on", date(2026, 11, 24)), ("weight_measured_on", date(2026, 8, 24)),
    ("activity_pal", Decimal("1.5")), ("training_sessions_per_week", 15),
])
def test_validation_ranges(field, value):
    with pytest.raises(ProfileInvalid) as e:
        validate_inputs(replace(ProfileInputs(), **{field: value}), TODAY)
    assert e.value.field == field

def test_measured_exactly_90_days_ago_is_valid():
    validate_inputs(ProfileInputs(weight_kg=Decimal("82"), weight_measured_on=date(2026, 8, 25)), TODAY)

@pytest.mark.parametrize("inputs,field", [
    (ProfileInputs(mode="PREGNANCY", goal=Goal.LOSE_FAT), "goal"),
    (ProfileInputs(mode="PREGNANCY", sex=Sex.MALE), "sex"),
    (ProfileInputs(pre_pregnancy_weight_kg=Decimal("58")), "pre_pregnancy_weight_kg"),
    (ProfileInputs(due_date=date(2027, 5, 15)), "due_date"),
])
def test_pregnancy_rules(inputs, field):
    with pytest.raises(ProfileInvalid) as e: validate_inputs(inputs, TODAY)
    assert e.value.field == field

def test_doc_round_trip():
    p = ProfileInputs(birth_date=date(1986, 3, 10), sex=Sex.MALE, weight_kg=Decimal("82.5"), goal=Goal.MAINTAIN)
    assert inputs_from_doc(json.loads(json.dumps(inputs_to_doc(p)))) == p
```

- [ ] **Step 2: Run** `PT packages/nutrition-domain/tests/test_profile.py`. Expected: FAIL (`ModuleNotFoundError: nutrition_domain.profile`).
- [ ] **Step 3: Implement `profile.py`.** Numeric text accepts one decimal comma or point; booleans and non-finite values are rejected. Text fields are stripped: `training_note` at most 120 characters, the three food fields at most 500, an empty string becomes `None`. `validate_inputs` checks the ranges in Global Constraints and these rules: `due_date` and `pre_pregnancy_weight_kg` only in `PREGNANCY`; in `PREGNANCY`, `goal` must be `None` and `sex` must be `None` or `FEMALE`; `mode` is `GENERAL` or `PREGNANCY`.
- [ ] **Step 4: Run** `PT packages/nutrition-domain/tests`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add packages/nutrition-domain && git commit -m "feat: add profile inputs and validation to nutrition domain"`

### Task 2: Target method v1

**Files:**
- Create: `packages/nutrition-domain/src/nutrition_domain/reference_values.py`, `packages/nutrition-domain/src/nutrition_domain/target_method.py`
- Modify: `services/nutrition/app/reference/pregnancy_targets.py` (re-export from the domain so `service.py` keeps working until Task 8 deletes it)
- Test: `packages/nutrition-domain/tests/test_target_method.py`

**Interfaces:**
- Consumes: Task 1 `ProfileInputs`, `Sex`, `Goal`, `age_on`; `rules.effective_limit`, `rules.trimester`.
- Produces:
  - `METHOD_V1 = "episteck-targets-1"`
  - `@dataclass(frozen=True) class Target`: `nutrient: str`, `value: Decimal` (unrounded, quantized to 0.1), `display_value: str` (energy to the nearest 50 kcal, grams to whole numbers, micronutrients as in the table), `unit: str`, `kind: str` (`"MIN"`, `"MAX"` or `"ABOUT"`), `source_org: str`, `source_ref: str`, `explanation: str` (one Spanish line for the app; exact copy is the builder's).
  - `@dataclass(frozen=True) class TargetSet`: `method: str`, `day: date`, `targets: dict[str, Target]`, `missing: dict[str, tuple[str, ...]]` (nutrient → field names).
  - `resting_energy_kcal(sex: Sex, weight_kg: Decimal, height_cm: Decimal, age: int) -> Decimal`
  - `total_pal(activity_pal: Decimal, sessions: int | None) -> Decimal`
  - `targets_for_day(inputs: ProfileInputs, day: date, method: str = METHOD_V1) -> TargetSet` (`ValueError` for an unknown method)
  - `reference_values.PREGNANCY_REFERENCE` (moved from the service, **without** its `energy_kcal` and `protein_g` entries, which are now calculated) and `reference_values.GENERAL_REFERENCE: dict[tuple[Sex, str], dict[str, tuple[Decimal, str, str, str]]]` keyed by sex and DGE band `"19-24"`, `"25-50"`, `"51-64"`, `"65+"`; values `(amount, unit, source_org, source_ref)`.

Method v1, from spec 6.3 (pinned values):

| Target | Rule | Needs |
| --- | --- | --- |
| `energy_kcal` GENERAL, kind ABOUT | Mifflin-St Jeor × `total_pal` × goal factor (MAINTAIN, PERFORMANCE or no goal 1.00; BUILD_MUSCLE 1.10; LOSE_FAT 0.85 with `max(…, resting)` as a guard) | birth_date, sex, height_cm, weight_kg, activity_pal |
| `energy_kcal` PREGNANCY | female formula with `pre_pregnancy_weight_kg`, × `total_pal`, no goal, + 0 / 250 / 500 kcal for trimester 1 / 2 / 3 on `day` (no supplement when `trimester()` is `None`) | birth_date, height_cm, pre_pregnancy_weight_kg, activity_pal, due_date |
| `protein_g` GENERAL, kind MIN | 1.6 g/kg when sessions ≥ 2 or goal is BUILD_MUSCLE, PERFORMANCE or LOSE_FAT (source ISSN 2017); otherwise 0.8 g/kg under 65 and 1.0 g/kg at 65+ (DGE) | weight_kg; birth_date only on the age-dependent branch |
| `protein_g` PREGNANCY | 0.8 / 0.9 / 1.0 g per kg of `pre_pregnancy_weight_kg` for trimester 1 / 2 / 3 (DGE; confirm, see Step 3) | pre_pregnancy_weight_kg, due_date |
| `fat_g`, kind ABOUT | energy × 0.30 ÷ 9 (DGE) | whatever energy needs |
| `fiber_g`, kind MIN | 30 g (DGE, adults) | nothing |
| `free_sugars_g`, kind MAX | `effective_limit(day, mode).value_g` with the rule's first source | nothing |
| micronutrients, kind MIN | GENERAL: `GENERAL_REFERENCE[(sex, band(age))]`; PREGNANCY: `PREGNANCY_REFERENCE` | GENERAL: sex, birth_date |

`total_pal` = `activity_pal` + 0 (no or 0 sessions), 0.1 (1–2), 0.2 (3–4), 0.3 (5+). The spec's cap of 2.4 cannot bind (the maximum is 2.3), so it is not implemented. In PREGNANCY the formula is the female one whatever `sex` holds (validation allows only `None` or `FEMALE`).

- [ ] **Step 1: Write the failing tests** (the worked examples from spec 6.3 and their pregnancy counterparts)

```python
ERICK = ProfileInputs(birth_date=date(1986, 3, 10), sex=Sex.MALE, height_cm=D("180"), weight_kg=D("82"),
                      activity_pal=D("1.6"), training_sessions_per_week=3, goal=Goal.PERFORMANCE)
ANA = ProfileInputs(mode="PREGNANCY", due_date=date(2027, 5, 15), birth_date=date(1992, 6, 1),
                    height_cm=D("165"), pre_pregnancy_weight_kg=D("58"), activity_pal=D("1.4"),
                    training_sessions_per_week=0)

def test_resting_energy_mifflin_st_jeor():
    assert resting_energy_kcal(Sex.MALE, D("82"), D("180"), 40) == D("1750")
    assert resting_energy_kcal(Sex.FEMALE, D("58"), D("165"), 34) == D("1280.25")

def test_worked_example_general():
    t = targets_for_day(ERICK, date(2026, 11, 23)).targets
    assert t["energy_kcal"].value == D("3150.0") and t["energy_kcal"].display_value == "3150"
    assert t["protein_g"].value == D("131.2") and t["protein_g"].display_value == "131"
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

def test_every_target_names_its_source():
    for s in (targets_for_day(ERICK, date(2026, 11, 23)), targets_for_day(ANA, date(2026, 11, 23))):
        assert all(t.source_org and t.source_ref and t.explanation for t in s.targets.values())

def test_unknown_method_is_refused():
    with pytest.raises(ValueError): targets_for_day(ERICK, date(2026, 11, 23), "episteck-targets-0")
```

- [ ] **Step 2: Run** `PT packages/nutrition-domain/tests/test_target_method.py`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement.** Move `PREGNANCY_REFERENCE` into `reference_values.py`, drop its `energy_kcal` and `protein_g` rows, and make `services/nutrition/app/reference/pregnancy_targets.py` import the table from there (its two helper functions stay until Task 8). Fill `GENERAL_REFERENCE` for calcium, iron, folate, vitamin B12, vitamin D, iodine, zinc and selenium. Starting values, to confirm against the DGE pages: calcium 1000 mg; iron men 11 mg, women 16 mg under 51 and 14 mg from 51; folate 300 µg; vitamin B12 4.0 µg; vitamin D 20 µg; zinc men 14 mg, women 8 mg (medium phytate); selenium men 70 µg, women 60 µg; iodine as the current DGE adult value (revised 2025). Do the same for the pregnancy protein g/kg values. Record the date checked in the module docstring, as `pregnancy_targets.py` does. Where a source differs from a starting value, the source wins; update that value in the tests above and say so in the commit message.
- [ ] **Step 4: Run** `PT packages/nutrition-domain/tests services/nutrition/tests/test_stage_f.py`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add packages/nutrition-domain services/nutrition/app/reference && git commit -m "feat: add target method v1 with sourced reference values"`

### Task 3: Nutrient totals and period averages

**Files:**
- Create: `packages/nutrition-domain/src/nutrition_domain/nutrient_totals.py`
- Test: `packages/nutrition-domain/tests/test_nutrient_totals.py`

**Interfaces:**
- Consumes: Task 2 `Target`, `TargetSet`; `day_summary.DayStatus`.
- Produces:
  - `DAY_NUTRIENTS = ("energy_kcal", "protein_g", "fat_g", "carb_g", "fiber_g", "calcium_mg", "iron_mg", "folate_ug", "vitamin_b12_ug", "vitamin_d_ug", "iodine_ug", "zinc_mg", "selenium_ug", "choline_mg", "dha_g")`
  - `@dataclass(frozen=True) class ItemFacts`: `grams: Decimal`, `nutrients_per_100g: Mapping[str, Decimal] | None` (`None` = no food match)
  - `@dataclass(frozen=True) class NutrientTotal`: `nutrient: str`, `known: Decimal | None` (0.1), `items_total: int`, `items_uncounted: int`; property `status -> str`: `"NONE"` with no items, `"PARTIAL"` when any are uncounted, else `"KNOWN"`
  - `total_nutrients(items: Sequence[ItemFacts]) -> dict[str, NutrientTotal]` (one entry per `DAY_NUTRIENTS`)
  - `percent_of_target(known: Decimal | None, target: Target | None) -> Decimal | None`: whole number, ROUND_HALF_UP
  - `@dataclass(frozen=True) class DayRow`: `day: date`, `day_status: DayStatus`, `totals: dict[str, NutrientTotal]`, `targets: TargetSet | None`
  - `@dataclass(frozen=True) class NutrientAverage`: `nutrient: str`, `average_known: Decimal | None`, `average_percent: Decimal | None`, `days_used: int`, `left_out_open: int`, `left_out_no_entries: int`, `left_out_partial: int`
  - `average_period(rows: Sequence[DayRow]) -> dict[str, NutrientAverage]`

- [ ] **Step 1: Write the failing tests**

```python
BREAD = ItemFacts(D("100"), {"energy_kcal": D("250"), "protein_g": D("9")})
EGG = ItemFacts(D("120"), {"energy_kcal": D("155"), "protein_g": D("13"), "fat_g": D("11")})
UNMATCHED = ItemFacts(D("150"), None)

def test_known_sum_per_nutrient():
    t = total_nutrients([BREAD, EGG])
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
```

(`_target` and `_row` are small builders in the test module.)

- [ ] **Step 2: Run** `PT packages/nutrition-domain/tests/test_nutrient_totals.py`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `nutrient_totals.py`. Item contribution is `grams × value ÷ 100`. An item counts for a nutrient only when its facts contain that nutrient. Averages are over rows that are COMPLETE and whose total for that nutrient has status KNOWN. `average_percent` is the mean of the per-day percentages on the rows that have a target for that nutrient, rounded to a whole number.
- [ ] **Step 4: Run** `PT packages/nutrition-domain/tests`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add packages/nutrition-domain && git commit -m "feat: add nutrient day totals and period averages"`

### Task 4: Profile versions: which one is in force, and the SQLite store

**Files:**
- Create: `packages/nutrition-domain/src/nutrition_domain/profile_versions.py`, `services/nutrition/app/store/profile_sqlite.py`
- Test: `packages/nutrition-domain/tests/test_profile_versions.py`, `services/nutrition/tests/test_profile_store.py`

**Interfaces:**
- Consumes: Task 1 `inputs_to_doc`.
- Produces:
  - `ORIGINS = ("PROFILE", "MODE", "MIGRATED")`. PROFILE = confirmed through `confirm_profile`; MODE = written by `set_nutrition_mode`; MIGRATED = from the legacy `profile` table.
  - `@dataclass(frozen=True) class VersionRef`: `version: int`, `valid_from: date`, `origin: str`
  - `version_in_force(versions: Sequence[VersionRef], day: date) -> int | None`
  - `class SqliteProfileStore(path: str)` with:
    - `list_versions(person_id) -> list[dict]`, ascending by version; each `{"version", "valid_from", "origin", "method", "doc", "created_at"}`
    - `latest(person_id) -> dict | None`
    - `append_version(person_id, doc: dict, valid_from: str, origin: str, method: str) -> dict`
    - `put_draft(person_id, doc: dict, expires_at: datetime) -> dict` (returns the doc plus `"id"`)
    - `get_draft(person_id, draft_id) -> dict | None` (adds `"expires_at"` and `"version"`, `None` until confirmed)
    - `confirm_draft(person_id, draft_id, build: Callable[[dict | None, dict], dict], valid_from: str, method: str) -> tuple[dict, bool]`: inside one `BEGIN IMMEDIATE` transaction it reads the latest version, calls `build(latest_doc, draft_doc)` to get the new version doc, appends it with origin PROFILE, and marks the draft. A draft already confirmed returns `(that version, False)`.
    - `migrate_legacy(today: str) -> int`
  - Tables, in the existing database file: `profile_version(person_id TEXT, version INTEGER, valid_from TEXT, origin TEXT, method TEXT, doc TEXT, created_at TEXT, PRIMARY KEY(person_id, version))` and `profile_draft(id TEXT PRIMARY KEY, person_id TEXT, doc TEXT, expires_at TEXT, version INTEGER)`. Connections and transactions as in `SqliteDiaryStore` (`isolation_level=None`, `BEGIN IMMEDIATE`).

`version_in_force` rules (spec 6.4):
1. If any PROFILE version exists, let F be the earliest `valid_from` among them. For a day before F, the answer is the highest-numbered PROFILE version with `valid_from == F` (the first onboarded day, last confirmation wins).
2. Otherwise, or for a day on or after F: the version with the latest `valid_from ≤ day`, highest number on a tie.
3. No such version: `None`.

- [ ] **Step 1: Write the failing tests**

```python
def V(n, d, origin): return VersionRef(n, date.fromisoformat(d), origin)

def test_first_profile_version_reaches_back_over_mode_only_versions():
    vs = [V(1, "2026-11-25", "MODE"), V(2, "2026-12-10", "PROFILE")]
    assert version_in_force(vs, date(2026, 11, 20)) == 2
    assert version_in_force(vs, date(2026, 12, 1)) == 2
    assert version_in_force(vs, date(2026, 12, 11)) == 2

def test_same_day_correction_reaches_back():
    vs = [V(1, "2026-11-23", "PROFILE"), V(2, "2026-11-23", "PROFILE")]
    assert version_in_force(vs, date(2026, 11, 21)) == 2

def test_next_day_correction_starts_that_day():
    vs = [V(1, "2026-11-23", "PROFILE"), V(2, "2026-11-24", "PROFILE")]
    assert version_in_force(vs, date(2026, 11, 21)) == 1
    assert version_in_force(vs, date(2026, 11, 23)) == 1
    assert version_in_force(vs, date(2026, 11, 24)) == 2

def test_mode_switch_after_onboarding_applies_from_its_day():
    vs = [V(1, "2026-11-23", "PROFILE"), V(2, "2027-06-01", "MODE")]
    assert version_in_force(vs, date(2027, 5, 31)) == 1 and version_in_force(vs, date(2027, 6, 1)) == 2

def test_migrated_never_reaches_back():
    vs = [V(1, "2026-11-30", "MIGRATED")]
    assert version_in_force(vs, date(2026, 11, 29)) is None and version_in_force(vs, date(2026, 11, 30)) == 1
```

```python
# services/nutrition/tests/test_profile_store.py
def test_append_numbers_versions_per_person(store): ...      # 1, 2 for one person; 1 for another
def test_draft_is_per_person(store):                         # get_draft under another person -> None
def test_concurrent_confirms_make_one_version(store):
    # two threads call confirm_draft for the same draft at once (as the diary store test does):
    # exactly one call returns created=True, both return the same version, list_versions has 1 row
def test_confirm_builds_on_the_latest_version(store):
    # a MODE version appended after the draft was made: build() receives it as latest_doc
def test_migrate_legacy_maps_rows_once(tmp_path):
    # legacy profile rows: {"context": "PREGNANCY", "due_date": "2027-05-15", "explicit_intolerances": "x"},
    # {"context": "G1_5_SYNTHETIC", "preferences": "p"} -> versions with origin MIGRATED, valid_from today,
    # inputs mode PREGNANCY / GENERAL, intolerances "x", preferences "p", no body fields, no targets copied.
    # A second migrate_legacy() returns 0 and adds nothing; a person who already has versions is skipped.
```

- [ ] **Step 2: Run** `PT packages/nutrition-domain/tests/test_profile_versions.py services/nutrition/tests/test_profile_store.py`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `profile_versions.py` and `profile_sqlite.py`. `migrate_legacy` reads the legacy `profile` table if it exists. In one transaction per person who has no versions, it appends a MIGRATED version whose doc is `{"inputs": inputs_to_doc(ProfileInputs(mode=..., due_date=..., preferences=..., dislikes=..., intolerances=...)), "changed": [], "targets_at_confirmation": []}`. Mode is PREGNANCY when the legacy `context` is PREGNANCY, otherwise GENERAL. Intolerances come from `intolerances`, else `explicit_intolerances`. A due date that does not parse is dropped. Legacy rows are never modified.
- [ ] **Step 4: Run** `PT packages/nutrition-domain/tests services/nutrition/tests`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add packages/nutrition-domain services/nutrition && git commit -m "feat: add versioned profile store with drafts and legacy migration"`

### Task 5: ProfileService

**Files:**
- Create: `services/nutrition/app/profile/__init__.py`, `services/nutrition/app/profile/service.py`
- Modify: `services/nutrition/app/deps.py` (`build_profile_service()`; calls `migrate_legacy(today)` once at build), `services/nutrition/tests/test_one_request_per_operation.py` (discover authorizing methods of `ProfileService` too and add a `PROFILE_OPERATIONS` inventory)
- Test: `services/nutrition/tests/test_profile_service.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4; `diary.service.DraftNotFound`, `DraftExpired`; `service._refuse_unless_allowed`, `AccessAuthorizer`.
- Produces `class ProfileService(store: SqliteProfileStore, *, authorizer: AccessAuthorizer, tz: str = "Europe/Berlin", clock: Callable[[], datetime] = _utc_now, draft_ttl: timedelta = timedelta(hours=24))`:
  - Public, one Home request each:
    - `get_profile_view(delegation, subject_person_id: str) -> dict | None` (`["VIEW"]`)
    - `propose_profile(delegation, subject_person_id: str, changes: dict) -> dict` (`["UPDATE", "VIEW"]`)
    - `confirm_profile(delegation, subject_person_id: str, draft_id: str) -> dict` (`["UPDATE", "VIEW"]`)
  - Internal, no authorization (callers have authorized):
    - `today() -> date`
    - `inputs_on(person: str, day: date) -> ProfileInputs | None`
    - `targets_on(person: str, day: date) -> TargetSet | None` (computed with the version's own `method`)
    - `version_on(person: str, day: date) -> int | None`
    - `has_onboarded(person: str) -> bool`
    - `record_mode(person: str, mode: str, due_date: date | None) -> dict` (appends a MODE version carrying everything else over; switching to PREGNANCY clears `goal`; switching to GENERAL clears `due_date`)
    - `view_of(person: str) -> dict | None`
- View shape, returned by `get_profile_view` and `view_of`:

```json
{"person_id": "PSN-00013", "version": 2, "valid_from": "2026-11-23", "origin": "PROFILE",
 "mode": "GENERAL", "due_date": null, "trimester": null,
 "inputs": {"birth_date": "1986-03-10", "age": 40, "sex": "MALE", "height_cm": "180", "weight_kg": "82",
            "weight_measured_on": "2026-11-23", "activity_pal": "1.6", "training_sessions_per_week": 3,
            "training_note": "...", "goal": "PERFORMANCE", "pre_pregnancy_weight_kg": null},
 "food": {"preferences": null, "dislikes": null, "intolerances": null},
 "targets": {"method": "episteck-targets-1", "on": "2026-11-23",
             "items": [{"nutrient": "energy_kcal", "value": "3150.0", "display_value": "3150", "unit": "kcal",
                        "kind": "ABOUT", "source_org": "...", "source_ref": "...", "explanation": "..."}],
             "missing": [{"nutrient": "...", "fields": ["..."]}]},
 "history": [{"version": 1, "valid_from": "2026-11-23", "origin": "PROFILE", "changed": ["birth_date", "..."]}],
 "context": "GENERAL", "target_source": "REFERENCE_TARGET", "targets_flat": {"energy_kcal": "3150.0"}}
```

The last three keys exist for the deployed Hub. Task 7 renders `targets_flat` as the wire key `targets` only on `GET /profile`. Inside this service it is named `targets_flat` so it cannot collide with the structured `targets`.

Behaviour:
- `propose_profile`: `changes` empty → `ProfileInvalid("changes")`. Parse; if `weight_kg` changes and `weight_measured_on` is not given, use today. Apply to the latest version's inputs (or empty `ProfileInputs()`), validate against today, compute `targets_for_day(new, today)`. Store a draft `{"changes": <wire changes as given>}`, so confirmation re-applies them to whatever is latest then. Return `{"draft_id", "expires_at", "profile": <view of the would-be profile, "version": null>, "changed": [...], "targets_before": <targets json or null>, "targets_after": <targets json>}`.
- Every version doc is `{"inputs": inputs_to_doc(...), "changed": [field names], "targets_at_confirmation": <targets json for valid_from>}` (spec 6.4: inputs, method and calculated targets kept for audit; reads always recompute with the version's `method`).
- `confirm_profile`: through `store.confirm_draft`, with a `build` that re-parses, re-applies and re-validates the draft's changes on the latest doc. Raise `DraftNotFound` for an unknown draft id or another person's draft, and `DraftExpired` after the time to live unless the draft was already confirmed. `valid_from` is today. Return `{"profile": view, "created": bool}`.

- [ ] **Step 1: Write the failing tests** (`Clock` and `AllowAllAuthorizer` as in `test_diary_service.py`; the clock starts at 2026-11-23 10:00 UTC)

```python
def test_onboarding_round_trip(env):
    svc, auth, *_ = env
    p = svc.propose_profile(SESSION, "PSN-E", ERICK_WIRE)      # the Task 2 ERICK inputs as wire values
    assert p["profile"]["version"] is None and _target(p["targets_after"], "energy_kcal")["display_value"] == "3150"
    assert svc.get_profile_view(SESSION, "PSN-E") is None       # a draft saves nothing
    c = svc.confirm_profile(SESSION, "PSN-E", p["draft_id"])
    assert c["created"] and c["profile"]["version"] == 1 and c["profile"]["valid_from"] == "2026-11-23"
    assert auth.requirements[-1] == (("NUTRITION", "UPDATE"), ("NUTRITION", "VIEW"))

def test_repeated_yes_is_idempotent(env): ...                 # second confirm: created False, same version, 1 version stored
def test_expired_draft(env): ...                              # clock + 25 h -> DraftExpired; nothing stored
def test_other_persons_draft_is_not_found(env): ...           # confirm under "PSN-A" -> DraftNotFound
def test_weight_change_dates_the_measurement_today(env): ...  # propose {"weight_kg": "80"} -> inputs.weight_measured_on == "2026-11-23"
def test_confirm_reapplies_changes_on_the_latest_version(env):
    # propose {"weight_kg": "80"}; then record_mode(person, "PREGNANCY", date(2027, 5, 15)) on a FEMALE profile;
    # confirm -> new version has mode PREGNANCY and weight 80 (the mode change is not undone)
def test_invalid_change_names_the_field(env): ...             # {"height_cm": "300"} -> ProfileInvalid.field == "height_cm"
def test_targets_on_follow_the_version_in_force(env): ...     # versions on 23 and 25 Nov: targets_on(22 Nov) from v1, (25 Nov) from v2
def test_view_keeps_the_keys_the_deployed_hub_reads(env):
    v = _onboard(env)
    assert v["context"] == "GENERAL" and v["target_source"] == "REFERENCE_TARGET"
    assert v["targets_flat"]["energy_kcal"] == "3150.0"
def test_denied_reads_and_writes_store_nothing(env): ...      # DenyAllAuthorizer -> AccessDenied, no draft, no version
```

Add to `test_one_request_per_operation.py`: `PROFILE_OPERATIONS = {"get_profile_view": (..., ["VIEW"]), "propose_profile": (..., ["UPDATE", "VIEW"]), "confirm_profile": (..., ["UPDATE", "VIEW"])}`, with the same three checks the diary inventory has: discovered set == inventory, one Home request with the planned actions, survives a replay-aware Home.

- [ ] **Step 2: Run** `PT services/nutrition/tests/test_profile_service.py services/nutrition/tests/test_one_request_per_operation.py`. Expected: FAIL (`ModuleNotFoundError: app.profile`).
- [ ] **Step 3: Implement** `ProfileService` and `build_profile_service()`. Authorization uses the same single-request helper pattern as `DiaryService._authorize`.
- [ ] **Step 4: Run** `PT services/nutrition/tests`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add services/nutrition && git commit -m "feat: add profile service with drafts and confirmation"`

### Task 6: Diary with versions, nutrients and periods

**Files:**
- Modify: `services/nutrition/app/diary/service.py`, `services/nutrition/app/deps.py` (`build_diary_service` passes the `ProfileService`), `services/nutrition/tests/test_diary_service.py` and `services/nutrition/tests/test_one_request_per_operation.py` (fixtures now build a `ProfileService`; `DIARY_OPERATIONS` gains `get_period_summary: ["VIEW"]`)
- Test: `services/nutrition/tests/test_diary_nutrients.py`

**Interfaces:**
- Consumes: Task 3 `total_nutrients`, `ItemFacts`, `DayRow`, `average_period`, `percent_of_target`, `DAY_NUTRIENTS`; Task 5 `ProfileService` internals.
- Produces:
  - `DiaryService(store, provider, profiles: ProfileService, *, authorizer, tz, clock, draft_ttl)`. The third argument is now the `ProfileService`.
  - Mode and due date for day D come from `profiles.inputs_on(person, D)` (no version: GENERAL, no due date). `confirm_intake` freezes the mode in force today.
  - `set_mode(...)`: unchanged validation and actions. It writes through `profiles.record_mode` and adds `"version"` to its result.
  - Day summaries (`get_day_summary`, `close_day`, and the `day` in every diary result) gain `"profile_version": int | None` and `"nutrients": {nutrient: block}` for `DAY_NUTRIENTS`. A block is `{"known": str | null, "items_total": int, "items_uncounted": int, "status": "NONE" | "KNOWN" | "PARTIAL", "target": {"value", "display_value", "unit", "kind"} | null, "percent": str | null}`. Existing keys are unchanged.
  - `get_period_summary(delegation, subject_person_id: str, start: str | None = None, end: str | None = None) -> dict` (`["VIEW"]`, one Home request for the whole period). It returns `{"start", "end", "has_profile": profiles.has_onboarded(person), "days": [{"date", "day_status", "mode", "trimester", "profile_version", "free_sugars_known_g", "items_uncounted", "nutrients"}], "averages": {nutrient: {"average_known", "average_percent", "days_used", "left_out": {"open", "no_entries", "partial"}}}}`. Defaults: `end` today, `start` = `end` − 6 days. `InvalidField("start"/"end")` for a bad format, `start > end`, more than 31 days, or `end` after today.

- [ ] **Step 1: Write the failing tests**

The fixture clock is 2026-11-23 10:00 UTC; `_log(svc, items, consumed_at)` proposes and confirms one entry.

```python
CHICKEN = {"label": "Pollo", "food_id": "syn-chicken-breast", "amount": 200, "unit": "g", "stated": True}
COLA = {"label": "Cola", "food_id": "syn-cola", "amount": 1, "unit": "small_glass"}   # synthetic cola has no energy value

def test_day_nutrients_from_frozen_facts(env):
    _log(svc, [CHICKEN], "2026-11-23T08:00")
    day = svc.get_day_summary(SESSION, P, "2026-11-23")
    assert day["nutrients"]["energy_kcal"]["known"] == "330.0" and day["nutrients"]["protein_g"]["known"] == "62.0"
    assert day["nutrients"]["energy_kcal"]["target"] is None and day["profile_version"] is None

def test_food_without_a_value_makes_the_nutrient_partial_never_zero(env):
    _log(svc, [CHICKEN, COLA], "2026-11-23T08:00")
    e = svc.get_day_summary(SESSION, P, "2026-11-23")["nutrients"]["energy_kcal"]
    assert (e["known"], e["status"], e["items_uncounted"]) == ("330.0", "PARTIAL", 1)
    _log(svc, [COLA], "2026-11-22T20:00")
    e = svc.get_day_summary(SESSION, P, "2026-11-22")["nutrients"]["energy_kcal"]
    assert e["known"] is None and e["items_uncounted"] == 1

def test_day_compares_with_targets_once_onboarded(env):
    _onboard(profiles, P)                                       # ERICK inputs, confirmed 2026-11-23
    e = svc.get_day_summary(SESSION, P, "2026-11-21")["nutrients"]["energy_kcal"]
    assert e["target"]["display_value"] == "3150"               # the first version reaches back
    assert e["percent"] is not None

def test_set_mode_creates_a_mode_version(env):
    r = svc.set_mode(SESSION, P, "PREGNANCY", "2027-05-15")
    assert r["version"] == 1 and profiles.inputs_on(P, date(2026, 11, 23)).mode == "PREGNANCY"

def test_period_defaults_to_the_last_seven_days(env):
    p = svc.get_period_summary(SESSION, P)
    assert (p["start"], p["end"]) == ("2026-11-17", "2026-11-23") and len(p["days"]) == 7

@pytest.mark.parametrize("start,end,field", [("2026-10-01", "2026-11-23", "start"), ("2026-11-23", "2026-11-22", "start"),
                                             ("2026-11-20", "2026-11-24", "end"), ("20261120", None, "start")])
def test_period_bounds(env, start, end, field): ...           # InvalidField(field)

def test_period_one_home_request(env): ...                     # auth.home_calls == 1 for a 31-day period

def test_period_uses_each_days_targets_across_a_change(env):
    # Move the clock to each day before acting on it. Onboard the Task 2 ANA inputs on 2027-02-18,
    # then confirm {"pre_pregnancy_weight_kg": "60"} on 2027-02-19.
    # On 2027-02-18, 19 and 20, log chicken grams that make energy equal to that day's
    # target_for_day energy, and close each day. Then read the period 2027-02-18..20 on 2027-02-21.
    # Expected energy targets: 18th 2042.4 (58 kg, trimester 2), 19th 2070.4 (60 kg, trimester 2),
    # 20th 2320.4 (60 kg, trimester 3). Each day's energy percent == "100";
    # averages["energy_kcal"]["average_percent"] == "100", days_used 3.

def test_period_without_profile_says_so(env):
    assert svc.get_period_summary(SESSION, P)["has_profile"] is False
```

- [ ] **Step 2: Run** `PT services/nutrition/tests/test_diary_nutrients.py`. Expected: FAIL (`KeyError: 'nutrients'` / missing method).
- [ ] **Step 3: Implement.** Factor `_day` into a core without `entries`, which the period summary reuses, plus the existing entries list for single days. Item facts come from each frozen item: `grams`, plus `facts["nutrients_per_100g"]` or `None` when `facts` is null. Update the existing diary test fixtures to build a `ProfileService` on the same database file.
- [ ] **Step 4: Run** `PT services/nutrition/tests packages/nutrition-domain/tests`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add services/nutrition && git commit -m "feat: add nutrient blocks and period summary to the diary"`

### Task 7: REST and MCP entry points

**Files:**
- Modify: `services/nutrition/app/main.py`, `services/nutrition/app/mcp/server.py`, `services/nutrition/tests/test_diary_api.py`, `services/nutrition/tests/test_one_request_per_operation.py`
- Test: `services/nutrition/tests/test_profile_api.py`

**Interfaces:**
- Consumes: Tasks 5 and 6.
- Produces:
  - REST: `GET /profile/{person_id}` → `profile.get_profile_view`, rendered with `targets` = the view's `targets_flat` and the structured targets under `"target_set"`; 404 `"no profile"` when `None`. `GET /diary/{person_id}/period?start=&end=` → `diary.get_period_summary`. The module-level `profile = build_profile_service()` sits beside `svc` and `diary`.
  - MCP tools: `get_nutrition_profile(subject_person_id)` and `get_pregnancy_profile(subject_person_id)` (both return the view, or `{"error": "no profile"}`); `propose_profile(subject_person_id: str, changes: dict)`; `confirm_profile(subject_person_id: str, draft_id: str)`; `get_period_summary(subject_person_id: str, start: str | None = None, end: str | None = None)`.
  - Error mapping in both `_diary_call`s, before the generic `ValueError` branch: `ProfileInvalid` → REST 400 `{"error": "INVALID_FIELD", "field": ...}`, MCP `{"error": "INVALID_FIELD", "field": ...}`. `DraftNotFound` and `DraftExpired` map as for intake drafts.
  - Tool descriptions (exact wording is the builder's) say: send only fields the person gave in this conversation; numbers may use a decimal comma; `activity_pal` is one of 1.4 / 1.6 / 1.8 / 2.0 and the chosen value must be shown to the person; show `targets_after` with sources and ask "¿Lo guardo? (sí / corrige)"; call `confirm_profile` only after a yes; mode and due date change only through `set_nutrition_mode`; never add up nutrients yourself, use `get_period_summary`.

- [ ] **Step 1: Write the failing tests**

```python
def test_get_profile_404_until_onboarded_then_view(api):
    _, _, client = api
    assert client.get(f"/profile/{P}", headers=H).json() == {"detail": "no profile"}
    _onboard_through_mcp(api)
    body = client.get(f"/profile/{P}", headers=H).json()
    assert body["context"] == "GENERAL" and body["targets"]["energy_kcal"] == "3150.0"   # the deployed Hub still parses
    assert body["target_set"]["method"] == "episteck-targets-1"

def test_period_route(api): ...                                # 200 with 7 days by default; 400 INVALID_ITEM field "start" for 40 days
def test_profile_invalid_maps_to_invalid_field(api): ...       # REST 400 {"error": "INVALID_FIELD", "field": "height_cm"}; MCP same dict
def test_mcp_propose_confirm_round_trip(api): ...              # propose -> draft_id; confirm -> created True; get_nutrition_profile -> version 1
```

Update `ALL_TOOLS` in `test_diary_api.py` with the three new tools (24 tools at this point). Add the new route and tools to the route and MCP inventories in `test_one_request_per_operation.py`.

- [ ] **Step 2: Run** `PT services/nutrition/tests/test_profile_api.py`. Expected: FAIL (404 for the period route / missing tools).
- [ ] **Step 3: Implement** the routes, tools and mappings.
- [ ] **Step 4: Run** `PT services/nutrition/tests`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add services/nutrition && git commit -m "feat: expose profile drafts and period summaries over REST and MCP"`

### Task 8: Retire the pre-diary intake paths

**Files:**
- Modify: `services/nutrition/app/service.py`, `services/nutrition/app/main.py`, `services/nutrition/app/mcp/server.py`, `services/nutrition/app/deps.py`
- Delete: `services/nutrition/app/reference/pregnancy_targets.py`
- Modify tests: `test_service.py`, `test_stage_f.py`, `test_authorization.py`, `test_single_call_authorization.py`, `test_policy_outcomes.py`, `test_transport_binding.py`, `test_boundaries.py`, `test_one_request_per_operation.py`, `test_diary_api.py`

**Interfaces:**
- Removed MCP tools: `record_planned_meal`, `record_actual_intake`, `ate_as_planned`, `get_daily_nutrition_gap`.
- Removed REST routes: `GET /daily/{person_id}/{date}`, `POST /intake/{person_id}/planned`, `POST /intake/{person_id}/actual`, `POST /intake/{person_id}/ate-as-planned`, `GET /gap-v2/{person_id}/{date}`, `PUT /profile/{person_id}`, `POST /profile/{person_id}/pregnancy`.
- `NutritionService` keeps only `evaluate_meal`, `propose_change`, `plan_menu`, `get_meal_plan` and their private helpers. Its constructor gains `targets_today: Callable[[str], dict[str, Decimal]]`, which `deps` wires to the person's targets in force today (empty when none). `plan_menu` compares against those.
- The legacy `profile` and `intake` tables and their rows stay in the database, unread except by `migrate_legacy`.
- Final MCP tool set, exactly 20: `get_nutrition_profile`, `evaluate_meal`, `propose_meal_change`, `search_recipes`, `get_meal_plan`, `search_foods`, `get_food_detail`, `get_pregnancy_profile`, `plan_menu`, `propose_intake`, `confirm_intake`, `correct_intake`, `void_intake`, `get_diary_entry`, `get_day_summary`, `close_day`, `set_nutrition_mode`, `propose_profile`, `confirm_profile`, `get_period_summary`.

- [ ] **Step 1: Change the tests first.** Set `ALL_TOOLS` to the 20 above with `len(tools) == 20`. Add `test_retired_routes_are_gone` (each removed route answers 404 or 405). Delete the tests whose subject was a removed operation. Where a test used a removed operation only as a vehicle for an authorization property (fail closed, one request, transport binding, no actor), move it to `ProfileService.get_profile_view` (VIEW), `propose_profile` (UPDATE + VIEW) or `NutritionService.plan_menu`, so each property is still tested at least once. Add `test_plan_menu_uses_todays_targets` (an onboarded person: `gap_vs_reference["energy_kcal"]` = 3150 minus the menu's energy).
- [ ] **Step 2: Run** `PT services/nutrition/tests`. Expected: FAIL (the tool count is 24; the retired routes still answer).
- [ ] **Step 3: Remove** the operations, routes and tools, and the `pregnancy_targets.py` module. Wire `targets_today`.
- [ ] **Step 4: Run** `PT services/nutrition/tests packages/nutrition-domain/tests`. Expected: all PASS, and `git grep -n "record_actual_intake\|get_daily_nutrition_gap\|gap-v2" -- services` prints nothing.
- [ ] **Step 5: Commit** `git add -A services/nutrition && git commit -m "refactor: retire pre-diary intake tools and routes"`

### Task 9: Roll out to Nuremberg

Owner-gated: every step that writes on the node runs only after the owner says go. It follows the helper block and stages in `docs/runbooks/nutrition-r1-rollout.md`, Nutrition component only. Plans 2 and 3 are not needed for this step. The deployed Hub keeps working because `GET /profile` keeps its old keys.

- [ ] **Step 1:** The owner merges this plan's branch to `main`; `SHA` = the merge commit. Check out `SHA` in a clean worktree and paste the runbook helper block.
- [ ] **Step 2 `[PREP]`:** `ARCHIVE svc-nutrition services/nutrition packages/nutrition-domain deploy/nutrition`, then `ROLL nutrition build $SHA`. Expected: an image id.
- [ ] **Step 3 `[CLAUDE VERIFY]`:** `ROLL nutrition baseline` and `ROLL nutrition preview $SHA`. Note the backup directory and `NRestarts`.
- [ ] **Step 4 `[OPERATOR]`:** `ROLL nutrition apply $SHA`, then `ROLL nutrition verify`. Expected: verify passes; `$SSH 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9930/profile/PSN-00013'` prints `401` (no delegation, fails closed).
- [ ] **Step 5 `[CLAUDE VERIFY]`:** run read-only queries against `/srv/episteck/services/nutrition/data/nutrition.sqlite` with `sqlite3 -readonly`. The `profile_version` rows should be MIGRATED rows for the legacy synthetic profiles only, and none for `PSN-00013` or `PSN-00014`. The `intake` row count should be unchanged (5 on 2026-11-23). In the Hub, the owner's Perfil shows "no profile" and Hoy renders as before.
- [ ] **Rollback:** `ROLL nutrition rollback <backup dir from Step 3>`. The new tables stay and are ignored by the old image.
