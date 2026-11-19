# Nutrition R1 · Plan 1: Diary backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give svc-nutrition a food diary: sugar data from BLS, Open Food Facts and USDA; drafts that Ana confirms; values frozen at confirmation; free sugars per day against a sourced limit; REST and MCP access.

**Architecture:** Pure, deterministic rules (portions, free-sugar classification, the limit, day summaries) live in `packages/nutrition-domain`. svc-nutrition gets a BLS provider, sugar fields in all providers, a SQLite diary store in the existing database file, and a `DiaryService` beside the existing `NutritionService`. Every person-sensitive operation makes exactly one Home authorization request.

**Tech Stack:** Python 3.11, Decimal arithmetic, SQLite (stdlib), FastAPI, fastmcp 4.0.3 (pinned), pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-nutrition-release-1-design.md` (sections 6.5–6.11). This is plan 1 of 4: plan 2 covers per-person agent runtimes, plan 3 Ana's agent, onboarding, the "Hoy" page and rollout, plan 4 step B.

## Global Constraints

- Run every test from the repo root with `PYTHONPATH="packages/nutrition-domain/src;services/nutrition"` (Windows; use `:` on Linux) and `python -m pytest -q -p no:cacheprovider <path>`. Abbreviated below as `PT <path>`.
- All nutrient math uses `Decimal`; inputs arriving as numbers are converted with `Decimal(str(x))`. API output renders Decimals as strings.
- Missing is unknown, never zero: an absent nutrient stays absent; an unknown sugar figure is `None`/`null`, never `"0"`.
- Each person-sensitive operation makes exactly **one** Home request (`check_access` for one action, `check_access_many` for several). Delegations are single-use.
- No tool or route takes an actor; the delegation comes from transport only (`X-Episteck-Delegation` / MCP context). `tests/test_boundaries.py` must keep passing.
- Presets (version `episteck-portions-1`), exact: `small_glass` 150 ml, `glass` 200 ml, `large_glass` 300 ml, `cup` 250 ml, `can` 330 ml, `tablespoon` 15 ml, `teaspoon` 5 ml. Volume converts at the food's density if known, else 1.0 g/ml.
- Limit v1: free sugars ≤ **50 g/day**, basis "<10% of energy" at **2,000 kcal**, origin `INSTITUTIONAL_REFERENCE`, applies to modes `GENERAL` and `PREGNANCY`, valid from 2026-11-18.
- Drafts expire after **24 hours** and never count in totals.
- Diary day = local date in `DIARY_TZ` (default `Europe/Berlin`).
- BLS attribution text, shown wherever a BLS value is shown: `Datos: Max Rubner-Institut, BLS 4.0`.
- Service logs record ids and statuses only, never food text.
- Do not change the `fastmcp==4.0.3` pin.

## Review Focus

- **The bot retries "sí":** two confirmations of one draft arrive at once; exactly one entry exists afterwards (Task 6 concurrency test).
- **A known food with no sugar value at the source, or an unclassified dish:** counted as "sin dato"; the day is `PARTIAL` and shows the known sum, never 0 (Task 7).
- **Late-evening entries:** 23:30 in Berlin belongs to that Berlin date even when the server clock is UTC (Task 7).
- **Wrong person:** a draft id confirmed under another subject id answers `NOT_FOUND` and reveals nothing (Task 7).
- **A food source is down while proposing:** no draft is stored and the caller gets `PROVIDER_UNAVAILABLE`, so the bot can retry (Task 7).

---

### Task 1: Sugar fields and source metadata in USDA and Open Food Facts

**Files:**
- Modify: `services/nutrition/app/providers/nutrient_map.py`, `services/nutrition/app/providers/food_provider.py`, `services/nutrition/app/providers/usda.py`, `services/nutrition/app/providers/openfoodfacts.py`
- Test: `services/nutrition/tests/test_provider_sugar.py`

**Interfaces:**
- Produces: `CANONICAL_UNITS["sugars_total_g"] == "g"`, `CANONICAL_UNITS["sugars_added_g"] == "g"`. `FoodRecord` gains keyword fields with defaults, so existing constructors keep working: `category: str | None = None`, `serving_g: Decimal | None = None`, `density_g_per_ml: Decimal | None = None`.

- [ ] **Step 1: Write the failing tests.** Stub HTTP the way `tests/test_stage_f.py` does. Fixtures: a USDA food with nutrients 269 = 10.6 g and 539 = 10.6 g, `foodCategory.description` "Beverages", first `foodPortions[].gramWeight` 248; an OFF product `5449000000996` with `sugars_100g` 10.6, no `added-sugars_100g`, `serving_quantity` 330 with unit "g", `categories_tags` `["en:beverages","en:carbonated-drinks","en:sodas"]`.

```python
def test_usda_maps_total_and_added_sugars(usda_stub):
    rec = UsdaFoodProvider(api_key="k").get_food("usda:123")
    assert rec.nutrients_per_100g["sugars_total_g"] == Decimal("10.6")
    assert rec.nutrients_per_100g["sugars_added_g"] == Decimal("10.6")
    assert rec.category == "Beverages"
    assert rec.serving_g == Decimal("248")

