"""Authoritative pregnancy nutrient reference targets (DGE / D-A-CH, EFSA).

These are POPULATION REFERENCE VALUES with provenance REFERENCE_TARGET — NOT medical
instruction and NOT LLM-generated. Each entry cites its source organization and a
reference identifier/URL. A physician/dietitian override would be PROFESSIONAL_PROVIDED.

Sources:
- DGE / D-A-CH Referenzwerte für die Nährstoffzufuhr (Deutsche Gesellschaft für Ernährung).
  https://www.dge.de/wissenschaft/referenzwerte/
- DGE folate + calcium update: https://www.ernaehrungs-umschau.de/print-artikel/10-07-2013-dge-aktualisierte-referenzwerte-fuer-folat-und-kalzium/
- EFSA Dietary Reference Values (used where D-A-CH not specific): https://www.efsa.europa.eu/en/topics/topic/dietary-reference-values

Values moved to nutrition_domain.reference_values (checked 2026-11-23); energy and protein are calculated
by nutrition_domain.target_method and no longer listed here.

Values are daily reference intakes for pregnancy (2nd/3rd trimester where DGE differentiates).
Unknown/uncited nutrients are OMITTED (unknown != zero).
"""
from __future__ import annotations
from decimal import Decimal

from nutrition_domain.reference_values import PREGNANCY_REFERENCE  # noqa: F401  (re-export)

# The table now lives in the domain package; energy and protein are calculated there (target method v1).
# service.py still expects fixed rows for both until Task 8 removes this module, so they stay here.
_LEGACY_FIXED = {
    "energy_kcal": (Decimal("2300"), "kcal", "DGE/D-A-CH", "Richtwert 2./3. Trimenon (approx, activity PAL 1.4)", "2nd/3rd trimester"),
    "protein_g":   (Decimal("58"),   "g",   "DGE/D-A-CH", "Referenzwert Protein Schwangerschaft ab 4. Monat", "from month 4"),
}
_TABLE = {**_LEGACY_FIXED, **PREGNANCY_REFERENCE}


def pregnancy_targets_map():
    """nutrient -> Decimal amount (canonical units) for authoritative pregnancy targets."""
    return {n: v[0] for n, v in _TABLE.items()}


def pregnancy_targets_detailed():
    """Full provenance detail per nutrient for storage/audit."""
    out = {}
    for n, (val, unit, org, ref, stage) in _TABLE.items():
        out[n] = {"value": str(val), "unit": unit, "source_org": org,
                  "source_ref": ref, "stage": stage, "provenance": "REFERENCE_TARGET"}
    return out
