"""BLS 4.0 (Max Rubner-Institut, CC BY 4.0) food provider over the SQLite file built by
scripts/import_bls.py. Ids are ``bls:<code>``; ``category`` is the BLS food-group letter.
A nutrient BLS does not state is absent from the record, never 0.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from decimal import Decimal

from .food_provider import FoodProvider, FoodRecord, FoodSearchHit

_MAX_HITS = 20


class BlsFoodProvider(FoodProvider):
    name = "BLS"

    def __init__(self, db_path: str):
        self._path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.create_function("cf", 1, lambda s: (s or "").casefold(), deterministic=True)
        return conn

    def search_food(self, query: str) -> list[FoodSearchHit]:
        q = (query or "").strip().casefold()
        if not q:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT code, name_de FROM foods "
                "WHERE instr(cf(name_de), ?) > 0 OR instr(cf(name_en), ?) > 0 "
                "ORDER BY (instr(cf(name_de), ?) = 1 OR instr(cf(name_en), ?) = 1) DESC, name_de, code "
                "LIMIT ?",
                (q, q, q, q, _MAX_HITS),
            ).fetchall()
        return [FoodSearchHit(f"bls:{code}", name) for code, name in rows]

    def get_food(self, food_id: str) -> FoodRecord:
        prefix, _, code = food_id.partition(":")
        if prefix != "bls" or not code:
            raise KeyError(f"not a BLS id {food_id!r}")
        with closing(self._connect()) as conn:
            food = conn.execute("SELECT name_de, category FROM foods WHERE code = ?", (code,)).fetchone()
            if food is None:
                raise KeyError(f"unknown food_id {food_id!r}")
            nutrients = {k: Decimal(v) for k, v in
                         conn.execute("SELECT key, value FROM nutrients WHERE code = ?", (code,))}
            version = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0]
        return FoodRecord(food_id, food[0], nutrients, self.name, version, category=food[1])

    def get_nutrients(self, food_id: str, quantity, unit: str) -> dict[str, Decimal]:
        if unit not in ("g", "gram", "grams"):
            raise ValueError(f"BLS provider only supports grams, got {unit!r}")
        factor = Decimal(str(quantity)) / Decimal("100")
        return {k: v * factor for k, v in self.get_food(food_id).nutrients_per_100g.items()}
