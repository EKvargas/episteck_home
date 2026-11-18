"""Turn a stated or guessed portion into grams, and record how it was converted.

Pure Decimal arithmetic, no rounding (rounding belongs to display).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

PORTION_TABLE_VERSION = "episteck-portions-1"

PRESETS_ML: dict[str, Decimal] = {
    "small_glass": Decimal("150"),
    "glass": Decimal("200"),
    "large_glass": Decimal("300"),
    "cup": Decimal("250"),
    "can": Decimal("330"),
    "tablespoon": Decimal("15"),
    "teaspoon": Decimal("5"),
}

_ASSUMED_DENSITY = Decimal("1.0")
_ESTIMATE_UNITS = frozenset({"piece", "slice", "plate", "portion"})


class ConversionMethod(str, Enum):
    USER_STATED = "USER_STATED"
    SOURCE_SERVING = "SOURCE_SERVING"
    PRESET = "PRESET"
    AGENT_ESTIMATE = "AGENT_ESTIMATE"


@dataclass(frozen=True)
class Conversion:
    grams: Decimal
    method: ConversionMethod
    detail: str
    table_version: str


class PortionError(ValueError):
    pass


def _density(density_g_per_ml: Decimal | None) -> tuple[Decimal, str]:
    if density_g_per_ml is not None:
        return density_g_per_ml, f"{density_g_per_ml} g/ml (food's own)"
    return _ASSUMED_DENSITY, "1.0 g/ml (assumed)"


def _estimate(amount: Decimal, unit: str, grams_estimate: Decimal | None) -> Conversion:
    if grams_estimate is None:
        raise PortionError(f"unit '{unit}' needs a gram estimate")
    if grams_estimate <= 0:
        raise PortionError("gram estimate must be greater than zero")
    return Conversion(grams_estimate, ConversionMethod.AGENT_ESTIMATE,
                      f"{amount} {unit} estimated at {grams_estimate} g in total",
                      PORTION_TABLE_VERSION)


def to_grams(amount: Decimal, unit: str, *, stated: bool,
             serving_g: Decimal | None = None,
             density_g_per_ml: Decimal | None = None,
             grams_estimate: Decimal | None = None) -> Conversion:
    """Convert `amount` of `unit` to grams. `grams_estimate` is the item total, not per unit."""
    if amount <= 0:
        raise PortionError("amount must be greater than zero")
    method = ConversionMethod.USER_STATED if stated else ConversionMethod.AGENT_ESTIMATE
    who = "stated" if stated else "estimated"

    if unit == "g":
        return Conversion(amount, method, f"{amount} g {who}", PORTION_TABLE_VERSION)
    if unit == "ml":
        density, text = _density(density_g_per_ml)
        return Conversion(amount * density, method,
                          f"{amount} ml {who} x {text}", PORTION_TABLE_VERSION)
    if unit in PRESETS_ML:
        ml = amount * PRESETS_ML[unit]
        density, text = _density(density_g_per_ml)
        return Conversion(ml * density, ConversionMethod.PRESET,
                          f"{amount} {unit} = {ml} ml x {text}", PORTION_TABLE_VERSION)
    if unit == "serving":
        if serving_g is not None:
            return Conversion(amount * serving_g, ConversionMethod.SOURCE_SERVING,
                              f"{amount} serving x {serving_g} g (source serving)",
                              PORTION_TABLE_VERSION)
        return _estimate(amount, unit, grams_estimate)
    if unit in _ESTIMATE_UNITS:
        return _estimate(amount, unit, grams_estimate)
    raise PortionError(f"unknown unit '{unit}'")
