"""Openings as open items or credits (R29) and the item/balance invariant (synthetic data only)."""
from __future__ import annotations

import random
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app import domain
from app.receivables.corrections import correct_exchange, forgive, record_opening, reverse
from app.receivables.funding import AlreadyLinked, create_funding, try_link
from app.receivables.ledger import (
    Evidence, LineInput, ValidationError, receivables_view, record_exchange,
)
from app.receivables.model import (
    OWNER, Counterparty, CounterpartyKind, EntryKind, Opening, ReceiptKind, Verification,
)
from app.receivables.pending import PendingQueue
from app.receivables.receipts import consume_credits, record_receipt
from app.store.receivables_repo import ReceivablesRepository
from tests.support import make_account, make_repo, seed_connection, seed_workspace

WS = "ws-1"
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
D13, D14, D15, D16 = (date(2026, 11, d) for d in (13, 14, 15, 16))
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
        add("f", "Fondo F", CounterpartyKind.FUND, opening=Opening.UNKNOWN)
        repo.add_partner_identifier(c, WS, repo.hash_key(PARTNER_IBAN), "p")
    return repo, PendingQueue(repo, lambda: NOW)


def exchange(repo, c, day=D13, lines=E1_LINES):
    return record_exchange(repo, c, WS, partner_id="p",
                           total_usd_minor=sum(ln.usd_minor for ln in lines), lines=lines,
                           evidence=Evidence(None, None, day), now=NOW)


def move(repo, c, mid, amount, day=D14):
    m = domain.Movement(mid, WS, "acc-eur", f"tx-{mid}", f"fp-{mid}",
                        domain.MovementStatus.BOOKED, day, day, amount, "EUR", "X",
                        repo.hash_key(PARTNER_IBAN), "transfer", None)
    repo.base.insert_movement_in_tx(c, m)
    return m


def fund(repo, c, q, mid, eur, day=D14):
    assert try_link(repo, c, WS, move(repo, c, mid, -eur, day), q, NOW) == "LINKED"


def receipt(repo, c, q, payer, cur, amount, day=D15):
    return record_receipt(repo, c, WS, kind=ReceiptKind.CASH, payer_id=payer, currency=cur,
                          amount_minor=amount, received_on=day,
                          verification=Verification.OWNER_CONFIRMED, queue=q, now=NOW)


def opening(repo, c, cp, cur, amount, **kw):
    return record_opening(repo, c, WS, cp, cur, amount, Opening.CONFIRMED, "segun el dueno",
                          NOW, **kw)


def items(repo, c, cp, cur):
    return [(o.is_opening, o.outstanding_minor) for o in repo.open_lines(c, WS, cp, cur)]


def credits(repo, c, cp, cur):
    return [left for _, left in repo.credit_sources(c, WS, cp, cur)]


def paid(repo, c, source_id):
    return [(a.line_id, a.amount_minor)
            for a in repo.live_allocations_for_receipt(c, WS, source_id)]


def settlements(repo, c, cp):
    """Effective ADJUSTMENT/FORGIVE entries of a counterparty as (kind, amount, source)."""
    refs = {e.source_ref for e in repo.entries(c, WS, cp)}
    return [(e.kind, e.amount_minor, e.source_ref) for e in repo.effective_entries_for_refs(
        c, WS, refs, (EntryKind.ADJUSTMENT, EntryKind.FORGIVE)) if e.counterparty_id == cp]


def check(repo, c):
    """Every PERSON and currency: Σ outstanding(open items) − Σ remaining credits = balance."""
    for cp in repo.list_counterparties(c, WS):
        if cp.kind is not CounterpartyKind.PERSON:
            continue
        for cur in ("USD", "EUR"):
            owed = sum(o.outstanding_minor for o in repo.open_lines(c, WS, cp.id, cur))
            held = sum(left for _, left in repo.credit_sources(c, WS, cp.id, cur))
            assert owed - held == repo.balance(c, WS, cp.id, cur), (cp.label, cur, owed, held)