def test_off_maps_sugars_category_and_serving(off_stub):
    rec = OpenFoodFactsProvider().get_food("off:5449000000996")
    assert rec.nutrients_per_100g["sugars_total_g"] == Decimal("10.6")
    assert "sugars_added_g" not in rec.nutrients_per_100g
    assert rec.category == "en:beverages,en:carbonated-drinks,en:sodas"
    assert rec.serving_g == Decimal("330")

def test_off_serving_in_ml_is_not_a_gram_serving(off_stub_ml):
    assert OpenFoodFactsProvider().get_food("off:1").serving_g is None
```

- [ ] **Step 2: Run** `PT services/nutrition/tests/test_provider_sugar.py`. Expected: FAIL (`KeyError: 'sugars_total_g'` / missing attribute).
- [ ] **Step 3: Implement.** Add USDA numbers `"269": ("sugars_total_g","G")`, `"539": ("sugars_added_g","G")`; OFF keys `"sugars_100g": ("sugars_total_g","g")`, `"added-sugars_100g": ("sugars_added_g","g")`. USDA `category` = `foodCategory.description`; `serving_g` = first `foodPortions[].gramWeight`, else `servingSize` when `servingSizeUnit` is g. OFF `category` = `",".join(categories_tags)`; `serving_g` = `serving_quantity` only when `serving_quantity_unit` is absent or "g". `density_g_per_ml` stays None (no source provides it yet).
- [ ] **Step 4: Run** `PT services/nutrition/tests` . Expected: all PASS (existing provider tests unchanged).
- [ ] **Step 5: Commit** `feat: map sugars and serving sizes from USDA and OFF`.

### Task 2: BLS 4.0 provider and import

**Files:**
- Create: `services/nutrition/app/providers/bls.py`, `services/nutrition/scripts/import_bls.py`
- Modify: `services/nutrition/app/providers/chain.py` (route prefix `bls` → provider name `BLS`), `services/nutrition/app/deps.py`
- Test: `services/nutrition/tests/test_bls_provider.py`

**Interfaces:**
- Produces: `build_bls_db(rows: Iterable[Mapping[str, str]], out_path: str, version: str = "BLS 4.0") -> int` (rows written) in `import_bls.py`; `BlsFoodProvider(db_path: str)` with `name = "BLS"`, ids `bls:<code>`, `FoodRecord.source == "BLS"`, `provider_version` read from the DB, `category` = the BLS food-group code. `deps._build_provider()` returns `ProviderChain([BlsFoodProvider, OpenFoodFactsProvider, UsdaFoodProvider])` when `BLS_DB` is set and the file exists; without `BLS_DB` the current chain is unchanged.

- [ ] **Step 1: Inspect the source.** Download the BLS 4.0 file from https://blsdb.de/download. Record its column names for code, German name, English name, food group, energy, total sugars and the other canonical nutrients in a `COLUMN_MAP` constant in `import_bls.py`, and list them in the commit message. The DB schema is yours to choose; it needs per-food canonical nutrients per 100 g plus a `meta` table holding the version and the attribution text.
- [ ] **Step 2: Write the failing tests** (rows built with `COLUMN_MAP` keys; a missing value is an empty string):

```python
def test_search_and_get(tmp_path):
    db = tmp_path / "bls.sqlite"
    build_bls_db([row(code="F110100", de="Apfel roh", en="Apple, raw", group="F", sugar="10.3", kcal="54")], str(db))
    p = BlsFoodProvider(str(db))
    assert p.search_food("apfel")[0].food_id == "bls:F110100"
    rec = p.get_food("bls:F110100")
    assert rec.nutrients_per_100g["sugars_total_g"] == Decimal("10.3")
    assert (rec.source, rec.provider_version, rec.category) == ("BLS", "BLS 4.0", "F")

