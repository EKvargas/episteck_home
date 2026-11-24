"""Decide how much of a food's sugar counts toward the daily free-sugar limit.

Episteck guidance, not an official classification (spec 6.9). Versioned so a
stored diary item records which table classified it. Pure Decimal arithmetic,
no rounding (rounding belongs to display).

  FREE      free sugars = total sugars (drinks, juices, sweets, cakes, jam, ...)
  NOT_FREE  free sugars = 0 (whole fruit, vegetables, plain milk, staples)
  UNKNOWN   not counted, unless the source states added sugars

Whatever the class, a food with at most 0.5 g of total sugars per 100 g has 0 g of free
sugars: free sugars are part of total sugars, and EU law already calls such a food
"sugars-free" (Regulation (EC) No 1924/2006, Annex).

episteck-fs-2 (2026-11-24) adds that rule, the USDA Survey (FNDDS) food groups (WWEIA food
categories 2021-2023, USDA ARS, November 2024) and SR Legacy "Cereal Grains and Pasta".
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from enum import Enum

FREE_SUGAR_MAP_VERSION = "episteck-fs-2"

# At or below this many grams of total sugars per 100 g a food has no free sugars.
NEGLIGIBLE_SUGARS_PER_100G = Decimal("0.5")


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
    "Cereal Grains and Pasta": _NOT_FREE,  # rice, pasta, flours, oats; cereals are separate
}

# --- USDA Survey (FNDDS): wweiaFoodCategory.wweiaFoodCategoryDescription ---
# Only groups that are sweet by definition, or plain staples. Groups that mix sweet and
# unsweet foods (coffee, tea, yogurt, cream cheese with whipped cream, cereals, bars,
# smoothies, vegetable juice) stay UNKNOWN.
_WWEIA_FREE = frozenset({
    "Cakes and pies", "Cookies and brownies", "Doughnuts, sweet rolls, pastries",
    "Candy containing chocolate", "Candy not containing chocolate",
    "Ice cream and frozen dairy desserts", "Pudding", "Gelatins, ices, sorbets",
    "Sugars and honey", "Jams, syrups, toppings",
    "Soft drinks", "Fruit drinks", "Sport and energy drinks",
    "Citrus juice", "Apple juice", "Other fruit juice",
    "Flavored milk, whole", "Flavored milk, reduced fat", "Flavored milk, lowfat",
    "Flavored milk, nonfat",
})
_WWEIA_NOT_FREE = frozenset({
    "Milk, whole", "Milk, reduced fat", "Milk, lowfat", "Milk, nonfat",
    "Cheese", "Cottage/ricotta cheese", "Rice", "Pasta, noodles, cooked grains",
})
# A staple whose name says it is sweetened or flavoured is not plain: it stays UNKNOWN.
_FNDDS_NEGATIVE = re.compile(
    r"unsweetened|no sugar added|no added sugar|sugar[- ]free|without sugar", re.IGNORECASE)
_FNDDS_SWEET_WORD = re.compile(
    r"sweet|sugar|syrup|honey|glaze|candied|caramel|chocolate|flavou?red|fruit|jam|jelly",
    re.IGNORECASE)

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
    r"saft|säfte|nektar(?!in)|gezuckert|gesüßt|sirup|konfitüre|marmelade|gelee|kandiert"
    r"|smoothie|limonade|\bcola|schoko|honig(?!melone)"
    r"|\bjuice|\bnectar|\bsugared\b|\bsweetened\b|\bsyrup\b|\bjam\b|\bcandied\b|\bchocolate",
    _I)
# Own juice / aspic is not a sweet marker (canned fish and meat fall back to the letter default).
_BLS_NOT_SWEET_PHRASE = re.compile(r"im eigenen saft|in gelee|in aspik", _I)
_BLS_FRUIT_PREP = re.compile(
    r"mit frucht|mit früchten|fruchtjoghurt|fruchtquark|with fruit", _I)
# An M product that is itself sweetened stays FREE even with a fruit preparation.
_BLS_M_SWEETENED = re.compile(r"gesüßt|schoko", _I)
# "Eis" as a word or compound ending (Vanilleeis), not Eisbein, Eier or Reis.
# "-kuchen" is a dessert except savoury or pancake kinds (Reibekuchen, Flammkuchen,
# Zwiebelkuchen, Kartoffel-Gemüse-Kuchen, Pfannkuchen, Eierkuchen).
# "creme" is a dessert except savoury creams and cream soups/sauces (checked below).
_BLS_DESSERT = re.compile(
    r"dessert|pudding|speiseeis|ice cream|torte|mousse|\b\w*(?<!r)eis\b"
    r"|(?<!reibe)(?<!flamm)(?<!zwiebel)(?<!kartoffel)(?<!gemüse)(?<!gemüse-)"
    r"(?<!pfann)(?<!eier)kuchen"
    r"|(?<!schinken)(?<!salat)(?<!dill)(?<!kräuter)(?<!krabben)(?<!avocado)(?<!frischkäse)creme",
    _I)
_BLS_SAVOURY_CREAM = re.compile(r"suppe|sauce|soße", _I)


def _classify_off(category: str | None) -> FreeSugarClass:
    if not category:
        return _UNKNOWN
    tags = {t.strip() for t in category.split(",")}
    if tags & _OFF_FREE:
        return _FREE
    if tags & _OFF_NOT_FREE:
        return _NOT_FREE
    return _UNKNOWN


def _is_dessert(name: str) -> bool:
    """Dessert words, but "creme" in a soup or sauce name does not count."""
    for m in _BLS_DESSERT.finditer(name):
        if m.group().lower() == "creme" and _BLS_SAVOURY_CREAM.search(name):
            continue
        return True
    return False


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
    if letter in ("X", "Y") and not negated and _is_dessert(name):
        return _FREE
    if not negated and _BLS_FREE_MARKER.search(_BLS_NOT_SWEET_PHRASE.sub(" ", name)):
        return _FREE
    return default


def _classify_wweia(category: str | None, name: str | None) -> FreeSugarClass:
    if category in _WWEIA_FREE:
        return _FREE
    if category in _WWEIA_NOT_FREE:
        plain = _FNDDS_NEGATIVE.sub(" ", name or "")
        return _UNKNOWN if _FNDDS_SWEET_WORD.search(plain) else _NOT_FREE
    return _UNKNOWN


def classify(source: str, category: str | None, name: str | None = None) -> FreeSugarClass:
    """Classify a food. `name` is used for BLS, whose code letter is coarse, and for
    USDA Survey (FNDDS) staples, whose name can say they are sweetened."""
    if source in ("OPEN_FOOD_FACTS", "SYNTHETIC"):
        return _classify_off(category)
    if source == "USDA_FDC:Survey (FNDDS)":
        return _classify_wweia(category, name)
    if source.split(":", 1)[0] == "USDA_FDC":
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
    total = nutrients_per_100g.get("sugars_total_g")
    if total is not None and total <= NEGLIGIBLE_SUGARS_PER_100G:
        return Decimal(0)
    key = "sugars_total_g" if cls is FreeSugarClass.FREE else "sugars_added_g"
    per_100g = nutrients_per_100g.get(key)
    if per_100g is None:
        return None
    return per_100g * grams / Decimal(100)
