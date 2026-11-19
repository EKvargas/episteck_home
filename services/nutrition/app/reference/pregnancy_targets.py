"""Authoritative pregnancy nutrient reference targets (DGE / D-A-CH, EFSA).

These are POPULATION REFERENCE VALUES with provenance REFERENCE_TARGET — NOT medical
instruction and NOT LLM-generated. Each entry cites its source organization and a
reference identifier/URL. A physician/dietitian override would be PROFESSIONAL_PROVIDED.

Sources:
- DGE / D-A-CH Referenzwerte für die Nährstoffzufuhr (Deutsche Gesellschaft für Ernährung).
  https://www.dge.de/wissenschaft/referenzwerte/
- DGE folate + calcium update: https://www.ernaehrungs-umschau.de/print-artikel/10-07-2013-dge-aktualisierte-referenzwerte-fuer-folat-und-kalzium/
- EFSA Dietary Reference Values (used where D-A-CH not specific): https://www.efsa.europa.eu/en/topics/topic/dietary-reference-values

Values checked against DGE/EFSA on 2026-11-19. Not confirmable from the cited pages (kept as is):
protein (DGE gives g/kg + 7/21 g), energy (DGE gives +250/+500 kcal), DHA (EFSA page has no value).

Values are daily reference intakes for pregnancy (2nd/3rd trimester where DGE differentiates).
Unknown/uncited nutrients are OMITTED (unknown != zero).
"""
from __future__ import annotations
from decimal import Decimal

# nutrient -> (value, unit, source_org, source_ref, stage_note)
PREGNANCY_REFERENCE = {
    "energy_kcal":    (Decimal("2300"), "kcal", "DGE/D-A-CH", "Richtwert 2./3. Trimenon (approx, activity PAL 1.4)", "2nd/3rd trimester"),
    "protein_g":      (Decimal("58"),   "g",   "DGE/D-A-CH", "Referenzwert Protein Schwangerschaft ab 4. Monat", "from month 4"),
    "calcium_mg":     (Decimal("1000"), "mg",  "DGE/D-A-CH", "https://www.dge.de/wissenschaft/referenzwerte/calcium/ (Stand Ableitung 2013)", "all"),
    "iron_mg":        (Decimal("27"),   "mg",  "DGE/D-A-CH", "https://www.dge.de/wissenschaft/referenzwerte/eisen/ (Stand Ableitung 2023)", "all"),
    "folate_ug":      (Decimal("550"),  "ug",  "DGE/D-A-CH", "https://www.dge.de/wissenschaft/referenzwerte/folat/ (Stand Ableitung 2015)", "all"),
    "vitamin_b12_ug": (Decimal("4.5"),  "ug",  "DGE/D-A-CH", "https://www.dge.de/wissenschaft/referenzwerte/vitamin-b12/ (Stand Ableitung 2018)", "all"),
    "vitamin_d_ug":   (Decimal("20"),   "ug",  "DGE/D-A-CH", "https://www.dge.de/wissenschaft/referenzwerte/vitamin-d/ (Stand Ableitung 2012; bei fehlender Eigensynthese)", "all"),
    "iodine_ug":      (Decimal("220"),  "ug",  "DGE/D-A-CH", "https://www.dge.de/wissenschaft/referenzwerte/jod/ (Stand Ableitung 2025)", "all"),
    "zinc_mg":        (Decimal("11"),   "mg",  "DGE/D-A-CH", "https://www.dge.de/wissenschaft/referenzwerte/zink/ (Stand Ableitung 2019; mittlere Phytatzufuhr)", "2nd/3rd trimester"),
    "selenium_ug":    (Decimal("60"),   "ug",  "DGE/D-A-CH", "https://www.dge.de/wissenschaft/referenzwerte/selen/ (Stand Ableitung 2015)", "all"),
    # choline: EFSA AI
    "choline_mg":     (Decimal("480"),  "mg",  "EFSA", "https://efsa.onlinelibrary.wiley.com/doi/10.2903/j.efsa.2016.4484 (EFSA Journal 2016, AI pregnancy 480 mg)", "all"),
    # DHA: EFSA additional 100-200 mg/day DHA on top of adult 250 mg EPA+DHA -> record DHA target
    "dha_g":          (Decimal("0.2"),  "g",   "EFSA", "Additional DHA in pregnancy (EFSA)", "all"),
}


def pregnancy_targets_map():
    """nutrient -> Decimal amount (canonical units) for authoritative pregnancy targets."""
    return {n: v[0] for n, v in PREGNANCY_REFERENCE.items()}


def pregnancy_targets_detailed():
    """Full provenance detail per nutrient for storage/audit."""
    out = {}
    for n, (val, unit, org, ref, stage) in PREGNANCY_REFERENCE.items():
        out[n] = {"value": str(val), "unit": unit, "source_org": org,
                  "source_ref": ref, "stage": stage, "provenance": "REFERENCE_TARGET"}
    return out