def test_missing_value_is_absent(tmp_path): ...   # sugar="" -> "sugars_total_g" not in nutrients
def test_chain_routes_bls_prefix(tmp_path): ...   # ProviderChain([bls]).get_food("bls:F110100").source == "BLS"
def test_deps_puts_bls_first(tmp_path, monkeypatch): ...  # BLS_DB set -> first provider name "BLS"
```

- [ ] **Step 3: Run** `PT services/nutrition/tests/test_bls_provider.py`. Expected: FAIL (module not found).
- [ ] **Step 4: Implement** `build_bls_db`, a CLI (`python services/nutrition/scripts/import_bls.py <downloaded file> <out.sqlite>`, reading xlsx with openpyxl as a script-only dependency, not a service dependency), `BlsFoodProvider` (case-insensitive search over German and English names, prefix matches first, at most 20 hits), and the chain and deps changes.
- [ ] **Step 5: Run** `PT services/nutrition/tests`. Expected: all PASS.
- [ ] **Step 6: Commit** `feat: add BLS 4.0 food provider and importer`.

### Task 3: Portions and conversion (domain)

**Files:**
- Create: `packages/nutrition-domain/src/nutrition_domain/portions.py`
- Test: `packages/nutrition-domain/tests/test_portions.py`

**Interfaces:**
- Produces: `PORTION_TABLE_VERSION = "episteck-portions-1"`, `PRESETS_ML: dict[str, Decimal]`, `class ConversionMethod(str, Enum)` with `USER_STATED`, `SOURCE_SERVING`, `PRESET`, `AGENT_ESTIMATE`; `@dataclass(frozen=True) class Conversion(grams: Decimal, method: ConversionMethod, detail: str, table_version: str)`; `class PortionError(ValueError)`; `to_grams(amount: Decimal, unit: str, *, stated: bool, serving_g: Decimal | None = None, density_g_per_ml: Decimal | None = None, grams_estimate: Decimal | None = None) -> Conversion`. `grams_estimate` is the total for the item, not per unit.

- [ ] **Step 1: Write the failing tests:**

```python
D = Decimal
def test_presets_exact():
    assert PRESETS_ML == {"small_glass": D("150"), "glass": D("200"), "large_glass": D("300"),
                          "cup": D("250"), "can": D("330"), "tablespoon": D("15"), "teaspoon": D("5")}
def test_preset_uses_assumed_density():
    c = to_grams(D("1"), "small_glass", stated=False)
    assert (c.grams, c.method) == (D("150"), ConversionMethod.PRESET) and "1.0 g/ml" in c.detail
def test_two_glasses():          assert to_grams(D("2"), "glass", stated=False).grams == D("400")
def test_source_density():       assert to_grams(D("1"), "can", stated=False, density_g_per_ml=D("1.04")).grams == D("343.20")
def test_stated_ml():            assert to_grams(D("330"), "ml", stated=True).method is ConversionMethod.USER_STATED
def test_guessed_grams():        assert to_grams(D("150"), "g", stated=False).method is ConversionMethod.AGENT_ESTIMATE
def test_source_serving():       assert to_grams(D("1"), "serving", stated=False, serving_g=D("125")).method is ConversionMethod.SOURCE_SERVING
def test_slices_need_estimate():
    c = to_grams(D("2"), "slice", stated=False, grams_estimate=D("60"))
    assert (c.grams, c.method) == (D("60"), ConversionMethod.AGENT_ESTIMATE)
    with pytest.raises(PortionError): to_grams(D("2"), "slice", stated=False)
