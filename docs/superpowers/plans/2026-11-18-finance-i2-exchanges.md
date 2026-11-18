# Olin Finance I2 (family exchanges) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner see, at any moment, who owes him what, in which currency and where that money is, what he holds for others and what he owes the exchange partner, with the bank feed as trigger and Telegram for the few questions the bank cannot answer.

**Architecture:** A new `app/receivables/` package inside `svc-finance`: an `Exchange` with lines plus an append-only per-counterparty running account (design approach B). A matcher runs after every sync and turns bank movements into fundings, receipts or pending questions. Two-phase commands carry every money-affecting write behind an explicit "Sí". The same service layer feeds the MCP tools (Hermes/Telegram) and REST routes (for I4a later).

**Tech Stack:** Python 3.13, FastAPI, FastMCP 4.0.3, SQLite (WAL, `BEGIN IMMEDIATE`), pytest; Hermes 0.21.2 skill + cron; Podman Quadlet on Nuremberg.

**Spec:** `docs/superpowers/specs/2026-11-18-finance-i2-exchanges-design.md` (Spanish). Section numbers below (`§6.2`, `E17`…) refer to it. Read it before any task.

## Global Constraints

- Public repo: **synthetic data only** in code, tests, docs and commit messages. Names like "Familiar A", "Fondo F", "socio". No real names, amounts, IBANs, phone numbers, references or frequencies.
- Money is `int` minor units + ISO currency. Never `float`. Strings enter through `app.money.parse_amount` and leave through `app.money.format_minor`.
- No tool or route accepts an actor, workspace, token, account id or SQL. Names are resolved by Finance.
- One Home request per operation through the existing `Authorizer` port. Reads use `Requirement("SELF","VIEW")`, writes use `Requirement("SELF","CREATE")`. The actor must hold role `OWNER` in the workspace. Any non-answer means nothing is read or written.
- Facts are append-only: every table in Task 3's "fact tables" list has `BEFORE UPDATE`/`BEFORE DELETE` triggers raising `facts are immutable`. Undo is a `revocation` row and/or a `REVERSAL` ledger entry.
- I2 only **adds** tables (`CREATE TABLE IF NOT EXISTS`). It never alters I1 tables.
- Logs carry kinds and counts only, never labels, aliases, notes or amounts.
- Constants (exact, from the spec): `NOTICE_BAND = 3 %`, `LINK_BAND = 8 %` (vs ECB), `EUR_ADJUST_TOLERANCE_MINOR = 100` (1,00 €), `FUND_ALERT_DEFAULT_MINOR = 50000` (500 USD), `HIGH_VALUE_USD_MINOR = 50000` (500 USD or equivalent), `EXACT_SUBSET_LIMIT = 16`, `RESURFACE_AFTER = 20 h`, Hermes cron at `06:35` and `18:35` UTC.
- Off limits: Nutrition files and `apps/home-hub/**` (Codex works in parallel; I4a is a later PR). No changes to `apps/episteck_home/**`.
- Git:
  - Commits use `git -c user.name="EKvargas" -c user.email="125833890+EKvargas@users.noreply.github.com" commit …` and end with the session line from the harness.
  - `gh` always with `--repo github.com/EKvargas/episteck_home` or `GH_HOST=github.com`.
  - **No stacked PRs:** each PR branches from the current `origin/main`, and the next starts only after the previous one merged.
  - Aim for ≤ 800 changed lines per PR.
- Production is run by the owner. Prepare exact `! ssh -F <ssh config> episteck-node1 '…'` commands with rollback; verify read-only afterwards. Real data stays on Nuremberg.
- Test command, from `services/finance` (called `FINTEST` below): `uv run --no-project --python 3.13 --with "fastapi>=0.140" --with uvicorn --with "pydantic>=2" --with httpx --with fastmcp==4.0.3 --with "pyjwt[crypto]" --with pytest python -m pytest`. Hermes tests, from the repo root: `uv run --no-project --python 3.13 --with pytest python -m pytest deploy/hermes/tests -q`. Before each PR, also run the Linux suite (WSL command in `docs/architecture/FINANCE_I1_PROGRESS.md` §4).

## Review Focus

1. **A `PENDING` movement already linked, later superseded by its `BOOKED` row.** Expect no second funding or receipt and no new question. Test in Task 9: `test_booked_successor_of_linked_pending_is_ignored`.
2. **Spanish-formatted amounts from the chat** ("1.250,50", "$275", "275$"). The skill normalises them. Finance rejects anything that is not a plain decimal with `validation_error` naming the field, and never misreads it. Test in Task 10: `test_non_plain_amount_is_a_validation_error`.
3. **One person with debts in USD and EUR at once** (a `debt_currency` override on one line). Balances stay per currency and allocation never crosses currencies. Test in Task 7: `test_receipt_never_allocates_across_currencies`.
4. **Alias variants** ("Mamá", "mama", " MAMA "). They resolve to one counterparty, and a duplicate alias is refused at setup. Test in Task 3: `test_alias_lookup_ignores_case_accents_and_spaces`, `test_duplicate_alias_is_rejected`.
5. **A race between chat and matcher:** the owner resolves `LINK_FUNDING` for a movement the matcher has just linked. Expect one funding and an `already_linked` result. Test in Task 6: `test_link_of_already_linked_movement_is_refused_without_side_effects`.

---

## PR map

| PR | Branch | Tasks |
| --- | --- | --- |
| 1 | `feature/finance-i2-exchanges` (holds the design commit) | 1, 2 |
| 2 | `feature/finance-i2-store` | 3, 4 |
| 3 | `feature/finance-i2-ledger` | 5, 6 |
| 4 | `feature/finance-i2-receipts` | 7, 8 |
| 5 | `feature/finance-i2-matcher` | 9 |
| 6 | `feature/finance-i2-tools` | 10, 11 |
| 7 | `feature/finance-i2-hermes` | 12 (needs Task 0 results) |
| — | (owner-run) | 13 deploy, live check, initial load |
| 8 (optional) | `feature/finance-i2-chat-import` | 14 |

Task 0 runs on the node in parallel with PRs 1–6.

---

### Task 0: Two spikes on the node (owner-run, no repo code)

**Files:** record results in `docs/architecture/FINANCE_I2_PROGRESS.md` (created in Task 1), section "Spikes". Facts only, no real data.

**Produces:** `S1 = BUTTONS | CODE_REPLY` plus the exact `hermes cron` invocation; `S2 = STABLE | UNSTABLE` plus the attachment path where Hermes stores files sent to the bot.

- [ ] **S1. Cron → Telegram with buttons.**
  1. Read-only: prepare `! ssh … 'sudo -u home-agent -H bash -lc "hermes cron --help; hermes --version"'` and read the installed Hermes docs for cron delivery and `clarify` buttons.
  2. Prepare a one-off test job. It runs at the next minute, delivers to the owner's Telegram, and its prompt asks the model to send one message with two inline buttons, "A" and "B", and then nothing else.
  3. The owner runs it and taps "A". Check the owner's next session receives the choice.
  4. Second job: its prompt says "if there is nothing to report, send nothing". Check it stays silent.
  5. Remove both jobs, with an explicit `hermes cron` remove command in the prepared script.
  6. Record whether buttons render and come back, whether silence works, and the exact create/list/remove syntax.
