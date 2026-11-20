# Finance Movements, Summary and Family Help Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Olin two read-only Finance tools: `finance_movements` searches movements, and `finance_summary` gives the owner's own income, spending and family help per month or year. Add one I2 answer, "it's from the partner", and a field census in the Enable Banking connector.

**Architecture:**
- A new package `app/movements/` interprets every current movement at read time from data Finance already stores: I2 fundings, receipts, roles, open questions, payer rules, own and partner IBAN hashes, and pairing. It writes nothing.
- `MovementsService` authorizes like `overview` (one Home call), loads I2 facts in bulk and shapes results for the MCP tools and the REST routes.
- The I2 change adds the role `PARTNER_SIDE`, written by a new `EXPLAIN_INCOMING` option and by the matcher for remembered senders.

**Tech Stack:** Python 3.11, FastAPI, FastMCP 4.0.3 (pinned), SQLite (WAL), pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-finance-movements-design.md` (Spanish). Read it: rule numbers (§5.1 rules 1–10), result fields and error codes below refer to it.

## Global Constraints

- Python 3.11 with the pins of `services/finance/requirements.lock`. Every test command in this plan runs that way. On Python 3.12+, `typing.TypedDict` passes, but it crashed the 3.11 image (#140). Setup, once per shell, from `services/finance`:
  ```bash
  PINS="${TMPDIR:-/tmp}/finance-pins.txt"   # any path outside the repo
  grep -E '^[^ #]+==' requirements.lock | cut -d' ' -f1 > "$PINS"
  T() { uv run --no-project --python 3.11 --with-requirements "$PINS" --with pytest -- python -m pytest -q "$@"; }
  ```
  `T tests/x.py::name` below means this. Skill tests run from the repo root:
  `uv run --no-project --python 3.11 --with pytest -- python -m pytest -q deploy/hermes/tests`.
- Public repo: synthetic data only in code, tests and docs. No real names, amounts, IBANs or employer. Use labels like `Familiar A`, `PERSONA UNO`, `XX00 SYNTHETIC …`.
- Commits: `git -c user.name=EKvargas -c user.email=125833890+EKvargas@users.noreply.github.com commit`. End each message with the line `Claude-Session: https://claude.ai/code/session_01W2joCzZjz3ouk6jmxh2Pw7`.
- Do not touch Nutrition or Home Hub files.
- `finance_movements` and `finance_summary` never write: no `write_tx`, no `command_log`, no connector call.
- Never sum different currencies. Money is `{"amount_minor": int, "amount": format_minor(...)}`.
- Logs carry kinds and counts only: never labels, names, amounts, descriptions or exception messages.
- No IBAN, IBAN hash, movement id or `provider_tx_id` in any tool or REST result.
- MCP tool argument types: no `typing.TypedDict` (use `typing_extensions` if one is ever needed). Tool docstrings contain no example figures.

## Review Focus

1. A movement with neither `booking_date` nor `value_date` is skipped everywhere (search, pairing, summary) without an error. Test in Task 4.
2. Two identical transfers on the same day between the same two accounts pair one to one (all four `OWN_TRANSFER`). With three equal outgoing and two incoming, exactly one outgoing stays `OWN`. Test in Task 5.
3. `amount` with a comma decimal (`"23,99"`) matches 23.99. `"23.999"` matches no currency, so the result is `bad_amount`. Test in Task 7.
4. A PENDING older than 5 days without a successor never pairs, and its look-alike counterpart stays `OWN`. Test in Task 5.
5. Search text with `%`, `_` or `(` matches literally. Test in Task 5.

---

### Task 1: Shared view authorization and account status

**Files:**
- Modify: `services/finance/app/service.py` (extract from `FinanceService.overview`)
- Modify: `services/finance/app/overview.py` (rename `_status` → `account_status`, `_TAINTED` → `TAINTED`)
- Test: `services/finance/tests/test_service_authorization.py` (add)

**Interfaces:**
- Produces, in `app/service.py`:
  - `@dataclass(frozen=True) class ViewGrant` with `actor: str` and `allowed_owners: frozenset[str]` (the actor, plus each owner whose VIEW was allowed);
  - its method `visible(self, accounts: Sequence[domain.Account]) -> tuple[list[domain.Account], int]`, which returns the visible accounts and the hidden count. An account is visible when all its `owner_person_ids` are in `allowed_owners`;
  - `authorize_view(repo: FinanceRepository, authorizer: Authorizer, workspace_id: str, delegation: str | None) -> ViewGrant`.
- Produces, in `app/overview.py`: `account_status(account, obs, conn, now) -> str` and `TAINTED: frozenset[str]` (`{STALE, REAUTH_REQUIRED}`).

`authorize_view` runs today's checks of `overview`, in today's order, up to `FeatureOff`. It reads nothing but `workspace_scope` and `is_member`. `overview` then checks `UnsupportedValuation`, calls `list_accounts` and `grant.visible`. Its behaviour is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_authorize_view_returns_actor_and_allowed_owners(repo):
    grant = authorize_view(SpyRepo(repo), FakeAuthorizer(), "ws-1", "deleg")
    assert grant.actor == "PSN-1" and "PSN-1" in grant.allowed_owners

def test_authorize_view_reads_no_account_data(repo):
    spy = SpyRepo(repo)
    authorize_view(spy, FakeAuthorizer(), "ws-1", "deleg")
    assert set(spy.calls) <= {"workspace_scope", "is_member"}