@pytest.mark.parametrize("amount,unit", [(D("0"), "g"), (D("-1"), "ml"), (D("1"), "bucket")])
def test_rejects(amount, unit):
    with pytest.raises(PortionError): to_grams(amount, unit, stated=True)
```

- [ ] **Step 2: Run** `PT packages/nutrition-domain/tests/test_portions.py`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** `to_grams` per the tests. Units `g` and `ml` honor `stated`; preset units → `PRESET`; `serving` uses `serving_g`, else `grams_estimate`, else error; `piece`, `slice`, `plate` and `portion` require `grams_estimate`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add portion presets and gram conversion`.

### Task 4: Free-sugar classification (domain)

**Files:**
- Create: `packages/nutrition-domain/src/nutrition_domain/free_sugars.py`
- Test: `packages/nutrition-domain/tests/test_free_sugars.py`

**Interfaces:**
- Produces: `FREE_SUGAR_MAP_VERSION = "episteck-fs-1"`; `class FreeSugarClass(str, Enum)` with `FREE`, `NOT_FREE`, `UNKNOWN`; `classify(source: str, category: str | None) -> FreeSugarClass`; `item_free_sugars_g(cls: FreeSugarClass, nutrients_per_100g: Mapping[str, Decimal], grams: Decimal) -> Decimal | None`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_classify_examples():
    assert classify("OPEN_FOOD_FACTS", "en:beverages,en:carbonated-drinks,en:sodas") is FreeSugarClass.FREE
    assert classify("OPEN_FOOD_FACTS", "en:fruit-juices") is FreeSugarClass.FREE
    assert classify("OPEN_FOOD_FACTS", "en:flavoured-milks") is FreeSugarClass.FREE
    assert classify("OPEN_FOOD_FACTS", "en:fresh-fruits") is FreeSugarClass.NOT_FREE
    assert classify("OPEN_FOOD_FACTS", "en:milks") is FreeSugarClass.NOT_FREE
    assert classify("USDA_FDC", "Sweets") is FreeSugarClass.FREE
    assert classify("USDA_FDC", "Fruits and Fruit Juices") is FreeSugarClass.UNKNOWN
    assert classify("OPEN_FOOD_FACTS", None) is FreeSugarClass.UNKNOWN
def test_item_free_sugars():
    n = {"sugars_total_g": Decimal("10.6")}
    assert item_free_sugars_g(FreeSugarClass.FREE, n, Decimal("330")) == Decimal("34.98")
    assert item_free_sugars_g(FreeSugarClass.FREE, {}, Decimal("330")) is None
    assert item_free_sugars_g(FreeSugarClass.NOT_FREE, n, Decimal("150")) == Decimal("0")
    assert item_free_sugars_g(FreeSugarClass.UNKNOWN, {"sugars_added_g": Decimal("5")}, Decimal("100")) == Decimal("5")
    assert item_free_sugars_g(FreeSugarClass.UNKNOWN, n, Decimal("100")) is None