- [ ] **S2. Shape of USD-account credit descriptions (read-only).**
  1. The owner runs a Python snippet as `svc-finance` inside a throwaway `finance-api` image container (`podman run --rm -v /srv/episteck/services/finance/data:/data:ro,z localhost/episteck-finance:<live sha> python - <<'EOF' … EOF`).
  2. For credits (`amount_minor > 0`) of the USD accounts, the snippet prints only:
     - the count of credits;
     - the count of distinct `description_key` values (Task 2's rule, inlined);
     - per credit, a token-class template where letters → `A`, digits → `9`, and the known words `ZELLE`, `FROM`, `TRANSFER`, `ONLINE`, `BANKING`, `CONF`, `ID`, `PAYMENT` are kept.
  3. **No names, no amounts.**
  4. `STABLE` if repeated payers map to one key, otherwise `UNSTABLE`.
  5. Also locate (read-only, `ls -la`) the directory where Hermes stores documents sent to the bot.

---

### Task 1: ADR-0016, documentation pointers and the I2 board

**Files:**
- Create: `docs/architecture/adr/0016-finance-exchanges-ledger.md`, `docs/architecture/FINANCE_I2_PROGRESS.md`
- Modify: `docs/architecture/proposals/OLIN_FINANCE_V1.md` (§5.2, §6.5, §9.1, §11 I2 row, §16 P7), `docs/architecture/DATA_OWNERSHIP.md` (Finance row), `docs/architecture/STATUS.md` (new "Olin Finance I2" section)

- [ ] **Step 1: Write ADR-0016** (Status/Context/Decision/Consequences/Alternatives, ADR-0011 style). Decisions:
  - Finance writes its own receivables ledger, never money.
  - Approach B (spec §5).
  - Two-phase confirmation for money-affecting writes (spec §8.1).
  - Content-derived idempotency with `possible_duplicate`.
  - Level-3 actions in Telegram until I4a deploys (owner 2026-11-18), expiring when I4a ships.
  - The matcher runs inside the sync unit with no Home call. Its writes are attributed `machine_caller="sync"`, `human_actor=NULL`.
  - Amends ADR-0011 point 7.
- [ ] **Step 2: Add a one-line pointer** at the top of V1 §5.2, §6.5, §9.1 and the I2 row of §11: "Sustituido por `docs/superpowers/specs/2026-11-18-finance-i2-exchanges-design.md`". In §16 P7, replace "amigo en España" with "socio de cambio".
- [ ] **Step 3: Extend the DATA_OWNERSHIP Finance row** with "counterparties, exchanges, running accounts, pending questions (I2, ADR-0016)". Add a STATUS section: "I2 designed and in implementation; nothing deployed".
- [ ] **Step 4: Create the I2 board**, modelled on `FINANCE_I1_PROGRESS.md` §0 and §5: the task list of this plan with statuses, a "Spikes" section (Task 0) and a session log.
- [ ] **Step 5: Commit** `docs: add adr-0016 and the finance i2 board`.

---

### Task 2: Pure core: model, FX arithmetic, allocation, text keys

**Files:**
- Create: `services/finance/app/receivables/__init__.py`, `…/model.py`, `…/fx.py`, `…/allocation.py`, `…/text.py`
- Test: `services/finance/tests/test_receivables_core.py`

**Interfaces (Produces):**
- `model.py`:
  - Enums (all `str, Enum`):
    - `CounterpartyKind{PERSON, EXCHANGE_PARTNER, FUND}`
    - `Opening{UNKNOWN, APPROXIMATE, CONFIRMED}`
    - `EntryKind{CHARGE, PAYMENT, OPENING, ADJUSTMENT, FORGIVE, REVERSAL}`
    - `ReceiptKind{BANK, CASH, IN_KIND}`
    - `Verification{BANK_POSTED, OWNER_CONFIRMED}`
    - `AllocationMethod{AUTO_EXACT, AUTO_FIFO, OWNER}`
    - `PendingKind{LINK_FUNDING, PREVIOUS_UNPAID, EXPLAIN_INCOMING, CONFIRM, REVIEW_OPENING, INFO}`
    - `MovementRoleKind{EXCHANGE_FUNDING, RECEIVABLE_PAYMENT, FUND_DEPOSIT, NOT_EXCHANGE}`
  - Sentinels: `OWNER = "OWNER"`, `CASH_ABROAD = "CASH_ABROAD"`. The Global Constraints constants live here.
  - Frozen dataclasses, fields as in spec §6:
    - `Counterparty(id, workspace_id, kind, label, status, pay_currency=None, settles_to=None, opening=None, alert_below_minor=None)`
    - `Exchange(id, workspace_id, number, partner_id, total_usd_minor, delivered_on, created_at, ves_amount_minor=None, ves_reference_hash=None)`
    - `ExchangeLine(id, exchange_id, version, position, payer_id, usd_minor, debt_currency, beneficiary_note=None, eur_override_minor=None)`
    - `Funding(id, workspace_id, number, movement_ids, exchange_ids, eur_minor, usd_minor, created_at)`
    - `LedgerEntry(id, workspace_id, number, counterparty_id, currency, amount_minor, kind, effective_on, source_ref, note="", basis=None, reverses_id=None)`
    - `Receipt(id, workspace_id, number, kind, payer_id, currency, amount_minor, received_on, verification, movement_id=None, description="")`
    - `Allocation(id, workspace_id, receipt_id, line_id, amount_minor, method)`
    - `PendingItem(code, workspace_id, kind, requires_answer, options, payload, dedupe_key, created_at, delivered_at=None, resolved_at=None, resolution=None, snooze_until=None)`
  - Human refs: `C<n>` exchange, `F<n>` funding, `R<n>` receipt, `E<n>` entry, `P<n>` pending.
- `fx.py`:
  - `implied_rate(eur_minor: int, usd_minor: int) -> Fraction` gives EUR per USD; `ValueError` if either is ≤ 0.
  - `split_largest_remainder(total_minor: int, weights: Sequence[int]) -> list[int]`.
  - `deviation(implied: Fraction, usd_per_eur: Decimal) -> Fraction` is `abs(implied * usd_per_eur - 1)`.
  - `rate_text(rate: Fraction) -> str` gives 4 decimals, `ROUND_HALF_EVEN`.
- `allocation.py`:
  - `OpenLine(line_id: str, outstanding_minor: int, order: int)`
  - `AllocationPlan(method: AllocationMethod, parts: tuple[tuple[str, int], ...], remainder_minor: int)`
  - `plan_allocation(amount_minor: int, lines: Sequence[OpenLine], limit: int = EXACT_SUBSET_LIMIT) -> AllocationPlan`
- `text.py`:
  - `normalize_alias(text: str) -> str`: NFKD, accents dropped, casefold, whitespace collapsed, edge punctuation stripped.
  - `description_key(text: str) -> str`: upper case, every token containing a digit removed, the token right after a token ending in `#` removed (S2: confirmation codes can lack digits), whitespace collapsed; `""` if nothing remains.

- [ ] **Step 1: Write the failing tests**

```python
def test_implied_rate_is_exact():
    assert implied_rate(27600, 30000) == Fraction(23, 25)            # 0.92
    assert rate_text(implied_rate(27600, 30000)) == "0.9200"

def test_split_largest_remainder_sums_exactly_and_is_deterministic():
    assert split_largest_remainder(27600, [12000, 8000, 4000, 6000]) == [11040, 7360, 3680, 5520]
    assert split_largest_remainder(100, [1, 1, 1]) == [34, 33, 33]    # ties -> earlier index
    assert sum(split_largest_remainder(1001, [3, 7, 11])) == 1001

def test_deviation_against_ecb():
    assert deviation(Fraction(23, 25), Decimal("1.0870")) < Fraction(3, 100)
    assert deviation(Fraction(23, 25), Decimal("1.2000")) > Fraction(8, 100)

def test_exact_subset_prefers_oldest_combination():
    lines = [OpenLine("a", 5000, 1), OpenLine("b", 3000, 2), OpenLine("c", 2000, 3), OpenLine("d", 5000, 4)]
    plan = plan_allocation(5000, lines)
    assert plan.method is AllocationMethod.AUTO_EXACT and plan.parts == (("a", 5000),)
    plan = plan_allocation(8000, lines)
    assert plan.parts == (("a", 5000), ("b", 3000))

def test_fifo_with_remainder_when_no_exact_subset():
    plan = plan_allocation(9500, [OpenLine("a", 5000, 1), OpenLine("b", 3000, 2)])
    assert plan.method is AllocationMethod.AUTO_FIFO
    assert plan.parts == (("a", 5000), ("b", 3000)) and plan.remainder_minor == 1500

def test_exact_search_only_over_oldest_limit_lines():
    lines = [OpenLine(f"l{i}", 100, i) for i in range(20)] + [OpenLine("late", 7, 99)]
    assert plan_allocation(7, lines).method is AllocationMethod.AUTO_FIFO

def test_alias_and_description_keys():
    assert normalize_alias("  Mamá ") == normalize_alias("MAMA") == "mama"
    assert description_key("Zelle payment from A B Conf# 7Q2X9 11/14") == "ZELLE PAYMENT FROM A B CONF#"
```

- [ ] **Step 2: Run** `FINTEST tests/test_receivables_core.py -q`. Expected: FAIL (`ModuleNotFoundError: app.receivables`).
- [ ] **Step 3: Implement the four modules.**
  - Exact subset: enumerate subsets of the `limit` lines with the lowest `order`. Among those summing to `amount_minor`, take the lexicographically smallest sorted tuple of `order`s.
  - Otherwise FIFO by `order`.
  - `amount_minor <= 0` raises `ValueError`.
- [ ] **Step 4: Run** `FINTEST tests/test_receivables_core.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add finance receivables core types and arithmetic`. Then open PR 1 (Tasks 1–2 plus the design commit already on the branch), titled `feat: finance i2 design, adr-0016 and core types`.

---

### Task 3: Schema and repository

**Files:**
- Create: `services/finance/app/store/receivables_schema.py`, `services/finance/app/store/receivables_repo.py`
- Modify: `services/finance/app/store/db.py` (`init_schema` also runs `SCHEMA_I2`)
- Test: `services/finance/tests/test_receivables_store.py`

**Interfaces:**
- Consumes: `FinanceRepository` (`connection()`, `hash_iban()`), `db.write_tx`, Task 2 types.
- Produces: `ReceivablesRepository(base: FinanceRepository)`. **Every method takes an open `conn` as its first argument.**
  - Transactions: `tx()` is a context manager yielding a connection inside `BEGIN IMMEDIATE`; `read()` yields a plain connection.
  - `hash_key(text: str) -> str` delegates to `base.hash_iban`.
  - `next_number(conn, ws, prefix: str) -> int`, per workspace and prefix, starting at 1.
  - Counterparties:
    - `insert_counterparty(conn, cp: Counterparty, aliases: Sequence[str]) -> None` raises `DuplicateAlias(alias)`.
    - `find_by_alias(conn, ws, text) -> list[Counterparty]`, `get_counterparty(conn, ws, id)`, `list_counterparties(conn, ws)`.
  - Exchanges and fundings:
    - `insert_exchange(conn, ex: Exchange, lines: Sequence[ExchangeLine])`, `current_lines(conn, exchange_id) -> list[ExchangeLine]` (max `version`).
    - `open_exchanges(conn, ws) -> list[Exchange]` (no live funding), `exchange_by_ref(conn, ws, ref)`, `exchange_by_ves_hash(conn, ws, h)`.
    - `insert_funding(conn, f: Funding, shares: Mapping[str, int])`, `live_funding_for_exchange(conn, exchange_id)`, `live_funding_for_movement(conn, movement_id)`, `funding_shares(conn, funding_id) -> dict[str, int]`.
  - Ledger and receipts:
    - `insert_entry(conn, e: LedgerEntry)`, `balance(conn, ws, cp_id, currency) -> int` (live entries), `balances(conn, ws) -> dict[tuple[str, str], int]`, `entries(conn, ws, cp_id) -> list[LedgerEntry]`.
    - `insert_receipt(conn, r: Receipt)`, `insert_allocation(conn, a: Allocation)`.
    - `open_lines(conn, ws, payer_id, currency) -> list[OpenLine]`: live `CHARGE` amount minus live allocations, > 0, `order` = exchange number × 100 + position.
    - `receipt_remainders(conn, ws, payer_id, currency) -> list[tuple[Receipt, int]]`, oldest first.
  - Revocation and rules:
    - `revoke(conn, ws, table: str, target_id: str, reason: str, at: datetime)`, `is_live(conn, table, target_id) -> bool`.
    - `insert_payer_rule(conn, ws, key_hash, counterparty_id | None)`, `rule_for(conn, ws, key_hash) -> str | None | Literal["IGNORE"]`.
    - `add_partner_identifier(conn, ws, iban_hash, cp_id)`, `partner_hashes(conn, ws) -> dict[str, str]`, `add_own_identifier(conn, ws, iban_hash)`, `own_hashes(conn, ws) -> set[str]`.
    - `set_watch(conn, ws, account_id, on: bool)`, `watched_accounts(conn, ws) -> set[str]`.
  - Movements:
    - `insert_movement_role(conn, ws, movement_id, role)`, `movement_role(conn, movement_id) -> MovementRoleKind | None`.
    - `movement_root(conn, movement_id) -> str` follows `supersedes_id`.
    - `movements_after(conn, ws, rowid) -> list[tuple[int, Movement]]`, `get_cursor(conn, ws) -> int`, `set_cursor(conn, ws, rowid)`.
  - Other: `insert_held_cash(conn, ws, cp_id, currency, amount_minor, stated_on)`, `latest_held_cash(conn, ws, cp_id, currency) -> tuple[int, date] | None`, `usd_per_eur_on(conn, day: date) -> Decimal | None` (latest `fx_rate` USD row with `date <= day`), `log_intervention(conn, ws, kind, at)`, `interventions_in_month(conn, ws, year, month) -> int`, `member_role(conn, ws, person_id) -> str | None`.
- Fact tables (immutability triggers): `exchange`, `exchange_line`, `funding`, `funding_movement`, `funding_exchange`, `funding_share`, `ledger_entry`, `receipt`, `allocation`, `held_cash_statement`, `payer_rule`, `movement_role`, `revocation`, `intervention_log`, `partner_identifier`, `own_identifier`.
- Mutable tables: `counterparty`, `counterparty_alias`, `account_watch`, `pending_item`, `ref_counter`, `matcher_cursor`.
- Every table has `workspace_id`.
- `receipt.movement_id` is `UNIQUE` when not null. `funding_movement.movement_id` stores the **root** movement id.

- [ ] **Step 1: Write the failing tests**

```python
def test_init_adds_i2_tables_without_touching_i1(tmp_path):
    repo = make_repo(tmp_path); before = column_names(repo, "movement")
    ReceivablesRepository(repo)
    assert {"exchange", "ledger_entry", "pending_item", "revocation"} <= set(table_names(repo))
    assert column_names(repo, "movement") == before

@pytest.mark.parametrize("table", FACT_TABLES)
def test_fact_tables_reject_update_and_delete(tmp_path, table): ...   # raw UPDATE/DELETE -> IntegrityError "facts are immutable"

def test_alias_lookup_ignores_case_accents_and_spaces(tmp_path):   # "Mamá" stored; " MAMA " finds it
def test_duplicate_alias_is_rejected(tmp_path):                     # second cp with alias "mama" -> DuplicateAlias
def test_balance_sums_live_entries_only(tmp_path):                  # +12000, +5000, revoke the 5000 -> 12000
def test_open_lines_subtract_live_allocations(tmp_path):            # CHARGE 12000, allocation 5000 -> outstanding 7000
def test_movement_root_follows_supersedes_chain(tmp_path):
def test_usd_per_eur_on_uses_latest_rate_not_after_day(tmp_path):
def test_next_number_is_per_prefix_and_workspace(tmp_path):         # C1, C2, P1 independent
```

- [ ] **Step 2: Run** `FINTEST tests/test_receivables_store.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `SCHEMA_I2` and `ReceivablesRepository` with the signatures above. "Live" means no `revocation` row for `(table, id)`. Aliases are stored normalised with `normalize_alias`.
- [ ] **Step 4: Run** the new test file plus the whole suite: `FINTEST tests -q`. Expected: PASS, I1 tests unchanged.
- [ ] **Step 5: Commit** `feat: add finance receivables schema and repository`.

---

### Task 4: Pending queue and intervention log

**Files:**
- Create: `services/finance/app/receivables/pending.py`
- Test: `services/finance/tests/test_receivables_pending.py`

**Interfaces:**
- Consumes: Task 3 repository.
- Produces: `PendingQueue(repo, clock)`:
  - `add(conn, ws, kind, options: Sequence[str], payload: dict, dedupe_key: str, requires_answer: bool = True) -> PendingItem` returns the existing unresolved item when `dedupe_key` matches.
  - `notice(conn, ws, text_key: str, payload: dict) -> PendingItem` is `INFO`, `requires_answer=False`, deduped by `text_key`.
  - `for_delivery(conn, ws) -> list[PendingItem]`: undelivered items, plus answer-requiring unresolved items whose last delivery is older than `RESURFACE_AFTER` and that are not snoozed. It sets `delivered_at=now` and marks `INFO` items resolved.
  - `get(conn, ws, code) -> PendingItem | None`.
  - `resolve(conn, ws, code, resolution: str, *, human: bool) -> PendingItem` raises `UnknownPending` / `AlreadyResolved(resolution)`; logs one intervention when `human`.
  - `open_items(conn, ws) -> list[PendingItem]`.
- `payload` is JSON-serialisable and never holds a raw IBAN or image.

- [ ] **Step 1: Write the failing tests:**
  - `test_dedupe_returns_same_open_item`
  - `test_codes_are_p1_p2_sequential`
  - `test_for_delivery_marks_delivered_and_resolves_info`
  - `test_unanswered_question_resurfaces_after_20h_not_before` (clock at +19 h → empty; +21 h → returned)
  - `test_resolve_twice_raises_already_resolved_with_first_resolution`
  - `test_human_resolution_logs_one_intervention_and_system_none`
- [ ] **Step 2: Run** `FINTEST tests/test_receivables_pending.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `PendingQueue` per the interface.
- [ ] **Step 4: Run** it. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add finance pending queue`. Open PR 2 (Tasks 3–4).

---

### Task 5: Ledger: record an exchange and the receivables view

**Files:**
- Create: `services/finance/app/receivables/ledger.py`
- Test: `services/finance/tests/test_receivables_ledger.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - Inputs and errors:
    - `LineInput(payer_id: str, usd_minor: int, debt_currency: str | None = None, beneficiary_note: str | None = None, eur_override_minor: int | None = None)`
    - `Evidence(ves_amount_minor: int | None, ves_reference: str | None, delivered_on: date | None)`
    - `class ValidationError(Exception)` with `.field`, `.detail: dict` (figures as strings).
  - `record_exchange(repo, conn, ws, *, partner_id, total_usd_minor, lines: Sequence[LineInput], evidence: Evidence | None, now) -> Exchange`:
    - Errors: `ValidationError("lines_total", {"total": …, "sum": …})` when Σ ≠ total; `"payer"` when a payer is unknown or a `EXCHANGE_PARTNER`; `"possible_duplicate"` handled by the caller through `exchange_by_ves_hash`.
    - `debt_currency` defaults to the payer's `pay_currency` (`FUND` → its USD; `OWNER` → `None`).
    - `CHARGE` entries: USD `PERSON` lines and every `FUND` line, `effective_on` = `delivered_on`.
    - `delivered_on` = evidence date, else today.
    - The VES reference is stored only as `repo.hash_key(reference)` in `ves_reference_hash`; the VES amount is kept as evidence and never valued.
  - `receivables_view(repo, conn, ws, now) -> dict` with exactly these keys (amounts via `format_minor`, dates ISO):
    - `as_of`
    - `owed_to_you`: list of `{counterparty, currency, amount, where, held_cash, opening, lines: [{exchange_ref, delivered_on, usd, debt, outstanding, currency}]}`
    - `to_fix`: list of `{counterparty, exchange_ref, usd}`
    - `held_for_others`: list of `{counterparty, kind, currency, amount | None, opening, since, out_since, in_since, account}`
    - `owed_to_partner`: `{currency: "USD", amount, exchanges: [{exchange_ref, delivered_on, usd}]}`
    - `subtotals`: `{owed_to_you: {cur: amount}, held_for_others: {cur: amount}}`
    - `interventions_this_month`
  - `where` is the label of the `settles_to` account, or `"CASH_ABROAD"`.
  - Funds with `opening=UNKNOWN`: `amount` is `null`, and `out_since`/`in_since` are Σ charges and Σ deposits since creation.
  - A `PERSON` with a negative balance is listed in `held_for_others` (prepayment).

- [ ] **Step 1: Write the failing tests** (E1 figures):
  - `test_record_exchange_creates_lines_and_usd_charges`: lines A 12000 USD, B 8000 EUR, OWNER 4000, F 6000. Charges: A +12000 USD, F +6000 USD, none for B or OWNER. `to_fix == [{"counterparty": "Familiar B", "exchange_ref": "C1", "usd": "80.00"}]`.
  - `test_lines_must_sum_to_total`: `ValidationError` with `field == "lines_total"`, `detail == {"total": "300.00", "sum": "290.00"}`.
  - `test_partner_cannot_be_a_payer`
  - `test_owed_to_partner_lists_open_exchanges`: `amount == "300.00"`.
  - `test_fund_with_unknown_opening_shows_flows_not_balance`
  - `test_prepaid_person_appears_in_held_for_others`
  - `test_currencies_are_never_summed_in_subtotals`
- [ ] **Step 2: Run** `FINTEST tests/test_receivables_ledger.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `record_exchange` and `receivables_view`.
- [ ] **Step 4: Run** it. Expected: PASS.
- [ ] **Step 5: Commit** `feat: record exchanges and the receivables view`.

---

### Task 6: Funding: link partner payments, rate, EUR shares

**Files:**
- Create: `services/finance/app/receivables/funding.py`
- Test: `services/finance/tests/test_receivables_funding.py`

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces:
  - `create_funding(repo, conn, ws, movement_ids: Sequence[str], exchange_ids: Sequence[str], queue: PendingQueue, now) -> Funding`, which:
    - stores root movement ids;
    - computes `implied_rate`;
    - computes shares with `split_largest_remainder` over the current lines (ordered by exchange `number`, then `position`);
    - writes `funding_share`;
    - writes EUR `CHARGE`s for `PERSON` lines with `debt_currency=EUR` (`eur_override_minor` wins);
    - consumes EUR credits FIFO (calls Task 7's `consume_credits`; until Task 7 exists, leave a no-op seam named `consume_credits`);
    - writes movement roles `EXCHANGE_FUNDING`;
    - emits an INFO notice `funding_closed`, and `rate_outlier` when `deviation > NOTICE_BAND`.
  - `try_link(repo, conn, ws, movement: Movement, queue: PendingQueue, now) -> Literal["LINKED", "WAITING", "AMBIGUOUS", "ALREADY_LINKED"]`, applying spec §6.2 rules 1–5:
    - candidates: `delivered_on <= movement date`;
    - compatibility: `deviation <= LINK_BAND`; with no ECB rate, every candidate counts as compatible;
    - pooled unlinked partner payments (movements with role absent and IBAN in `partner_hashes`) try a combined link;
    - `AMBIGUOUS` creates `LINK_FUNDING` with options `["C<n>" …, "ALL", "REGISTER", "NOT_EXCHANGE"]`.
  - `link_choice(repo, conn, ws, movement_id, choice: str, queue, now) -> dict` serves the `LINK_FUNDING` and `PREVIOUS_UNPAID` resolutions:
    - `ADD_TO:C<n>` revokes that funding and recreates it with the extra movement.
    - Picking a movement in `PREVIOUS_UNPAID` also calls `add_partner_identifier` with its IBAN hash.
    - Returns `{"ok": False, "error": "already_linked"}` without side effects if the movement already has a live funding.
  - `reverse_funding(repo, conn, ws, funding_id, reason, queue, now)`:
    - revokes the funding and its roles;
    - writes `REVERSAL`s of its EUR charges;
    - revokes allocations on those lines;
    - re-raises `LINK_FUNDING` for its movements.

- [ ] **Step 1: Write the failing tests:**
  - `test_e1_single_open_exchange_links_automatically`: −27600 EUR to a partner IBAN; shares 11040/7360/3680/5520; B `CHARGE` +7360 EUR; `funding_closed` notice; rate "0.9200".
  - `test_e17_next_exchange_registered_before_sync_does_not_block_link`: C1 300 USD delivered 13/11; payment 20/11; C2 200 USD delivered 20/11. The payment is compatible with C1 only → LINKED, no question.
  - `test_e4_two_compatible_open_exchanges_ask`: pending options include `"ALL"`.
  - `test_e12_outlier_links_with_notice_and_far_outlier_waits`: +5 % → LINKED + `rate_outlier`; −12 % → WAITING, no pending yet.
  - `test_split_payment_links_when_pool_is_compatible`: two payments 13800 + 13800 for C1 → one funding with both movements.
  - `test_eur_override_wins_over_share`
  - `test_link_of_already_linked_movement_is_refused_without_side_effects` (Review Focus 5)
  - `test_reverse_funding_restores_open_state_and_asks_again`
- [ ] **Step 2: Run** `FINTEST tests/test_receivables_funding.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per the interface.
- [ ] **Step 4: Run** it. Expected: PASS.
- [ ] **Step 5: Commit** `feat: link partner payments to exchanges`. Open PR 3 (Tasks 5–6).

---

### Task 7: Receipts, allocation, credits, held cash, small-difference adjustment

**Files:**
- Create: `services/finance/app/receivables/receipts.py`
- Modify: `services/finance/app/receivables/funding.py` (wire the real `consume_credits`)
- Test: `services/finance/tests/test_receivables_receipts.py`

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces:
  - `record_receipt(repo, conn, ws, *, kind: ReceiptKind, payer_id, currency, amount_minor, received_on, verification, movement_id=None, description="", queue, now) -> Receipt`, which:
    - writes a `PAYMENT` (−amount);
    - allocates with `plan_allocation` over `open_lines(payer, currency)`;
    - leaves any remainder as credit;
    - applies the ≤ 1,00 € rule for EUR only: if the payer's EUR balance was > 0 before and is within `[-100, 100]` and ≠ 0 after, writes `ADJUSTMENT` of −balance plus an INFO `small_difference_closed`;
    - emits an INFO `receipt_applied` with the refs of the covered exchanges.
  - `IN_KIND` requires a non-empty `description`. A `FUND` payer means a deposit, with role `FUND_DEPOSIT`; otherwise the role is `RECEIVABLE_PAYMENT`.
  - `consume_credits(repo, conn, ws, payer_id, currency) -> None`: FIFO over `receipt_remainders` × `open_lines`, `method=AUTO_FIFO`.
  - `reallocate(repo, conn, ws, receipt_id, parts: Sequence[tuple[str, int]], now) -> None`: revokes and inserts `OWNER` allocations; invariants per spec §6.3; `ValidationError` with figures.
  - `mark_held_cash(repo, conn, ws, cp_id, currency, amount_minor, now) -> None`.
  - `held_cash_shown(repo, conn, ws, cp_id, currency) -> int | None` = `min(stated − cash receipts since the statement, balance)`, floored at 0.

- [ ] **Step 1: Write the failing tests:**
  - `test_e1_bank_receipts_close_balances`
  - `test_e2_prepayment_is_credit_then_consumed_at_funding`: B −5000 EUR → funding → `CHARGE` 7360 → balance 2360; allocation `AUTO_FIFO`.
  - `test_e3_exact_subset_and_fifo_with_remainder`
  - `test_e18_small_difference_closes_and_larger_stays`: 7300 → ADJUSTMENT 60, balance 0; 7500 → balance −140, no adjustment.
  - `test_in_kind_requires_description`
  - `test_receipt_never_allocates_across_currencies` (Review Focus 3)
  - `test_e8_held_cash_display_follows_cash_receipts`: 15000 stated, 10000 cash → 5000.
  - `test_fund_deposit_increases_what_you_hold`
  - `test_reallocate_respects_invariants`
- [ ] **Step 2: Run** `FINTEST tests/test_receivables_receipts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per the interface.
- [ ] **Step 4: Run** the full `FINTEST tests -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: record receipts and allocate them to exchanges`.

---

### Task 8: Corrections, forgiveness and generic reversal

**Files:**
- Create: `services/finance/app/receivables/corrections.py`
- Test: `services/finance/tests/test_receivables_corrections.py`

**Interfaces:**
- Consumes: Tasks 2–7.
- Produces:
  - `correct_exchange(repo, conn, ws, exchange_id, lines: Sequence[LineInput], total_usd_minor: int | None, reason, now) -> Exchange`. It does, in order:
    1. Refuses with `ValidationError("below_collected", {"payer": label, "collected": …, "new": …})` if any payer's live allocations on this exchange exceed their new debt on it.
    2. Writes version n+1 lines.
    3. Writes `REVERSAL` for every live `CHARGE` of the old lines.
    4. Writes new USD charges.
    5. If a live funding exists, recomputes its shares with the new weights (same funding EUR), writes new `funding_share` rows (replacement noted in `revocation`) and new EUR charges.
    6. Revokes the old lines' allocations and re-runs `consume_credits` for the affected payers.
  - `forgive(repo, conn, ws, target_ref: str, amount_minor: int | None, reason, now) -> LedgerEntry`, where the target is `C<n>:<payer label>` or a counterparty; default = outstanding.
  - `record_opening(repo, conn, ws, cp_id, currency, amount_minor, basis: Opening, note: str, now) -> LedgerEntry`. `note` is required. For a `FUND`, `amount_minor` is what you hold, stored negative, and the counterparty's `opening` is updated.
  - `reverse(repo, conn, ws, ref: str, reason, queue, now) -> dict`, which dispatches on prefix:
    - `F` → `reverse_funding`;
    - `R` → revoke the receipt and its allocations, `REVERSAL` of its `PAYMENT`, re-run `consume_credits`; a `BANK` receipt also raises `EXPLAIN_INCOMING` again;
    - `E` → `REVERSAL` of an `OPENING`/`ADJUSTMENT`/`FORGIVE`;
    - `C` → reverse a whole exchange (refused while a live funding exists);
    - payer rule by counterparty label + `"rule"` → revoke.

- [ ] **Step 1: Write the failing tests:**
  - `test_e11_correct_paid_exchange_recomputes_eur_shares_and_allocations`
  - `test_correction_below_collected_is_refused_with_figures`
  - `test_forgive_defaults_to_outstanding`
  - `test_opening_requires_note`
  - `test_fund_opening_replaces_unknown`
  - `test_reverse_bank_receipt_asks_again`
  - `test_reverse_exchange_with_live_funding_is_refused`
  - `test_history_keeps_every_version` (`entries()` shows the reversed and the new entries)
- [ ] **Step 2: Run** `FINTEST tests/test_receivables_corrections.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: correct, forgive and reverse receivables facts`. Open PR 4 (Tasks 7–8).

---

### Task 9: Matcher after each sync, and operator commands

**Files:**
- Create: `services/finance/app/receivables/matcher.py`
- Modify: `services/finance/app/sync.py` (`main()` runs the matcher after `engine.run`, even if a connection failed, and logs counts only), `services/finance/app/admin.py` (subcommands `watch-account <account_id> on|off` and `own-iban <account_id>`; `own-iban` reads the IBAN from stdin without echo and stores only its hash)
- Test: `services/finance/tests/test_receivables_matcher.py`, extend `tests/test_admin.py`

**Interfaces:**
- Consumes: Tasks 2–8. `Settings` gains `description_rules: bool` from `FINANCE_DESCRIPTION_RULES` (default `off`; Task 13 sets it from S2).
- Produces: `Matcher(repo, queue, clock, description_rules: bool).run(ws, sync_started_at: datetime) -> dict[str, int]`. Counts keys: `linked`, `waiting`, `asked`, `receipts`, `ignored`. The run:
  1. Takes movements after the cursor. Skips one whose root already has a role, funding or receipt.
  2. **Outgoing EUR to a partner IBAN** → `try_link`.
  3. **Incoming on a watched account:**
     - IBAN in `own_hashes` → nothing;
     - `rule_for` the key → `IGNORE` (`NOT_EXCHANGE` role) or a counterparty (BANK receipt);
     - no rule → `EXPLAIN_INCOMING`.
     - The key is the IBAN hash if present, else the `description_key` hash, used only when `description_rules`.
     - Options: the unique exact-match payer first (outstanding or exact subset), then the others with a balance in that currency, then `OTHER`, `NOT_EXCHANGE`.
  4. **Previous exchange unpaid:** for each exchange registered before `sync_started_at` while an older exchange is still OPEN → `PREVIOUS_UNPAID` for the older one. Options: up to 8 unlinked outgoing EUR movements of the last 30 days, each as `M:<movement_id>` with a label `dd/mm · amount · counterparty_name[:20]`, plus `NOT_YET`.
  5. **Waiting payments:** those that waited through one previous run → `LINK_FUNDING`.
  6. **Funds:** a fund with a known opening crossing below its alert → notice `fund_low` (dedupe per crossing).
  7. **Opening review:** a counterparty with an `APPROXIMATE` or `UNKNOWN` opening → `REVIEW_OPENING` once per ISO week, during its first 4 weeks only (options `CONFIRM`, `LATER`).
  8. Advances the cursor.
- `resolve_explain_incoming(repo, conn, ws, movement_id, choice, queue, now)`: a counterparty choice → payer rule (when a key exists) + BANK receipt; `NOT_EXCHANGE` → `IGNORE` rule + role.

- [ ] **Step 1: Write the failing tests:**
  - `test_e6_unknown_credit_asks_then_rule_makes_next_automatic`
  - `test_e6_salary_ignored_after_one_answer`
  - `test_own_iban_credit_is_never_asked`
  - `test_description_rules_off_asks_every_time_with_exact_match_first`
  - `test_booked_successor_of_linked_pending_is_ignored` (Review Focus 1)
  - `test_previous_unpaid_only_after_a_sync_following_registration`
  - `test_previous_unpaid_pick_learns_partner_iban`
  - `test_waiting_payment_becomes_question_on_next_run`
  - `test_fund_low_notice_once_per_crossing`
  - `test_review_opening_weekly_for_first_four_weeks`
  - `test_matcher_logs_counts_only` (caplog has no label or amount)
  - `test_admin_own_iban_stores_hash_only`
- [ ] **Step 2: Run** `FINTEST tests/test_receivables_matcher.py tests/test_admin.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the matcher, the `sync.main` hook and the admin subcommands.
- [ ] **Step 4: Run** the full suite plus `deploy/finance/tests`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: match bank movements to exchanges after sync`. Open PR 5.

---

### Task 10: Commands and `ReceivablesService`

**Files:**
- Create: `services/finance/app/receivables/commands.py`, `services/finance/app/receivables/service.py`
- Modify: `services/finance/app/deps.py` (`build_receivables_service(settings=None) -> ReceivablesService`, same authorizer factory)
- Test: `services/finance/tests/test_receivables_service.py`

**Interfaces:**
- Consumes: everything above; `service.SessionInvalid/AccessDenied/PolicyUnavailable/FeatureOff`; `Authorizer`, `Requirement`, `SELF`.
- Produces: `ReceivablesService(repo: FinanceRepository, authorizer, workspace_id, clock)`. Every public method takes `delegation: str | None` first and authorizes once (VIEW for reads, CREATE for writes; actor role `OWNER`; workspace `ACTIVE`).
  - Reads: `receivables(delegation, counterparty: str | None = None) -> dict` (Task 5 view, optionally filtered), `exchanges(delegation, status: str | None = None, since: str | None = None) -> dict`, `pending(delegation, for_delivery: bool = False) -> dict`, `explain(delegation, ref: str) -> dict`.
  - Proposals, all two-phase, return `{"ok": True, "status": "confirmation_required" | "possible_duplicate", "code": "P<n>", "echo": {...}, "high_value": bool}`:
    - `propose_exchange(delegation, total_usd: str, lines: list[dict], evidence: dict | None, delivered_on: str | None)`
    - `propose_receipt(delegation, payer: str, amount: str, currency: str, kind: str, received_on: str | None, description: str | None)`
    - `propose_correction(delegation, exchange_ref, lines, total_usd: str | None, reason)`
    - `propose_forgive(delegation, target, amount: str | None, reason)`
    - `propose_opening(delegation, counterparty, amount: str, currency, basis, note)`
    - `propose_counterparty(delegation, label, kind, aliases: list[str], pay_currency: str | None, settles_to: str | None, alert_below: str | None)`
    - `propose_reverse(delegation, ref, reason)`
    - `propose_reallocate(delegation, receipt_ref, allocations: list[dict])`
  - Direct (level 1): `mark_held_cash(delegation, counterparty, amount: str, currency) -> dict`, `resolve(delegation, code: str, choice: str, details: dict | None = None) -> dict`.
- Rules:
  - **Proposals:** parse every amount with `parse_amount`; a failure → `{"ok": False, "error": "validation_error", "field": …}`. Resolve names with `find_by_alias`; zero or several matches → `{"ok": False, "error": "clarification_needed", "field": …, "candidates": [labels]}`.
  - **Keys and duplicates:** `key = sha256(type + canonical payload + UTC date)`.
    - An open `CONFIRM` with `dedupe_key == key` → return it.
    - A `command_log` row with that key → `possible_duplicate` (a new `CONFIRM` whose payload carries `nonce`).
    - For exchanges, an existing `ves_reference` hash → `possible_duplicate`.
  - **`resolve(code, "yes")` on a `CONFIRM`:** runs the stored payload through `FinanceRepository.run_command` with `key` (or `key:nonce`), `human_actor=actor`, `machine_caller="finance-mcp"` or `"finance-api"`, `channel="telegram"` or `"web"`. The effect function lives in `commands.py`, keyed by command type. `"no"`/`"cancel"` resolves without effect.
  - Other pending kinds dispatch to `link_choice` / `resolve_explain_incoming` / the review-opening handler.
  - **Review-opening handler:** `CONFIRM` re-records an `APPROXIMATE` opening with basis `CONFIRMED` (a `REVERSAL` plus a new `OPENING`, same amount). For an `UNKNOWN` fund it writes nothing and returns `{"ok": True, "status": "needs_amount"}`. `LATER` snoozes 7 days.
  - **`high_value`:** cash or in-kind amount ≥ `HIGH_VALUE_USD_MINOR` in USD, or its ECB-converted EUR (no rate → `True`); and any reversal of `F`, a `BANK` `R`, or a rule.
  - **Errors:** `ValidationError` → `{"ok": False, "error": "validation_error", "field": …, "detail": …}`. `IdempotencyConflict` → `{"ok": False, "error": "idempotency_conflict"}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_reads_authorize_view_self_once_and_writes_create_self_once`: `FakeAuthorizer.calls` has one batch with `Requirement("SELF","VIEW")`, then `("SELF","CREATE")`.
  - `test_non_owner_member_is_denied` (role `MEMBER` → `AccessDenied`)
  - `test_home_unavailable_writes_nothing` (`count_rows` unchanged)
  - `test_proposal_writes_nothing_until_yes`
  - `test_agent_retry_returns_same_confirm`
  - `test_identical_command_after_completion_is_possible_duplicate_and_es_otro_records_it`
  - `test_same_ves_reference_is_possible_duplicate`
  - `test_non_plain_amount_is_a_validation_error` (Review Focus 2: `"1.250,50"`)
  - `test_ambiguous_alias_returns_candidates`
  - `test_high_value_cash_and_bank_reversal_are_flagged`
  - `test_resolve_logs_intervention_and_audit_actor`
  - `test_e7_cash_in_kind_and_high_value`
  - `test_e15_feature_off_for_paused_workspace`
  - `test_e14_effect_failure_leaves_no_partial_rows` (an exception inside the effect: no `command_log` row and no fact rows; the `CONFIRM` stays open)
- [ ] **Step 2: Run** `FINTEST tests/test_receivables_service.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `commands.py` (one effect per command type) and `service.py`.
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add the receivables service with two-phase commands`.

---

### Task 11: MCP tools and REST routes

**Files:**
- Create: `services/finance/app/mcp/receivables_tools.py` (`register_receivables_tools(mcp: FastMCP, service: ReceivablesService) -> None`), `services/finance/app/api_receivables.py` (`create_receivables_router(service) -> APIRouter`)
- Modify: `services/finance/app/mcp/server.py` (`create_mcp(service, receivables: ReceivablesService | None = None)`; the `__main__` block builds both), `services/finance/app/api.py` (`create_app(service, callback=None, receivables=None)` includes the router), `services/finance/app/main.py` if it builds the app
- Test: `services/finance/tests/test_receivables_transport.py` (real FastMCP HTTP server and `TestClient`, the pattern of `test_mcp_transport.py`)

**Interfaces:**
- MCP tool names and parameters exactly as spec §8.1, plus `finance_record_opening(counterparty, amount, currency, basis, note)`. The tools are:
  `finance_receivables`, `finance_exchanges`, `finance_pending`, `finance_explain`, `finance_record_exchange`, `finance_record_receipt`, `finance_resolve_pending`, `finance_mark_held_cash`, `finance_correct_exchange`, `finance_reallocate`, `finance_forgive`, `finance_setup_counterparty`, `finance_record_opening`, `finance_reverse`.
- Each tool calls `service.<method>(current_delegation(), …)` and maps the refusals with the existing `_REFUSALS` table.
- REST:
  - `GET /receivables`, `GET /exchanges`, `GET /pending` (query `for_delivery`).
  - `POST /commands/{type}`, where the body is the tool's arguments and `type` ∈ {`exchange`, `receipt`, `correction`, `forgive`, `opening`, `counterparty`, `reverse`, `reallocate`, `held_cash`}.
  - `POST /pending/{code}/resolve` with body `{choice, details?}`.
  - Delegation from the `X-Episteck-Delegation` header via `human_session`; refusals via `_authorized`.
- No parameter named `actor`, `workspace`, `account`, `token`, `sql` anywhere.

- [ ] **Step 1: Write the failing tests:**
  - `test_every_tool_is_registered_with_no_forbidden_parameter` (inspect the tool schemas)
  - `test_mcp_and_rest_return_identical_receivables` (E15)
  - `test_mcp_two_phase_exchange_over_http_with_header_delegation`
  - `test_rest_resolve_requires_delegation_header` (401 without it)
  - `test_refusal_codes_match_overview_tool`
- [ ] **Step 2: Run** `FINTEST tests/test_receivables_transport.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the tools, the router and the wiring.
- [ ] **Step 4: Run** the full suite plus the Linux suite (WSL). Expected: PASS.
- [ ] **Step 5: Commit** `feat: expose receivables over mcp and rest`. Open PR 6 (Tasks 10–11).

---

### Task 12: Hermes skill, cron and runbook (after Task 0)

**Files:**
- Modify: `deploy/hermes/home-agent/skills/olin-finance/SKILL.md`, `deploy/hermes/install-olin-finance.sh` (new step `cron` and its rollback), `deploy/hermes/tests/test_olin_finance_skill.py`, `docs/runbooks/finance-i1-nuremberg-bringup.md` (new I2 section, or a new `docs/runbooks/finance-i2-exchanges.md` linked from it)

**Interfaces:**
- Consumes: Task 11 tool names; Task 0 S1 syntax and outcome.

- [ ] **Step 1: Update the tests first:**
  - `requires_tools` lists `finance_overview`, `finance_receivables`, `finance_record_exchange`, `finance_record_receipt`, `finance_resolve_pending`, `finance_pending`.
  - New `test_skill_covers_every_receivables_tool_and_error_code`: every tool from Task 11 and the codes `validation_error`, `clarification_needed`, `possible_duplicate`, `idempotency_conflict`, `already_linked` appear in the skill.
  - New `test_skill_forbids_confirming_without_the_owner_tap`.
  - New `test_install_script_has_cron_step_with_rollback`.
  - Existing `test_skill_contains_no_example_figures_the_model_could_repeat` still passes.
- [ ] **Step 2: Run** the Hermes tests. Expected: FAIL.
- [ ] **Step 3: Rewrite the skill sections** (Spanish answers, rules from spec §8.3):
  - when to call each tool;
  - amount normalisation ("1.250,50" → "1250.50"; "$275"/"275$" → "275.00"; never convert VES);
  - the echo + buttons flow (`[Sí] [Corregir] [Cancelar]`, plus code replies "P7 sí" if S1 = CODE_REPLY);
  - never `resolve(...,"yes")` without the tap;
  - `high_value` wording;
  - receivables answer layout (Te deben / Guardas de otros / Debes al socio; subtotals per currency, never summed);
  - "where is my money" calls `finance_overview` + `finance_receivables` and says "de los cuales" only from returned figures;
  - the cron prompt contract (call `finance_pending(for_delivery=true)`, one message, silent when empty);
  - memory prohibitions.
- [ ] **Step 4: Add the `cron` step** to `install-olin-finance.sh`: create the 06:35 and 18:35 UTC job with S1's exact syntax, `verify` lists it, and `rollback` removes it. Write the runbook section: build by SHA, restart `finance-api`/`finance-mcp`, sync timer unchanged, skill + cron install, `watch-account` and `own-iban` commands, `FINANCE_DESCRIPTION_RULES` from S2, and rollback to the previous image SHA.
- [ ] **Step 5: Run** the Hermes tests plus `deploy/finance/tests`. Expected: PASS.
- [ ] **Step 6: Commit** `feat: teach olin the exchanges and schedule its questions`. Open PR 7.

---

### Task 13: Deploy, live check and initial load (owner-run)

**Files:** update `docs/architecture/FINANCE_I2_PROGRESS.md` and `docs/architecture/STATUS.md` (small docs PR at the end).

- [ ] **Step 1: Prepare the exact `! ssh` script** from the runbook. Steps:
  1. `bringup.sh build <main sha>`; confirm the image label equals the SHA;
  2. switch `finance-api`, `finance-mcp`, `finance-sync` to that SHA;
  3. schema check: `sqlite3` `.tables` shows the I2 tables, and `PRAGMA integrity_check` returns `ok`;
  4. `watch-account` for the USD and EUR accounts, `own-iban` for each own account (the owner types the IBANs);
  5. skill + cron install.
  Rollback: the previous image SHA. The new tables stay, inert.
- [ ] **Step 2: Live checks, read-only.**
  - **Authorization matrix on the new tools:** E13 via the gateway, with I1's B11 cases.
  - **Next sync:** the journal shows matcher counts only.
  - **Cron:** the next 06:35/18:35 run is silent or shows real pending items to the owner.
  - **Backup (E14):** restore the newest restic `finance` snapshot to a scratch directory on the node; `PRAGMA integrity_check` returns `ok` and the I2 tables are present; then delete the scratch copy.
- [ ] **Step 3: Initial load with the owner in Telegram (spec F8).**
  1. Counterparties.
  2. Opening balances (`APPROXIMATE` with a note).
  3. The fund with `UNKNOWN` opening.
  4. The open exchange.
  5. Partner IBAN via a picked payment.
  Check each step through `finance_receivables`.
- [ ] **Step 4: Real-use acceptance.** For 2–3 weeks, the owner contrasts every notice and balance with the WhatsApp group. Log the error count and `interventions_this_month`, with the targets of spec §10. Record the outcome on the board, and in STATUS as "Olin Finance I2 live".

---

### Task 14 (optional): Fund reconstruction from the chat export

**Files:**
- Create: `services/finance/app/receivables/chat_import.py`
- Modify: `services/finance/app/admin.py` (subcommand `import-chat --file PATH --fund <label> --labels a,b,c`)
- Test: `services/finance/tests/test_chat_import.py` with a hand-made **synthetic** export in both iOS (`[dd/mm/yy, HH:MM:SS] Name: text`) and Android (`dd/mm/yy, HH:MM - Name: text`) formats.

**Interfaces:**
- `parse_export(lines: Iterable[str]) -> list[ChatMessage(sent_at: datetime, text: str)]` handles multi-line messages and ignores system lines.
- `extract_fund_spends(messages, labels: Sequence[str]) -> list[Candidate(day: date, usd_minor: int, label: str)]` matches lines `^\s*(\d+(?:[.,]\d{1,2})?)\s*\$?\s+(<label>)\b`, case- and accent-insensitive. When an edited split repeats in a later message, only the latest one counts (same day ± 1, same label).
- The admin command stores candidates in a new fact table `import_candidate`, prints counts only, and deletes nothing itself. The runbook deletes the file. Review goes through pending `REVIEW_OPENING` batches per month (options `CONFIRM`, `SKIP`). The final opening goes through `propose_opening` with basis `CONFIRMED` and the note "reconstruido desde la exportación del chat, confirmado por el dueño el <fecha>".

- [ ] **Step 1: Write the failing tests:**
  - `test_parse_ios_and_android_exports`
  - `test_extract_matches_labels_and_ignores_other_numbers`
  - `test_edited_split_counts_once`
  - `test_admin_import_prints_counts_only`
  - `test_e19_reconstruction_replaces_unknown_opening`
- [ ] **Step 2: Run** `FINTEST tests/test_chat_import.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: reconstruct a fund from a chat export`. Open PR 8. The owner-run import follows the runbook: the file is copied on the node into the Finance import dir, the command runs, review happens in Telegram, and the file is deleted with `shred -u`.
