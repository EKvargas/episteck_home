"""Receivables schema and repository (synthetic data only)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app import domain
from app.receivables.allocation import OpenLine
from app.receivables.model import (
    Allocation, AllocationMethod, Counterparty, CounterpartyKind, EntryKind, Exchange,
    ExchangeLine, Funding, LedgerEntry, MovementRoleKind, Receipt, ReceiptKind, Verification,
)
from app.store import db
from app.store.receivables_repo import (
    AlreadyRevoked, DuplicateAlias, DuplicateReceipt, ReceivablesRepository,
)
from app.store.receivables_schema import FACT_TABLES
from app.store.repo import FinanceRepository
from tests.support import (
    PEPPER, T0, column_names, make_account, make_movement, make_repo, raw_execute,
    seed_connection, seed_workspace,
)

WS = "ws-1"
D = date(2026, 10, 9)
I2_TABLES = set(FACT_TABLES) | {
    "counterparty", "counterparty_alias", "account_watch", "pending_item", "ref_counter",
    "matcher_cursor"}


def make(tmp_path):
    repo = make_repo(tmp_path)
    seed_workspace(repo)
    return repo, ReceivablesRepository(repo)


def cp(cid="cp-1", label="Familiar A", kind=CounterpartyKind.PERSON, ws=WS):
    return Counterparty(cid, ws, kind, label, "ACTIVE")


def entry(eid="e1", number=1, amount=12000, cpid="cp-1", kind=EntryKind.CHARGE, src="line-1",
          cur="USD", rev=None):
    return LedgerEntry(eid, WS, number, cpid, cur, amount, kind, D, src, reverses_id=rev)


def reversal(eid, number, target, amount, src="line-1", cur="USD"):
    return entry(eid, number, amount, kind=EntryKind.REVERSAL, src=src, cur=cur, rev=target)


def exchange(eid="x1", number=1, ves_hash=None):
    return Exchange(eid, WS, number, "cp-p", 20000, D, T0, ves_reference_hash=ves_hash)


def line(lid="line-1", eid="x1", version=1, position=1, usd=12000):
    return ExchangeLine(lid, eid, version, position, "cp-1", usd, "USD")


def receipt(rid="r1", number=1, amount=5000, movement_id=None, received=D, cur="USD"):
    return Receipt(rid, WS, number, ReceiptKind.CASH, "cp-1", cur, amount, received,
                   Verification.OWNER_CONFIRMED, movement_id)


def _master(path) -> dict[tuple[str, str], str | None]:
    conn = sqlite3.connect(path)
    try:
        return {(t, n): s for t, n, s in conn.execute("SELECT type, name, sql FROM sqlite_master")}
    finally:
        conn.close()


def test_init_adds_i2_tables_without_touching_i1(tmp_path):
    # An I1-only database, as it exists on the box before I2 ships.
    path = str(tmp_path / "i1.sqlite")
    conn = db.connect(path)
    try:
        conn.executescript(db.SCHEMA)
        conn.execute("INSERT INTO workspace VALUES('ws-1','Test','PERSONAL','ACTIVE')")
    finally:
        conn.close()
    i1 = _master(path)
    assert not {n for _, n in i1} & I2_TABLES
    FinanceRepository(path, pepper=PEPPER)  # the I2-aware init
    first = _master(path)
    repo = FinanceRepository(path, pepper=PEPPER)  # a second start changes nothing
    assert _master(path) == first
    assert {k: first.get(k) for k in i1} == i1  # every I1 object kept, DDL unchanged
    assert I2_TABLES <= {n for t, n in first if t == "table"}
    assert {f"{t}_no_{op}" for t in FACT_TABLES for op in ("update", "delete")} <= {
        n for t, n in first if t == "trigger"}
    assert raw_execute(repo, "SELECT id FROM workspace") == [("ws-1",)]


SAMPLES = {
    "exchange": "INSERT INTO exchange VALUES('x',?,1,'p',1,'2026-10-09','t',NULL,NULL)",
    "exchange_line": "INSERT INTO exchange_line VALUES('l',?,'x',1,1,'c',1,'USD',NULL,NULL)",
    "funding": "INSERT INTO funding VALUES('f',?,1,1,1,'t')",
    "funding_movement": "INSERT INTO funding_movement VALUES(?,'f','m')",
    "funding_exchange": "INSERT INTO funding_exchange VALUES(?,'f','x')",
    "funding_share": "INSERT INTO funding_share VALUES('s',?,'f','c',1)",
    "ledger_entry": "INSERT INTO ledger_entry VALUES('e',?,1,'c','USD',1,'CHARGE','2026-10-09','s','',NULL,NULL)",
    "receipt": "INSERT INTO receipt VALUES('r',?,1,'CASH','c','USD',1,'2026-10-09','OWNER_CONFIRMED',NULL,'')",
    "allocation": "INSERT INTO allocation VALUES('a',?,'r','l',1,'OWNER')",
    "held_cash_statement": "INSERT INTO held_cash_statement VALUES('h',?,'c','USD',1,'2026-10-09')",
    "payer_rule": "INSERT INTO payer_rule VALUES('pr',?,'k',NULL)",
    "movement_role": "INSERT INTO movement_role VALUES('mr',?,'m','NOT_EXCHANGE')",
    "revocation": "INSERT INTO revocation VALUES('rv',?,'exchange','x','r','t')",
    "intervention_log": "INSERT INTO intervention_log VALUES('i',?,'k','t')",
    "partner_identifier": "INSERT INTO partner_identifier VALUES('pi',?,'h','c',NULL)",
    "own_identifier": "INSERT INTO own_identifier VALUES('oi',?,'h')",
}


def test_samples_cover_every_fact_table():
    assert set(SAMPLES) == set(FACT_TABLES)


def index_shapes(repo, table: str) -> set[tuple[tuple[str, ...], bool]]:
    """(indexed columns, unique) for every index on ``table``."""
    return {
        (tuple(r[2] for r in raw_execute(repo, f"PRAGMA index_info('{name}')")), bool(unique))
        for _, name, unique, *_ in raw_execute(repo, f"PRAGMA index_list('{table}')")
    }


def test_lookup_indexes(tmp_path):
    repo, _ = make(tmp_path)
    assert (("reverses_id",), False) in index_shapes(repo, "ledger_entry")
    receipt_ix = index_shapes(repo, "receipt")
    assert (("movement_id",), False) in receipt_ix  # uniqueness per live root is in code
    assert (("movement_id",), True) not in receipt_ix
    assert (("funding_id",), False) in index_shapes(repo, "funding_share")
    assert (("workspace_id", "dedupe_key"), True) in index_shapes(repo, "pending_item")


@pytest.mark.parametrize("table", FACT_TABLES)
def test_fact_tables_reject_update_and_delete(tmp_path, table):
    repo, _ = make(tmp_path)
    raw_execute(repo, SAMPLES[table], (WS,))
    with pytest.raises(sqlite3.IntegrityError, match="facts are immutable"):
        raw_execute(repo, f"UPDATE {table} SET workspace_id='x'")
    with pytest.raises(sqlite3.IntegrityError, match="facts are immutable"):
        raw_execute(repo, f"DELETE FROM {table}")


def test_alias_lookup_ignores_case_accents_and_spaces(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_counterparty(c, cp(), ["Mamá"])
    with rr.read() as c:
        assert [x.id for x in rr.find_by_alias(c, WS, " MAMA ")] == ["cp-1"]
        assert rr.find_by_alias(c, WS, "nobody") == []
        assert rr.get_counterparty(c, WS, "cp-1").label == "Familiar A"
        assert [x.id for x in rr.list_counterparties(c, WS)] == ["cp-1"]


def test_duplicate_alias_is_rejected(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_counterparty(c, cp(), ["mama"])
    with pytest.raises(DuplicateAlias) as exc:
        with rr.tx() as c:
            rr.insert_counterparty(c, cp("cp-2", "Familiar B"), ["MAMÁ"])
    assert exc.value.alias == "mama"
    assert "mama" not in str(exc.value).lower()  # messages never carry aliases (§6.9)
    with rr.read() as c:
        assert rr.get_counterparty(c, WS, "cp-2") is None


def test_label_is_always_an_alias(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_counterparty(c, cp(), ["Mamá"])
    with rr.read() as c:
        assert [x.id for x in rr.find_by_alias(c, WS, "familiar a")] == ["cp-1"]
    with pytest.raises(DuplicateAlias):  # labels are unique (R41)
        with rr.tx() as c:
            rr.insert_counterparty(c, cp("cp-2", "FAMILIAR  Á"), ["otra"])


@pytest.mark.parametrize("alias", ["--", "  ", "¿?"])
def test_alias_that_normalises_to_empty_is_rejected(tmp_path, alias):
    _, rr = make(tmp_path)
    with pytest.raises(ValueError) as exc:
        with rr.tx() as c:
            rr.insert_counterparty(c, cp(), ["Familiar A", alias])
    assert "familiar" not in str(exc.value).lower()
    with rr.read() as c:
        assert rr.get_counterparty(c, WS, "cp-1") is None
        assert c.execute("SELECT COUNT(*) FROM counterparty_alias").fetchone()[0] == 0


@pytest.mark.parametrize("text", ["", "?", " -- "])
def test_find_by_alias_of_blank_text_finds_nothing(tmp_path, text):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_counterparty(c, cp(), ["Familiar A"])
        # a stray empty key must never match blank input
        c.execute("INSERT INTO counterparty_alias VALUES(?,?,?)", (WS, "", "cp-1"))
    with rr.read() as c:
        assert rr.find_by_alias(c, WS, text) == []


def test_balance_sums_live_entries_only(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_entry(c, entry("e1", 1, 12000))
        rr.insert_entry(c, entry("e2", 2, 5000, src="line-2"))
        rr.revoke(c, WS, "ledger_entry", "e2", "mistake", T0)
    with rr.read() as c:
        assert rr.balance(c, WS, "cp-1", "USD") == 12000
        assert rr.balances(c, WS) == {("cp-1", "USD"): 12000}
        assert [e.id for e in rr.entries(c, WS, "cp-1")] == ["e1", "e2"]


def test_revoke_twice_raises_and_is_live(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_entry(c, entry())
        assert rr.is_live(c, "ledger_entry", "e1")
        rr.revoke(c, WS, "ledger_entry", "e1", "r", T0)
        assert not rr.is_live(c, "ledger_entry", "e1")
    with pytest.raises(AlreadyRevoked):
        with rr.tx() as c:
            rr.revoke(c, WS, "ledger_entry", "e1", "again", T0)


def test_entry_undone_by_live_reversal_cannot_also_be_revoked(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_entry(c, entry("e1", 1, 12000))
        rr.insert_entry(c, reversal("e2", 2, "e1", -12000))
    with pytest.raises(ValueError):
        with rr.tx() as c:
            rr.revoke(c, WS, "ledger_entry", "e1", "double undo", T0)
    with rr.read() as c:
        assert rr.balance(c, WS, "cp-1", "USD") == 0  # not -12000
        assert rr.is_live(c, "ledger_entry", "e1")
    with rr.tx() as c:  # undoing the REVERSAL first makes the entry revocable again
        rr.revoke(c, WS, "ledger_entry", "e2", "undo the undo", T0)
        assert rr.balance(c, WS, "cp-1", "USD") == 12000
        rr.revoke(c, WS, "ledger_entry", "e1", "now allowed", T0)
        assert rr.balance(c, WS, "cp-1", "USD") == 0


def test_reversal_needs_one_effective_target(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_entry(c, entry("e1", 1, 12000))
        rr.insert_entry(c, entry("e2", 2, 3000, src="line-2"))
        rr.revoke(c, WS, "ledger_entry", "e2", "mistake", T0)
        rr.insert_entry(c, reversal("e3", 3, "e1", -12000))
    bad = [
        reversal("e9", 9, "nope", -1),                              # unknown target
        reversal("e9", 9, None, -1),                                # no target at all
        reversal("e9", 9, "e2", -3000, src="line-2"),               # revoked target
        reversal("e9", 9, "e1", -12000),                            # already reversed
        reversal("e9", 9, "e3", 12000),                             # a REVERSAL of a REVERSAL
        entry("e9", 9, 5, kind=EntryKind.ADJUSTMENT, rev="e1"),     # only REVERSAL references
    ]
    for e in bad:
        with pytest.raises(ValueError):
            with rr.tx() as c:
                rr.insert_entry(c, e)
    with rr.read() as c:
        assert [e.id for e in rr.entries(c, WS, "cp-1")] == ["e1", "e2", "e3"]
        assert rr.balance(c, WS, "cp-1", "USD") == 0
    with rr.tx() as c:  # once the first REVERSAL is revoked, the entry can be reversed again
        rr.revoke(c, WS, "ledger_entry", "e3", "wrong reversal", T0)
        rr.insert_entry(c, reversal("e4", 4, "e1", -12000))
        assert rr.balance(c, WS, "cp-1", "USD") == 0


def test_reversal_must_mirror_its_target(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_entry(c, entry("e1", 1, 12000))
    bad = [
        entry("e9", 9, -12000, cpid="cp-2", kind=EntryKind.REVERSAL, rev="e1"),  # other party
        reversal("e9", 9, "e1", -12000, cur="EUR"),                             # other currency
        reversal("e9", 9, "e1", -11999),                                        # not the negation
        reversal("e9", 9, "e1", 12000),                                         # same sign
    ]
    for e in bad:
        with pytest.raises(ValueError):
            with rr.tx() as c:
                rr.insert_entry(c, e)
    with rr.tx() as c:
        rr.insert_entry(c, reversal("e2", 2, "e1", -12000))
        assert rr.balance(c, WS, "cp-1", "USD") == 0


def test_open_lines_subtract_forgiveness_sourced_to_the_line(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange(), [line()])
        rr.insert_entry(c, entry("e1", 1, 12000))
        rr.insert_entry(c, entry("e2", 2, -2000, kind=EntryKind.FORGIVE))
    with rr.read() as c:
        assert rr.open_lines(c, WS, "cp-1", "USD") == [OpenLine("line-1", 10000, 101)]
        assert rr.balance(c, WS, "cp-1", "USD") == 10000


def test_lookups_by_human_ref(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange(), [line()])
        rr.insert_funding(c, Funding("f1", WS, 3, (), ("x1",), 9200, 10000, T0), {"cp-1": 9200})
        rr.insert_receipt(c, receipt("r1", 4, 5000))
        rr.insert_entry(c, entry("e1", 5, 12000))
        rr.insert_entry(c, entry("e2", 6, 100, kind=EntryKind.ADJUSTMENT))
        rr.insert_entry(c, reversal("e3", 7, "e2", -100))
        assert rr.funding_by_ref(c, WS, " f3").id == "f1"
        assert rr.receipt_by_ref(c, WS, "r4").id == "r1"
        assert rr.entry_by_ref(c, WS, "E5").id == "e1"
        assert rr.entry_by_ref(c, WS, "E6") is None  # undone by a live REVERSAL
        assert rr.entry_by_ref(c, WS, "E6", include_undone=True).id == "e2"
        assert rr.exchange_by_id(c, WS, "x1").number == 1
        for ref in ("F", "F3x", "C3", "f99", "F" + "9" * 10):
            assert rr.funding_by_ref(c, WS, ref) is None
        rr.revoke(c, WS, "funding", "f1", "r", T0)
        rr.revoke(c, WS, "receipt", "r1", "r", T0)
        rr.revoke(c, WS, "exchange", "x1", "r", T0)
        assert rr.funding_by_ref(c, WS, "F3") is None
        assert rr.funding_by_ref(c, WS, "F3", include_revoked=True).id == "f1"
        assert rr.receipt_by_ref(c, WS, "R4") is None
        assert rr.exchange_by_id(c, WS, "x1") is None


def test_open_lines_subtract_live_allocations(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange(), [line()])
        rr.insert_entry(c, entry("e1", 1, 12000, src="line-1"))
        rr.insert_receipt(c, receipt("r1", 1, 5000))
        rr.insert_allocation(c, Allocation("a1", WS, "r1", "line-1", 5000, AllocationMethod.OWNER))
    with rr.read() as c:
        (ln,) = rr.open_lines(c, WS, "cp-1", "USD")
        assert (ln.line_id, ln.outstanding_minor, ln.order) == ("line-1", 7000, 101)
        assert rr.open_lines(c, WS, "cp-1", "EUR") == []
    with rr.tx() as c:
        rr.revoke(c, WS, "allocation", "a1", "r", T0)
    with rr.read() as c:
        assert rr.open_lines(c, WS, "cp-1", "USD")[0].outstanding_minor == 12000


def test_open_lines_skip_a_reversed_charge(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange(), [line()])
        rr.insert_entry(c, entry("e1", 1, 12000))
        rr.insert_entry(c, reversal("e2", 2, "e1", -12000))
    with rr.read() as c:
        assert rr.open_lines(c, WS, "cp-1", "USD") == []


def test_open_lines_count_a_recharged_line_once(tmp_path):
    # EUR charge 7360 -> REVERSAL -> new charge 7400 on the same line (funding re-created).
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange(), [line()])
        rr.insert_entry(c, entry("e1", 1, 7360, cur="EUR"))
        rr.insert_entry(c, reversal("e2", 2, "e1", -7360, cur="EUR"))
        rr.insert_entry(c, entry("e3", 3, 7400, cur="EUR"))
    with rr.read() as c:
        assert rr.open_lines(c, WS, "cp-1", "EUR") == [OpenLine("line-1", 7400, 101)]
    with rr.tx() as c:
        rr.insert_receipt(c, receipt("r1", 1, 7000, cur="EUR"))
        rr.insert_allocation(c, Allocation("a1", WS, "r1", "line-1", 7000, AllocationMethod.OWNER))
    with rr.read() as c:
        assert rr.open_lines(c, WS, "cp-1", "EUR") == [OpenLine("line-1", 400, 101)]


def test_open_lines_after_correction_list_only_the_new_version(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange(), [line("l1v1"), line("l1v2", version=2, usd=10000)])
        rr.insert_entry(c, entry("e1", 1, 12000, src="l1v1"))
        rr.insert_entry(c, reversal("e2", 2, "e1", -12000, src="l1v1"))
        rr.insert_entry(c, entry("e3", 3, 10000, src="l1v2"))
    with rr.read() as c:
        assert rr.open_lines(c, WS, "cp-1", "USD") == [OpenLine("l1v2", 10000, 101)]
        assert rr.balance(c, WS, "cp-1", "USD") == 10000


def test_open_lines_skip_lines_of_a_revoked_exchange(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange(), [line()])
        rr.insert_entry(c, entry("e1", 1, 12000))
        rr.revoke(c, WS, "exchange", "x1", "r", T0)
    with rr.read() as c:
        assert rr.open_lines(c, WS, "cp-1", "USD") == []


def test_open_lines_sum_two_allocations_on_one_line_and_order_by_exchange(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange("x2", 2), [line("l2", "x2", position=0)])
        rr.insert_exchange(c, exchange("x1", 1), [line("l1", "x1", position=5)])
        rr.insert_entry(c, entry("e1", 1, 12000, src="l2"))
        rr.insert_entry(c, entry("e2", 2, 9000, src="l1"))
        rr.insert_receipt(c, receipt("r1", 1, 5000))
        rr.insert_receipt(c, receipt("r2", 2, 3000))
        rr.insert_allocation(c, Allocation("a1", WS, "r1", "l2", 5000, AllocationMethod.OWNER))
        rr.insert_allocation(c, Allocation("a2", WS, "r2", "l2", 3000, AllocationMethod.OWNER))
    with rr.read() as c:
        assert rr.open_lines(c, WS, "cp-1", "USD") == [
            OpenLine("l1", 9000, 105), OpenLine("l2", 4000, 200)]


def test_receipt_remainders_live_oldest_first(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_receipt(c, receipt("r1", 1, 5000, received=date(2026, 10, 9)))
        rr.insert_receipt(c, receipt("r2", 2, 3000, received=date(2026, 10, 1)))
        rr.insert_receipt(c, receipt("r3", 3, 900, received=date(2026, 9, 1)))
        rr.insert_receipt(c, receipt("r4", 4, 4000, received=date(2026, 10, 2)))
        rr.revoke(c, WS, "receipt", "r3", "x", T0)
        rr.insert_allocation(c, Allocation("a1", WS, "r2", "l", 3000, AllocationMethod.OWNER))
        rr.insert_allocation(c, Allocation("a2", WS, "r4", "l", 1000, AllocationMethod.OWNER))
    with rr.read() as c:
        assert [(r.id, left) for r, left in rr.receipt_remainders(c, WS, "cp-1", "USD")] == [
            ("r4", 3000), ("r1", 5000)]


def test_duplicate_live_receipt_for_a_movement_is_refused(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_receipt(c, receipt("r1", 1, movement_id="m1"))
    with pytest.raises(DuplicateReceipt) as exc:
        with rr.tx() as c:
            rr.insert_receipt(c, receipt("r2", 2, movement_id="m1"))
    assert (exc.value.movement_id, exc.value.receipt_id) == ("m1", "r1")
    assert "m1" not in str(exc.value) and "r1" not in str(exc.value)  # generic message
    with rr.read() as c:
        assert rr.live_receipt_for_movement(c, "m1").id == "r1"
        assert rr.live_receipt_for_movement(c, "m9") is None


def _pending_then_booked(tmp_path):
    repo, rr = make(tmp_path)
    seed_connection(repo)
    repo.add_account(make_account())
    repo.insert_movement(make_movement("m1", tx="t1", fp="f1",
                                       status=domain.MovementStatus.PENDING))
    repo.insert_movement(make_movement("m2", tx="t1", fp="f2", supersedes="m1"))
    return repo, rr


@pytest.mark.parametrize("first,second", [("m1", "m2"), ("m2", "m1")])
def test_receipt_for_pending_and_its_booked_successor_is_refused(tmp_path, first, second):
    repo, rr = _pending_then_booked(tmp_path)
    with rr.tx() as c:
        rr.insert_receipt(c, receipt("r1", 1, movement_id=first))
    with pytest.raises(DuplicateReceipt):
        with rr.tx() as c:
            rr.insert_receipt(c, receipt("r2", 2, movement_id=second))
    with rr.read() as c:
        assert rr.live_receipt_for_movement(c, "m1").id == "r1"
        assert rr.live_receipt_for_movement(c, "m2").id == "r1"
        assert rr.live_receipt_for_movement(c, "m2").movement_id == "m1"  # stored as root
    assert raw_execute(repo, "SELECT movement_id FROM receipt") == [("m1",)]


def test_receipt_can_be_recorded_again_after_revocation(tmp_path):
    # A BANK receipt reversed (Task 8) and re-attributed to another payer (Task 9).
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_receipt(c, receipt("r1", 1, movement_id="m1"))
        rr.revoke(c, WS, "receipt", "r1", "wrong payer", T0)
        assert rr.live_receipt_for_movement(c, "m1") is None
        rr.insert_receipt(c, receipt("r2", 2, movement_id="m1"))
    with rr.read() as c:
        assert rr.live_receipt_for_movement(c, "m1").id == "r2"


def test_exchanges_funding_and_open_exchanges(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange("x1", 1, "vh"),
                           [line("l1", "x1"), line("l2", "x1", 2, 1, 9)])
        rr.insert_exchange(c, exchange("x2", 2), [line("l3", "x2")])
        rr.insert_exchange(c, exchange("x3", 3), [])
        rr.revoke(c, WS, "exchange", "x3", "r", T0)
        f = Funding("f1", WS, 1, ("m1",), ("x1",), 9000, 10000, T0)
        rr.insert_funding(c, f, {"cp-1": 9000})
    with rr.read() as c:
        assert [x.id for x in rr.current_lines(c, "x1")] == ["l2"]
        assert [e.id for e in rr.open_exchanges(c, WS)] == ["x2"]
        assert rr.exchange_by_ves_hash(c, WS, "vh").id == "x1"
        assert rr.live_funding_for_exchange(c, "x1") == f
        assert rr.live_funding_for_movement(c, "m1") == f
        assert rr.funding_shares(c, "f1") == {"cp-1": 9000}
        assert rr.live_funding_for_exchange(c, "x2") is None
    with rr.tx() as c:
        rr.revoke(c, WS, "funding", "f1", "r", T0)
    with rr.read() as c:
        assert rr.live_funding_for_exchange(c, "x1") is None
        assert {e.id for e in rr.open_exchanges(c, WS)} == {"x1", "x2"}


def test_funding_shares_are_live_ordered_and_replaceable(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_funding(c, Funding("f1", WS, 1, ("m1",), ("x1",), 9000, 10000, T0),
                          {"cp-2": 3000, "cp-1": 6000})
    with rr.read() as c:
        assert list(rr.funding_shares(c, "f1").items()) == [("cp-2", 3000), ("cp-1", 6000)]
    with rr.tx() as c:  # E11: same funding EUR, new weights
        rr.replace_funding_shares(c, WS, "f1", {"cp-1": 5000, "cp-3": 4000}, "corrected", T0)
    with rr.read() as c:
        assert list(rr.funding_shares(c, "f1").items()) == [("cp-1", 5000), ("cp-3", 4000)]
        assert c.execute("SELECT COUNT(*) FROM revocation WHERE table_name='funding_share'"
                         ).fetchone()[0] == 2
    with rr.tx() as c:  # a second replacement revokes only the live set
        rr.replace_funding_shares(c, WS, "f1", {"cp-1": 9000}, "corrected again", T0)
    with rr.read() as c:
        assert rr.funding_shares(c, "f1") == {"cp-1": 9000}
        assert c.execute("SELECT COUNT(*) FROM funding_share").fetchone()[0] == 5


def test_funding_share_revoked_one_by_one_is_hidden(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_funding(c, Funding("f1", WS, 1, ("m1",), ("x1",), 9000, 10000, T0),
                          {"cp-1": 6000, "cp-2": 3000})
        sid = c.execute("SELECT id FROM funding_share WHERE payer_id='cp-2'").fetchone()[0]
        rr.revoke(c, WS, "funding_share", sid, "r", T0)
        assert rr.funding_shares(c, "f1") == {"cp-1": 6000}


def test_replace_funding_shares_needs_a_live_funding(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_funding(c, Funding("f1", WS, 1, ("m1",), ("x1",), 9000, 10000, T0),
                          {"cp-1": 9000})
        rr.revoke(c, WS, "funding", "f1", "reversed", T0)
    for fid in ("f1", "f9"):
        with pytest.raises(ValueError):
            with rr.tx() as c:
                rr.replace_funding_shares(c, WS, fid, {"cp-1": 1}, "r", T0)
    with rr.read() as c:
        assert rr.funding_shares(c, "f1") == {"cp-1": 9000}


@pytest.mark.parametrize("bad", [
    line("l1", "x-other"),          # line of another exchange
    line("l1", position=100),       # order would collide with the next exchange
    line("l1", position=-1),
])
def test_insert_exchange_validates_lines(tmp_path, bad):
    _, rr = make(tmp_path)
    with pytest.raises(ValueError):
        with rr.tx() as c:
            rr.insert_exchange(c, exchange(), [line("l0", position=0), bad])
    with rr.read() as c:
        assert c.execute("SELECT COUNT(*) FROM exchange").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM exchange_line").fetchone()[0] == 0


@pytest.mark.parametrize("ref,expected", [("C2", "x2"), ("c2", "x2"), ("C9", None),
                                          ("F2", None), ("C", None), ("2", None), ("Cx", None),
                                          ("C000000002", "x2"), ("C1234567890", None),
                                          ("C" + "9" * 25, None)])
def test_exchange_by_ref(tmp_path, ref, expected):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange("x2", 2), [])
    with rr.read() as c:
        got = rr.exchange_by_ref(c, WS, ref)
        assert (got.id if got else None) == expected


def test_exchange_by_ref_hides_revoked_unless_asked(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange("x2", 2), [])
        rr.revoke(c, WS, "exchange", "x2", "r", T0)
    with rr.read() as c:
        assert rr.exchange_by_ref(c, WS, "C2") is None
        assert rr.exchange_by_ref(c, WS, "C2", include_revoked=True).id == "x2"


def test_rule_for_ignore_and_latest(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        assert rr.rule_for(c, WS, "k") is None
        rr.insert_payer_rule(c, WS, "k", "cp-1")
        assert rr.rule_for(c, WS, "k") == "cp-1"
        rr.insert_payer_rule(c, WS, "k", None)
        assert rr.rule_for(c, WS, "k") == "IGNORE"
        rr.insert_payer_rule(c, WS, "k", "cp-2")
        assert rr.rule_for(c, WS, "k") == "cp-2"


def test_rule_ids_are_returned_and_revocation_falls_back(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        first = rr.insert_payer_rule(c, WS, "k", "cp-1")
        second = rr.insert_payer_rule(c, WS, "k", None)
        rr.insert_payer_rule(c, WS, "other", "cp-2")
        assert isinstance(first, str) and first != second
        assert rr.live_rule_ids(c, WS, "k") == [first, second]
        rr.revoke(c, WS, "payer_rule", second, "owner changed mind", T0)
        assert rr.live_rule_ids(c, WS, "k") == [first]
        assert rr.rule_for(c, WS, "k") == "cp-1"
        assert rr.live_rule_ids(c, "ws-2", "k") == []


def test_revoked_role_and_partner_identifier_are_not_live(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        older = rr.insert_movement_role(c, WS, "m1", MovementRoleKind.NOT_EXCHANGE)
        newer = rr.insert_movement_role(c, WS, "m1", MovementRoleKind.EXCHANGE_FUNDING)
        assert rr.live_role_ids_for_movement(c, "m1") == [older, newer]
        rr.revoke(c, WS, "movement_role", newer, "funding reversed", T0)
        assert rr.movement_role(c, "m1") is MovementRoleKind.NOT_EXCHANGE
        rr.revoke(c, WS, "movement_role", older, "re-explained", T0)
        assert rr.movement_role(c, "m1") is None
        assert rr.live_role_ids_for_movement(c, "m1") == []
        kept = rr.add_partner_identifier(c, WS, "h1", "cp-p")
        gone = rr.add_partner_identifier(c, WS, "h2", "cp-p")
        assert isinstance(kept, str) and kept != gone
        rr.revoke(c, WS, "partner_identifier", gone, "wrong iban", T0)
        assert rr.partner_hashes(c, WS) == {"h1": "cp-p"}


def test_is_live_rejects_unknown_table(tmp_path):
    _, rr = make(tmp_path)
    with rr.read() as c:
        with pytest.raises(ValueError):
            rr.is_live(c, "ledger_entries", "e1")
        with pytest.raises(ValueError):
            rr.is_live(c, "movement", "m1")


def test_identifiers_watch_roles_cursor_cash(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.add_partner_identifier(c, WS, "h1", "cp-p")
        rr.add_own_identifier(c, WS, "h2")
        rr.set_watch(c, WS, "acc-1", True)
        rr.set_watch(c, WS, "acc-2", True)
        rr.set_watch(c, WS, "acc-2", False)
        rr.insert_movement_role(c, WS, "m1", MovementRoleKind.NOT_EXCHANGE)
        rr.insert_movement_role(c, WS, "m1", MovementRoleKind.FUND_DEPOSIT)
        assert rr.get_cursor(c, WS) == 0
        rr.set_cursor(c, WS, 7)
        rr.set_cursor(c, WS, 9)
        rr.insert_held_cash(c, WS, "cp-1", "USD", 100, date(2026, 10, 1))
        rr.insert_held_cash(c, WS, "cp-1", "USD", 250, date(2026, 10, 5))
        rr.log_intervention(c, WS, "PUSH", datetime(2026, 10, 3, tzinfo=timezone.utc))
        rr.log_intervention(c, WS, "PUSH", datetime(2026, 11, 3, tzinfo=timezone.utc))
        assert rr.hash_key("abc")
    with rr.read() as c:
        assert rr.partner_hashes(c, WS) == {"h1": "cp-p"}
        assert rr.own_hashes(c, WS) == {"h2"}
        assert rr.watched_accounts(c, WS) == {"acc-1"}
        assert rr.movement_role(c, "m1") is MovementRoleKind.FUND_DEPOSIT
        assert rr.movement_role(c, "nope") is None
        assert rr.get_cursor(c, WS) == 9
        assert rr.latest_held_cash(c, WS, "cp-1", "USD") == (250, date(2026, 10, 5))
        assert rr.latest_held_cash(c, WS, "cp-1", "EUR") is None
        assert rr.interventions_in_month(c, WS, 2026, 10) == 1
        assert rr.member_role(c, WS, "PSN-1") == "OWNER"
        assert rr.member_role(c, WS, "PSN-9") is None


def test_movement_root_follows_supersedes_chain(tmp_path):
    repo, rr = make(tmp_path)
    seed_connection(repo)
    repo.add_account(make_account())
    repo.insert_movement(make_movement("m1", tx="t1", fp="f1"))
    repo.insert_movement(make_movement("m2", tx="t2", fp="f2", supersedes="m1"))
    repo.insert_movement(make_movement("m3", tx="t3", fp="f3", supersedes="m2"))
    with rr.read() as c:
        assert rr.movement_root(c, "m3") == "m1"
        assert rr.movement_root(c, "m1") == "m1"
        rows = rr.movements_after(c, WS, 0)
        assert [m.id for _, m in rows] == ["m1", "m2", "m3"]
        assert rr.movements_after(c, WS, rows[1][0]) == rows[2:]


def test_usd_per_eur_on_uses_latest_rate_not_after_day(tmp_path):
    repo, rr = make(tmp_path)
    repo.store_fx_rates(date(2026, 10, 1), {"USD": Decimal("1.10")})
    repo.store_fx_rates(date(2026, 10, 5), {"USD": Decimal("1.20")})
    with rr.read() as c:
        assert rr.usd_per_eur_on(c, date(2026, 9, 30)) is None
        assert rr.usd_per_eur_on(c, date(2026, 10, 4)) == Decimal("1.10")
        assert rr.usd_per_eur_on(c, date(2026, 10, 9)) == Decimal("1.20")


def test_next_number_is_per_prefix_and_workspace(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        assert [rr.next_number(c, WS, "C"), rr.next_number(c, WS, "C"),
                rr.next_number(c, WS, "P"), rr.next_number(c, "ws-2", "C")] == [1, 2, 1, 1]


def _chain(tmp_path):
    repo, rr = make(tmp_path)
    seed_connection(repo)
    repo.add_account(make_account())
    repo.insert_movement(make_movement("m1", tx="t1", fp="f1"))
    repo.insert_movement(make_movement("m2", tx="t2", fp="f2", supersedes="m1"))
    repo.insert_movement(make_movement("m3", tx="t3", fp="f3", supersedes="m2"))
    return repo, rr


@pytest.mark.parametrize("funded,looked_up", [("m1", "m3"), ("m3", "m1")])
def test_funding_stores_root_movement(tmp_path, funded, looked_up):
    _, rr = _chain(tmp_path)
    with rr.tx() as c:
        rr.insert_funding(c, Funding("f1", WS, 1, (funded,), ("x1",), 1, 1, T0), {})
    with rr.read() as c:
        assert rr.live_funding_for_movement(c, looked_up).id == "f1"
        assert rr.live_funding_for_movement(c, "m2").id == "f1"
    assert raw_execute(_chain_repo(tmp_path), "SELECT movement_id FROM funding_movement") == [("m1",)]


def _chain_repo(tmp_path):
    return make_repo(tmp_path)


@pytest.mark.parametrize("written,read", [("m2", "m1"), ("m1", "m3"), ("m3", "m2")])
def test_movement_role_is_stored_on_the_root(tmp_path, written, read):
    repo, rr = _chain(tmp_path)
    with rr.tx() as c:
        rid = rr.insert_movement_role(c, WS, written, MovementRoleKind.RECEIVABLE_PAYMENT)
    with rr.read() as c:
        assert rr.movement_role(c, read) is MovementRoleKind.RECEIVABLE_PAYMENT
        assert rr.live_role_ids_for_movement(c, read) == [rid]
    assert raw_execute(repo, "SELECT movement_id FROM movement_role") == [("m1",)]


def test_revoke_rejects_unknown_table(tmp_path):
    _, rr = make(tmp_path)
    with pytest.raises(ValueError):
        with rr.tx() as c:
            rr.revoke(c, WS, "ledger_entries", "e1", "typo", T0)
    with rr.read() as c:
        assert c.execute("SELECT COUNT(*) FROM revocation").fetchone()[0] == 0


def test_receipt_by_id_finds_the_live_receipt_only(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_receipt(c, receipt("r1", 1, 5000))
        assert rr.receipt_by_id(c, WS, "r1").number == 1
        assert rr.receipt_by_id(c, "ws-2", "r1") is None
        assert rr.receipt_by_id(c, WS, "nope") is None
        rr.revoke(c, WS, "receipt", "r1", "x", T0)
        assert rr.receipt_by_id(c, WS, "r1") is None


def test_partner_identifier_records_the_funding_that_taught_it(tmp_path):
    """R60: an older table gains the nullable ``funding_id`` (added by ``upgrade_i2``)."""
    base, _ = make(tmp_path)
    raw_execute(base, "DROP TABLE partner_identifier")  # the table as an earlier build made it
    raw_execute(base, "CREATE TABLE partner_identifier(id TEXT PRIMARY KEY, workspace_id TEXT "
                      "NOT NULL, iban_hash TEXT NOT NULL, counterparty_id TEXT NOT NULL)")
    raw_execute(base, "INSERT INTO partner_identifier VALUES('pi-old',?,'h0','cp-p')", (WS,))
    rr = ReceivablesRepository(FinanceRepository(base.path, pepper=PEPPER))
    assert column_names(base, "partner_identifier")[-1] == "funding_id"
    FinanceRepository(base.path, pepper=PEPPER)  # a second open changes nothing
    with rr.tx() as c:
        rr.insert_funding(c, Funding("f1", WS, 1, ("m1",), ("x1",), 100, 100, T0), {})
        rr.insert_funding(c, Funding("f2", WS, 2, ("m1",), ("x1",), 120, 100, T0), {})  # redo
        rr.insert_funding(c, Funding("f3", WS, 3, ("m9",), ("x2",), 100, 100, T0), {})
        taught = rr.add_partner_identifier(c, WS, "h1", "cp-p", funding_id="f1")
        rr.add_partner_identifier(c, WS, "h2", "cp-p")  # set by the operator: no funding
        assert rr.identifiers_taught_by(c, WS, "f1") == [taught]
        assert rr.identifiers_taught_by(c, WS, "f2") == [taught]  # the same payment
        assert rr.identifiers_taught_by(c, WS, "f3") == []
        assert rr.identifiers_taught_by(c, "ws-2", "f1") == []
        rr.revoke(c, WS, "partner_identifier", taught, "funding reversed", T0)
        assert rr.identifiers_taught_by(c, WS, "f1") == []
        assert rr.partner_hashes(c, WS) == {"h0": "cp-p", "h2": "cp-p"}
    with pytest.raises(sqlite3.IntegrityError, match="facts are immutable"):
        raw_execute(base, "UPDATE partner_identifier SET funding_id='x'")


def test_owner_unlinked_and_go_live_mark(tmp_path):
    """R57: a funding revoked for any reason but the system's own leaves its payments for the
    owner's answer. R59: the go-live mark; 0 before the first matcher run."""
    _, rr = make(tmp_path)
    with rr.tx() as c:
        for fid, n, mid in (("f1", 1, "m1"), ("f2", 2, "m2"), ("f3", 3, "m3"), ("f4", 4, "m4")):
            rr.insert_funding(c, Funding(fid, WS, n, (mid,), (f"x{n}",), 100, 100, T0), {})
        rr.revoke(c, WS, "funding", "f1", "booked_amount_changed", T0)
        rr.revoke(c, WS, "funding", "f2", "add_to", T0)
        rr.revoke(c, WS, "funding", "f3", "no era para C3", T0)
        reasons = ("booked_amount_changed", "add_to")
        assert [rr.unlinked_by_owner(c, m, reasons) for m in ("m1", "m2", "m3", "m4")] == [
            False, False, True, False]
        assert rr.go_live_rowid(c, WS) == 0
        rr.init_cursor(c, WS, 7)
        rr.set_cursor(c, WS, 9)
        assert rr.go_live_rowid(c, WS) == 7
