"""Fixed daily reference intakes (DGE / D-A-CH, EFSA) for adults and pregnancy.

These are POPULATION REFERENCE VALUES with provenance REFERENCE_TARGET, not medical
instruction. Energy and protein are not listed here: Target method v1 calculates them.
Unknown or uncited nutrients are omitted (unknown is not zero).

Sources: DGE Referenzwerte, https://www.dge.de/wissenschaft/referenzwerte/ and the per-nutrient
pages cited in each entry; EFSA Dietary Reference Values for choline and DHA.

Checked against the DGE pages on 2026-11-23 (the "Stand Ableitung" year is in each ref):
- Confirmed as stated: calcium 1000 mg, folate 300 ug, vitamin B12 4.0 ug, vitamin D 20 ug
  (only when there is no endogenous synthesis), selenium men 70 ug / women 60 ug,
  iron men 11 mg / women 16 mg (premenopausal; 14 mg after menopause, applied here from age 51),
  zinc men 14 mg / women 8 mg at medium phytate intake.
- Iodine: the DGE page (Stand 2025) gives 150 ug for every adult band and both sexes
  (pregnancy 220 ug).
- Pregnancy values (iron 27, folate 550, B12 4.5, iodine 220, zinc 11, selenium 60, calcium 1000,
  vitamin D 20) confirmed against the same pages. Choline and DHA (EFSA) are kept from the
  earlier check of 2026-11-19 and were not re-fetched.
"""

from __future__ import annotations

from decimal import Decimal

from .profile import Sex

# nutrient -> (value, unit, source_org, source_ref, stage_note)
PREGNANCY_REFERENCE = {
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

_DGE = "DGE/D-A-CH"
_URL = "https://www.dge.de/wissenschaft/referenzwerte/"
_BANDS = ("19-24", "25-50", "51-64", "65+")


def _row(amount: str, unit: str, page: str, stand: str, note: str = "") -> tuple[Decimal, str, str, str]:
    return (Decimal(amount), unit, _DGE, f"{_URL}{page}/ (Stand Ableitung {stand}{note})")


def _build() -> dict[tuple[Sex, str], dict[str, tuple[Decimal, str, str, str]]]:
    table: dict[tuple[Sex, str], dict[str, tuple[Decimal, str, str, str]]] = {}
    for sex in Sex:
        male = sex is Sex.MALE
        for band in _BANDS:
            premenopausal = band in ("19-24", "25-50")
            iron = "11" if male else ("16" if premenopausal else "14")
            table[(sex, band)] = {
                "calcium_mg": _row("1000", "mg", "calcium", "2013"),
                "iron_mg": _row(iron, "mg", "eisen", "2023"),
                "folate_ug": _row("300", "ug", "folat", "2015"),
                "vitamin_b12_ug": _row("4.0", "ug", "vitamin-b12", "2018"),
                "vitamin_d_ug": _row("20", "ug", "vitamin-d", "2012", "; bei fehlender Eigensynthese"),
                "iodine_ug": _row("150", "ug", "jod", "2025"),
                "zinc_mg": _row("14" if male else "8", "mg", "zink", "2019", "; mittlere Phytatzufuhr"),
                "selenium_ug": _row("70" if male else "60", "ug", "selen", "2015"),
            }
    return table


GENERAL_REFERENCE: dict[tuple[Sex, str], dict[str, tuple[Decimal, str, str, str]]] = _build()