def test_visible_hides_an_account_with_an_owner_not_allowed(repo):
    grant = ViewGrant("PSN-1", frozenset({"PSN-1"}))
    shared = make_account(aid="acc-2", owner_person_ids=("PSN-1", "PSN-2"))
    visible, hidden = grant.visible([make_account(aid="acc-1"), shared])
    assert [a.id for a in visible] == ["acc-1"] and hidden == 1
```
Also: every non-answer mode refuses `authorize_view`, with the same exception as `overview` in the existing parametrized test. Add `authorize_view` to that test.

- [ ] **Step 2: Run, expect failure** — `T tests/test_service_authorization.py` → ImportError for `authorize_view`.
- [ ] **Step 3: Implement** the extraction. `overview` must call `authorize_view`.
- [ ] **Step 4: Run** `T tests/test_service_authorization.py tests/test_overview.py tests/test_api.py tests/test_mcp_transport.py` → all PASS.
- [ ] **Step 5: Commit** `refactor: share finance view authorization and account status`

---

### Task 2: "It's from the partner" answer in I2 (role `PARTNER_SIDE`)

**Files:**
- Modify: `services/finance/app/receivables/model.py` (`MovementRoleKind.PARTNER_SIDE = "PARTNER_SIDE"`)
- Modify: `services/finance/app/receivables/explain.py` (`explain_question`)
- Modify: `services/finance/app/receivables/matcher.py` (`resolve_explain_incoming`, `Matcher._incoming`, `reopen_explain`, `unhide`)
- Modify: `services/finance/app/receivables/commands.py` (`ignored_movements`, `_unignore`)
- Test: `services/finance/tests/test_receivables_matcher.py` (add; update tests that assert exact `EXPLAIN_INCOMING` option lists)
- Test: `services/finance/tests/test_receivables_service.py` (add one test)

**Interfaces:**
- Produces: `MovementRoleKind.PARTNER_SIDE`; option token `"PARTNER"`; result `{"ok": True, "status": "partner_favor", "rule": <rule or None>}`.
- `unhide(repo, conn, ws, key, movement_id, queue, now, role: MovementRoleKind = MovementRoleKind.NOT_EXCHANGE) -> list[str]`.

The behaviour (spec §5.7):
- **Question.** `explain_question` appends `"PARTNER"` after `"OTHER", "NOT_EXCHANGE"` when exactly one counterparty of kind `EXCHANGE_PARTNER` has status `ACTIVE`. Then `payload["labels"]["PARTNER"]` is that partner's label.
- **Answer.** `resolve_explain_incoming(..., "PARTNER")` refuses with `unknown_choice` unless exactly one active partner exists. Otherwise it writes the payer rule `key → partner id` through `_remember` (unless `remember=False`) and the role `PARTNER_SIDE` on the movement.
- **Matcher.** In `Matcher._incoming`, a rule target whose counterparty kind is `EXCHANGE_PARTNER` gets the role `PARTNER_SIDE` and `counts["ignored"] += 1`. It records no receipt and asks no question. Today the matcher would try a receipt, fail and ask.
- **Reopen.** `reopen_explain` revokes rules whose target is the partner id when the revoked role was `PARTNER_SIDE` (today it only revokes `IGNORE`). It calls `unhide(..., role=MovementRoleKind.PARTNER_SIDE)` in that case.
- **Ignored list.** `ignored_movements` also lists incoming roots with a live `PARTNER_SIDE` role. `_unignore` undoes them the same way: the rule target is the partner id, and `unhide` is called with `PARTNER_SIDE`.

- [ ] **Step 1: Write the failing tests** (in `test_receivables_matcher.py`, using `Env`/`make` with `rules=True`; sender text `"ZELLE FROM PERSONA NUEVA CONF# X1"`, `iban=None`, `name=""`, `acc="acc-usd"`):

```python
def test_explain_offers_partner_last_when_exactly_one_partner(tmp_path):
    ...  # z1 incoming, env.run()
    assert item.options[-3:] == ["OTHER", "NOT_EXCHANGE", "PARTNER"]
    assert item.payload["labels"]["PARTNER"] == "Socio"

def test_no_partner_option_with_two_active_partners(tmp_path):
    ...  # env.add(c, "p2", "Socio dos", CounterpartyKind.EXCHANGE_PARTNER) before the run
    assert "PARTNER" not in item.options

def test_partner_answer_writes_role_and_remembers_sender(tmp_path):
    out = resolve_explain_incoming(env.repo, c, WS, "z1", "PARTNER", env.q, env.now,
                                   description_rules=True)
    assert out["ok"] and out["status"] == "partner_favor"
    assert env.repo.movement_role(c, "z1") is MovementRoleKind.PARTNER_SIDE
    assert env.repo.rule_for(c, WS, incoming_key(env.repo, z1, True)) == "p"

def test_partner_answer_with_remember_false_writes_no_rule(tmp_path): ...
    # rule_for(...) is None, role written

def test_partner_choice_refused_without_a_single_partner(tmp_path): ...
    # two partners -> {"ok": False, "error": "unknown_choice"}; no role, no rule

def test_next_payment_from_partner_side_sender_is_set_aside_without_question(tmp_path):
    ...  # z2 same sender, other CONF#, after z1 answered PARTNER
    assert env.run() == counts(ignored=1)
    assert env.item(c, "EXPLAIN_INCOMING:z2") is None
    assert env.repo.movement_role(c, "z2") is MovementRoleKind.PARTNER_SIDE

def test_reopening_partner_answer_revokes_role_rule_and_auto_roles(tmp_path):   # M22
    out = reopen_explain(env.repo, c, WS, code_of_z1, env.q, env.now)
    assert out["status"] == "reopened" and len(out["also_asked"]) == 1   # z2 asked again
    assert env.repo.movement_role(c, "z1") is None and env.repo.movement_role(c, "z2") is None
    assert env.repo.rule_for(c, WS, key) is None
