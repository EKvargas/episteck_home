"""Corrections, forgiveness, openings and generic reversal (synthetic data only)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app import domain
from app.receivables.corrections import correct_exchange, forgive, record_opening, reverse
from app.receivables.funding import create_funding, link_choice, try_link
from app.receivables.ledger import (
    Evidence, LineInput, ValidationError, receivables_view, record_exchange,
)
from app.receivables.model import (
    OWNER, Counterparty, CounterpartyKind, EntryKind, Opening, PendingKind, ReceiptKind,
    Verification,
)
from app.receivables.pending import PendingQueue
from app.receivables.receipts import reallocate, record_receipt
from app.store.receivables_repo import ReceivablesRepository
from tests.support import make_account, make_repo, seed_connection, seed_workspace

WS = "ws-1"
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
D13, D14, D15 = (date(2026, 11, d) for d in (13, 14, 15))
PARTNER_IBAN = "XX00 SYNTHETIC PARTNER 0001"
PAYER_IBAN = "XX00 SYNTHETIC PAYER 0004"
E1_LINES = [LineInput("a", 12000), LineInput("b", 8000), LineInput(OWNER, 4000),
            LineInput("f", 6000)]
TABLES = ("exchange", "exchange_line", "ledger_entry", "allocation", "funding_share", "receipt",
          "revocation", "pending_item", "movement_role", "payer_rule", "ref_counter")
CHARGE, PAYMENT, REVERSAL = EntryKind.CHARGE, EntryKind.PAYMENT, EntryKind.REVERSAL


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


def move(repo, c, mid, amount, day=D14, currency="EUR", iban=PARTNER_IBAN):
    m = domain.Movement(mid, WS, "acc-eur", f"tx-{mid}", f"fp-{mid}",
                        domain.MovementStatus.BOOKED, day, day, amount, currency, "X",
                        repo.hash_key(iban), "transfer", None)
    repo.base.insert_movement_in_tx(c, m)
    return m


def fund(repo, c, q, mid, eur, day=D14):
    assert try_link(repo, c, WS, move(repo, c, mid, -eur, day), q, NOW) == "LINKED"


def receipt(repo, c, q, payer, cur, amount, kind=ReceiptKind.CASH, **kw):
    ver = Verification.BANK_POSTED if kind is ReceiptKind.BANK else Verification.OWNER_CONFIRMED
    return record_receipt(repo, c, WS, kind=kind, payer_id=payer, currency=cur,
                          amount_minor=amount, received_on=D15, verification=ver, queue=q,
                          now=NOW, **kw)


def allocs(c, rid):
    rows = c.execute("SELECT a.line_id, a.amount_minor, a.method FROM allocation a WHERE "
                     "a.receipt_id=? AND NOT EXISTS (SELECT 1 FROM revocation r WHERE "
                     "r.table_name='allocation' AND r.target_id=a.id) ORDER BY a.rowid",
                     (rid,)).fetchall()
    return [(r["line_id"], r["amount_minor"], r["method"]) for r in rows]


def counts(c):
    return {t: c.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in TABLES}


def history(repo, c, cp):
    return [(e.kind, e.amount_minor, e.source_ref) for e in repo.entries(c, WS, cp)]


def outstanding(repo, c, cp, cur):
    return [o.outstanding_minor for o in repo.open_lines(c, WS, cp, cur)]


def test_e11_correct_paid_exchange_recomputes_eur_shares_and_allocations(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        fund(repo, c, q, "m1", 27600)
        f = repo.live_funding_for_exchange(c, ex.id)
        rb = receipt(repo, c, q, "b", "EUR", 7360)
        ra = receipt(repo, c, q, "a", "USD", 12000)
        old = repo.current_lines(c, ex.id)
        lines = [LineInput("a", 12000), LineInput("b", 10000), LineInput(OWNER, 4000),
                 LineInput("f", 6000)]
        out = correct_exchange(repo, c, WS, ex.id, lines, 32000, "b was 100", NOW, queue=q)
        assert out.id == ex.id
        new = repo.current_lines(c, ex.id)
        assert [ln.version for ln in new] == [2, 2, 2, 2]
        assert {ln.id for ln in new}.isdisjoint({ln.id for ln in old})
        # same funding, same EUR, new rate 276/320: every share recomputed
        assert repo.live_funding_for_exchange(c, ex.id).id == f.id
        assert repo.funding_shares(c, f.id) == {"a": 10350, "b": 8625, OWNER: 3450, "f": 5175}
        assert c.execute("SELECT COUNT(*) AS n FROM revocation WHERE table_name='funding_share'"
                         ).fetchone()["n"] == 4
        assert history(repo, c, "b") == [(CHARGE, 7360, old[1].id), (PAYMENT, -7360, rb.id),
                                         (REVERSAL, -7360, old[1].id), (CHARGE, 8625, new[1].id)]
        assert repo.entries(c, WS, "b")[-1].effective_on == D14  # the partner payment day
        assert repo.balance(c, WS, "b", "EUR") == 8625 - 7360
        assert allocs(c, rb.id) == [(new[1].id, 7360, "AUTO_FIFO")]
        assert outstanding(repo, c, "b", "EUR") == [1265]
        assert repo.balance(c, WS, "a", "USD") == 0
        assert allocs(c, ra.id) == [(new[0].id, 12000, "AUTO_FIFO")]
        assert repo.balance(c, WS, "f", "USD") == 6000
        assert repo.entries(c, WS, OWNER) == []
        assert receivables_view(repo, c, WS, NOW)["owed_to_partner"]["amount"] == "0.00"


def test_correction_below_collected_is_refused_with_figures(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        receipt(repo, c, q, "a", "USD", 12000)
        before = counts(c)
        lines = [LineInput("a", 10000), LineInput("b", 8000), LineInput(OWNER, 6000),
                 LineInput("f", 6000)]
        with pytest.raises(ValidationError) as e:
            correct_exchange(repo, c, WS, ex.id, lines, None, "x", NOW, queue=q)
        assert e.value.field == "below_collected"
        assert e.value.detail == {"payer": "Familiar A", "currency": "USD", "collected": "120.00",
                                  "new": "100.00"}
        assert counts(c) == before


def test_forgive_defaults_to_outstanding(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        line_a, line_b = repo.current_lines(c, ex.id)[:2]
        receipt(repo, c, q, "a", "USD", 5000)
        before = counts(c)
        with pytest.raises(ValidationError) as e:
            forgive(repo, c, WS, "C1:Familiar A", 7001, "gift", NOW)
        assert (e.value.field, e.value.detail["outstanding"]) == ("amount", "70.00")
        assert counts(c) == before
        entry = forgive(repo, c, WS, " c1 : familiar a", None, "gift", NOW)
        assert (entry.kind, entry.currency, entry.amount_minor, entry.source_ref, entry.note) == (
            EntryKind.FORGIVE, "USD", -7000, line_a.id, "gift")
        assert repo.balance(c, WS, "a", "USD") == 0
        assert outstanding(repo, c, "a", "USD") == []
        fund(repo, c, q, "m1", 27600)
        entry_b = forgive(repo, c, WS, "Familiar B", None, "gift", NOW)  # by counterparty
        assert (entry_b.currency, entry_b.amount_minor, entry_b.source_ref) == (
            "EUR", -7360, line_b.id)
        assert repo.balance(c, WS, "b", "EUR") == 0
        with pytest.raises(ValidationError):
            forgive(repo, c, WS, "Familiar B", None, "gift", NOW)  # nothing owed any more


def test_opening_requires_note(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        before = counts(c)
        for note in ("", "   "):
            with pytest.raises(ValidationError) as e:
                record_opening(repo, c, WS, "f", "USD", 50000, Opening.APPROXIMATE, note, NOW)
            assert e.value.field == "note"
        with pytest.raises(ValidationError) as e:
            record_opening(repo, c, WS, "f", "USD", 50000, Opening.UNKNOWN, "x", NOW)
        assert e.value.field == "basis"
        assert counts(c) == before
        assert repo.get_counterparty(c, WS, "f").opening is Opening.UNKNOWN


def fund_row(repo, c):
    return next(r for r in receivables_view(repo, c, WS, NOW)["held_for_others"]
                if r["kind"] == "FUND")


def test_fund_opening_replaces_unknown(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c)  # the fund is charged 60.00 USD
        assert (fund_row(repo, c)["amount"], fund_row(repo, c)["opening"]) == (None, "UNKNOWN")
        first = record_opening(repo, c, WS, "f", "USD", 50000, Opening.APPROXIMATE,
                               "segun el dueno, a fecha 18/11", NOW)
        assert (first.kind, first.amount_minor, first.basis, first.note) == (
            EntryKind.OPENING, -50000, "APPROXIMATE", "segun el dueno, a fecha 18/11")
        assert repo.get_counterparty(c, WS, "f").opening is Opening.APPROXIMATE
        assert (fund_row(repo, c)["amount"], fund_row(repo, c)["opening"]) == (
            "440.00", "APPROXIMATE")
        record_opening(repo, c, WS, "f", "USD", 52000, Opening.CONFIRMED, "reconstruido", NOW)
        assert [k for k, _, _ in history(repo, c, "f")] == [
            CHARGE, EntryKind.OPENING, REVERSAL, EntryKind.OPENING]
        assert repo.balance(c, WS, "f", "USD") == -52000 + 6000
        assert repo.get_counterparty(c, WS, "f").opening is Opening.CONFIRMED
        record_opening(repo, c, WS, "a", "USD", 3000, Opening.APPROXIMATE, "segun el dueno", NOW)
        assert repo.balance(c, WS, "a", "USD") == 12000 + 3000  # a PERSON owes it
        assert repo.get_counterparty(c, WS, "a").opening is Opening.APPROXIMATE


def test_reverse_bank_receipt_asks_again(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c)
        move(repo, c, "m9", 12000, D15, "USD", iban=PAYER_IBAN)
        r = receipt(repo, c, q, "a", "USD", 12000, kind=ReceiptKind.BANK, movement_id="m9")
        out = reverse(repo, c, WS, "r1", "wrong payer", q, NOW)
        assert (out["ok"], out["status"], out["ref"]) == (True, "reversed", "R1")
        assert repo.balance(c, WS, "a", "USD") == 12000
        assert outstanding(repo, c, "a", "USD") == [12000]
        assert allocs(c, r.id) == []
        assert repo.live_receipt_for_movement(c, "m9") is None
        assert repo.movement_role(c, "m9") is None
        item = repo.pending_by_dedupe(c, WS, "EXPLAIN_INCOMING:m9")
        assert (item.kind, item.requires_answer, item.code) == (
            PendingKind.EXPLAIN_INCOMING, True, out["question"])
        assert item.payload["movement_id"] == "m9"
        text = json.dumps(item.payload)
        assert PAYER_IBAN not in text and repo.hash_key(PAYER_IBAN) not in text
        assert [k for k, _, _ in history(repo, c, "a")] == [CHARGE, PAYMENT, REVERSAL]
        with pytest.raises(ValidationError):
            reverse(repo, c, WS, "R1", "again", q, NOW)


def test_reverse_exchange_with_live_funding_is_refused(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        fund(repo, c, q, "m1", 27600)
        before = counts(c)
        with pytest.raises(ValidationError) as e:
            reverse(repo, c, WS, "C1", "duplicate", q, NOW)
        assert (e.value.field, e.value.detail) == ("funded", {"funding_ref": "F1"})
        assert counts(c) == before
        out = reverse(repo, c, WS, "f1", "wrong payment", q, NOW)
        assert out["ref"] == "F1" and len(out["questions"]) == 1
        assert reverse(repo, c, WS, "C1", "duplicate", q, NOW)["ref"] == "C1"
        assert repo.exchange_by_ref(c, WS, "C1") is None
        assert repo.exchange_by_ref(c, WS, "C1", include_revoked=True).id == ex.id
        assert repo.balances(c, WS) == {("a", "USD"): 0, ("b", "EUR"): 0, ("f", "USD"): 0}
        assert repo.open_exchanges(c, WS) == []


def test_history_keeps_every_version(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        v1 = repo.current_lines(c, ex.id)
        correct_exchange(repo, c, WS, ex.id, [LineInput("a", 10000), LineInput("f", 8000)],
                         None, "first fix", NOW, queue=q)
        v2 = repo.current_lines(c, ex.id)
        correct_exchange(repo, c, WS, ex.id, [LineInput("a", 9000), LineInput("f", 9000)],
                         18000, "second fix", NOW, queue=q)
        v3 = repo.current_lines(c, ex.id)
        assert [ln.version for ln in v3] == [3, 3]
        assert c.execute("SELECT COUNT(*) AS n FROM exchange_line WHERE exchange_id=?",
                         (ex.id,)).fetchone()["n"] == 4 + 2 + 2
        entries = repo.entries(c, WS, "a")
        assert [(e.kind, e.amount_minor, e.source_ref) for e in entries] == [
            (CHARGE, 12000, v1[0].id), (REVERSAL, -12000, v1[0].id), (CHARGE, 10000, v2[0].id),
            (REVERSAL, -10000, v2[0].id), (CHARGE, 9000, v3[0].id)]
        assert entries[1].reverses_id == entries[0].id and entries[1].note == "first fix"
        assert repo.balance(c, WS, "a", "USD") == 9000
        assert outstanding(repo, c, "a", "USD") == [9000]


def test_correction_recomputes_every_exchange_of_a_shared_funding(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13, [LineInput("a", 12000), LineInput("b", 8000)])
        c2 = exchange(repo, c, D13, [LineInput("b", 4000, eur_override_minor=3700),
                                     LineInput("b", 2000)])
        move(repo, c, "m1", -23920)
        f = create_funding(repo, c, WS, ["m1"], [c1.id, c2.id], q, NOW)
        kept, moved = repo.current_lines(c, c2.id)
        assert (repo.line_charged(c, WS, kept.id), repo.line_charged(c, WS, moved.id)) == (
            3700, 1840)
        correct_exchange(repo, c, WS, c1.id, [LineInput("a", 12000), LineInput("b", 6000)],
                         None, "b was 60", NOW, queue=q)
        # 239.20 EUR over 240 USD now: the rate changes for C2 as well
        assert repo.funding_shares(c, f.id) == {"a": 11960, "b": 5980 + 3987 + 1993}
        assert repo.line_charged(c, WS, kept.id) == 3700  # owner figure: untouched
        assert repo.line_charged(c, WS, moved.id) == 1993
        assert [e.source_ref for e in repo.entries(c, WS, "b")
                if e.kind is REVERSAL] == [repo.entries(c, WS, "b")[0].source_ref, moved.id]
        assert repo.balance(c, WS, "b", "EUR") == 5980 + 3700 + 1993


def adjustments(repo, c, cp):
    refs = {e.source_ref for e in repo.entries(c, WS, cp)}
    return [(e.amount_minor, e.source_ref)
            for e in repo.effective_adjustments_for_refs(c, WS, refs)]


def undone(repo, c, entry):
    """The entry is no longer effective and exactly one REVERSAL references it."""
    reversals = [e for e in repo.entries(c, WS, entry.counterparty_id)
                 if e.kind is REVERSAL and e.reverses_id == entry.id]
    return repo.entry_by_ref(c, WS, f"E{entry.number}") is None and len(reversals) == 1


def test_reverse_funding_undoes_forgiveness_with_the_charge(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c)
        fund(repo, c, q, "m1", 27600)
        gift = forgive(repo, c, WS, "C1:Familiar B", 2000, "gift", NOW)
        assert repo.balance(c, WS, "b", "EUR") == 5360
        reverse(repo, c, WS, "F1", "wrong payment", q, NOW)
        assert undone(repo, c, gift)
        assert repo.balance(c, WS, "b", "EUR") == 0  # no fake credit
        assert not [r for r in receivables_view(repo, c, WS, NOW)["held_for_others"]
                    if r["counterparty"] == "Familiar B"]
        assert link_choice(repo, c, WS, "m1", "C1", q, NOW)["status"] == "linked"  # the owner's answer (R57)
        assert repo.balance(c, WS, "b", "EUR") == 7360  # charged in full again
        assert outstanding(repo, c, "b", "EUR") == [7360]
        again = forgive(repo, c, WS, "C1:Familiar B", None, "gift again", NOW)
        assert again.amount_minor == -7360 and repo.balance(c, WS, "b", "EUR") == 0


def test_correction_undoes_forgiveness_on_a_recharged_line_of_the_funding(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13, [LineInput("a", 12000), LineInput("b", 8000)])
        c2 = exchange(repo, c, D13, [LineInput("b", 4000)])
        move(repo, c, "m1", -22080)
        create_funding(repo, c, WS, ["m1"], [c1.id, c2.id], q, NOW)
        gift = forgive(repo, c, WS, "C2:Familiar B", 1000, "gift", NOW)
        assert repo.balance(c, WS, "b", "EUR") == 7360 + 3680 - 1000
        correct_exchange(repo, c, WS, c1.id, [LineInput("a", 12000), LineInput("b", 6000)],
                         None, "b was 60", NOW, queue=q)
        assert undone(repo, c, gift)
        assert repo.balance(c, WS, "b", "EUR") == 6022 + 4014  # C2 re-charged in full
        forgive(repo, c, WS, "C2:Familiar B", 1000, "gift again", NOW)
        assert repo.balance(c, WS, "b", "EUR") == 6022 + 4014 - 1000


def test_reverse_exchange_undoes_its_forgiveness_once(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c)
        gift = forgive(repo, c, WS, "C1:Familiar A", 2000, "gift", NOW)
        reverse(repo, c, WS, "C1", "duplicate", q, NOW)
        assert undone(repo, c, gift)
        assert repo.balance(c, WS, "a", "USD") == 0


def test_correction_moves_a_small_difference_to_the_new_line(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        fund(repo, c, q, "m1", 27600)
        old_b = repo.current_lines(c, ex.id)[1]
        receipt(repo, c, q, "b", "EUR", 7300)  # 0.60 short: closed on the line
        assert adjustments(repo, c, "b") == [(-60, old_b.id)]
        correct_exchange(repo, c, WS, ex.id, E1_LINES, None, "same figures", NOW, queue=q)
        new_b = repo.current_lines(c, ex.id)[1]
        assert adjustments(repo, c, "b") == [(-60, new_b.id)]  # reversed, then closed again
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert outstanding(repo, c, "b", "EUR") == []


def test_reverse_receipt_undoes_the_small_difference_it_closed(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c)
        fund(repo, c, q, "m1", 27600)
        receipt(repo, c, q, "b", "EUR", 7300)
        out = reverse(repo, c, WS, "R1", "never paid", q, NOW)
        assert "question" not in out  # a CASH receipt asks nothing
        assert adjustments(repo, c, "b") == []
        assert repo.balance(c, WS, "b", "EUR") == 7360
        assert outstanding(repo, c, "b", "EUR") == [7360]


def test_correction_validates_before_writing(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        before = counts(c)
        bad = [
            ("nope", [LineInput("a", 100)], None, "exchange"),
            (ex.id, [], None, "lines"),
            (ex.id, [LineInput("a", 0)], None, "usd"),
            (ex.id, [LineInput("zz", 100)], None, "payer"),
            (ex.id, [LineInput(OWNER, 100, eur_override_minor=90)], None, "eur_override"),
            (ex.id, [LineInput("a", 100)], 200, "lines_total"),
        ]
        for eid, lines, total, field in bad:
            with pytest.raises(ValidationError) as e:
                correct_exchange(repo, c, WS, eid, lines, total, "x", NOW, queue=q)
            assert e.value.field == field
        assert counts(c) == before


def test_correction_refused_while_a_line_is_forgiven(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        entry = forgive(repo, c, WS, "C1:Familiar A", 2000, "gift", NOW)
        before = counts(c)
        with pytest.raises(ValidationError) as e:
            correct_exchange(repo, c, WS, ex.id, E1_LINES, None, "x", NOW, queue=q)
        assert (e.value.field, e.value.detail) == ("forgiven", {"entry": f"E{entry.number}"})
        assert counts(c) == before
        reverse(repo, c, WS, f"E{entry.number}", "not a gift", q, NOW)
        correct_exchange(repo, c, WS, ex.id, E1_LINES, None, "x", NOW, queue=q)
        assert repo.balance(c, WS, "a", "USD") == 12000


def test_reverse_entries_and_payer_rules(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        opening = record_opening(repo, c, WS, "f", "USD", 50000, Opening.APPROXIMATE, "x", NOW)
        out = reverse(repo, c, WS, f"e{opening.number}", "wrong figure", q, NOW)
        assert out["ref"] == f"E{opening.number}"
        assert repo.balance(c, WS, "f", "USD") == 0
        assert repo.get_counterparty(c, WS, "f").opening is Opening.UNKNOWN
        ex = exchange(repo, c)
        [charge] = [e for e in repo.entries(c, WS, "a") if e.kind is CHARGE]
        before = counts(c)
        for ref in (f"E{charge.number}", f"E{opening.number}", "E999", "C9", "F1", "R1",
                    "Familiar A rule", "bogus"):
            with pytest.raises(ValidationError):
                reverse(repo, c, WS, ref, "x", q, NOW)
        assert counts(c) == before
        repo.insert_payer_rule(c, WS, repo.hash_key("KEY-1"), "a")
        assert reverse(repo, c, WS, "familiar a rule", "wrong person", q, NOW)["rules"] == 1
        assert repo.rule_for(c, WS, repo.hash_key("KEY-1")) is None
        assert ex.id == repo.exchange_by_ref(c, WS, "C1").id


def test_forgive_never_makes_a_balance_negative(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13, [LineInput("a", 10000)])
        c2 = exchange(repo, c, D14, [LineInput("a", 5000)])
        r = receipt(repo, c, q, "a", "USD", 10000)  # exact: C1
        reallocate(repo, c, WS, r.id, [(repo.current_lines(c, c2.id)[0].id, 5000)], NOW)
        assert repo.balance(c, WS, "a", "USD") == 5000  # C1 shows 100.00, R1 keeps 50.00
        assert outstanding(repo, c, "a", "USD") == [10000]
        before = counts(c)
        with pytest.raises(ValidationError) as e:
            forgive(repo, c, WS, "C1:Familiar A", 6000, "gift", NOW)
        assert (e.value.field, e.value.detail["outstanding"]) == ("amount", "50.00")
        assert counts(c) == before
        entry = forgive(repo, c, WS, "C1:Familiar A", None, "gift", NOW)
        assert entry.amount_minor == -5000 and repo.balance(c, WS, "a", "USD") == 0
        after = counts(c)
        for target in ("C1:Familiar A", "Familiar A"):  # nothing is owed: no credit is made
            with pytest.raises(ValidationError) as e:
                forgive(repo, c, WS, target, None, "gift", NOW)
            assert e.value.field == "outstanding"
        assert counts(c) == after


def test_forgive_on_an_exchange_uses_the_currency_still_open(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13, [LineInput("b", 8000), LineInput("b", 2000, debt_currency="USD")])
        fund(repo, c, q, "m1", 9200)
        with pytest.raises(ValidationError) as e:
            forgive(repo, c, WS, "C1:Familiar B", None, "gift", NOW)  # both still open
        assert e.value.field == "currency"
        receipt(repo, c, q, "b", "USD", 2000)
        entry = forgive(repo, c, WS, "C1:Familiar B", None, "gift", NOW)
        assert (entry.currency, entry.amount_minor) == ("EUR", -7360)
        with pytest.raises(ValidationError) as e:
            forgive(repo, c, WS, "C1:Familiar B", None, "gift", NOW)
        assert e.value.field == "outstanding"


def test_reversing_a_persons_only_opening_clears_the_flag(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        only = record_opening(repo, c, WS, "a", "USD", 12000, Opening.APPROXIMATE, "segun", NOW)
        reverse(repo, c, WS, f"E{only.number}", "typo", q, NOW)
        assert repo.get_counterparty(c, WS, "a").opening is None
        record_opening(repo, c, WS, "a", "USD", 100, Opening.CONFIRMED, "segun", NOW)
        eur = record_opening(repo, c, WS, "a", "EUR", 200, Opening.APPROXIMATE, "segun", NOW)
        reverse(repo, c, WS, f"E{eur.number}", "typo", q, NOW)
        assert repo.get_counterparty(c, WS, "a").opening is Opening.CONFIRMED


def test_correct_exchange_requires_the_queue(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c)
        before = counts(c)
        with pytest.raises(TypeError):
            correct_exchange(repo, c, WS, ex.id, E1_LINES, None, "x", NOW)
        assert counts(c) == before
