"""Canonical nutrient set for the pregnancy pilot + provider->canonical mappings.
Missing nutrient = UNKNOWN (absent from dict), never zero. Units are canonical.
"""
from __future__ import annotations

# canonical nutrient key -> canonical unit
CANONICAL_UNITS = {
    "energy_kcal": "kcal", "protein_g": "g", "carb_g": "g", "fat_g": "g", "fiber_g": "g",
    "calcium_mg": "mg", "iron_mg": "mg", "folate_ug": "ug", "vitamin_b12_ug": "ug",
    "vitamin_d_ug": "ug", "iodine_ug": "ug", "zinc_mg": "mg", "selenium_ug": "ug",
    "choline_mg": "mg", "dha_g": "g", "epa_g": "g",
}

# USDA FoodData Central nutrient number -> canonical key (+ expected USDA unit).
# USDA reports per 100 g with a unitName; we normalize unit where needed.
USDA_BY_NUMBER = {
    "208": ("energy_kcal", "KCAL"), "203": ("protein_g", "G"), "205": ("carb_g", "G"),
    "204": ("fat_g", "G"), "291": ("fiber_g", "G"), "301": ("calcium_mg", "MG"),
    "303": ("iron_mg", "MG"), "417": ("folate_ug", "UG"), "418": ("vitamin_b12_ug", "UG"),
    "328": ("vitamin_d_ug", "UG"),  # Vitamin D (D2 + D3) in ug
    "314": ("iodine_ug", "UG"), "309": ("zinc_mg", "MG"), "317": ("selenium_ug", "UG"),
    "421": ("choline_mg", "MG"),
    "621": ("dha_g", "G"), "629": ("epa_g", "G"),
}

# Open Food Facts nutriments key (per 100g) -> (canonical key, OFF unit)
OFF_KEYS = {
    "energy-kcal_100g": ("energy_kcal", "kcal"), "proteins_100g": ("protein_g", "g"),
    "carbohydrates_100g": ("carb_g", "g"), "fat_100g": ("fat_g", "g"),
    "fiber_100g": ("fiber_g", "g"), "calcium_100g": ("calcium_mg", "g"),   # OFF minerals often in g!
    "iron_100g": ("iron_mg", "g"), "vitamin-b12_100g": ("vitamin_b12_ug", "g"),
    "vitamin-d_100g": ("vitamin_d_ug", "g"), "zinc_100g": ("zinc_mg", "g"),
    "selenium_100g": ("selenium_ug", "g"), "iodine_100g": ("iodine_ug", "g"),
    "folates_100g": ("folate_ug", "g"),
}

# unit conversion to canonical (factor to multiply the raw value by)
_TO_CANON = {
    ("G","g"):1, ("g","g"):1, ("MG","mg"):1, ("mg","mg"):1, ("UG","ug"):1, ("ug","ug"):1,
    ("KCAL","kcal"):1, ("kcal","kcal"):1,
    ("g","mg"):1000, ("g","ug"):1_000_000, ("mg","ug"):1000,   # OFF g -> canonical mg/ug
    ("g","g_"):1,
}

def to_canonical(value, from_unit: str, canonical_unit: str):
    """Convert a raw provider value+unit to the canonical unit. Returns Decimal.
    Raises if conversion path unknown (fail loud rather than silently wrong)."""
    from decimal import Decimal
    key = (from_unit, canonical_unit)
    if from_unit == canonical_unit:
        return Decimal(str(value))
    if key in _TO_CANON:
        return Decimal(str(value)) * Decimal(str(_TO_CANON[key]))
    raise ValueError(f"no unit conversion {from_unit!r}->{canonical_unit!r}")
