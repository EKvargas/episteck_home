"""Build the BLS 4.0 SQLite file the nutrition service reads (offline, run by hand).

    python services/nutrition/scripts/import_bls.py <BLS_4_0_Daten_2025_DE.xlsx> <out.sqlite>

BLS 4.0 (Max Rubner-Institut, CC BY 4.0) is NOT checked into the repo. openpyxl is a
script-only dependency (not in the service's pyproject): it is imported lazily by the CLI.
The BLS data sheet has no food-group column; the leading letter of the BLS code is the
Hauptlebensmittelgruppe (documentation section 2.4), so ``category`` = code[0].
"""
from __future__ import annotations

import os
import sqlite3
import sys
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

ATTRIBUTION = "Datos: Max Rubner-Institut, BLS 4.0"

# logical key -> header in BLS_4_0_Daten_2025_DE.xlsx (sheet BLS_4_0_Daten_2025_DE, row 1).
# Nutrient keys are the canonical keys of app.providers.nutrient_map. BLS has no selenium,
# choline or added-sugars column, so those canonical nutrients are simply never present.
COLUMN_MAP: dict[str, str] = {
    "code": "BLS Code",
    "de": "Lebensmittelbezeichnung",
    "en": "Food name",
    "energy_kcal": "ENERCC Energie (Kilokalorien) [kcal/100g]",
    "protein_g": "PROT625 Protein (Nx6,25) [g/100g]",
    "carb_g": "CHO Kohlenhydrate, verfügbar [g/100g]",
    "fat_g": "FAT Fett [g/100g]",
    "fiber_g": "FIBT Ballaststoffe, gesamt [g/100g]",
    "sugars_total_g": "SUGAR Zucker (Mono- und Disaccharide), gesamt [g/100g]",
    "calcium_mg": "CA Calcium [mg/100g]",
    "iron_mg": "FE Eisen [mg/100g]",
    "zinc_mg": "ZN Zink [mg/100g]",
    "iodine_ug": "ID Iodid [µg/100g]",
    "folate_ug": "FOL Folat-Äquivalent [µg/100g]",
    "vitamin_b12_ug": "VITB12 Vitamin B12 (Cobalamine) [µg/100g]",
    "vitamin_d_ug": "VITD Vitamin D [µg/100g]",
    "dha_g": "F22:6CN3 Fettsäure C22:6 n-3 all-cis (Docosahexaensäure) [g/100g]",
    "epa_g": "F20:5CN3 Fettsäure C20:5 n-3 all-cis (Eicosapentaensäure) [g/100g]",
}
# "group" is a logical key without a column; rows may carry it, else it is derived from the code.
_NUTRIENT_KEYS = [k for k in COLUMN_MAP if k not in ("code", "de", "en")]

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE foods (
    code TEXT PRIMARY KEY, name_de TEXT NOT NULL, name_en TEXT NOT NULL, category TEXT NOT NULL
);
CREATE TABLE nutrients (
    code TEXT NOT NULL REFERENCES foods(code), key TEXT NOT NULL, value TEXT NOT NULL,
    PRIMARY KEY (code, key)
);
"""


def _decimal(raw) -> Decimal | None:
    """Empty or non-numeric -> None (unknown), never zero."""
    text = str(raw).strip().replace(",", ".") if raw is not None else ""
    if not text:
        return None
    try:
        d = Decimal(text)
    except InvalidOperation:
        return None
    return d if d.is_finite() and d >= 0 else None


def build_bls_db(rows: Iterable[Mapping[str, str]], out_path: str, version: str = "BLS 4.0") -> int:
    """Write rows (keyed by COLUMN_MAP logical keys) to a fresh SQLite file; return rows written."""
    if os.path.exists(out_path):
        os.remove(out_path)
    conn = sqlite3.connect(out_path)
    written = 0
    try:
        conn.executescript(_SCHEMA)
        conn.executemany("INSERT INTO meta VALUES (?, ?)", [("version", version), ("attribution", ATTRIBUTION)])
        for r in rows:
            code = str(r.get("code") or "").strip()
            if not code:
                continue
            group = str(r.get("group") or "").strip() or code[0]
            conn.execute("INSERT INTO foods VALUES (?, ?, ?, ?)",
                         (code, str(r.get("de") or "").strip(), str(r.get("en") or "").strip(), group))
            for key in _NUTRIENT_KEYS:
                d = _decimal(r.get(key))
                if d is not None:
                    conn.execute("INSERT INTO nutrients VALUES (?, ?, ?)", (code, key, str(d)))
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def read_xlsx_rows(path: str) -> Iterable[dict[str, str]]:
    from openpyxl import load_workbook  # script-only dependency

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        it = wb.worksheets[0].iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(it)]
        missing = [h for h in COLUMN_MAP.values() if h not in header]
        if missing:
            raise SystemExit(f"BLS file lacks expected columns: {missing}")
        idx = {k: header.index(h) for k, h in COLUMN_MAP.items()}
        for values in it:
            yield {k: ("" if values[i] is None else str(values[i])) for k, i in idx.items()}
    finally:
        wb.close()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: import_bls.py <BLS xlsx> <out.sqlite>", file=sys.stderr)
        return 2
    n = build_bls_db(read_xlsx_rows(argv[1]), argv[2])
    print(f"wrote {n} foods to {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