```
Also:
- Copy the existing test that undoes an incoming `NOT_EXCHANGE` from the ignored list (find it with `grep -n "_unignore\|ignored" tests/`). Run it with a `PARTNER_SIDE` role: same assertions, rule target `"p"`.
- In `test_receivables_service.py`, copy the existing service-level `EXPLAIN_INCOMING` `NOT_EXCHANGE` resolve test and answer `"PARTNER"`. Expect `status == "partner_favor"`.

- [ ] **Step 2: Run, expect failure** — `T tests/test_receivables_matcher.py tests/test_receivables_service.py`.
- [ ] **Step 3: Implement** the five changes above. Then update every existing assertion on a full `EXPLAIN_INCOMING` option list to end with `"PARTNER"`: the test `Env` has exactly one partner.
- [ ] **Step 4: Run** `T tests/` (whole Finance suite) → all PASS.
- [ ] **Step 5: Commit** `feat: answer an incoming payment as a partner favor`

---

### Task 3: Enable Banking field census

**Files:**
- Modify: `services/finance/app/connectors/enable_banking.py` (`fetch_movements`)
- Test: `services/finance/tests/test_eb_connector.py` (add; follow its existing HTTP stubbing)

**Interfaces:** none new. `RawMovement` values and fingerprints are unchanged (spec §5.5: changing name or remittance would duplicate rows without a provider id).

After pagination, `fetch_movements` logs exactly one INFO line on `logger` (`finance.enable_banking`):
- Format: `"enable banking descriptor census: ref=%s rows=%d remittance_information=%d party_name=%d bank_transaction_code=%d note=%d merchant_category_code=%d reference_number=%d"`.
- `ref` is `account_ref[:8]`; `rows` counts every dict row fetched.
- Each count is the number of rows where that field is present and non-empty. A list or dict counts when it holds a non-empty value. `party_name` is `creditor.name` for `DBIT` and `debtor.name` for `CRDT`.

- [ ] **Step 1: Write the failing test** `test_fetch_movements_logs_field_census_without_values`. Use two rows:
  - a `DBIT` with `remittance_information: ["Texto"]`, `creditor: {"name": "Comercio"}`, `bank_transaction_code: {"description": "Card"}`, `note: "Nota"`, `merchant_category_code: "5411"`, `reference_number: "R1"`;
  - a `CRDT` with none of them.

  Assert:
  ```python
  assert [r.getMessage() for r in caplog.records if "census" in r.getMessage()] == [
      "enable banking descriptor census: ref=" + ref[:8] + " rows=2 remittance_information=1 "
      "party_name=1 bank_transaction_code=1 note=1 merchant_category_code=1 reference_number=1"]
  for value in ("Texto", "Comercio", "Card", "Nota", "5411", "R1"):
      assert value not in caplog.text
  assert movements[1].counterparty_name == "" and movements[1].remittance == ""
  ```
- [ ] **Step 2: Run, expect failure** — `T tests/test_eb_connector.py::test_fetch_movements_logs_field_census_without_values`.
- [ ] **Step 3: Implement** the census in `fetch_movements`: count over all fetched rows, log once.
- [ ] **Step 4: Run** `T tests/test_eb_connector.py tests/test_sync.py` → PASS.
- [ ] **Step 5: Commit** `feat: log which descriptive fields enable banking sends`

---

### Task 4: Movement model, bulk I2 facts and movement reads

**Files:**
- Create: `services/finance/app/movements/__init__.py` (empty), `services/finance/app/movements/model.py`
- Modify: `services/finance/app/store/receivables_repo.py` (add 4 methods)
- Test: `services/finance/tests/test_movements_store.py`

**Interfaces:**
- Produces, in `app/movements/model.py`:
  - `class Kind(str, Enum)` with values `OWN`, `OWN_TRANSFER`, `EXCHANGE`, `PARTNER_FAVOR`, `FAMILY`, `FAMILY_HELP`, `FUND`, `UNCLEAR`.
  - `EXCLUDED_GROUPS = {Kind.OWN_TRANSFER: "own_transfers", Kind.EXCHANGE: "exchange", Kind.PARTNER_FAVOR: "partner_favor", Kind.FAMILY: "family", Kind.FUND: "fund"}`.
  - `@dataclass(frozen=True) class Interpretation` with `kind: Kind`, `about: str | None = None`, `ref: str | None = None` (`F<n>`, `R<n>`, `P<n>`) and `funding_id: str | None = None`.
  - `@dataclass(frozen=True) class HelpItem` with `source: str` (`"exchange_help"`, `"exchange_own"` or `"forgiven"`), `currency: str`, `amount_minor: int`, `day: date`, `about: str | None` and `funding_ref: str | None`.
  - `@dataclass(frozen=True) class Period` with `start: date`, `end: date` and `label: str` (`"YYYY-MM"` or `"YYYY"`).
  - `@dataclass(frozen=True) class InterpretationFacts` with:
    - `supersedes: Mapping[str, str]`: movement id → the id it supersedes;
    - `fundings: Mapping[str, Funding]`: root → live funding;
    - `receipts: Mapping[str, Receipt]`: root → live BANK receipt;
    - `roles: Mapping[str, MovementRoleKind]`: root → live role;
    - `questions: Mapping[str, str]`: root → the code of an open `LINK_FUNDING` or `EXPLAIN_INCOMING`;
    - `partner_hashes: Mapping[str, str]` and `own_hashes: frozenset[str]`;
    - `rules: Mapping[str, str]`: key hash → the target of the newest live rule (a counterparty id or `IGNORE`);
    - `counterparties: Mapping[str, Counterparty]`;
    - `person_names: Mapping[str, str]`: `normalize_alias(label or alias)` → id, for PERSON counterparties;
    - `root(self, movement_id: str) -> str`, which follows `supersedes` to the end.
  - `movement_day(mv: domain.Movement) -> date | None` returns `booking_date`, else `value_date`.
  - Constants: `PAIR_WINDOW_DAYS = 5`, `STALE_PENDING_DAYS = 5`, `DEFAULT_LOOKBACK_DAYS = 90`, `MAX_RANGE_DAYS = 400`, `DEFAULT_LIMIT = 20`, `MAX_LIMIT = 50`, `MAX_MONTHS_BACK = 24`, `WHO_CHARS = 40`, `TEXT_CHARS = 80`, `TOP_SPENDING = 5`, `TEXT_MIN_CHARS = 2`, `TEXT_MAX_CHARS = 60`.
- Produces, on `ReceivablesRepository`:
  - `interpretation_facts(conn, ws: str) -> InterpretationFacts`. It runs a fixed number of queries, independent of movement count. Each map uses the same "live" SQL conditions as the single-row method it mirrors (`live_funding_for_movement`, `live_receipt_for_movement`, `movement_role`, `pending_by_dedupe`, `rule_for`).
  - `current_movements_between(conn, ws: str, account_ids: Sequence[str], since: date, until: date) -> list[tuple[int, domain.Movement]]` returns `(rowid, movement)` pairs:
    - only rows not superseded;
    - `COALESCE(booking_date, value_date)` within [since, until];
    - ordered by that date, then rowid.
  - `current_incoming(conn, ws: str, account_ids: Sequence[str]) -> list[domain.Movement]` returns every current movement with `amount_minor > 0` and a date.
  - `history_from(conn, ws: str) -> dict[str, date]`: the earliest dated current movement per account.

- [ ] **Step 1: Write the failing tests:**
  - `test_facts_agree_with_single_row_lookups`. Reuse `Env`/`make` imported from `tests.test_receivables_matcher`. Build:
    - a linked funding and one reversed with `reverse_funding`;
    - a BANK receipt and one revoked;
    - a `NOT_EXCHANGE` role and one revoked;
    - an open `EXPLAIN_INCOMING` and one resolved;
    - two rules on one key, the newer one revoked;
    - a PENDING→BOOKED pair.

    For every movement id, compare against the single-row methods:
    - `facts.root(id)` equals `rx.movement_root(c, id)`;
    - the ids of the fundings and receipts match;
    - roles match;
    - `questions` matches the open items (`pending_by_dedupe`) by code;
    - `rules[k]` equals `rule_for(c, WS, k)` for every key in `payer_rule`.
  - `test_current_movements_between_skips_superseded_dateless_and_out_of_range` (Review Focus 1). A PENDING superseded by a BOOKED gives only the BOOKED. A movement with both dates `None` is absent. Account and date filters apply.
  - `test_history_from_is_the_earliest_dated_movement_per_account`.
- [ ] **Step 2: Run, expect failure** — `T tests/test_movements_store.py`.
- [ ] **Step 3: Implement** the model module and the four repository methods.
- [ ] **Step 4: Run** `T tests/test_movements_store.py` → PASS.
- [ ] **Step 5: Commit** `feat: load movement facts for interpretation in bulk`

---

### Task 5: Text helpers, interpretation and pairing

**Files:**
- Create: `services/finance/app/movements/text.py`, `services/finance/app/movements/interpret.py`
- Test: `services/finance/tests/test_movements_interpret.py`

**Interfaces:**
- Consumes: Task 4 model and `InterpretationFacts`; `app.receivables.text.description_key`; `app.receivables.explain.sender_text` and `_RAILS`.
- Produces, in `text.py`:
  - `fold(text: str) -> str`: casefold, drop combining marks after NFKD, collapse spaces.
  - `matches(query: str, *fields: str) -> bool`: every space-separated word of `fold(query)` is a substring of `fold(" ".join(fields))`.
  - `display_who(name: str, remittance: str) -> str`:
    - `description_key(name or remittance)`;
    - a leading incoming rail (`_RAILS`) or outgoing rail removed;
    - words ending in `#` dropped;
    - at most `WHO_CHARS`.
  - `display_text(remittance: str) -> str`:
    - original case kept;
    - tokens with a digit, tokens ending in `#` and the token after one ending in `#` dropped;
    - at most `TEXT_CHARS`.
  - `OUTGOING_RAILS = ("ZELLE PAYMENT TO ", "ZELLE TO ")`.
  - `zelle_recipient(name: str, remittance: str) -> str | None`:
    - checks `description_key(remittance)`, then `description_key(name)`;
    - returns the text after an outgoing rail, with words ending in `#` dropped;
    - returns `None` when neither starts with one.
  - `same_person(a: str, b: str) -> bool`: both have at least 2 words, and one word set contains the other.
  - `is_undescribed(mv) -> bool`: name and remittance both empty after strip.
