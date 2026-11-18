"""Receipts, allocation, credits, held cash, small-difference rule (synthetic data only)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app import domain
from app.receivables.corrections import correct_exchange, forgive
from app.receivables.funding import link_choice, reverse_funding, try_link
from app.receivables.ledger import Evidence, LineInput, ValidationError, receivables_view, record_exchange
from app.receivables.model import (
    OWNER, Counterparty, CounterpartyKind, EntryKind, Funding, MovementRoleKind, ReceiptKind,
    Verification,
)
from app.receivables.pending import PendingQueue
from app.receivables.receipts import (
    consume_credits, held_cash_shown, mark_held_cash, reallocate, record_receipt,
)
from app.store.receivables_repo import DuplicateReceipt, ReceivablesRepository
from tests.support import make_account, make_repo, seed_connection, seed_workspace

WS = "ws-1"
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
D13, D14, D15, D20, D21 = (date(2026, 11, d) for d in (13, 14, 15, 20, 21))
PARTNER_IBAN = "XX00 SYNTHETIC PARTNER 0001"
E1_LINES = [LineInput("a", 12000), LineInput("b", 8000), LineInput(OWNER, 4000),
            LineInput("f", 6000)]


def make(tmp_path):
    base = make_repo(tmp_path)
    seed_workspace(base)
    seed_connection(base)
    base.add_account(make_account(aid="acc-eur", currency="EUR"))
    base.store_fx_rates(D13, {"USD": Decimal("1.0870")})
    repo = ReceivablesRepository(base)
    with repo.tx() as c:
        def add(cid, label, kind, **kw):
            repo.insert_counterparty(c, Counterparty(cid, WS, kind, label, "ACTIVE", **kw), [label])
        add("p", "Socio", CounterpartyKind.EXCHANGE_PARTNER)
        add("a", "Familiar A", CounterpartyKind.PERSON, pay_currency="USD")
        add("b", "Familiar B", CounterpartyKind.PERSON, pay_currency="EUR")
        add("f", "Fondo F", CounterpartyKind.FUND)
        repo.add_partner_identifier(c, WS, repo.hash_key(PARTNER_IBAN), "p")
    return repo, PendingQueue(repo, lambda: NOW)


def exchange(repo, c, day, lines=E1_LINES):
    return record_exchange(repo, c, WS, partner_id="p",
                           total_usd_minor=sum(ln.usd_minor for ln in lines), lines=lines,
                           evidence=Evidence(None, None, day), now=NOW)


def move(repo, c, mid, amount, day=D14, currency="EUR", iban=PARTNER_IBAN):
    m = domain.Movement(mid, WS, "acc-eur", f"tx-{mid}", f"fp-{mid}",
                        domain.MovementStatus.BOOKED, day, day, amount, currency, "X",
                        repo.hash_key(iban), "transfer", None)
    repo.base.insert_movement_in_tx(c, m)
    return m


def fund_all(repo, c, q, mid, eur, day=D14):
    m = move(repo, c, mid, -eur, day)
    assert try_link(repo, c, WS, m, q, NOW) == "LINKED"


def receipt(repo, c, q, payer, cur, amount, day=D15, kind=ReceiptKind.CASH, **kw):
    default = (Verification.BANK_POSTED if kind is ReceiptKind.BANK
               else Verification.OWNER_CONFIRMED)
    ver = kw.pop("verification", default)
    return record_receipt(repo, c, WS, kind=kind, payer_id=payer, currency=cur,
                          amount_minor=amount, received_on=day, verification=ver, queue=q,
                          now=NOW, **kw)


def allocs(c, rid):
    rows = c.execute("SELECT a.line_id, a.amount_minor, a.method FROM allocation a WHERE "
                     "a.receipt_id=? AND NOT EXISTS (SELECT 1 FROM revocation r WHERE "
                     "r.table_name='allocation' AND r.target_id=a.id) ORDER BY a.rowid",
                     (rid,)).fetchall()
    return [(r["line_id"], r["amount_minor"], r["method"]) for r in rows]


def count(c, table):
    return c.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def adjustments(repo, c, cp):
    return [e for e in repo.entries(c, WS, cp) if e.kind is EntryKind.ADJUSTMENT]


def test_e1_bank_receipts_close_balances(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c, D13)
        lines = repo.current_lines(c, ex.id)
        move(repo, c, "m1", 12000, D15, "USD")
        r = receipt(repo, c, q, "a", "USD", 12000, kind=ReceiptKind.BANK, movement_id="m1")
        assert (r.number, r.kind) == (1, ReceiptKind.BANK)
        assert repo.balance(c, WS, "a", "USD") == 0
        assert allocs(c, r.id) == [(lines[0].id, 12000, "AUTO_EXACT")]
        assert repo.movement_role(c, "m1") is MovementRoleKind.RECEIVABLE_PAYMENT
        pay_entry = [e for e in repo.entries(c, WS, "a") if e.kind is EntryKind.PAYMENT][0]
        assert (pay_entry.amount_minor, pay_entry.source_ref) == (-12000, r.id)
        n = repo.pending_by_dedupe(c, WS, "INFO:receipt_applied:R1")
        assert n.payload["text_key"] == "receipt_applied:R1"
        assert n.payload["exchanges"] == [
            {"exchange_ref": "C1", "delivered_on": "2026-11-13", "amount": "120.00"}]
        with pytest.raises(DuplicateReceipt):
            receipt(repo, c, q, "a", "USD", 12000, kind=ReceiptKind.BANK, movement_id="m1")


def test_e2_prepayment_is_credit_then_consumed_at_funding(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        r = receipt(repo, c, q, "b", "EUR", 5000)
        assert repo.balance(c, WS, "b", "EUR") == -5000
        assert allocs(c, r.id) == []
        n = repo.pending_by_dedupe(c, WS, "INFO:receipt_applied:R1")
        assert (n.payload["exchanges"], n.payload["credit"], n.payload["balance_after"]) == (
            [], "50.00", "-50.00")
        exchange(repo, c, D13)
        fund_all(repo, c, q, "m1", 27600)
        assert repo.balance(c, WS, "b", "EUR") == 2360
        [(_, amount, method)] = allocs(c, r.id)
        assert (amount, method) == (5000, "AUTO_FIFO")
        assert repo.receipt_remainders(c, WS, "b", "EUR") == []
        assert [o.outstanding_minor for o in repo.open_lines(c, WS, "b", "EUR")] == [2360]


def test_e3_exact_subset_and_fifo_with_remainder(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13, [LineInput("a", 3000), LineInput("a", 5000)])
        c2 = exchange(repo, c, D14, [LineInput("a", 2000)])
        ids = [ln.id for ln in repo.current_lines(c, c1.id)] + [repo.current_lines(c, c2.id)[0].id]
        r = receipt(repo, c, q, "a", "USD", 7000)  # 5000 + 2000 exact (not the oldest FIFO)
        assert allocs(c, r.id) == [(ids[1], 5000, "AUTO_EXACT"), (ids[2], 2000, "AUTO_EXACT")]
        r2 = receipt(repo, c, q, "a", "USD", 4000)  # no exact: FIFO 3000, 1000 credit
        assert allocs(c, r2.id) == [(ids[0], 3000, "AUTO_FIFO")]
        assert repo.receipt_remainders(c, WS, "a", "USD") == [(r2, 1000)]
        assert repo.balance(c, WS, "a", "USD") == 10000 - 11000


def test_e18_small_difference_closes(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        fund_all(repo, c, q, "m1", 27600)
        assert repo.balance(c, WS, "b", "EUR") == 7360
        line = repo.open_lines(c, WS, "b", "EUR")[0].line_id
        r = receipt(repo, c, q, "b", "EUR", 7300)
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert repo.open_lines(c, WS, "b", "EUR") == []
        assert [(e.amount_minor, e.source_ref) for e in adjustments(repo, c, "b")] == [(-60, line)]
        [adj] = adjustments(repo, c, "b")
        n = repo.pending_by_dedupe(c, WS, f"INFO:small_difference_closed:E{adj.number}").payload
        assert n == {"entry_ref": f"E{adj.number}", "receipt_ref": f"R{r.number}",
                     "currency": "EUR", "amount": "0.60", "direction": "they_owed",
                     "text_key": f"small_difference_closed:E{adj.number}"}


def test_e18_larger_difference_stays(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        fund_all(repo, c, q, "m1", 27600)
        receipt(repo, c, q, "b", "EUR", 7500)
        assert repo.balance(c, WS, "b", "EUR") == -140
        assert adjustments(repo, c, "b") == []


def test_small_difference_is_eur_only(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        receipt(repo, c, q, "a", "USD", 11950)  # 0.50 USD short: stays
        assert repo.balance(c, WS, "a", "USD") == 50
        assert adjustments(repo, c, "a") == []


def test_prepaid_credit_meeting_charge_gets_small_difference_closed(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        r = receipt(repo, c, q, "b", "EUR", 7300)
        exchange(repo, c, D13)
        fund_all(repo, c, q, "m1", 27600)
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert repo.open_lines(c, WS, "b", "EUR") == []
        [adj] = adjustments(repo, c, "b")
        assert adj.amount_minor == -60 and adj.source_ref != r.id
        n = repo.pending_by_dedupe(c, WS, f"INFO:small_difference_closed:E{adj.number}").payload
        assert (n["receipt_ref"], n["direction"]) == (f"R{r.number}", "they_owed")
        consume_credits(repo, c, WS, "b", "EUR", queue=q, now=NOW)  # nothing left: no-op
        assert len(adjustments(repo, c, "b")) == 1


def test_overpayment_within_tolerance_closes_the_receipt_remainder(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        fund_all(repo, c, q, "m1", 27600)
        r = receipt(repo, c, q, "b", "EUR", 7400)  # 0.40 over the 73.60 line
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert repo.receipt_remainders(c, WS, "b", "EUR") == []
        [adj] = adjustments(repo, c, "b")
        assert (adj.amount_minor, adj.source_ref) == (40, r.id)
        exchange(repo, c, D20, [LineInput("b", 1000)])
        fund_all(repo, c, q, "m2", 920, D20)
        assert repo.balance(c, WS, "b", "EUR") == 920  # the old 0.40 does not reduce it
        assert [o.outstanding_minor for o in repo.open_lines(c, WS, "b", "EUR")] == [920]


def test_in_kind_requires_description(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        for desc in ("", "   "):
            with pytest.raises(ValidationError) as e:
                receipt(repo, c, q, "a", "USD", 1000, kind=ReceiptKind.IN_KIND, description=desc)
            assert e.value.field == "description"
        r = receipt(repo, c, q, "a", "USD", 1000, kind=ReceiptKind.IN_KIND,
                    description="gift card")
        assert r.description == "gift card"
        assert count(c, "receipt") == 1


def test_validation_writes_nothing(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        tables = ("receipt", "ledger_entry", "ref_counter", "allocation")
        before = {t: count(c, t) for t in tables}
        bad = [
            dict(amount=0), dict(amount=-5), dict(cur="GBP"), dict(payer="zz"), dict(payer="p"),
            dict(kind=ReceiptKind.BANK, verification=Verification.OWNER_CONFIRMED,
                 movement_id="m9"),
            dict(kind=ReceiptKind.BANK),  # BANK_POSTED but no movement
            dict(verification=Verification.BANK_POSTED),  # CASH cannot be bank posted
            dict(kind=ReceiptKind.BANK, movement_id="nope"),
        ]
        move(repo, c, "m9", 1000, D15, "USD")
        for kw in bad:
            args = {"payer": "a", "cur": "USD", "amount": 1000, **kw}
            with pytest.raises(ValidationError):
                receipt(repo, c, q, args.pop("payer"), args.pop("cur"), args.pop("amount"), **args)
        assert before == {t: count(c, t) for t in tables}


def test_receipt_never_allocates_across_currencies(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)  # a owes USD
        r = receipt(repo, c, q, "a", "EUR", 5000)
        assert allocs(c, r.id) == []
        assert repo.balance(c, WS, "a", "USD") == 12000
        assert repo.balance(c, WS, "a", "EUR") == -5000
        assert [o.outstanding_minor for o in repo.open_lines(c, WS, "a", "USD")] == [12000]


def test_e8_held_cash_display_follows_cash_receipts(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13, [LineInput("a", 30000)])
        assert held_cash_shown(repo, c, WS, "a", "USD") is None
        assert receivables_view(repo, c, WS, NOW)["owed_to_you"][0]["held_cash"] is None
        mark_held_cash(repo, c, WS, "a", "USD", 15000, NOW)
        assert held_cash_shown(repo, c, WS, "a", "USD") == 15000
        receipt(repo, c, q, "a", "USD", 10000, day=D21)  # CASH, after the statement day
        assert held_cash_shown(repo, c, WS, "a", "USD") == 5000
        assert receivables_view(repo, c, WS, NOW)["owed_to_you"][0]["held_cash"] == "50.00"
        receipt(repo, c, q, "a", "USD", 7000, kind=ReceiptKind.IN_KIND, description="x",
                day=D21)  # not cash: no effect
        assert held_cash_shown(repo, c, WS, "a", "USD") == 5000
        mark_held_cash(repo, c, WS, "a", "USD", 90000, NOW)  # capped at the balance
        assert held_cash_shown(repo, c, WS, "a", "USD") == 13000


def test_held_cash_same_day_receipt_before_statement_is_not_zeroed(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13, [LineInput("a", 30000)])
        receipt(repo, c, q, "a", "USD", 10000, day=D20)  # same day as the statement
        mark_held_cash(repo, c, WS, "a", "USD", 15000, NOW)  # NOW is D20
        assert held_cash_shown(repo, c, WS, "a", "USD") == 15000


def test_mark_held_cash_validates(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        for cp, cur, amt in (("zz", "USD", 1), ("p", "USD", 1), ("a", "GBP", 1), ("a", "USD", -1)):
            with pytest.raises(ValidationError):
                mark_held_cash(repo, c, WS, cp, cur, amt, NOW)
        assert count(c, "held_cash_statement") == 0


def test_fund_deposit_increases_what_you_hold(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        before = repo.balance(c, WS, "f", "USD")
        move(repo, c, "m1", 4000, D15, "USD")
        r = receipt(repo, c, q, "f", "USD", 4000, kind=ReceiptKind.BANK, movement_id="m1")
        assert repo.balance(c, WS, "f", "USD") == before - 4000
        assert allocs(c, r.id) == []
        n = repo.pending_by_dedupe(c, WS, "INFO:receipt_applied:R1")
        # the fund's opening is unknown: no balance or credit figure is shown (spec 6.5)
        assert (n.payload["exchanges"], n.payload["credit"], n.payload["balance_after"]) == (
            [], None, None)
        assert repo.movement_role(c, "m1") is MovementRoleKind.FUND_DEPOSIT
        [e] = [e for e in repo.entries(c, WS, "f") if e.kind is EntryKind.PAYMENT]
        assert (e.amount_minor, e.source_ref) == (-4000, r.id)


def test_reallocate_respects_invariants(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13, [LineInput("a", 3000), LineInput("a", 5000)])
        c2 = exchange(repo, c, D14, [LineInput("a", 2000), LineInput("b", 1000)])
        la = [ln.id for ln in repo.current_lines(c, c1.id)] + [repo.current_lines(c, c2.id)[0].id]
        lb = repo.current_lines(c, c2.id)[1].id
        r = receipt(repo, c, q, "a", "USD", 4000)
        assert allocs(c, r.id) == [(la[0], 3000, "AUTO_FIFO"), (la[1], 1000, "AUTO_FIFO")]
        tables = ("allocation", "revocation")
        before = {t: count(c, t) for t in tables}

        def refuse(parts):
            with pytest.raises(ValidationError) as e:
                reallocate(repo, c, WS, r.id, parts, NOW)
            assert before == {t: count(c, t) for t in tables}
            assert len(allocs(c, r.id)) == 2
            return e.value

        refuse([(la[0], 0)])
        refuse([(la[0], -1)])
        refuse([("nope", 100)])
        refuse([(lb, 100)])  # another payer's line
        refuse([(la[2], 4001)])  # sum above the receipt amount
        err = refuse([(la[2], 2001)])  # more than the line's outstanding (2000)
        assert err.detail["outstanding"] == "20.00" and err.detail["part"] == "20.01"
        refuse([(la[0], 1500), (la[0], 1600)])  # duplicates are summed: 3100 > 3000
        with pytest.raises(ValidationError):
            reallocate(repo, c, WS, "nope", [], NOW)

        reallocate(repo, c, WS, r.id, [(la[2], 2000), (la[0], 2000)], NOW)
        assert allocs(c, r.id) == [(la[2], 2000, "OWNER"), (la[0], 2000, "OWNER")]
        reallocate(repo, c, WS, r.id, [(la[1], 4000)], NOW)  # parts may reuse freed lines
        assert allocs(c, r.id) == [(la[1], 4000, "OWNER")]
        reallocate(repo, c, WS, r.id, [], NOW)
        assert allocs(c, r.id) == []
        assert repo.balance(c, WS, "a", "USD") == 10000 - 4000  # the balance never changes
        f = receipt(repo, c, q, "f", "USD", 100)
        with pytest.raises(ValidationError):
            reallocate(repo, c, WS, f.id, [(la[0], 100)], NOW)


def adjustment_total(repo, c):
    """Sum of effective ADJUSTMENTs, whether sourced to a line or to a receipt."""
    refs = [r["ref"] for r in c.execute(
        "SELECT DISTINCT source_ref AS ref FROM ledger_entry WHERE kind='ADJUSTMENT'")]
    return sum(e.amount_minor for e in repo.effective_adjustments_for_refs(c, WS, refs))


def test_reverse_funding_reverses_small_difference_with_its_charge(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c, D13)
        m = move(repo, c, "m1", -27600)
        assert try_link(repo, c, WS, m, q, NOW) == "LINKED"
        r = receipt(repo, c, q, "b", "EUR", 7300)
        assert adjustment_total(repo, c) == -60
        reverse_funding(repo, c, WS, repo.live_funding_for_exchange(c, ex.id).id, "x", q, NOW)
        assert adjustment_total(repo, c) == 0
        assert repo.balance(c, WS, "b", "EUR") == -7300
        assert repo.receipt_remainders(c, WS, "b", "EUR") == [(r, 7300)]
        assert repo.open_lines(c, WS, "b", "EUR") == []
        assert try_link(repo, c, WS, m, q, NOW) == "LINKED"  # re-fund the same exchange
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert adjustment_total(repo, c) == -60  # not applied twice
        assert repo.open_lines(c, WS, "b", "EUR") == []
        assert repo.receipt_remainders(c, WS, "b", "EUR") == []


def test_add_to_reverses_small_difference_before_recharging(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        assert try_link(repo, c, WS, move(repo, c, "m1", -27600), q, NOW) == "LINKED"
        receipt(repo, c, q, "b", "EUR", 7300)
        assert adjustment_total(repo, c) == -60
        move(repo, c, "m2", -100, D15)
        assert link_choice(repo, c, WS, "m2", "ADD_TO:C1", q, NOW)["ok"] is not False
        assert repo.balance(c, WS, "b", "EUR") == 0  # 73.87 charged, 73.00 paid, 0.87 closed
        assert adjustment_total(repo, c) == -87
        assert repo.open_lines(c, WS, "b", "EUR") == []


def test_reverse_funding_reverses_receipt_side_write_off(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c, D13)
        m = move(repo, c, "m1", -27600)
        assert try_link(repo, c, WS, m, q, NOW) == "LINKED"
        r = receipt(repo, c, q, "b", "EUR", 7400)
        assert adjustment_total(repo, c) == 40
        reverse_funding(repo, c, WS, repo.live_funding_for_exchange(c, ex.id).id, "x", q, NOW)
        assert adjustment_total(repo, c) == 0
        assert repo.balance(c, WS, "b", "EUR") == -7400
        assert repo.receipt_remainders(c, WS, "b", "EUR") == [(r, 7400)]
        assert try_link(repo, c, WS, m, q, NOW) == "LINKED"  # the 0.40 is closed once
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert adjustment_total(repo, c) == 40
        assert repo.receipt_remainders(c, WS, "b", "EUR") == []


def test_reallocate_reverses_credit_write_off_first(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13)
        assert try_link(repo, c, WS, move(repo, c, "m1", -27600), q, NOW) == "LINKED"
        r = receipt(repo, c, q, "b", "EUR", 7400)
        assert adjustment_total(repo, c) == 40
        line = repo.current_lines(c, c1.id)[1].id
        with pytest.raises(ValidationError):  # the full receipt amount bounds the parts
            reallocate(repo, c, WS, r.id, [(line, 7401)], NOW)
        assert adjustment_total(repo, c) == 40  # nothing written on error
        reallocate(repo, c, WS, r.id, [(line, 7000)], NOW)
        assert adjustment_total(repo, c) == 0
        assert repo.balance(c, WS, "b", "EUR") == -40
        assert repo.receipt_remainders(c, WS, "b", "EUR") == [(r, 400)]


def test_receipt_applied_reports_the_balance_after_the_small_difference(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        fund_all(repo, c, q, "m1", 27600)
        receipt(repo, c, q, "b", "EUR", 7400)  # 0.40 over the 73.60 line: written off

        def applied(ref):
            n = repo.pending_by_dedupe(c, WS, f"INFO:receipt_applied:{ref}").payload
            return n["credit"], n["balance_after"]

        assert applied("R1") == ("0.00", "0.00")
        n = repo.pending_by_dedupe(c, WS, "INFO:receipt_applied:R1").payload
        assert (n["exchanges"], n["opening"]) == (
            [{"exchange_ref": "C1", "delivered_on": "2026-11-13", "amount": "73.60"}], None)
        exchange(repo, c, D20, [LineInput("b", 1000)])
        fund_all(repo, c, q, "m2", 920, D20)
        receipt(repo, c, q, "b", "EUR", 500)
        assert applied("R2") == ("0.00", "4.20")
        receipt(repo, c, q, "b", "EUR", 2000)
        assert applied("R3") == ("15.80", "-15.80")


def test_usd_credit_is_consumed_when_an_exchange_is_registered(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        r = receipt(repo, c, q, "a", "USD", 5000, day=D13)  # paid ahead
        ex = exchange(repo, c, D14, [LineInput("a", 12000)])
        line = repo.current_lines(c, ex.id)[0].id
        assert allocs(c, r.id) == [(line, 5000, "AUTO_FIFO")]
        assert [o.outstanding_minor for o in repo.open_lines(c, WS, "a", "USD")] == [7000]
        receipt(repo, c, q, "a", "USD", 7000, day=D20)
        assert repo.open_lines(c, WS, "a", "USD") == []
        assert repo.receipt_remainders(c, WS, "a", "USD") == []
        with pytest.raises(ValidationError) as e:
            forgive(repo, c, WS, "C1:Familiar A", None, "gift", NOW)
        assert e.value.field == "outstanding"
        assert repo.balance(c, WS, "a", "USD") == 0


def test_small_difference_notice_is_one_per_adjustment(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c, D13)
        receipt(repo, c, q, "b", "EUR", 7400, day=D13)  # paid 74.00 ahead
        fund_all(repo, c, q, "m1", 27600)  # charged 73.60: the 0.40 held is written off

        def notice(entry):
            n = repo.pending_by_dedupe(c, WS, f"INFO:small_difference_closed:E{entry.number}")
            return {k: n.payload[k] for k in ("entry_ref", "receipt_ref", "currency", "amount",
                                              "direction")}

        [first] = adjustments(repo, c, "b")
        assert notice(first) == {"entry_ref": f"E{first.number}", "receipt_ref": "R1",
                                 "currency": "EUR", "amount": "0.40", "direction": "you_held"}
        lines = [LineInput("a", 12000), LineInput("b", 8100), LineInput(OWNER, 3900),
                 LineInput("f", 6000)]
        correct_exchange(repo, c, WS, ex.id, lines, None, "b was 81", NOW, queue=q)
        _, second = adjustments(repo, c, "b")  # the first one is reversed
        assert notice(second) == {"entry_ref": f"E{second.number}", "receipt_ref": "R1",
                                  "currency": "EUR", "amount": "0.52", "direction": "they_owed"}
        assert repo.balance(c, WS, "b", "EUR") == 0


def test_bank_receipt_must_match_its_movement(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        fund_all(repo, c, q, "m1", 27600)  # outgoing, linked to F1
        move(repo, c, "in1", 12000, D15, "USD")
        move(repo, c, "in2", 12000, D15, "USD")
        repo.insert_movement_role(c, WS, "in2", MovementRoleKind.NOT_EXCHANGE)
        move(repo, c, "in3", 5000, D15, "USD")
        repo.insert_funding(c, Funding("fx", WS, 99, ("in3",), (), 5000, 5000, NOW), {})
        pending = domain.Movement("in-p", WS, "acc-eur", "tx-p", "fp-p",
                                  domain.MovementStatus.PENDING, D15, D15, 12000, "USD", "X",
                                  None, "t", None)
        repo.base.insert_movement_in_tx(c, pending)
        booked = domain.Movement("in-b", WS, "acc-eur", "tx-b", "fp-b",
                                 domain.MovementStatus.BOOKED, D20, D20, 11000, "USD", "X",
                                 None, "t", "in-p")
        repo.base.insert_movement_in_tx(c, booked)
        tables = ("receipt", "ledger_entry", "allocation", "movement_role", "ref_counter")
        before = {t: count(c, t) for t in tables}
        for payer, cur, amount, mid, reason in [
                ("b", "EUR", 99999, "in1", "currency"), ("a", "USD", 11000, "in1", "amount"),
                ("b", "EUR", 27600, "m1", "outgoing"), ("a", "USD", 12000, "in2", "classified"),
                ("a", "USD", 5000, "in3", "funded"), ("a", "USD", 12000, "nope", "unknown"),
                ("a", "USD", 12000, "in-p", "amount")]:  # the bank now says 110.00
            with pytest.raises(ValidationError) as e:
                receipt(repo, c, q, payer, cur, amount, kind=ReceiptKind.BANK, movement_id=mid)
            assert (e.value.field, e.value.detail["reason"]) == ("movement", reason)
        assert before == {t: count(c, t) for t in tables}
        receipt(repo, c, q, "a", "USD", 11000, kind=ReceiptKind.BANK, movement_id="in-p")
        receipt(repo, c, q, "a", "USD", 12000, kind=ReceiptKind.BANK, movement_id="in1")
        assert repo.balance(c, WS, "a", "USD") == 12000 - 23000
