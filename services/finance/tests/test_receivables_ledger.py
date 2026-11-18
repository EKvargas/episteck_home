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


def _fund_rows(view):
    return {(r["counterparty"], r["currency"]): r for r in view["held_for_others"]}


def _entry(repo, c, n, cp, cur, amount, kind=EntryKind.CHARGE, basis=None):
    repo.insert_entry(c, LedgerEntry(f"t{n}", WS, 900 + n, cp, cur, amount, kind,
                                     date(2026, 11, 13), f"s{n}", basis=basis))


def _add(repo, c, cid, label, kind, status="ACTIVE", **kw):
    repo.insert_counterparty(c, Counterparty(cid, WS, kind, label, status, **kw), [label])


def _bad(repo, lines):
    with repo.tx() as c:
        with pytest.raises(ValidationError) as err:
            record_exchange(repo, c, WS, partner_id="p",
                            total_usd_minor=sum(ln.usd_minor for ln in lines), lines=lines,
                            evidence=None, now=NOW)
    return err.value


def test_override_must_be_positive(tmp_path):
    repo = make(tmp_path)
    for ov in (0, -7350):
        err = _bad(repo, [LineInput("b", 8000, eur_override_minor=ov)])
        assert err.field == "eur_override" and err.detail["usd"] == "80.00"
    assert isinstance(err.detail["override"], str)


def test_override_refused_with_explicit_usd_debt(tmp_path):
    repo = make(tmp_path)
    assert _bad(repo, [LineInput("b", 8000, "USD", eur_override_minor=7350)]).field == "eur_override"


def test_override_refused_on_owner_and_fund_lines(tmp_path):
    repo = make(tmp_path)
    assert _bad(repo, [LineInput(OWNER, 8000, eur_override_minor=100)]).field == "eur_override"
    assert _bad(repo, [LineInput("f", 8000, eur_override_minor=100)]).field == "eur_override"


def test_override_on_usd_paying_person_without_debt_currency_makes_it_eur(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        ex = record_exchange(repo, c, WS, partner_id="p", total_usd_minor=8000,
                             lines=[LineInput("a", 8000, eur_override_minor=7350)],
                             evidence=None, now=NOW)
        ln = repo.current_lines(c, ex.id)[0]
        assert ln.debt_currency == "EUR" and ln.eur_override_minor == 7350
        assert repo.balance(c, WS, "a", "USD") == 0


def test_explicit_eur_debt_on_fund_line_is_refused(tmp_path):
    repo = make(tmp_path)
    assert _bad(repo, [LineInput("f", 8000, "EUR")]).field == "debt_currency"


def test_inactive_fund_with_balance_is_listed(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        _add(repo, c, "g", "Fondo G", CounterpartyKind.FUND, "ARCHIVED", opening=Opening.CONFIRMED)
        _entry(repo, c, 1, "g", "USD", -50000, EntryKind.OPENING, "CONFIRMED")
        rows = _fund_rows(receivables_view(repo, c, WS, NOW))
        assert rows[("Fondo G", "USD")]["amount"] == "500.00"
        assert receivables_view(repo, c, WS, NOW)["subtotals"]["held_for_others"] == {"USD": "500.00"}


def test_fund_balance_in_eur_is_listed(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        _add(repo, c, "g", "Fondo G", CounterpartyKind.FUND, opening=Opening.CONFIRMED)
        _entry(repo, c, 1, "g", "EUR", -10000, EntryKind.PAYMENT)
        view = receivables_view(repo, c, WS, NOW)
        assert _fund_rows(view)[("Fondo G", "EUR")]["amount"] == "100.00"
        assert view["subtotals"]["held_for_others"] == {"EUR": "100.00"}


def test_advancing_fund_shows_negative_and_does_not_net_subtotal(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        _add(repo, c, "g", "Fondo G", CounterpartyKind.FUND, opening=Opening.CONFIRMED)
        _add(repo, c, "h", "Fondo H", CounterpartyKind.FUND, opening=Opening.CONFIRMED)
        _entry(repo, c, 1, "g", "USD", -50000, EntryKind.OPENING, "CONFIRMED")
        _entry(repo, c, 2, "h", "USD", 10000)
        view = receivables_view(repo, c, WS, NOW)
        rows = _fund_rows(view)
        assert rows[("Fondo H", "USD")]["amount"] == "-100.00"
        assert view["subtotals"]["held_for_others"] == {"USD": "500.00"}


def test_known_opening_fund_shows_balance(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        _add(repo, c, "g", "Fondo G", CounterpartyKind.FUND, opening=Opening.CONFIRMED)
        view = receivables_view(repo, c, WS, NOW)
        assert _fund_rows(view)[("Fondo G", "USD")]["amount"] == "0.00"


def test_cash_abroad_where_is_kept_on_owed_rows(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        _entry(repo, c, 1, "c", "USD", 5000)
        rows = receivables_view(repo, c, WS, NOW)["owed_to_you"]
        assert rows[0]["where"] == CASH_ABROAD


def test_every_live_balance_appears_in_some_row(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        _add(repo, c, "g", "Fondo G", CounterpartyKind.FUND, "ARCHIVED", opening=Opening.CONFIRMED)
        _entry(repo, c, 1, "g", "EUR", -700, EntryKind.PAYMENT)
        _entry(repo, c, 2, "f", "EUR", 300)
        _entry(repo, c, 3, "a", "USD", 900)
        _entry(repo, c, 4, "b", "EUR", -400, EntryKind.PAYMENT)
        view = receivables_view(repo, c, WS, NOW)
        shown = {(r["counterparty"], r["currency"])
                 for r in view["owed_to_you"] + view["held_for_others"]}
        labels = {cp.id: cp.label for cp in repo.list_counterparties(c, WS)}
        for (cid, cur), bal in repo.balances(c, WS).items():
            if bal:
                assert (labels[cid], cur) in shown


def test_owed_to_partner_sums_current_lines_after_correction(tmp_path):
    repo = make(tmp_path)
    with repo.tx() as c:
        ex = e1(repo, c)
        c.execute("INSERT INTO exchange_line(id,workspace_id,exchange_id,version,position,"
                  "payer_id,usd_minor,debt_currency) VALUES('l2',?,?,2,0,'a',25000,'USD')",
                  (WS, ex.id))
        owed = receivables_view(repo, c, WS, NOW)["owed_to_partner"]
        assert owed["amount"] == "250.00" and owed["exchanges"][0]["usd"] == "250.00"