- Produces, in `interpret.py`:
  - `family_senders(incoming: Sequence[domain.Movement], facts: InterpretationFacts, key_of: Callable[[domain.Movement], str | None]) -> dict[str, str]` maps `display_who(...)` to a PERSON label. A sender qualifies through a live receipt from a PERSON on its root, or a live rule from its key to a PERSON.
  - `pair_transfers(candidates: Sequence[tuple[int, domain.Movement]], today: date) -> set[str]` implements spec §5.2:
    - opposite sign, same currency and same absolute amount, in different accounts;
    - at most `PAIR_WINDOW_DAYS` apart;
    - excluding stale PENDING (PENDING whose day is more than `STALE_PENDING_DAYS` before `today`) and dateless rows;
    - one to one: closest days first, ties by the pair's lower rowid, then the higher.
  - `interpret(rows: Sequence[tuple[int, domain.Movement]], accounts: Mapping[str, domain.Account], facts: InterpretationFacts, key_of: Callable[[domain.Movement], str | None], senders: Mapping[str, str], today: date) -> dict[str, Interpretation]`:
    - keyed by movement id;
    - applies spec §5.1 rules 1–10 in order, on the root;
    - pairing (rule 9) runs on the rows still `OWN` after rules 1–8;
    - rule 8 needs an account with `currency == "USD"`, `amount_minor < 0`, a `zelle_recipient`, and a `same_person` match against `senders`.

