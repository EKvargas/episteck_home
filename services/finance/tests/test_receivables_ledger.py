"""record_exchange and receivables_view (synthetic data only)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.receivables.ledger import (
    Evidence, LineInput, ValidationError, receivables_view, record_exchange,
)
from app.receivables.model import (
    CASH_ABROAD, OWNER, Counterparty, CounterpartyKind, EntryKind, LedgerEntry, Opening,
)
from app.store.receivables_repo import ReceivablesRepository
from tests.support import make_account, make_repo, seed_connection, seed_workspace

WS = "ws-1"
NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)


def make(tmp_path):
    base = make_repo(tmp_path)
    seed_workspace(base)
    seed_connection(base)
    base.add_account(make_account(aid="acc-usd", currency="USD", institution="Banco Sintetico"))
    repo = ReceivablesRepository(base)
    with repo.tx() as c:
        def add(cid, label, kind, **kw):
            repo.insert_counterparty(c, Counterparty(cid, WS, kind, label, "ACTIVE", **kw), [label])
        add("p", "Socio", CounterpartyKind.EXCHANGE_PARTNER)
        add("a", "Familiar A", CounterpartyKind.PERSON, pay_currency="USD", settles_to="acc-usd")
        add("b", "Familiar B", CounterpartyKind.PERSON, pay_currency="EUR")
        add("f", "Fondo F", CounterpartyKind.FUND, opening=Opening.UNKNOWN)
        add("c", "Familiar C", CounterpartyKind.PERSON, pay_currency="USD", settles_to=CASH_ABROAD)
    return repo


def e1(repo, c, ref="ref-1"):
    return record_exchange(
        repo, c, WS, partner_id="p", total_usd_minor=30000,
        lines=[LineInput("a", 12000), LineInput("b", 8000), LineInput(OWNER, 4000),
               LineInput("f", 6000)],
        evidence=Evidence(9_000_000, ref, date(2026, 11, 13)), now=NOW)


def test_record_exchange_creates_lines_and_usd_charges(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        ex = e1(repo, c)
        assert ex.number == 1 and ex.ves_reference_hash == repo.hash_key("ref-1")
        assert ex.ves_reference_hash != "ref-1"
        lines = repo.current_lines(c, ex.id)
        assert [ln.debt_currency for ln in lines] == ["USD", "EUR", "USD", "USD"]
        assert repo.balance(c, WS, "a", "USD") == 12000
        assert repo.balance(c, WS, "f", "USD") == 6000
        assert repo.entries(c, WS, "b") == []
        ent = repo.entries(c, WS, "a")[0]
        assert ent.kind is EntryKind.CHARGE and ent.source_ref == lines[0].id
        assert ent.effective_on == date(2026, 11, 13)
        assert repo.open_lines(c, WS, "a", "USD")[0].outstanding_minor == 12000
        view = receivables_view(repo, c, WS, NOW)
    assert view["to_fix"] == [{"counterparty": "Familiar B", "exchange_ref": "C1", "usd": "80.00"}]
    assert list(view) == ["as_of", "owed_to_you", "to_fix", "held_for_others", "owed_to_partner",
                          "subtotals", "interventions_this_month"]


def test_delivered_on_defaults_to_today(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        ex = record_exchange(repo, c, WS, partner_id="p", total_usd_minor=100,
                             lines=[LineInput("a", 100)], evidence=None, now=NOW)
    assert ex.delivered_on == NOW.date() and ex.ves_reference_hash is None


def test_lines_must_sum_to_total(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c, pytest.raises(ValidationError) as ei:
        record_exchange(repo, c, WS, partner_id="p", total_usd_minor=30000,
                        lines=[LineInput("a", 12000), LineInput("f", 17000)], evidence=None,
                        now=NOW)
    assert ei.value.field == "lines_total"
    assert ei.value.detail == {"total": "300.00", "sum": "290.00"}


@pytest.mark.parametrize("payer", ["p", "nobody"])
def test_partner_cannot_be_a_payer(tmp_path, payer):
    repo = make(tmp_path)
    with repo.tx() as c, pytest.raises(ValidationError) as ei:
        record_exchange(repo, c, WS, partner_id="p", total_usd_minor=100,
                        lines=[LineInput(payer, 100)], evidence=None, now=NOW)
    assert ei.value.field == "payer"


def test_partner_and_amounts_are_validated(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        with pytest.raises(ValidationError) as ei:
            record_exchange(repo, c, WS, partner_id="a", total_usd_minor=100,
                            lines=[LineInput("a", 100)], evidence=None, now=NOW)
        assert ei.value.field == "partner"
        with pytest.raises(ValidationError) as ei:
            record_exchange(repo, c, WS, partner_id="p", total_usd_minor=100,
                            lines=[LineInput("a", 150), LineInput("f", -50)], evidence=None,
                            now=NOW)
        assert ei.value.field == "usd"


def test_owed_to_partner_lists_open_exchanges(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        e1(repo, c)
        view = receivables_view(repo, c, WS, NOW)
    assert view["owed_to_partner"] == {
        "currency": "USD", "amount": "300.00",
        "exchanges": [{"exchange_ref": "C1", "delivered_on": "2026-11-13", "usd": "300.00"}]}


def test_owed_to_you_row_and_where(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        e1(repo, c)
        view = receivables_view(repo, c, WS, NOW)
    assert view["owed_to_you"] == [{
        "counterparty": "Familiar A", "currency": "USD", "amount": "120.00",
        "where": "Banco Sintetico", "held_cash": None, "opening": None,
        "lines": [{"exchange_ref": "C1", "delivered_on": "2026-11-13", "usd": "120.00",
                   "debt": "120.00", "outstanding": "120.00", "currency": "USD"}]}]


def test_fund_with_unknown_opening_shows_flows_not_balance(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        e1(repo, c)
        repo.insert_entry(c, LedgerEntry("d1", WS, 90, "f", "USD", -2500, EntryKind.PAYMENT,
                                         date(2026, 11, 14), "dep"))
        view = receivables_view(repo, c, WS, NOW)
    row = view["held_for_others"][0]
    assert row["kind"] == "FUND" and row["amount"] is None and row["opening"] == "UNKNOWN"
    assert row["out_since"] == "60.00" and row["in_since"] == "25.00"
    assert row["since"] == "2026-11-13"
    assert view["subtotals"]["held_for_others"] == {}


def test_prepaid_person_appears_in_held_for_others(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        repo.insert_entry(c, LedgerEntry("e1", WS, 1, "c", "USD", -2000, EntryKind.PAYMENT,
                                         date(2026, 11, 1), "pre"))
        view = receivables_view(repo, c, WS, NOW)
    prepaid = [r for r in view["held_for_others"] if r["kind"] == "PREPAYMENT"]
    assert prepaid == [{"counterparty": "Familiar C", "kind": "PREPAYMENT", "currency": "USD",
                        "amount": "20.00", "opening": None, "since": None, "out_since": None,
                        "in_since": None, "account": CASH_ABROAD}]
    assert view["owed_to_you"] == []
    assert view["subtotals"]["held_for_others"] == {"USD": "20.00"}


def test_currencies_are_never_summed_in_subtotals(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        ex = e1(repo, c)
        b_line = repo.current_lines(c, ex.id)[1]
        repo.insert_entry(c, LedgerEntry("eb", WS, 91, "b", "EUR", 7360, EntryKind.CHARGE,
                                         date(2026, 11, 13), b_line.id))
        view = receivables_view(repo, c, WS, NOW)
    assert view["subtotals"]["owed_to_you"] == {"EUR": "73.60", "USD": "120.00"}
    b = next(r for r in view["owed_to_you"] if r["currency"] == "EUR")
    assert b["lines"][0]["debt"] == "73.60" and b["lines"][0]["usd"] == "80.00"


def test_interventions_this_month(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        repo.log_intervention(c, WS, "x", NOW)
        assert receivables_view(repo, c, WS, NOW)["interventions_this_month"] == 1


def test_repo_flows_ignore_reversed_charges(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        e1(repo, c)
        eid = repo.entries(c, WS, "f")[0].id
        repo.insert_entry(c, LedgerEntry("r1", WS, 99, "f", "USD", -6000, EntryKind.REVERSAL,
                                         date(2026, 11, 13), "x", reverses_id=eid))
        assert repo.flows_since_creation(c, WS, "f", "USD") == (0, 0, None)