```

- [ ] **Step 2: Run** `PT packages/nutrition-domain/tests/test_free_sugars.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** OFF categories match as exact tags after splitting on ","; `FREE` patterns win over `NOT_FREE`. Use the class lists in spec 6.9. BLS group codes go in the same table once Task 2 Step 1 has recorded them; until then BLS returns `UNKNOWN`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: classify free sugars by source category`.

### Task 5: The limit rule, trimester and day summary (domain)

**Files:**
- Create: `packages/nutrition-domain/src/nutrition_domain/rules.py`, `packages/nutrition-domain/src/nutrition_domain/day_summary.py`
- Test: `packages/nutrition-domain/tests/test_rules.py`, `packages/nutrition-domain/tests/test_day_summary.py`

**Interfaces:**
- Produces in `rules.py`: `@dataclass(frozen=True) class RuleSource(title: str, url: str)`; `@dataclass(frozen=True) class LimitRule(rule_id: str, version: int, valid_from: date, metric: str, operator: str, period: str, value_g: Decimal, basis: str, energy_basis_kcal: int, origin: str, sources: tuple[RuleSource, ...], adaptation: str, modes: frozenset[str])`; `FREE_SUGARS_LIMIT_V1`; `RULES: tuple[LimitRule, ...]`; `effective_limit(on: date, mode: str, rules: Sequence[LimitRule] = RULES) -> LimitRule | None` (latest version with `valid_from <= on` that applies to `mode`); `trimester(due: date, on: date) -> int | None`.
- Produces in `day_summary.py`: `class DayStatus(str, Enum)` with `NO_ENTRIES`, `OPEN`, `COMPLETE`; `class SugarStatus(str, Enum)` with `NONE`, `KNOWN`, `PARTIAL`; `@dataclass(frozen=True) class DaySummary(day: date, day_status: DayStatus, sugar_status: SugarStatus, free_sugars_known_g: Decimal | None, items_total: int, items_uncounted: int, limit: LimitRule | None)`; `summarize_day(day: date, item_free_sugars: Sequence[Decimal | None], closed: bool, limit: LimitRule | None) -> DaySummary`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_rule_v1_values():
    r = FREE_SUGARS_LIMIT_V1
    assert (r.rule_id, r.version, r.valid_from) == ("free-sugars-daily-max", 1, date(2026, 11, 18))
    assert (r.metric, r.operator, r.period, r.value_g) == ("free_sugars_g", "max", "day", Decimal("50"))
    assert (r.basis, r.energy_basis_kcal, r.origin) == ("<10% of energy", 2000, "INSTITUTIONAL_REFERENCE")
    assert r.modes == frozenset({"GENERAL", "PREGNANCY"}) and len(r.sources) == 3
def test_effective_limit_respects_dates_and_versions():
    v2 = replace(FREE_SUGARS_LIMIT_V1, version=2, valid_from=date(2027, 1, 1), value_g=Decimal("45"))
    assert effective_limit(date(2026, 11, 17), "PREGNANCY") is None
    assert effective_limit(date(2026, 12, 31), "PREGNANCY", [FREE_SUGARS_LIMIT_V1, v2]).version == 1
    assert effective_limit(date(2027, 1, 2), "GENERAL", [FREE_SUGARS_LIMIT_V1, v2]).version == 2
def test_trimester():
    due = date(2027, 5, 20)
    assert trimester(due, date(2026, 11, 18)) == 1   # 13+6
    assert trimester(due, date(2026, 11, 19)) == 2   # 14+0
    assert trimester(due, date(2027, 2, 24)) == 2    # 27+6
    assert trimester(due, date(2027, 2, 25)) == 3    # 28+0
    assert trimester(due, date(2026, 6, 1)) is None  # before pregnancy
def test_empty_day_is_never_zero():
    s = summarize_day(date(2026, 11, 20), [], closed=True, limit=FREE_SUGARS_LIMIT_V1)
    assert (s.day_status, s.sugar_status, s.free_sugars_known_g) == (DayStatus.NO_ENTRIES, SugarStatus.NONE, None)
def test_partial_day():
    s = summarize_day(date(2026, 11, 20), [Decimal("17"), Decimal("0"), None], closed=False, limit=None)
    assert (s.free_sugars_known_g, s.items_total, s.items_uncounted) == (Decimal("17"), 3, 1)
    assert (s.sugar_status, s.day_status) == (SugarStatus.PARTIAL, DayStatus.OPEN)
def test_complete_known_day():
    s = summarize_day(date(2026, 11, 20), [Decimal("17"), Decimal("15")], closed=True, limit=None)
    assert (s.free_sugars_known_g, s.sugar_status, s.day_status) == (Decimal("32"), SugarStatus.KNOWN, DayStatus.COMPLETE)
```

- [ ] **Step 2: Run** `PT packages/nutrition-domain/tests/test_rules.py packages/nutrition-domain/tests/test_day_summary.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Gestational age in days = `280 - (due - on).days`; below 0 → None; T1 below 98 days, T2 98–195, T3 from 196. Sources (titles exactly): "WHO Guideline: Sugars intake for adults and children (2015)", "DGE/DAG/DDG: Quantitative Empfehlung zur Zuckerzufuhr in Deutschland (2018)", "familienplanung.de (BIOEG): Zucker in der Schwangerschaft". URLs: take them from `docs/architecture/reviews/2026-11-15-nutrition-sugar-review.json` `fuentes_externas`, plus the WHO publication page; open each once to confirm it resolves. `adaptation = "10 % of a standard 2,000 kcal day"`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add free-sugar limit rule and day summary`.