- [ ] **Step 1: Write the failing tests.** Build `InterpretationFacts` directly with synthetic values; no database needed.
  - One test per rule:
    - `test_rule_1_live_funding_is_exchange_with_ref` (`ref == "F3"`, `funding_id` set);
    - `test_rule_2_bank_receipt_is_family_or_fund_by_payer_kind` (`about == "Familiar A"`, `ref == "R2"`);
    - `test_rule_3_roles_map_to_kinds`, parametrized:
      - `FUND_DEPOSIT` → `FUND`;
      - `EXCHANGE_FUNDING` → `EXCHANGE`;
      - `RECEIVABLE_PAYMENT` → `FAMILY`;
      - `PARTNER_SIDE` → `PARTNER_FAVOR`;
      - `NOT_EXCHANGE` → falls through;
    - `test_rule_4_open_question_is_unclear_with_code` (`ref == "P7"`);
    - `test_rule_5_partner_iban_is_exchange_even_with_not_exchange_role` (M4);
    - `test_rule_6_own_iban_is_own_transfer` (M3);
    - `test_rule_7_payer_rule_maps_by_kind_and_not_exchange_skips_it` (PERSON → `FAMILY`, EXCHANGE_PARTNER → `PARTNER_FAVOR`, FUND → `FUND`, `IGNORE` → falls through);
    - `test_rule_8_zelle_to_known_family_sender_is_family_help_else_own` (M19; sender `"PERSONA UNO DOS"`, outgoing `"ZELLE PAYMENT TO PERSONA UNO DOS CONF# AB1"`);
    - `test_rule_9_pairs_both_sides_across_month_edge` (M2, M14: out on day 30, in on day 2 of the next month);
    - `test_rule_10_rest_is_own`.
  - Review Focus:
    - `test_two_identical_transfers_pair_one_to_one_and_extra_stays_own`;
    - `test_stale_pending_never_pairs`;
    - `test_matches_is_accent_and_case_blind_and_literal`:
      ```python
      assert matches("reembolso", "", "RËEMBOLSO pedido 302-123")
      assert matches("50%", "", "Rabatt 50% Aktion") and not matches("a_b", "", "axb")
      assert matches("(x", "", "(x) y")
      ```
  - Text:
    - `test_display_drops_digit_tokens_rails_and_caps_length` (M10, M15):
      ```python
      assert display_text("Amazon 302-1234567 Erstattung") == "Amazon Erstattung"
      assert display_who("", "ZELLE PAYMENT TO PERSONA UNO CONF# AB12") == "PERSONA UNO"
      assert len(display_who("X " * 60, "")) <= 40 and len(display_text("y " * 90)) <= 80
      ```
    - `test_same_person_needs_two_words_and_containment`: `("PERSONA UNO DOS", "PERSONA DOS")` → True; `("UNO", "UNO")` → False; `("PERSONA UNO", "PERSONA DOS")` → False.
- [ ] **Step 2: Run, expect failure** — `T tests/test_movements_interpret.py`.
- [ ] **Step 3: Implement** `text.py` and `interpret.py`.
- [ ] **Step 4: Run** `T tests/test_movements_interpret.py` → PASS.
- [ ] **Step 5: Commit** `feat: interpret movements for the owner's own figures`

---

### Task 6: Family help and the summary

**Files:**
- Create: `services/finance/app/movements/help.py`, `services/finance/app/movements/views.py`, `services/finance/app/movements/summary.py`
- Modify: `services/finance/app/store/receivables_repo.py` (`forgive_history`)
- Test: `services/finance/tests/test_movements_summary.py`

