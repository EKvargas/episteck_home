import sqlite3
from decimal import Decimal

import pytest

from app.providers.bls import BlsFoodProvider
from app.providers.chain import ProviderChain
from scripts.import_bls import COLUMN_MAP, build_bls_db


def row(code, de, en="", group="", **nutrients):
    """A BLS row keyed by COLUMN_MAP logical keys; a missing value is an empty string."""
    r = {k: "" for k in COLUMN_MAP}
    r.update(code=code, de=de, en=en, group=group)
    r.update(nutrients)
    return r


def _db(tmp_path, *rows):
    path = tmp_path / "bls.sqlite"
    n = build_bls_db(list(rows), str(path))
    return str(path), n


def test_search_and_get(tmp_path):
    db, n = _db(tmp_path, row("F110100", "Apfel roh", "Apple, raw", "F",
                              sugars_total_g="10.3", energy_kcal="54"))
    assert n == 1
    p = BlsFoodProvider(db)
    assert p.search_food("apfel")[0].food_id == "bls:F110100"
    rec = p.get_food("bls:F110100")
    assert rec.nutrients_per_100g["sugars_total_g"] == Decimal("10.3")
    assert rec.nutrients_per_100g["energy_kcal"] == Decimal("54")
    assert (rec.source, rec.provider_version, rec.category) == ("BLS", "BLS 4.0", "F")
    assert rec.name == "Apfel roh"


def test_missing_value_is_absent(tmp_path):
    db, _ = _db(tmp_path, row("F110100", "Apfel roh", group="F", sugars_total_g="", energy_kcal="-",
                              protein_g="0"))
    rec = BlsFoodProvider(db).get_food("bls:F110100")
    assert "sugars_total_g" not in rec.nutrients_per_100g
    assert "energy_kcal" not in rec.nutrients_per_100g  # not numeric -> absent, never 0
    assert rec.nutrients_per_100g["protein_g"] == Decimal("0")  # a stated zero stays zero


def test_group_defaults_to_first_letter_of_code(tmp_path):
    db, _ = _db(tmp_path, row("S121000", "Blütenhonig"))
    assert BlsFoodProvider(db).get_food("bls:S121000").category == "S"


def test_search_is_case_insensitive_over_both_languages_prefix_first_and_capped(tmp_path):
    rows = [row("F000001", "Birne mit Apfel", "Pear with apple", "F"),
            row("F000002", "Apfelsaft", "Apple juice", "F"),
            row("G000003", "Äpfel gedünstet", "Stewed apples", "G")]
    rows += [row(f"X{i:06d}", f"Apfelgericht {i}", "", "X") for i in range(30)]
    db, _ = _db(tmp_path, *rows)
    p = BlsFoodProvider(db)
    hits = p.search_food("APFEL")
    assert len(hits) == 20
    assert hits[0].name.lower().startswith("apfel")          # prefix matches before contains
    assert [h.food_id for h in p.search_food("pear")] == ["bls:F000001"]  # English name
    assert [h.food_id for h in p.search_food("äpfel")] == ["bls:G000003"]  # non-ASCII fold
    assert p.search_food("zzz") == []
    assert p.search_food("   ") == []


def test_get_food_unknown_or_foreign_id_raises(tmp_path):
    db, _ = _db(tmp_path, row("F110100", "Apfel roh"))
    p = BlsFoodProvider(db)
    with pytest.raises(KeyError):
        p.get_food("bls:NOPE")
    with pytest.raises(KeyError):
        p.get_food("usda:1")


def test_get_nutrients_grams_only(tmp_path):
    db, _ = _db(tmp_path, row("F110100", "Apfel roh", sugars_total_g="10.3"))
    p = BlsFoodProvider(db)
    assert p.get_nutrients("bls:F110100", Decimal("200"), "g") == {"sugars_total_g": Decimal("20.6")}
    with pytest.raises(ValueError):
        p.get_nutrients("bls:F110100", Decimal("1"), "ml")


def test_meta_holds_version_and_attribution(tmp_path):
    db, _ = _db(tmp_path, row("F110100", "Apfel roh"))
    meta = dict(sqlite3.connect(db).execute("SELECT key, value FROM meta"))
    assert meta["version"] == "BLS 4.0"
    assert meta["attribution"] == "Datos: Max Rubner-Institut, BLS 4.0"