# --- a positive opening is the oldest open item ----------------------------------------
def test_paid_person_opening_leaves_no_credit(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        op = opening(repo, c, "a", "USD", 12000)
        r = receipt(repo, c, q, "a", "USD", 12000)
        assert repo.balance(c, WS, "a", "USD") == 0
        assert repo.receipt_remainders(c, WS, "a", "USD") == []  # no fake 120.00 credit
        assert paid(repo, c, r.id) == [(op.id, 12000)]
        n = repo.pending_by_dedupe(c, WS, "INFO:receipt_applied:R1").payload
        assert (n["exchanges"], n["opening"], n["credit"], n["balance_after"]) == (
            [], {"entry_ref": f"E{op.number}", "amount": "120.00"}, "0.00", "0.00")
        exchange(repo, c, D16, [LineInput("a", 5000)])  # new debt: nothing pays it
        consume_credits(repo, c, WS, "a", "USD", queue=q, now=NOW)
        assert items(repo, c, "a", "USD") == [(False, 5000)]
        [row] = receivables_view(repo, c, WS, NOW)["owed_to_you"]
        assert (row["amount"], [ln["exchange_ref"] for ln in row["lines"]]) == ("50.00", ["C1"])
        assert forgive(repo, c, WS, "C1:Familiar A", None, "gift", NOW).amount_minor == -5000
        check(repo, c)


def test_opening_is_the_oldest_open_item(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        op = opening(repo, c, "a", "USD", 12000)
        exchange(repo, c, D13, [LineInput("a", 12000)])
        first, second = repo.open_lines(c, WS, "a", "USD")
        assert (first.line_id, first.is_opening, second.is_opening) == (op.id, True, False)
        assert first.order < second.order
        [row] = receivables_view(repo, c, WS, NOW)["owed_to_you"]
        assert row["lines"][0] == {
            "exchange_ref": None, "entry_ref": f"E{op.number}", "delivered_on": "2026-11-20",
            "usd": None, "debt": "120.00", "outstanding": "120.00", "currency": "USD"}
        assert (row["lines"][1]["exchange_ref"], row["lines"][1]["entry_ref"]) == ("C1", None)
        receipt(repo, c, q, "a", "USD", 12000)  # both items match exactly: the opening is older
        assert items(repo, c, "a", "USD") == [(False, 12000)]
        receipt(repo, c, q, "a", "USD", 5000)
        assert items(repo, c, "a", "USD") == [(False, 7000)]
        check(repo, c)


def test_forgive_by_counterparty_settles_the_opening_first(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        op = opening(repo, c, "a", "USD", 3000)
        ex = exchange(repo, c, D13, [LineInput("a", 12000)])
        line = repo.current_lines(c, ex.id)[0].id
        forgive(repo, c, WS, "Familiar A", 5000, "gift", NOW)
        assert settlements(repo, c, "a") == [(EntryKind.FORGIVE, -3000, op.id),
                                             (EntryKind.FORGIVE, -2000, line)]
        reverse(repo, c, WS, f"E{op.number}", "no opening", q, NOW)  # its gift goes with it
        assert settlements(repo, c, "a") == [(EntryKind.FORGIVE, -2000, line)]
        assert repo.balance(c, WS, "a", "USD") == 10000
        assert items(repo, c, "a", "USD") == [(False, 10000)]
        check(repo, c)


def test_small_difference_on_an_opening_never_becomes_a_credit(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        op = opening(repo, c, "b", "EUR", 7360)
        receipt(repo, c, q, "b", "EUR", 7300)  # 0.60 short: closed on the opening
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert repo.receipt_remainders(c, WS, "b", "EUR") == []
        assert settlements(repo, c, "b") == [(EntryKind.ADJUSTMENT, -60, op.id)]
        reverse(repo, c, WS, "R1", "never paid", q, NOW)
        assert settlements(repo, c, "b") == []
        assert items(repo, c, "b", "EUR") == [(True, 7360)]
        check(repo, c)


# --- a negative opening is a credit -----------------------------------------------------
def test_negative_person_opening_is_a_credit_consumed_by_charges(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        op = opening(repo, c, "a", "USD", -5000)
        assert (items(repo, c, "a", "USD"), credits(repo, c, "a", "USD")) == ([], [5000])
        ex = exchange(repo, c, D13, [LineInput("a", 12000)])
        line = repo.current_lines(c, ex.id)[0].id
        assert paid(repo, c, op.id) == [(line, 5000)]
        assert items(repo, c, "a", "USD") == [(False, 7000)]
        assert forgive(repo, c, WS, "C1:Familiar A", None, "gift", NOW).amount_minor == -7000
        assert repo.balance(c, WS, "a", "USD") == 0
        check(repo, c)


def test_negative_eur_opening_meets_a_funded_charge(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        opening(repo, c, "b", "EUR", -7300, queue=q)
        exchange(repo, c)
        fund(repo, c, q, "m1", 27600)  # b is charged 73.60; the opening pays 73.00
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert (items(repo, c, "b", "EUR"), credits(repo, c, "b", "EUR")) == ([], [])
        [n] = [p.payload for p in q.open_items(c, WS)
               if p.payload["text_key"].startswith("small_difference_closed")]
        assert (n["receipt_ref"], n["amount"], n["direction"]) == (None, "0.60", "they_owed")
        check(repo, c)


# --- undo and replace -------------------------------------------------------------------
def test_reversing_a_paid_opening_frees_the_receipt(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        op = opening(repo, c, "a", "USD", 12000)
        r = receipt(repo, c, q, "a", "USD", 12000)
        reverse(repo, c, WS, f"E{op.number}", "typo", q, NOW)
        assert repo.balance(c, WS, "a", "USD") == -12000
        assert (paid(repo, c, r.id), credits(repo, c, "a", "USD")) == ([], [12000])
        assert repo.get_counterparty(c, WS, "a").opening is None
        check(repo, c)


def test_reversing_a_credit_opening_reopens_what_it_paid(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        op = opening(repo, c, "a", "USD", -5000)
        exchange(repo, c, D13, [LineInput("a", 12000)])
        reverse(repo, c, WS, f"E{op.number}", "typo", q, NOW)
        assert (paid(repo, c, op.id), items(repo, c, "a", "USD")) == ([], [(False, 12000)])
        check(repo, c)


def test_replacing_an_opening_reapplies_the_credits(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        r = receipt(repo, c, q, "a", "USD", 5000, day=D13)  # paid ahead
        first = opening(repo, c, "a", "USD", 12000)
        assert (items(repo, c, "a", "USD"), paid(repo, c, r.id)) == ([(True, 7000)],
                                                                      [(first.id, 5000)])
        second = opening(repo, c, "a", "USD", 10000)
        assert repo.entry_by_ref(c, WS, f"E{first.number}") is None
        assert (items(repo, c, "a", "USD"), paid(repo, c, r.id)) == ([(True, 5000)],
                                                                      [(second.id, 5000)])
        check(repo, c)


# --- the invariant over sequences -------------------------------------------------------
def _opening_paid(repo, c, q):
    op = opening(repo, c, "a", "USD", 12000)
    yield
    r = receipt(repo, c, q, "a", "USD", 12000)
    yield
    exchange(repo, c, D16, [LineInput("a", 5000)])
    yield
    reverse(repo, c, WS, f"R{r.number}", "x", q, NOW)
    yield
    reverse(repo, c, WS, f"E{op.number}", "x", q, NOW)
    yield


def _opening_exchange_partials(repo, c, q):
    op = opening(repo, c, "a", "USD", 12000)
    yield
    exchange(repo, c, D13, [LineInput("a", 12000)])
    yield
    receipt(repo, c, q, "a", "USD", 5000)
    yield
    r2 = receipt(repo, c, q, "a", "USD", 10000)
    yield
    receipt(repo, c, q, "a", "USD", 9000)
    yield
    reverse(repo, c, WS, f"R{r2.number}", "x", q, NOW)
    yield
    reverse(repo, c, WS, "C1", "x", q, NOW)
    yield
    reverse(repo, c, WS, f"E{op.number}", "x", q, NOW)
    yield


def _negative_opening_funding(repo, c, q):
    op = opening(repo, c, "b", "EUR", -7300, queue=q)
    yield
    exchange(repo, c)
    yield
    fund(repo, c, q, "m1", 27600)
    yield
    reverse(repo, c, WS, "F1", "x", q, NOW)
    yield
    reverse(repo, c, WS, f"E{op.number}", "x", q, NOW)
    yield
    assert try_link(repo, c, WS, repo.movement_current(c, WS, "m1"), q, NOW) == "LINKED"
    yield


def _eur_opening_small_difference(repo, c, q):
    opening(repo, c, "b", "EUR", 7360, queue=q)
    yield
    r = receipt(repo, c, q, "b", "EUR", 7300)
    yield
    opening(repo, c, "b", "EUR", 7000, queue=q)  # replaced: R1 now pays 3.00 too much
    yield
    reverse(repo, c, WS, f"R{r.number}", "x", q, NOW)
    yield
    forgive(repo, c, WS, "Familiar B", None, "gift", NOW)
    yield


def _forgive_and_correct(repo, c, q):
    op = opening(repo, c, "a", "USD", 3000)
    yield
    ex = exchange(repo, c, D13, [LineInput("a", 12000), LineInput("b", 8000)])
    yield
    gift = forgive(repo, c, WS, "Familiar A", 3000, "gift", NOW)  # the opening, oldest
    yield
    reverse(repo, c, WS, f"E{gift.number}", "x", q, NOW)
    yield
    correct_exchange(repo, c, WS, ex.id, [LineInput("a", 10000), LineInput("b", 8000)], None,
                     "x", NOW, queue=q)
    yield
    receipt(repo, c, q, "a", "USD", 13000)
    yield
    reverse(repo, c, WS, f"E{op.number}", "x", q, NOW)
    yield


@pytest.mark.parametrize("scenario", [
    _opening_paid, _opening_exchange_partials, _negative_opening_funding,
    _eur_opening_small_difference, _forgive_and_correct])
def test_items_explain_the_balance_after_every_step(tmp_path, scenario):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        for _ in scenario(repo, c, q):
            check(repo, c)


def _random_step(repo, c, q, rnd: random.Random, refs: list[str], n: int) -> None:
    person = rnd.choice(["a", "b"])
    cur = rnd.choice(["USD", "EUR"])
    op = rnd.choice(["opening", "exchange", "exchange", "fund", "receipt", "receipt",
                     "reverse", "forgive", "correct"])
    if op == "opening":
        e = opening(repo, c, person, cur, rnd.choice([-7300, -5000, 3000, 7360, 12000]), queue=q)
        refs.append(f"E{e.number}")
    elif op == "exchange":
        lines = [LineInput(p, rnd.choice([2000, 5000, 8000, 12000]))
                 for p in rnd.sample(["a", "b", "f"], rnd.randint(1, 2))]
        refs.append(f"C{exchange(repo, c, D13, lines).number}")
    elif op == "fund":
        open_ = repo.open_exchanges(c, WS)
        if open_:
            ex = rnd.choice(open_)
            usd = sum(ln.usd_minor for ln in repo.current_lines(c, ex.id))
            mv = move(repo, c, f"m{n}", -(usd * 92 // 100 + rnd.choice([0, 37])))
            refs.append(f"F{create_funding(repo, c, WS, [mv.id], [ex.id], q, NOW).number}")
    elif op == "receipt":  # some land within 1.00 of a funded EUR share (x 0.92)
        amount = rnd.choice([99, 1000, 1800, 4000, 4600, 7300, 7360, 11000, 12000])
        refs.append(f"R{receipt(repo, c, q, person, cur, amount).number}")
    elif op == "reverse" and refs:
        reverse(repo, c, WS, rnd.choice(refs), "x", q, NOW)
    elif op == "forgive":
        forgive(repo, c, WS, rnd.choice(["Familiar A", "Familiar B"]), None, "gift", NOW)
    elif op == "correct":
        open_ = [ex for ex in repo.open_exchanges(c, WS)]
        if open_:
            ex = rnd.choice(open_)
            lines = [LineInput(p, rnd.choice([3000, 8000])) for p in ("a", "b")]
            correct_exchange(repo, c, WS, ex.id, lines, None, "x", NOW, queue=q)


@pytest.mark.parametrize("seed", range(1, 7))
def test_items_explain_the_balance_on_a_random_walk(tmp_path, seed):
    repo, q = make(tmp_path)
    rnd, refs = random.Random(seed), []
    with repo.tx() as c:
        for n in range(60):
            try:
                _random_step(repo, c, q, rnd, refs, n)
            except (ValidationError, AlreadyLinked):
                pass  # refused before any write
            check(repo, c)