**Interfaces:**
- Consumes: Tasks 4–5; `funding_shares`, `current_lines`, `movement_current`, `alias_names`; `app.receivables.fx.split_largest_remainder`; `app.receivables.model.OWNER`; `app.receivables.text.normalize_alias`.
- Produces:
  - `ReceivablesRepository.forgive_history(conn, ws) -> list[LedgerEntry]`: live `FORGIVE` entries, plus live `REVERSAL` entries whose `reverses_id` is a `FORGIVE`, oldest first.
  - `help.help_items(rx: ReceivablesRepository, conn, ws: str, facts: InterpretationFacts) -> list[HelpItem]` covers all periods. Spec §5.3:
    - **Exchange parts.** Take each distinct live funding with a non-zero `OWNER` share.
      - The share is split over its `OWNER` lines by `split_largest_remainder` on their `usd_minor`. Lines are ordered by exchange number, then line order (the order `link_funding` uses).
      - Each part is one item: `source` `"exchange_help"` when `beneficiary_note` is non-blank, else `"exchange_own"`. `about` is the note resolved to a PERSON label through `facts.person_names`, else the note as written; `None` for own.
      - `currency "EUR"`, `day` the latest `movement_day` of the funding's current payments, `funding_ref f"F{n}"`.
      - A funding is skipped while any payment is PENDING or missing.
    - **Forgiven.** A `FORGIVE` gives `amount_minor = -entry.amount_minor` on `effective_on`, `about` = the counterparty label. Its `REVERSAL` gives `-reversal.amount_minor` (negative) on its own `effective_on`.
  - `views.money(minor: int, currency: str) -> dict`.
  - `views.flow(movements: Iterable[domain.Movement], currency: str) -> dict` returns `{"count", "in": money, "out": money}`, with `out` as a positive absolute value.
  - `views.movement_line(mv, interp, account, today, parts: Sequence[HelpItem] = ()) -> dict` returns the spec §5.6 line:
    - keys `date`, `account` `{id, institution}`, `amount_minor`, `amount`, `currency`;
    - `status`, `stale_pending`, `who`, `text`, `kind`, `about`, `ref`;
    - for `EXCHANGE` with `parts`, also `own_part` (money of the `exchange_own` parts, or `None`) and `help` (`[{about, **money}]`).
  - `summary.summarize(period: Period, rows: Sequence[tuple[domain.Movement, Interpretation]], helps: Sequence[HelpItem], accounts: Mapping[str, domain.Account], currencies: Sequence[str], today: date) -> dict` returns `{"currencies": [...], "exchanges_without_split": bool}`:
    - `rows` are all current movements dated in the period, BOOKED and PENDING, with their interpretation. Figures use BOOKED rows only; `pending_bank` is the flow of the PENDING rows. `helps` are filtered to the period by `day` inside `summarize`.
    - Currencies are sorted. Each block has the spec §5.4 keys:
      - `currency`, `income`;
      - `spending`: money plus `bank`, `zelle_help`, `exchange_own`, `exchange_help` and `forgiven`;
      - `family_help`: money plus `by_person` (`[{about, **money}]`, descending, zero totals dropped);
      - `net`;
      - `excluded`: `{group: flow}` for every `EXCLUDED_GROUPS` value;
      - `unclear`, `pending_bank` and `undescribed` (flows);
      - `top_spending`: up to `TOP_SPENDING` lines of the largest `OWN` debits.

- [ ] **Step 1: Write the failing tests** (database tests reuse `Env` from `tests.test_receivables_matcher`; `summarize` tests are pure):
  - `test_exchange_parts_split_owner_share_by_usd_and_sum_exactly` (M16). Use an exchange with three lines:
    - `OWNER` 30 USD, beneficiary `"Familiar B"`;
    - `OWNER` 10 USD, no beneficiary;
    - `"a"` 60 USD.

    The funding is 91.00 EUR. Expect:
    - two items whose `amount_minor` sum equals `funding_shares(...)["OWNER"]`;
    - sources `exchange_help` (about `"Familiar B"`) and `exchange_own` (about `None`);
    - no item for line `"a"`.
  - `test_exchange_parts_wait_for_booked_payments` (M17).
  - `test_forgive_counts_in_its_month_and_reversal_in_its_own` (M18).
  - `test_summary_income_spending_net_and_help_breakdown` (M1, M16). `spending.amount_minor` equals the sum of its five parts; `family_help` equals `zelle_help + exchange_help + forgiven`; `net = income − spending`.
  - `test_summary_never_mixes_currencies` (M9). One block each for EUR and USD.
  - `test_summary_unclear_pending_and_undescribed_are_separate` (M6, M8, M20). `undescribed` rows still count in `income`/`spending`.
  - `test_summary_flags_exchanges_without_split` (M4).
  - `test_year_equals_sum_of_months` (M23). Run `summarize` for `2026` and for each of its 12 months; per currency, every money field of the year equals the sum of the months.
  - `test_movement_line_has_no_ids_or_hashes` (M15). JSON-dump a line built from a movement with a provider id, a fingerprint and an IBAN hash. None of those strings appears; no match for `r"[A-Z]{2}\d{2}[A-Z0-9 ]{10,}"`.
  - `test_movement_line_marks_stale_pending` (M8). A PENDING dated 9 days before `today` has `stale_pending` True; one dated 2 days before has False; a BOOKED row always False.
- [ ] **Step 2: Run, expect failure** — `T tests/test_movements_summary.py`.
- [ ] **Step 3: Implement** `forgive_history`, `help.py`, `views.py` and `summary.py`.
- [ ] **Step 4: Run** `T tests/test_movements_summary.py tests/test_movements_interpret.py tests/test_movements_store.py` → PASS.
- [ ] **Step 5: Commit** `feat: compute own spending and family help per period`

---

### Task 7: MovementsService, MCP tools, REST and wiring

**Files:**
- Create: `services/finance/app/movements/service.py`, `services/finance/app/mcp/movements_tools.py`, `services/finance/app/api_movements.py`
- Modify: `services/finance/app/mcp/server.py`, `services/finance/app/api.py`, `services/finance/app/main.py`, `services/finance/app/deps.py`
- Test: `services/finance/tests/test_movements_service.py`, `services/finance/tests/test_movements_transport.py`, `services/finance/tests/test_deps_wiring.py` (add)

