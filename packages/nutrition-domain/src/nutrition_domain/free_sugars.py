"""Decide how much of a food's sugar counts toward the daily free-sugar limit.

Episteck guidance, not an official classification (spec 6.9). Versioned so a
stored diary item records which table classified it. Pure Decimal arithmetic,
no rounding (rounding belongs to display).

  FREE      free sugars = total sugars (drinks, juices, sweets, cakes, jam, ...)
  NOT_FREE  free sugars = 0 (whole fruit, vegetables, plain milk, staples)
  UNKNOWN   not counted, unless the source states added sugars
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from enum import Enum

FREE_SUGAR_MAP_VERSION = "episteck-fs-1"


class FreeSugarClass(str, Enum):
    FREE = "FREE"
    NOT_FREE = "NOT_FREE"
    UNKNOWN = "UNKNOWN"


_FREE = FreeSugarClass.FREE
_NOT_FREE = FreeSugarClass.NOT_FREE
_UNKNOWN = FreeSugarClass.UNKNOWN

# --- Open Food Facts (also used for SYNTHETIC foods, which carry OFF tags) ---
# Tags match exactly after splitting the comma-joined string. FREE wins.
_OFF_FREE = frozenset({
    "en:sodas", "en:carbonated-drinks", "en:sweetened-beverages", "en:fruit-juices",
    "en:fruit-nectars", "en:nectars", "en:smoothies", "en:iced-teas", "en:sweetened-teas",
    "en:energy-drinks", "en:flavoured-milks", "en:chocolates", "en:chocolate-bars",
    "en:candies", "en:confectioneries", "en:sweet-snacks", "en:cakes", "en:pastries",
    "en:biscuits", "en:cookies", "en:desserts", "en:ice-creams", "en:ice-creams-and-sorbets",
    "en:jams", "en:honeys", "en:syrups", "en:sugars", "en:sweet-spreads",
    "en:fruits-in-syrup", "en:candied-fruits",
})
_OFF_NOT_FREE = frozenset({
    "en:fresh-fruits", "en:fruits", "en:fresh-vegetables", "en:vegetables", "en:milks",
    "en:plain-yogurts", "en:waters", "en:eggs", "en:meats", "en:fishes", "en:pastas",
    "en:rices", "en:legumes", "en:nuts",
})

# --- USDA FoodData Central: foodCategory.description ---
# Only categories that unambiguously fit a class. "Beverages", "Baked Products",
# "Fruits and Fruit Juices" etc. mix sweet and unsweet foods, so they stay UNKNOWN.
_USDA: dict[str, FreeSugarClass] = {
    "Sweets": _FREE,
    "Vegetables and Vegetable Products": _NOT_FREE,
    "Legumes and Legume Products": _NOT_FREE,
    "Nut and Seed Products": _NOT_FREE,
    "Fats and Oils": _NOT_FREE,
    "Finfish and Shellfish Products": _NOT_FREE,
    "Beef Products": _NOT_FREE,
    "Pork Products": _NOT_FREE,
    "Poultry Products": _NOT_FREE,
    "Lamb, Veal, and Game Products": _NOT_FREE,
}

# --- BLS 4.0: first letter of the code (meanings read from the data) ---
_BLS_LETTER: dict[str, FreeSugarClass] = {
    **dict.fromkeys("SDN", _FREE),  # sweets/honey/cocoa/ice, baked goods, soft drinks
    **dict.fromkeys("FGHKQTUVWBECM", _NOT_FREE),  # fruit, veg, legumes, potatoes, fats, fish,
    # meat, poultry, sausage, bread, pasta/eggs, cereals, milk
    **dict.fromkeys("RXYP", _UNKNOWN),  # sauces, prepared dishes, alcohol
}

_I = re.IGNORECASE
_BLS_NEGATIVE = re.compile(
    r"ungesüßt|ungezuckert|ohne zucker|unsweetened|no added sugar|without sugar", _I)
# German stems match inside compounds (Apfelsaft); English words need boundaries.
_BLS_FREE_MARKER = re.compile(
    r"saft|säfte|nektar|gezuckert|gesüßt|sirup|konfitüre|marmelade|gelee|kandiert"
    r"|smoothie|limonade|\bcola|schoko|honig(?!melone)"
    r"|\bjuice|\bnectar|\bsugared\b|\bsweetened\b|\bsyrup\b|\bjam\b|\bcandied\b|\bchocolate",
    _I)
_BLS_FRUIT_PREP = re.compile(
    r"mit frucht|mit früchten|fruchtjoghurt|fruchtquark|with fruit", _I)
# An M product that is itself sweetened stays FREE even with a fruit preparation.
_BLS_M_SWEETENED = re.compile(r"gesüßt|schoko", _I)
# "Eis" as a word or compound ending (Vanilleeis), not Eisbein, Eier or Reis.
_BLS_DESSERT = re.compile(
    r"dessert|pudding|speiseeis|ice cream|kuchen|torte|creme|mousse|\b\w*(?<!r)eis\b", _I)


def _classify_off(category: str | None) -> FreeSugarClass:
    if not category:
        return _UNKNOWN
    tags = {t.strip() for t in category.split(",")}
    if tags & _OFF_FREE:
        return _FREE
    if tags & _OFF_NOT_FREE:
        return _NOT_FREE
    return _UNKNOWN


def _classify_bls(letter: str | None, name: str | None) -> FreeSugarClass:
    letter = (letter or "").strip().upper()
    default = _BLS_LETTER.get(letter, _UNKNOWN)
    if not name:
        return default
    negated = bool(_BLS_NEGATIVE.search(name))
    if letter == "M" and _BLS_FRUIT_PREP.search(name) and (
        negated or not _BLS_M_SWEETENED.search(name)
    ):
        return _UNKNOWN
    if letter in ("X", "Y") and not negated and _BLS_DESSERT.search(name):
        return _FREE
    if not negated and _BLS_FREE_MARKER.search(name):
        return _FREE
    return default


def classify(source: str, category: str | None, name: str | None = None) -> FreeSugarClass:
    """Classify a food. `name` is used only for BLS, whose code letter is coarse."""
    if source in ("OPEN_FOOD_FACTS", "SYNTHETIC"):
        return _classify_off(category)
    if source == "USDA_FDC":
        return _USDA.get(category or "", _UNKNOWN)
    if source == "BLS":
        return _classify_bls(category, name)
    return _UNKNOWN


def item_free_sugars_g(
    cls: FreeSugarClass, nutrients_per_100g: Mapping[str, Decimal], grams: Decimal
) -> Decimal | None:
    """Free sugars in `grams` of food; None when unknown. Never 0 for unknown."""
    if cls is FreeSugarClass.NOT_FREE:
        return Decimal(0)
    key = "sugars_total_g" if cls is FreeSugarClass.FREE else "sugars_added_g"
    per_100g = nutrients_per_100g.get(key)
    if per_100g is None:
        return None
    return per_100g * grams / Decimal(100)