### Task 6: Diary store

**Files:**
- Create: `services/nutrition/app/store/diary_sqlite.py`
- Test: `services/nutrition/tests/test_diary_store.py`

**Interfaces:**
- Produces: `class SqliteDiaryStore(path: str)` using the same database file as `SqliteNutritionRepository`, with:
  - `put_draft(person_id: str, doc: dict, expires_at: datetime) -> dict` (returns the doc with `id`)
  - `get_draft(person_id: str, draft_id: str) -> dict | None` (None for another person's draft)
  - `confirm_draft(person_id: str, draft_id: str, entry_doc: dict) -> tuple[dict, bool]`: one transaction (`BEGIN IMMEDIATE`); returns `(entry, created)`; an already-confirmed draft returns its entry with `created=False`
  - `get_entry(person_id: str, entry_id: str) -> dict | None`: latest revision, with `rev` and `voided`
  - `add_revision(person_id: str, entry_id: str, doc: dict) -> dict`
  - `void_entry(person_id: str, entry_id: str) -> dict`
  - `list_entries(person_id: str, day: str) -> list[dict]`: latest revisions, not voided, ordered by `consumed_at`
  - `close_day(person_id: str, day: str, closed_at: datetime) -> None`
  - `is_day_closed(person_id: str, day: str) -> bool`
- Uniqueness: an entry's `draft_id` column is `UNIQUE NOT NULL`.

- [ ] **Step 1: Write the failing tests:** `test_confirm_twice_returns_same_entry` (second call `created is False`, same id); `test_concurrent_confirms_create_one_entry` (two threads, a barrier, then exactly one row in `diary_entry`); `test_other_persons_draft_is_invisible`; `test_revision_and_void` (rev 2 listed, voided excluded from `list_entries` but `get_entry(...)["voided"] is True`); `test_close_day`; `test_entries_ordered_by_consumed_at`.
- [ ] **Step 2: Run** `PT services/nutrition/tests/test_diary_store.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the four tables (`diary_draft`, `diary_entry`, `diary_revision`, `diary_day`) created idempotently on init, following `sqlite_repo.py`'s style.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add SQLite diary store with idempotent confirm`.

### Task 7: DiaryService

**Files:**
- Create: `services/nutrition/app/diary/__init__.py`, `services/nutrition/app/diary/service.py`
- Modify: `services/nutrition/app/providers/synthetic.py` (add sugar foods)
- Test: `services/nutrition/tests/test_diary_service.py`

**Interfaces:**
- Consumes: Tasks 3–6; `_refuse_unless_allowed`, `AccessAuthorizer`, `AccessDenied` from `app.service`; `FoodProvider`; `NutritionRepository` (profile doc).
- Produces: exceptions `DraftNotFound(LookupError)`, `EntryNotFound(LookupError)`, `DraftExpired(Exception)`, `ProviderUnavailable(Exception)`; and
  `DiaryService(store, provider, profiles, *, authorizer, tz: str = "Europe/Berlin", clock: Callable[[], datetime] = <utc now>, draft_ttl: timedelta = timedelta(hours=24))` with (Home actions in brackets):
  - `propose_intake(delegation, subject_person_id, items: list[dict], consumed_at: str | None = None) -> dict` [CREATE+VIEW]: `{"draft_id", "expires_at", "items", "day"}`
  - `confirm_intake(delegation, subject_person_id, draft_id) -> dict` [CREATE+VIEW]: `{"entry", "day"}`
  - `correct_intake(delegation, subject_person_id, entry_id, items) -> dict` [UPDATE+VIEW]: `{"entry", "day"}`
  - `void_intake(delegation, subject_person_id, entry_id) -> dict` [UPDATE+VIEW]: `{"entry", "day"}`
  - `get_entry(delegation, subject_person_id, entry_id) -> dict` [VIEW]
  - `get_day_summary(delegation, subject_person_id, day: str) -> dict` [VIEW]
  - `close_day(delegation, subject_person_id, day: str) -> dict` [UPDATE+VIEW]
  - `set_mode(delegation, subject_person_id, mode: str, due_date: str | None = None) -> dict` [UPDATE+VIEW]: merges `context` and `due_date` into the existing profile doc
- Item input: `{"label": str, "food_id": str | None, "amount": number|str, "unit": str, "stated": bool, "grams_estimate": number|str|None}`.
- Frozen item (stored and returned): `{"label", "food_id", "food_name", "amount", "unit", "grams", "conversion": {"method", "detail", "table_version"}, "facts": {"nutrients_per_100g", "source", "provider_version", "category", "retrieved_at"} | None, "free_sugar_class", "free_sugar_map_version", "free_sugars_g": str | None}`. Facts are resolved when the draft is made and copied unchanged at confirmation; confirmation fetches nothing.
- Day dict: `{"date", "mode", "trimester", "day_status", "sugar_status", "free_sugars_known_g": str | None (one decimal, ROUND_HALF_UP), "items_total", "items_uncounted", "limit": {"rule_id", "version", "value_g", "basis", "energy_basis_kcal", "origin", "sources": [{"title", "url"}], "adaptation"} | None, "entries": [{"id", "consumed_at", "items"}], "attribution": [str]}`. `attribution` holds the BLS text when any shown item comes from BLS.

- [ ] **Step 1: Extend the synthetic provider** with `syn-cola` (sugars_total 10.6, category `en:sodas`), `syn-orange-juice` (8.4, `en:fruit-juices`), `syn-apple` (10.3, `en:fresh-fruits`), `syn-bread` (sugars_total 3.0, category None).
- [ ] **Step 2: Write the failing tests** (`AllowAllAuthorizer`/`DenyAllAuthorizer` from `tests/support.py`, a temp DB, an injectable clock):

```python
def test_propose_then_confirm_counts_once():
    d = svc.propose_intake(S, "p1", [cola(1, "small_glass")], consumed_at="2026-11-20T16:00:00+01:00")
    assert d["items"][0]["free_sugars_g"] == "15.9" and d["day"]["day_status"] == "NO_ENTRIES"
    first = svc.confirm_intake(S, "p1", d["draft_id"]); again = svc.confirm_intake(S, "p1", d["draft_id"])
    assert first["entry"]["id"] == again["entry"]["id"] and again["day"]["free_sugars_known_g"] == "15.9"
def test_draft_expires(): ...                 # clock + 25 h -> DraftExpired; nothing stored
def test_frozen_facts_survive_provider_change(): ...   # swap provider sugars after confirm -> same day total
def test_unknown_food_is_uncounted():         # {"label":"arepa","food_id":None,"amount":1,"unit":"piece","grams_estimate":120}
    day = ...; assert (day["sugar_status"], day["items_uncounted"]) == ("PARTIAL", 1)
def test_correction_keeps_revision(): ...     # small_glass -> large_glass: day "31.8", get_entry rev == 2
def test_void_excludes_entry(): ...
def test_close_day_marks_complete(): ...
def test_late_evening_uses_berlin_date():
    assert propose(consumed_at="2026-11-18T23:30:00+01:00")["day"]["date"] == "2026-11-18"
    assert propose(consumed_at="2026-11-18T23:30:00Z")["day"]["date"] == "2026-11-19"
def test_other_person_cannot_confirm(): ...   # draft for p1, confirm as p2 -> DraftNotFound
def test_provider_outage_stores_no_draft(): ...  # provider.get_food raises httpx.ConnectError -> ProviderUnavailable; no draft row
def test_each_operation_is_one_home_request(): ...  # every public method: authorizer.home_calls increases by exactly 1
def test_denied_creates_nothing(): ...        # DenyAllAuthorizer -> AccessDenied; no draft row
def test_mode_stamp_and_trimester(): ...      # set_mode PREGNANCY due 2027-05-20; confirm on 2026-11-19 -> entry["mode"] == "PREGNANCY", day["trimester"] == 2
def test_bls_item_adds_attribution(): ...     # day["attribution"] == ["Datos: Max Rubner-Institut, BLS 4.0"]
```

- [ ] **Step 3: Run** `PT services/nutrition/tests/test_diary_service.py`. Expected: FAIL.
- [ ] **Step 4: Implement.** Authorize first, with one request, before any read or write. An unknown `food_id` raises `ValueError`; network errors from a provider raise `ProviderUnavailable`. `correct_intake` reuses the frozen facts of an item whose `food_id` is unchanged and resolves only new foods. A voided entry cannot be corrected (`EntryNotFound`). Mode is read from profile `context` (default `GENERAL`); `due_date` is accepted only with `PREGNANCY`; other modes raise `ValueError`.
- [ ] **Step 5: Run** `PT services/nutrition/tests`. Expected: all PASS.
- [ ] **Step 6: Commit** `feat: add diary service with drafts, revisions and day summary`.

### Task 8: REST routes, MCP tools and wiring

**Files:**
- Modify: `services/nutrition/app/main.py`, `services/nutrition/app/mcp/server.py`, `services/nutrition/app/deps.py` (`build_diary_service()`, `DIARY_TZ`), `services/nutrition/pyproject.toml` (add `tzdata`), `docs/architecture/STATUS.md` (Nutrition row: diary merged, not deployed)
- Test: `services/nutrition/tests/test_diary_api.py`

**Interfaces:**
- Consumes: Task 7.
- Produces, REST (delegation from `X-Episteck-Delegation` only):
  - `POST /diary/{person_id}/drafts`: body `{items, consumed_at?}`
  - `POST /diary/{person_id}/drafts/{draft_id}/confirm`
  - `POST /diary/{person_id}/entries/{entry_id}/revisions`: body `{items}`
  - `POST /diary/{person_id}/entries/{entry_id}/void`
  - `GET /diary/{person_id}/entries/{entry_id}`
  - `GET /diary/{person_id}/days/{date}`
  - `POST /diary/{person_id}/days/{date}/close`
  - `PUT /profile/{person_id}/mode`: body `{mode, due_date?}`
- Produces, MCP tools: `propose_intake`, `confirm_intake`, `correct_intake`, `void_intake`, `get_diary_entry`, `get_day_summary`, `close_day`, `set_nutrition_mode`, each taking `subject_person_id` first.
- Error mapping, REST status and body: `DraftNotFound`/`EntryNotFound` → 404 `NOT_FOUND`; `DraftExpired` → 409 `DRAFT_EXPIRED`; `ValueError` (including `PortionError`) → 400 `INVALID_ITEM`; `ProviderUnavailable` → 503 `PROVIDER_UNAVAILABLE`; existing 401/403/503 mapping unchanged. MCP returns `{"error": "<same code>"}`.

- [ ] **Step 1: Write the failing tests** with FastAPI `TestClient`, as `tests/test_boundaries.py` does: a full propose → confirm → day round trip; the 404, 409, 400 and 503 mappings; the MCP tool list contains the eight new names.
- [ ] **Step 2: Run** `PT services/nutrition/tests/test_diary_api.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the routes, tools and wiring.
- [ ] **Step 4: Run** `PT services/nutrition/tests packages/nutrition-domain/tests`. Expected: all PASS, including `test_boundaries.py` (no actor parameter on any new tool or route).
- [ ] **Step 5: Commit** `feat: expose the diary over REST and MCP`.

### Task 9: Current pregnancy reference values

**Files:**
- Modify: `services/nutrition/app/reference/pregnancy_targets.py`, any test asserting the old constants (search `tests/` for `"30"` with `iron_mg` and `"230"` with `iodine_ug`)
- Test: `services/nutrition/tests/test_stage_f.py`

- [ ] **Step 1: Write the failing test:**

```python
def test_reference_values_current():
    m = pregnancy_targets_map()
    assert m["iron_mg"] == Decimal("27") and m["iodine_ug"] == Decimal("220")
```

- [ ] **Step 2: Run** `PT services/nutrition/tests/test_stage_f.py`. Expected: FAIL (30 / 230).
- [ ] **Step 3: Update** iron (https://www.dge.de/wissenschaft/referenzwerte/eisen/) and iodine (https://www.dge.de/wissenschaft/referenzwerte/jod/). Check every other row against its cited DGE or EFSA page, and correct any that differ. Add the check date (2026-11-18 or later) to the module docstring.
- [ ] **Step 4: Run** `PT services/nutrition/tests`. Expected: all PASS.
- [ ] **Step 5: Commit** `fix: update pregnancy reference values to current DGE`.