**Interfaces:**
- Consumes: Task 1 `authorize_view`, `account_status`, `TAINTED`; Tasks 4–6.
- Produces:
  - `class MovementsService` with `__init__(self, repo: FinanceRepository, authorizer: Authorizer, workspace_id: str, *, description_rules: bool = False, clock: Callable[[], datetime] = <utc now>)`. It builds its own `ReceivablesRepository(repo)` and reads in one `rx.read()` per call.
  - `MovementsService.movements(self, delegation: str | None, text: str | None = None, amount: str | None = None, account: str | None = None, direction: str | None = None, since: str | None = None, until: str | None = None, limit: int | None = None) -> dict`.
  - `MovementsService.summary(self, delegation: str | None, period: str | None = None) -> dict`.
  - `register_movements_tools(mcp: FastMCP, service: MovementsService) -> None`. It registers `finance_movements` (same parameters as `movements` minus `delegation`) and `finance_summary(period: str | None = None)`.
  - `create_mcp(service, receivables=None, movements=None)`.
  - `create_movements_router(service: MovementsService) -> APIRouter` (GET `/movements`, GET `/summary`).
  - `create_app(service, callback=None, receivables=None, movements=None)`.
  - `deps.build_movements_service(settings: Settings | None = None) -> MovementsService` (same authorizer factory; `description_rules=settings.description_rules`).

**Service behaviour:**
- **Authorization first.** One `authorize_view` call. Then the actor's `rx.member_role` must be `"OWNER"`, else `AccessDenied`. Refusals raise the I1 exceptions.
- **Validation after authorization.** Domain errors return `{"ok": False, "error": code}`:
  - `bad_text`: not 2–60 characters after strip;
  - `bad_amount`: replace a lone `","` with `"."` when there is no `"."`, parse with `parse_amount` per visible currency, and take the absolute value. This error means no currency parses;
  - `bad_direction`: not `in`/`out`;
  - `bad_date`: not `YYYY-MM-DD`;
  - `bad_range`: `since > until`, or more than 400 days;
  - `bad_limit`: not an int in 1–50 (bool refused);
  - `bad_period`: not `YYYY`/`YYYY-MM`, a future start, or a start before the first day of the month 24 months before today's month;
  - `unknown_account`: comes with `"accounts": [{"id", "institution"}]` of the visible accounts.

  `account` matches an id or an institution, casefolded. It can match several accounts.
- **Defaults.** `until` = today, `since` = today − 90 days, `limit` = 20. The default period is today's `YYYY-MM`. Today is `clock().date()` in UTC.
- **Loading.**
  - Rows: `current_movements_between` on the visible accounts over the range, widened by `PAIR_WINDOW_DAYS` each side.
  - Facts: `interpretation_facts`.
  - Senders: `family_senders(current_incoming(USD visible accounts), …)`.
  - `key_of = lambda mv: incoming_key(rx, mv, description_rules)`.
  - Then `interpret`, and `help_items` once.
- **Search result.**
  - Filter to the requested range, then text (`matches(text, name, remittance)` on the raw text), amount and direction.
  - Newest first, by day then rowid. Each line is `movement_line` with the funding's parts.
  - The result: `{"ok": True, "since", "until", "total_matches", "truncated", "movements", "accounts"}`.
  - Each entry of `accounts` is `{"id", "institution", "currency", "synced_at", "history_from", "stale"}`:
    - `stale`: `account_status(...)` is in `TAINTED`, using `latest_balance` and the connection as `overview` does;
    - `synced_at`: the connection's `last_success_at`.
- **Summary result.**
  - The fields: `{"ok": True, "period", "from", "to", "complete", "incomplete_reasons", "currencies", "accounts", "hidden_accounts"}`.
  - `incomplete_reasons` takes, in this order, each that applies: `in_progress`, `history_starts_late`, `account_stale`, `hidden_accounts`, `exchanges_without_split`.
  - Currencies: those of the visible accounts, plus any help item's currency in the period.

**MCP tool docstrings (exact):**
- `finance_movements`: "Search bank movements of the visible accounts by text, amount, account, direction (in or out) and dates (YYYY-MM-DD, default the last 90 days). Each line says what it is for Finance. Accounts without descriptions are found by amount and date only. Every figure you state must come from this tool's result."
- `finance_summary`: "Own income, own spending (family help included and broken down by person) and net per currency for a month (YYYY-MM, default this month) or a year (YYYY), with what was set aside and whether the data is complete. Every figure you state must come from this tool's result."

Refusals become `{"ok": False, "error": refusal_code(e)}`. Any other exception becomes `internal_error`, and the log carries the type name only. Do this as `receivables_tools._call` does, with a local helper.

**REST:**
- Refusals map like `api._authorized`: 401, 503, 403, 409.
- `ok: False` results are 400.
- `internal_error` is 500 with `{"ok": False, "error": "internal_error"}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_movements_service.py` (synthetic accounts EUR A, EUR B and USD C; the clock fixed at 2026-11-20T10:00Z):
    - `test_refusals_read_no_movement_data` (M12). Parametrized like `test_service_authorization`; `SpyRepo` shows none of `DATA_READS` plus `current_movements_between`.
    - `test_non_owner_member_is_denied`. `repo.add_member("ws-1", "PSN-2", "MEMBER")` and `FakeAuthorizer(actor="PSN-2")` raise `AccessDenied`.
    - `test_hidden_account_is_absent_and_does_not_pair` (M11).
    - `test_validation_errors` (parametrized over each code). For `unknown_account`, `accounts` lists only visible accounts.
    - `test_amount_accepts_comma_and_rejects_extra_decimals` (Review Focus 3).
    - `test_defaults_window_limit_and_newest_first` (90 days, 20 lines, `truncated`).
    - `test_search_finds_text_hidden_from_display` (M10). Query `"302-1234567"` finds the line whose `text` omits it.
    - `test_summary_completeness_reasons` (M13, `in_progress`, `history_starts_late`, `hidden_accounts`).
    - `test_query_count_does_not_grow_with_movements`. Monkeypatch `app.store.db.connect` to wrap the connection with `set_trace_callback` that appends each statement to a list. Then 10 versus 200 movements give the same statement count for `summary` and `movements`.
  - `test_movements_transport.py`:
    - `test_mcp_tools_have_exactly_these_parameters`. `finance_movements` parameters are `{text, amount, account, direction, since, until, limit}`; `finance_summary` parameters are `{period}`.
    - `test_mcp_refusal_is_typed` (`{"ok": False, "error": "session_invalid"}`).
    - `test_rest_maps_refusals_and_domain_errors` (401, 403, 503, 409, 400 `bad_period`).
    - `test_rest_summary_ok`.
  - `test_deps_wiring.py`: `build_movements_service` with an empty Home environment returns a service whose calls end in `PolicyUnavailable`.