def test_rebuild_replaces_existing_file(tmp_path):
    db, _ = _db(tmp_path, row("F110100", "Apfel roh"), row("F110200", "Birne roh"))
    _, n = _db(tmp_path, row("F110100", "Apfel roh"))
    assert n == 1
    assert [h.food_id for h in BlsFoodProvider(db).search_food("birne")] == []


def test_chain_routes_bls_prefix(tmp_path):
    db, _ = _db(tmp_path, row("F110100", "Apfel roh", group="F"))
    chain = ProviderChain([BlsFoodProvider(db)])
    assert chain.get_food("bls:F110100").source == "BLS"


def test_deps_puts_bls_first(tmp_path, monkeypatch):
    from app import deps
    db, _ = _db(tmp_path, row("F110100", "Apfel roh"))
    monkeypatch.setenv("FOOD_PROVIDER", "auto")
    monkeypatch.delenv("USDA_API_KEY", raising=False)
    monkeypatch.delenv("OFF_BASE_URL", raising=False)
    monkeypatch.setenv("BLS_DB", db)
    names = [p.name for p in deps._build_provider()._providers]
    assert names == ["BLS", "OPEN_FOOD_FACTS", "USDA_FDC"]


def test_deps_ignores_bls_when_file_missing_or_synthetic(tmp_path, monkeypatch):
    from app import deps
    from app.providers.synthetic import SyntheticFoodProvider
    monkeypatch.delenv("USDA_API_KEY", raising=False)
    monkeypatch.delenv("OFF_BASE_URL", raising=False)
    monkeypatch.setenv("FOOD_PROVIDER", "auto")
    monkeypatch.setenv("BLS_DB", str(tmp_path / "missing.sqlite"))
    assert isinstance(deps._build_provider(), SyntheticFoodProvider)
    db, _ = _db(tmp_path, row("F110100", "Apfel roh"))
    monkeypatch.setenv("BLS_DB", db)
    monkeypatch.setenv("FOOD_PROVIDER", "synthetic")
    assert isinstance(deps._build_provider(), SyntheticFoodProvider)


def _service(tmp_path, provider):
    from datetime import datetime, timezone
    from app.diary.service import DiaryService
    from app.profile.service import ProfileService
    from app.store.diary_sqlite import SqliteDiaryStore
    from app.store.profile_sqlite import SqliteProfileStore
    from tests.support import AllowAllAuthorizer
    db = str(tmp_path / "n.sqlite")
    profiles = ProfileService(SqliteProfileStore(db), authorizer=AllowAllAuthorizer())
    return DiaryService(SqliteDiaryStore(db), provider, profiles,
                        authorizer=AllowAllAuthorizer(),
                        clock=lambda: datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)), db


def _bls_item():
    return {"label": "Apfel", "food_id": "bls:F110100", "amount": 100, "unit": "g", "stated": True}


def _drafts(db):
    with sqlite3.connect(db) as c:
        try:
            return c.execute("SELECT COUNT(*) FROM diary_draft").fetchone()[0]
        except sqlite3.OperationalError:
            return 0


def test_bls_without_metadata_is_provider_unavailable(tmp_path):
    from app.diary.service import ProviderUnavailable
    db, _ = _db(tmp_path, row("F110100", "Apfel roh", group="F", energy_kcal="54"))
    with sqlite3.connect(db) as c:
        c.execute("DELETE FROM meta")
    svc, ndb = _service(tmp_path, BlsFoodProvider(db))
    with pytest.raises(ProviderUnavailable):
        svc.propose_intake("s", "p1", [_bls_item()], consumed_at="2026-11-19T10:30:00+01:00")
    assert _drafts(ndb) == 0


def test_bls_file_that_is_not_sqlite_is_provider_unavailable(tmp_path):
    from app.diary.service import ProviderUnavailable
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"not a database")
    svc, ndb = _service(tmp_path, BlsFoodProvider(str(bad)))
    with pytest.raises(ProviderUnavailable):
        svc.propose_intake("s", "p1", [_bls_item()], consumed_at="2026-11-19T10:30:00+01:00")
    assert _drafts(ndb) == 0


def test_bls_opens_read_only(tmp_path):
    db, _ = _db(tmp_path, row("F110100", "Apfel roh", group="F"))
    p = BlsFoodProvider(db)
    with pytest.raises(sqlite3.OperationalError):
        p._connect().execute("CREATE TABLE x(a)")
