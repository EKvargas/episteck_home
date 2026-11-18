"""Receipts, allocation, credits, held cash, small-difference rule (synthetic data only)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app import domain
from app.receivables.funding import link_choice, reverse_funding, try_link
from app.receivables.ledger import Evidence, LineInput, ValidationError, receivables_view, record_exchange
from app.receivables.model import (
    OWNER, Counterparty, CounterpartyKind, EntryKind, MovementRoleKind, ReceiptKind,
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
        assert (n.payload["exchanges"], n.payload["credit"]) == ([], "50.00")
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
        assert repo.pending_by_dedupe(c, WS, f"INFO:small_difference_closed:{r.id}") is not None


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
        assert repo.pending_by_dedupe(c, WS, f"INFO:small_difference_closed:{r.id}") is not None
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
        assert (n.payload["exchanges"], n.payload["credit"]) == ([], "40.00")
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


def live_adjustment_sum(repo, c):
    return sum(e.amount_minor for e in repo.effective_adjustments_for_lines(
        c, WS, [r["line_id"] for r in c.execute(
            "SELECT DISTINCT source_ref AS line_id FROM ledger_entry WHERE kind='ADJUSTMENT'")]))


def test_reverse_funding_reverses_small_difference_with_its_charge(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c, D13)
        m = move(repo, c, "m1", -27600)
        assert try_link(repo, c, WS, m, q, NOW) == "LINKED"
        r = receipt(repo, c, q, "b", "EUR", 7300)
        assert live_adjustment_sum(repo, c) == -60
        reverse_funding(repo, c, WS, repo.live_funding_for_exchange(c, ex.id).id, "x", q, NOW)
        assert live_adjustment_sum(repo, c) == 0
        assert repo.balance(c, WS, "b", "EUR") == -7300
        assert repo.receipt_remainders(c, WS, "b", "EUR") == [(r, 7300)]
        assert repo.open_lines(c, WS, "b", "EUR") == []
        assert try_link(repo, c, WS, m, q, NOW) == "LINKED"  # re-fund the same exchange
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert live_adjustment_sum(repo, c) == -60  # not applied twice
        assert repo.open_lines(c, WS, "b", "EUR") == []
        assert repo.receipt_remainders(c, WS, "b", "EUR") == []


def test_add_to_reverses_small_difference_before_recharging(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        assert try_link(repo, c, WS, move(repo, c, "m1", -27600), q, NOW) == "LINKED"
        receipt(repo, c, q, "b", "EUR", 7300)
        assert live_adjustment_sum(repo, c) == -60
        move(repo, c, "m2", -100, D15)
        assert link_choice(repo, c, WS, "m2", "ADD_TO:C1", q, NOW)["ok"] is not False
        assert repo.balance(c, WS, "b", "EUR") == 0  # 73.87 charged, 73.00 paid, 0.87 closed
        assert live_adjustment_sum(repo, c) == -87
        assert repo.open_lines(c, WS, "b", "EUR") == []
