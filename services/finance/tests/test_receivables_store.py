"""Receivables schema and repository (synthetic data only)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.receivables.model import (
    Allocation, AllocationMethod, Counterparty, CounterpartyKind, EntryKind, Exchange,
    ExchangeLine, Funding, LedgerEntry, MovementRoleKind, Receipt, ReceiptKind, Verification,
)
from app.store.receivables_repo import AlreadyRevoked, DuplicateAlias, ReceivablesRepository
from app.store.receivables_schema import FACT_TABLES
from tests.support import (
    T0, column_names, make_account, make_movement, make_repo, raw_execute, seed_connection,
    seed_workspace, table_names,
)

WS = "ws-1"
D = date(2026, 10, 9)


def make(tmp_path):
    repo = make_repo(tmp_path)
    seed_workspace(repo)
    return repo, ReceivablesRepository(repo)


def cp(cid="cp-1", label="Familiar A", kind=CounterpartyKind.PERSON, ws=WS):
    return Counterparty(cid, ws, kind, label, "ACTIVE")


def entry(eid="e1", number=1, amount=12000, cpid="cp-1", kind=EntryKind.CHARGE, src="line-1",
          cur="USD"):
    return LedgerEntry(eid, WS, number, cpid, cur, amount, kind, D, src)


def exchange(eid="x1", number=1, ves_hash=None):
    return Exchange(eid, WS, number, "cp-p", 20000, D, T0, ves_reference_hash=ves_hash)


def line(lid="line-1", eid="x1", version=1, position=1, usd=12000):
    return ExchangeLine(lid, eid, version, position, "cp-1", usd, "USD")


def receipt(rid="r1", number=1, amount=5000, movement_id=None, received=D):
    return Receipt(rid, WS, number, ReceiptKind.CASH, "cp-1", "USD", amount, received,
                   Verification.OWNER_CONFIRMED, movement_id)


def test_init_adds_i2_tables_without_touching_i1(tmp_path):
    repo = make_repo(tmp_path)
    before = column_names(repo, "movement")
    ReceivablesRepository(repo)
    assert {"exchange", "ledger_entry", "pending_item", "revocation"} <= set(table_names(repo))
    assert column_names(repo, "movement") == before


SAMPLES = {
    "exchange": "INSERT INTO exchange VALUES('x',?,1,'p',1,'2026-10-09','t',NULL,NULL)",
    "exchange_line": "INSERT INTO exchange_line VALUES('l',?,'x',1,1,'c',1,'USD',NULL,NULL)",
    "funding": "INSERT INTO funding VALUES('f',?,1,1,1,'t')",
    "funding_movement": "INSERT INTO funding_movement VALUES(?,'f','m')",
    "funding_exchange": "INSERT INTO funding_exchange VALUES(?,'f','x')",
    "funding_share": "INSERT INTO funding_share VALUES(?,'f','c',1)",
    "ledger_entry": "INSERT INTO ledger_entry VALUES('e',?,1,'c','USD',1,'CHARGE','2026-10-09','s','',NULL,NULL)",
    "receipt": "INSERT INTO receipt VALUES('r',?,1,'CASH','c','USD',1,'2026-10-09','OWNER_CONFIRMED',NULL,'')",
    "allocation": "INSERT INTO allocation VALUES('a',?,'r','l',1,'OWNER')",
    "held_cash_statement": "INSERT INTO held_cash_statement VALUES('h',?,'c','USD',1,'2026-10-09')",
    "payer_rule": "INSERT INTO payer_rule VALUES('pr',?,'k',NULL)",
    "movement_role": "INSERT INTO movement_role VALUES('mr',?,'m','NOT_EXCHANGE')",
    "revocation": "INSERT INTO revocation VALUES('rv',?,'exchange','x','r','t')",
    "intervention_log": "INSERT INTO intervention_log VALUES('i',?,'k','t')",
    "partner_identifier": "INSERT INTO partner_identifier VALUES('pi',?,'h','c')",
    "own_identifier": "INSERT INTO own_identifier VALUES('oi',?,'h')",
}


def test_samples_cover_every_fact_table():
    assert set(SAMPLES) == set(FACT_TABLES)


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
    with pytest.raises(DuplicateAlias):
        with rr.tx() as c:
            rr.insert_counterparty(c, cp("cp-2", "Familiar B"), ["MAMÁ"])
    with rr.read() as c:
        assert rr.get_counterparty(c, WS, "cp-2") is None


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


def test_receipt_movement_id_unique(tmp_path):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_receipt(c, receipt("r1", 1, movement_id="m1"))
    with pytest.raises(sqlite3.IntegrityError):
        with rr.tx() as c:
            rr.insert_receipt(c, receipt("r2", 2, movement_id="m1"))


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


@pytest.mark.parametrize("ref,expected", [("C2", "x2"), ("c2", "x2"), ("C9", None),
                                          ("F2", None), ("C", None), ("2", None), ("Cx", None)])
def test_exchange_by_ref(tmp_path, ref, expected):
    _, rr = make(tmp_path)
    with rr.tx() as c:
        rr.insert_exchange(c, exchange("x2", 2), [])
    with rr.read() as c:
        got = rr.exchange_by_ref(c, WS, ref)
        assert (got.id if got else None) == expected


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