- [ ] **Step 2: Run, expect failure** — `T tests/test_movements_service.py tests/test_movements_transport.py tests/test_deps_wiring.py`.
- [ ] **Step 3: Implement** the service, tools, router and wiring. Also update `app/mcp/server.py`'s `__main__` and `app/main.py` to pass `build_movements_service(...)`.
- [ ] **Step 4: Run** `T tests/` → the whole Finance suite PASSES.
- [ ] **Step 5: Commit** `feat: add finance_movements and finance_summary`

---

### Task 8: Olin skill 2.1.0, skill tests and runbook

**Files:**
- Modify: `deploy/hermes/home-agent/skills/olin-finance/SKILL.md`
- Modify: `deploy/hermes/tests/test_olin_finance_skill.py`
- Create: `docs/runbooks/finance-movements.md`

**Interfaces:**
- Consumes: the tool names, parameters, result fields, kinds, error codes, completeness reasons and the `PARTNER` option from Tasks 2 and 7.

**Skill.** Version `2.1.0`. `requires_tools` appends `mcp__finance__finance_movements, mcp__finance__finance_summary` to the one-line list. Content per spec §5.12. It names:
- every `Kind` value;
- every summary field (`income`, `spending`, `family_help`, `by_person`, `net`, `excluded`, `unclear`, `pending_bank`, `undescribed`, `top_spending`, `complete`, `incomplete_reasons`);
- every reason (`in_progress`, `history_starts_late`, `account_stale`, `hidden_accounts`, `exchanges_without_split`);
- the search fields `stale_pending`, `synced_at`, `own_part`, `help`;
- every new error code.

It gives the `PARTNER` option's text, `"Es del socio (un favor)"`. It contains no example figures, no names, no employer.

**Runbook** (`docs/runbooks/finance-movements.md`) reuses the helpers of `docs/runbooks/finance-i2-exchanges.md` (`SSH`, `STEP`, `HSTEP`, `PYRO`, `SHA`). The steps:
1. **Build** by SHA, then smoke test in the image:
   `python -c 'from fastmcp import FastMCP; from app.mcp.movements_tools import register_movements_tools; register_movements_tools(FastMCP("smoke"), None); print("MOVEMENTS TOOLS OK")'`.
2. **Install and verify** (`STEP install`, `STEP verify`; re-run verify after about 10 s).
3. **Skill reinstall**, the same `HSTEP` step as the I2 runbook's skill step, with its backup.
4. **Timing check.** In the image with the data mounted read-only, use an allow-all authorizer stub. Time `summary(period=<current year>)` and `movements()`, and print only `elapsed=<s> ok=<bool>`. The budget is under 1 s.
5. **Telegram smoke**: a month question, a family-help question, a search by amount.
6. **Census.** After two syncs, run `journalctl --user -u finance-sync` as `svc-finance`, grepping `descriptor census`, and record the counts.
7. **Rollback.**
   - First a read-only count of live `PARTNER_SIDE` roles: `SELECT COUNT(*) FROM movement_role r WHERE r.role='PARTNER_SIDE' AND NOT EXISTS (SELECT 1 FROM revocation v WHERE v.table_name='movement_role' AND v.target_id=r.id)`. It must be 0, or those answers are reopened with the new image first.
   - Then `STEP install $PREV_SHA` and the previous skill.

- [ ] **Step 1: Write the failing tests** in `test_olin_finance_skill.py`:
  - extend `REQUIRED_TOOLS` with `"finance_movements", "finance_summary"`;
  - make `test_the_required_tools_exist_in_the_finance_mcp_server` also scan `services/finance/app/mcp/movements_tools.py`;
  - add `test_skill_covers_movements_kinds_fields_reasons_and_errors`, whose literal lists are those in the paragraph above;
  - add `test_skill_shows_the_partner_option` (`"PARTNER"` and `"Es del socio (un favor)"`);
  - add `test_skill_version_is_2_1_0`;
  - add `test_movements_runbook_has_smoke_timing_census_and_partner_rollback_check`. It needs `register_movements_tools`, `MOVEMENTS TOOLS OK`, `elapsed=`, `descriptor census`, `PARTNER_SIDE`, `PREV_SHA`.
- [ ] **Step 2: Run, expect failure** — `uv run --no-project --python 3.11 --with pytest -- python -m pytest -q deploy/hermes/tests` (from the repo root).
- [ ] **Step 3: Write** the skill sections and the runbook.
- [ ] **Step 4: Run** the skill tests and `T tests/` → all PASS.
- [ ] **Step 5: Commit** `docs: teach olin movements, summary and partner favors`
