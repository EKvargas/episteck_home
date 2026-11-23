"""Target method v1 (episteck-targets-1): daily targets from a person's profile inputs.

Pure and deterministic. A published method is never edited; a change is a new method id.
A target whose inputs are missing is absent and listed under `missing`, never guessed.

Protein for training, or a performance, fat-loss or muscle goal, follows the ISSN 2017
position stand (1.6 g/kg). Pregnancy protein uses the DGE g/kg values for the 2nd and 3rd
trimester (0.9 / 1.0 g/kg; DGE page "Protein", Stand 2017, checked 2026-11-23). The same page
also gives fixed additions of 7 / 21 g/day for those trimesters; method v1 uses the g/kg form.
The DGE energy supplements for pregnancy (+250 / +500 kcal) were not re-checked here (the
earlier pregnancy table of 2026-11-19 had them) and are kept as the brief pins them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .profile import Goal, ProfileInputs, Sex, age_on
from .reference_values import GENERAL_REFERENCE, PREGNANCY_REFERENCE
from .rules import effective_limit, trimester

METHOD_V1 = "episteck-targets-1"

_TENTH = Decimal("0.1")
_ONE = Decimal("1")
_FIFTY = Decimal("50")

_DGE = "DGE/D-A-CH"
_ISSN_ORG = "ISSN Position Stand: protein and exercise (2017)"
_ISSN_REF = "https://doi.org/10.1186/s12970-017-0177-8"
_PROTEIN_URL = "https://www.dge.de/wissenschaft/referenzwerte/protein/ (Stand Ableitung 2017)"
_FAT_URL = "https://www.dge.de/wissenschaft/referenzwerte/fett/"
_FIBER_URL = "https://www.dge.de/wissenschaft/referenzwerte/ballaststoffe/"
_ENERGY_URL = "https://www.dge.de/wissenschaft/referenzwerte/energie/"
_MSJ_ORG = "Mifflin-St Jeor (1990)"
_MSJ_REF = "Am J Clin Nutr 51(2):241-247"

_NAMES_ES = {
    "calcium_mg": "calcio", "iron_mg": "hierro", "folate_ug": "folato", "vitamin_b12_ug": "vitamina B12",
    "vitamin_d_ug": "vitamina D", "iodine_ug": "yodo", "zinc_mg": "zinc", "selenium_ug": "selenio",
    "choline_mg": "colina", "dha_g": "DHA",
}

_GOAL_FACTOR = {Goal.BUILD_MUSCLE: Decimal("1.10"), Goal.LOSE_FAT: Decimal("0.85")}
_PROTEIN_GOALS = (Goal.BUILD_MUSCLE, Goal.PERFORMANCE, Goal.LOSE_FAT)
_PREGNANCY_PROTEIN = {None: Decimal("0.8"), 1: Decimal("0.8"), 2: Decimal("0.9"), 3: Decimal("1.0")}
_PREGNANCY_ENERGY = {None: Decimal(0), 1: Decimal(0), 2: Decimal(250), 3: Decimal(500)}


@dataclass(frozen=True)
class Target:
    nutrient: str
    value: Decimal
    display_value: str
    unit: str
    kind: str
    source_org: str
    source_ref: str
    explanation: str


@dataclass(frozen=True)
class TargetSet:
    method: str
    day: date
    targets: dict[str, Target]
    missing: dict[str, tuple[str, ...]]


def _tenth(value: Decimal) -> Decimal:
    return value.quantize(_TENTH, rounding=ROUND_HALF_UP)


def _whole(value: Decimal) -> str:
    return str(value.quantize(_ONE, rounding=ROUND_HALF_UP))


def _es(value: Decimal | int) -> str:
    """A number for Spanish explanation text: decimal comma (values keep the point)."""
    return str(value).replace(".", ",")


def resting_energy_kcal(sex: Sex, weight_kg: Decimal, height_cm: Decimal, age: int) -> Decimal:
    base = Decimal(10) * weight_kg + Decimal("6.25") * height_cm - Decimal(5) * age
    return base + (Decimal(5) if sex is Sex.MALE else Decimal(-161))


def total_pal(activity_pal: Decimal, sessions: int | None) -> Decimal:
    if not sessions:
        extra = "0"
    elif sessions <= 2:
        extra = "0.1"
    elif sessions <= 4:
        extra = "0.2"
    else:
        extra = "0.3"
    return activity_pal + Decimal(extra)


def _band(age: int) -> str:
    if age < 25:
        return "19-24"
    if age < 51:
        return "25-50"
    if age < 65:
        return "51-64"
    return "65+"


def _absent(inputs: ProfileInputs, names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(n for n in names if getattr(inputs, n) is None)


def _micro(nutrient: str, amount: Decimal, unit: str, org: str, ref: str, context: str) -> Target:
    name = _NAMES_ES.get(nutrient, nutrient)
    shown_unit = "µg" if unit == "ug" else unit
    return Target(nutrient, _tenth(amount), str(amount), unit, "MIN", org, ref,
                  f"Valor de referencia de {name}: {_es(amount)} {shown_unit} al día {context}.")


def _energy_targets(inputs: ProfileInputs, day: date, tri: int | None, pregnancy: bool,
                    targets: dict[str, Target], missing: dict[str, tuple[str, ...]]) -> None:
    if pregnancy:
        need = _absent(inputs, ("birth_date", "height_cm", "pre_pregnancy_weight_kg", "activity_pal", "due_date"))
    else:
        need = _absent(inputs, ("birth_date", "sex", "height_cm", "weight_kg", "activity_pal"))
    if need:
        missing["energy_kcal"] = need
        missing["fat_g"] = need
        return
    age = age_on(inputs.birth_date, day)
    pal = total_pal(inputs.activity_pal, inputs.training_sessions_per_week)
    if pregnancy:
        resting = resting_energy_kcal(Sex.FEMALE, inputs.pre_pregnancy_weight_kg, inputs.height_cm, age)
        extra = _PREGNANCY_ENERGY[tri]
        energy = resting * pal + extra
        why = f"Gasto en reposo (Mifflin-St Jeor) por actividad, más {_es(extra)} kcal por el trimestre {tri}." if extra else \
            "Gasto en reposo (Mifflin-St Jeor) por actividad, sin suplemento de embarazo."
        org, ref = f"{_MSJ_ORG}; {_DGE}", f"{_MSJ_REF}; {_ENERGY_URL}"
    else:
        resting = resting_energy_kcal(inputs.sex, inputs.weight_kg, inputs.height_cm, age)
        energy = resting * pal
        factor = _GOAL_FACTOR.get(inputs.goal)
        if factor is not None:
            energy = max(energy * factor, resting)
        why = "Gasto en reposo (Mifflin-St Jeor) por nivel de actividad y entrenamiento" + (
            " y ajuste por tu objetivo." if factor is not None else ".")
        org, ref = _MSJ_ORG, _MSJ_REF
    nearest = (energy / _FIFTY).quantize(_ONE, rounding=ROUND_HALF_UP) * _FIFTY
    targets["energy_kcal"] = Target("energy_kcal", _tenth(energy), str(nearest), "kcal", "ABOUT", org, ref, why)
    fat = energy * Decimal("0.30") / Decimal(9)
    targets["fat_g"] = Target("fat_g", _tenth(fat), _whole(fat), "g", "ABOUT", _DGE, _FAT_URL,
                              "Alrededor del 30 % de la energía en forma de grasa.")


def _protein_target(inputs: ProfileInputs, day: date, tri: int | None, pregnancy: bool,
                    targets: dict[str, Target], missing: dict[str, tuple[str, ...]]) -> None:
    if pregnancy:
        need = _absent(inputs, ("pre_pregnancy_weight_kg", "due_date"))
        if need:
            missing["protein_g"] = need
            return
        per_kg = _PREGNANCY_PROTEIN[tri]
        org, ref = _DGE, _PROTEIN_URL
        why = f"{_es(per_kg)} g de proteína por kg de peso antes del embarazo."
        weight = inputs.pre_pregnancy_weight_kg
    else:
        sessions = inputs.training_sessions_per_week or 0
        sporty = sessions >= 2 or inputs.goal in _PROTEIN_GOALS
        need = _absent(inputs, ("weight_kg",) if sporty else ("birth_date", "weight_kg"))
        if need:
            missing["protein_g"] = need
            return
        weight = inputs.weight_kg
        if sporty:
            per_kg = Decimal("1.6")
            org, ref = _ISSN_ORG, _ISSN_REF
            why = "1,6 g de proteína por kg de peso por tu entrenamiento u objetivo."
        else:
            per_kg = Decimal("1.0") if age_on(inputs.birth_date, day) >= 65 else Decimal("0.8")
            org, ref = _DGE, _PROTEIN_URL
            why = f"{_es(per_kg)} g de proteína por kg de peso, valor de referencia para tu edad."
    protein = per_kg * weight
    targets["protein_g"] = Target("protein_g", _tenth(protein), _whole(protein), "g", "MIN", org, ref, why)


def targets_for_day(inputs: ProfileInputs, day: date, method: str = METHOD_V1) -> TargetSet:
    if method != METHOD_V1:
        raise ValueError(f"unknown target method: {method}")
    pregnancy = inputs.mode == "PREGNANCY"
    tri = trimester(inputs.due_date, day) if pregnancy and inputs.due_date else None
    targets: dict[str, Target] = {}
    missing: dict[str, tuple[str, ...]] = {}

    _energy_targets(inputs, day, tri, pregnancy, targets, missing)
    _protein_target(inputs, day, tri, pregnancy, targets, missing)

    targets["fiber_g"] = Target("fiber_g", Decimal("30"), "30", "g", "MIN", _DGE, _FIBER_URL,
                                "Al menos 30 g de fibra al día para adultos.")
    rule = effective_limit(day, inputs.mode)
    if rule is not None:
        first = rule.sources[0]
        targets["free_sugars_g"] = Target(
            "free_sugars_g", rule.value_g, str(rule.value_g), "g", "MAX", first.title, first.url,
            f"Máximo de {_es(rule.value_g)} g de azúcares libres al día (menos del 10 % de la energía).")

    if pregnancy:
        for nutrient, (amount, unit, org, ref, _stage) in PREGNANCY_REFERENCE.items():
            targets[nutrient] = _micro(nutrient, amount, unit, org, ref, "durante el embarazo")
    else:
        need = _absent(inputs, ("sex", "birth_date"))
        if need:
            for nutrient in GENERAL_REFERENCE[(Sex.MALE, "19-24")]:
                missing[nutrient] = need
        else:
            band = _band(age_on(inputs.birth_date, day))
            for nutrient, (amount, unit, org, ref) in GENERAL_REFERENCE[(inputs.sex, band)].items():
                targets[nutrient] = _micro(nutrient, amount, unit, org, ref, "para tu edad y sexo")
    return TargetSet(method, day, targets, missing)
