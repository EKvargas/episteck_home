"""Matcher after each sync: links, receipts, questions and notices (synthetic data only)."""
from __future__ import annotations

import inspect
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app import domain
from app.receivables.corrections import record_opening
from app.receivables.funding import link_choice
from app.receivables.ledger import Evidence, LineInput, record_exchange
from app.receivables.matcher import Matcher, reopen_explain, resolve_explain_incoming
from app.receivables.model import (
    OWNER, Counterparty, CounterpartyKind, EntryKind, MovementRoleKind, Opening, PendingKind,
    ReceiptKind, Verification,
)
from app.receivables.pending import PendingQueue
from app.receivables.receipts import record_receipt
from app.store.receivables_repo import ReceivablesRepository
from app.store.repo import FinanceRepository
from tests.support import (
    PEPPER, column_names, count_rows, make_account, make_repo, raw_execute, seed_connection,
    seed_workspace,
)

WS = "ws-1"
T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
D13, D14, D15, D16, D17 = (date(2026, 11, d) for d in (13, 14, 15, 16, 17))
ECB = Decimal("1.0870")  # USD per EUR: 0.9200 EUR per USD is within 0.01 % of it
PARTNER_IBAN = "XX00 SYNTHETIC PARTNER 0001"
NEW_IBAN = "XX00 SYNTHETIC PARTNER 0002"
OWN_IBAN = "XX00 SYNTHETIC OWN 0003"
EMPLOYER_IBAN = "XX00 SYNTHETIC EMPLOYER 0004"
PAYER_IBAN = "XX00 SYNTHETIC PAYER 0005"
PARTNER_NAME = "Socio de cambio sintetico"  # 25 characters: labels keep 20
E1 = [LineInput("a", 12000), LineInput("b", 8000), LineInput(OWNER, 10000)]  # 300 USD
ZELLE_1 = "ZELLE FROM FAMILIAR A CONF# AB12CD 1111"
ZELLE_2 = "ZELLE FROM FAMILIAR A CONF# QWERTY 2222"


def counts(**kw):
    return {"linked": 0, "waiting": 0, "asked": 0, "receipts": 0, "ignored": 0, **kw}


class Env:
    def __init__(self, tmp_path, rules=False):
        base = make_repo(tmp_path)
        seed_workspace(base)
        seed_connection(base)
        for aid, cur in (("acc-eur", "EUR"), ("acc-usd", "USD"), ("acc-other", "EUR")):
            base.add_account(make_account(aid=aid, currency=cur))
        base.store_fx_rates(D13, {"USD": ECB})
        self.repo = repo = ReceivablesRepository(base)
        self.now = T0
        self.q = PendingQueue(repo, lambda: self.now)
        self.matcher = Matcher(repo, self.q, lambda: self.now, rules)
        with repo.tx() as c:
            self.add(c, "p", "Socio", CounterpartyKind.EXCHANGE_PARTNER)
            self.add(c, "a", "Familiar A", CounterpartyKind.PERSON, pay_currency="USD")
            self.add(c, "b", "Familiar B", CounterpartyKind.PERSON, pay_currency="EUR")
            self.add(c, "c", "Familiar C", CounterpartyKind.PERSON, pay_currency="USD")
            repo.add_partner_identifier(c, WS, repo.hash_key(PARTNER_IBAN), "p")
            repo.add_own_identifier(c, WS, repo.hash_key(OWN_IBAN))
            repo.set_watch(c, WS, "acc-eur", True)
            repo.set_watch(c, WS, "acc-usd", True)

    def add(self, c, cid, label, kind, **kw):
        self.repo.insert_counterparty(c, Counterparty(cid, WS, kind, label, "ACTIVE", **kw), [label])

    def run(self, started=None):
        return self.matcher.run(WS, started or self.now)

    def exchange(self, c, day=D13, lines=E1, at=None):
        return record_exchange(self.repo, c, WS, partner_id="p",
                               total_usd_minor=sum(ln.usd_minor for ln in lines), lines=lines,
                               evidence=Evidence(None, None, day), now=at or self.now)

    def move(self, c, mid, amount, day=D14, acc="acc-eur", iban=PARTNER_IBAN, text="transfer",
             status=domain.MovementStatus.BOOKED, supersedes=None, name=PARTNER_NAME):
        cur = "USD" if acc == "acc-usd" else "EUR"
        m = domain.Movement(mid, WS, acc, f"tx-{mid}", f"fp-{mid}", status, day, day, amount, cur,
                            name, self.repo.hash_key(iban) if iban else None, text, supersedes)
        self.repo.base.insert_movement_in_tx(c, m)
        return m

    def questions(self, c):
        return [p for p in self.repo.pending_open(c, WS) if p.requires_answer]

    def item(self, c, key):
        return self.repo.pending_by_dedupe(c, WS, key, include_resolved=True)

    def resolve_all(self):
        with self.repo.tx() as c:
            for p in self.questions(c):
                self.q.resolve(c, WS, p.code, "LATER", human=True)


def make(tmp_path, rules=False):
    env = Env(tmp_path, rules)
    assert env.run() == counts()  # go-live: no movement from before it is processed
    return env


def test_first_run_initialises_cursor_and_asks_nothing_about_history(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        env.move(c, "old1", -27600, D14)  # a partner payment from before go-live
        env.move(c, "old2", 12000, D14, acc="acc-usd", iban=None, text=ZELLE_1)
    assert env.run() == counts()
    with env.repo.read() as c:
        assert env.questions(c) == []
        assert env.repo.get_cursor(c, WS) == 2
        assert env.repo.live_funding_for_movement(c, "old1") is None
    with env.repo.tx() as c:
        env.move(c, "m1", -27600, D15)
    assert env.run() == counts(linked=1)
    assert env.run() == counts()  # the historic payment is never asked about
    with env.repo.read() as c:
        assert env.repo.live_funding_for_movement(c, "m1").movement_ids == ("m1",)
        assert env.questions(c) == []


def test_e6_unknown_credit_asks_then_rule_makes_next_automatic(tmp_path):
    env = make(tmp_path, rules=True)
    with env.repo.tx() as c:
        env.exchange(c)
        env.move(c, "in1", 12000, acc="acc-usd", iban=None, text=ZELLE_1, name="")
    assert env.run() == counts(asked=1)
    with env.repo.tx() as c:
        item = env.item(c, "EXPLAIN_INCOMING:in1")
        assert (item.kind, item.options) == (
            PendingKind.EXPLAIN_INCOMING, ("CP:a", "OTHER", "NOT_EXCHANGE"))
        assert item.payload == {
            "movement_id": "in1", "booking_date": "2026-11-14", "currency": "USD",
            "amount": "120.00", "sender": "FAMILIAR A", "exact": "CP:a",
            "labels": {"CP:a": "Familiar A"}}
        assert resolve_explain_incoming(env.repo, c, WS, "in1", "CP:a", env.q, env.now,
                                        description_rules=True) == {
            "ok": True, "status": "recorded", "receipt_ref": "R1", "rule": True}
        env.q.resolve(c, WS, item.code, "CP:a", human=True)
        assert env.repo.balance(c, WS, "a", "USD") == 0
        env.move(c, "in2", 5000, D15, acc="acc-usd", iban=None, text=ZELLE_2, name="")
    assert env.run() == counts(receipts=1)
    with env.repo.read() as c:
        rec = env.repo.live_receipt_for_movement(c, "in2")
        assert (rec.payer_id, rec.kind, rec.verification) == (
            "a", ReceiptKind.BANK, Verification.BANK_POSTED)
        assert env.repo.balance(c, WS, "a", "USD") == -5000  # ahead: a credit
        assert env.questions(c) == []


def test_e6_salary_ignored_after_one_answer(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.move(c, "s1", 250000, iban=EMPLOYER_IBAN, text="NOMINA 10/2026", name="Empresa")
    assert env.run() == counts(asked=1)
    with env.repo.tx() as c:
        item = env.item(c, "EXPLAIN_INCOMING:s1")
        assert item.options == ("OTHER", "NOT_EXCHANGE")
        text = json.dumps(item.payload)
        assert EMPLOYER_IBAN not in text and env.repo.hash_key(EMPLOYER_IBAN) not in text
        assert resolve_explain_incoming(env.repo, c, WS, "s1", "NOT_EXCHANGE", env.q,
                                        env.now) == {
            "ok": True, "status": "not_exchange", "rule": True}
        env.q.resolve(c, WS, item.code, "NOT_EXCHANGE", human=True)
        assert env.repo.movement_role(c, "s1") is MovementRoleKind.NOT_EXCHANGE
        env.move(c, "s2", 250000, D16, iban=EMPLOYER_IBAN, text="NOMINA 11/2026", name="Empresa")
    assert env.run() == counts(ignored=1)
    with env.repo.read() as c:
        assert env.repo.movement_role(c, "s2") is MovementRoleKind.NOT_EXCHANGE
        assert env.questions(c) == []


def test_own_iban_credit_is_never_asked(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.move(c, "o1", 50000, iban=OWN_IBAN, name="Yo")
        env.move(c, "x1", 7000, acc="acc-other", iban=PAYER_IBAN)  # an unwatched account
    assert env.run() == counts(ignored=1)
    with env.repo.read() as c:
        assert env.questions(c) == []
        assert env.repo.movement_role(c, "o1") is None
        assert env.repo.movement_role(c, "x1") is None
    assert count_rows(env.repo.base, "payer_rule") == 0


def test_description_rules_off_asks_every_time_with_exact_match_first(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c, lines=[LineInput("a", 12000), LineInput("a", 3000), LineInput("c", 7000),
                               LineInput(OWNER, 8000)])
        env.move(c, "in1", 7000, acc="acc-usd", iban=None, text=ZELLE_1, name="")
        env.move(c, "in2", 15000, acc="acc-usd", iban=None, text=ZELLE_1, name="")
    assert env.run() == counts(asked=2)
    with env.repo.tx() as c:
        first, second = env.item(c, "EXPLAIN_INCOMING:in1"), env.item(c, "EXPLAIN_INCOMING:in2")
        assert first.options == ("CP:c", "CP:a", "OTHER", "NOT_EXCHANGE")
        assert first.payload["exact"] == "CP:c"
        assert second.options == ("CP:a", "CP:c", "OTHER", "NOT_EXCHANGE")
        assert second.payload["exact"] == "CP:a"  # 120 + 30: the whole outstanding
        assert resolve_explain_incoming(env.repo, c, WS, "in2", "CP:a", env.q, env.now) == {
            "ok": True, "status": "recorded", "receipt_ref": "R1", "rule": False}
        env.q.resolve(c, WS, second.code, "CP:a", human=True)
        env.move(c, "in3", 2000, D15, acc="acc-usd", iban=None, text=ZELLE_2, name="")
    assert env.run() == counts(asked=1)
    assert count_rows(env.repo.base, "payer_rule") == 0


def test_booked_successor_of_linked_pending_is_ignored(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        env.move(c, "m1", -27600, D14, status=domain.MovementStatus.PENDING)
    assert env.run() == counts(linked=1)
    with env.repo.tx() as c:
        env.move(c, "m2", -27600, D15, supersedes="m1")
    assert env.run() == counts()
    with env.repo.read() as c:
        assert env.repo.live_funding_for_movement(c, "m2").number == 1
        assert env.questions(c) == []
    assert count_rows(env.repo.base, "funding") == 1


def test_booked_successor_with_another_amount_relinks_rerecords_or_asks(tmp_path):
    env = make(tmp_path)
    pending = domain.MovementStatus.PENDING
    with env.repo.tx() as c:
        env.exchange(c)
        env.move(c, "p1", -27600, D14, status=pending)
        env.repo.insert_payer_rule(c, WS, env.repo.hash_key(PAYER_IBAN), "a")
        env.move(c, "r1", 12000, D14, acc="acc-usd", iban=PAYER_IBAN, status=pending)
    assert env.run() == counts(linked=1, receipts=1)
    with env.repo.tx() as c:
        env.move(c, "p2", -27800, D15, supersedes="p1")  # 0.9267: still within LINK_BAND
        env.move(c, "r2", 11900, D15, acc="acc-usd", iban=PAYER_IBAN, supersedes="r1")
    assert env.run() == counts()
    with env.repo.read() as c:
        f = env.repo.live_funding_for_movement(c, "p2")
        assert (f.number, f.eur_minor, f.movement_ids) == (2, 27800, ("p1",))
        assert env.item(c, "INFO:booked_amount_changed:F1").payload == {
            "funding_ref": "F1", "new_funding_ref": "F2", "eur_before": "276.00",
            "eur_after": "278.00", "text_key": "booked_amount_changed:F1"}
        rec = env.repo.live_receipt_for_movement(c, "r2")
        assert (rec.number, rec.amount_minor, rec.payer_id) == (2, 11900, "a")
        assert env.item(c, "INFO:booked_amount_changed:R1").payload == {
            "receipt_ref": "R1", "new_receipt_ref": "R2", "currency": "USD",
            "amount_before": "120.00", "amount_after": "119.00",
            "text_key": "booked_amount_changed:R1"}
        assert env.repo.balance(c, WS, "a", "USD") == 100
        assert env.questions(c) == []
    with env.repo.tx() as c:
        env.exchange(c, D15, [LineInput("a", 10000)])
        env.move(c, "p3", -9200, D16, status=pending)
    assert env.run() == counts(linked=1)
    with env.repo.tx() as c:
        env.move(c, "p4", -18400, D17, supersedes="p3")  # 1.84 EUR per USD: outside the band
    assert env.run() == counts(asked=1)
    with env.repo.read() as c:
        assert env.repo.live_funding_for_movement(c, "p4") is None
        assert [q.dedupe_key for q in env.questions(c)] == ["LINK_FUNDING:p3"]
        assert env.item(c, "INFO:booked_amount_changed:F3").payload["new_funding_ref"] is None


def test_previous_unpaid_only_after_a_sync_following_registration(tmp_path):
    env = make(tmp_path)
    t1, t2, t4 = (T0 + timedelta(hours=h) for h in (1, 2, 4))
    with env.repo.tx() as c:
        c1 = env.exchange(c, at=t1)
        env.move(c, "old", -1000, date(2026, 10, 15), iban=NEW_IBAN)  # older than 30 days
        env.move(c, "x1", -5000, D14, iban=NEW_IBAN)
        env.move(c, "x2", -27600, D15, iban=NEW_IBAN)
        env.move(c, "in", 9000, D15, acc="acc-other", iban=PAYER_IBAN)  # incoming: not listed
        c2 = env.exchange(c, D15, [LineInput("a", 5000)], at=t2)
    env.now = T0 + timedelta(hours=3)
    assert env.run(started=t2 - timedelta(minutes=5)) == counts()  # began before C2
    assert env.run(started=t2 + timedelta(minutes=5)) == counts(asked=1)
    with env.repo.tx() as c:
        item = env.item(c, f"PREVIOUS_UNPAID:{c1.id}")
        assert (item.kind, item.options) == (
            PendingKind.PREVIOUS_UNPAID, ("M:x2", "M:x1", "NOT_YET"))
        assert item.payload == {
            "exchange_ref": "C1", "delivered_on": "2026-11-13", "usd": "300.00",
            "after_ref": "C2", "labels": {"M:x2": "15/11 · 276.00 · Socio de cambio sint",
                                          "M:x1": "14/11 · 50.00 · Socio de cambio sint"}}
    assert env.run(started=t2 + timedelta(minutes=5)) == counts()  # still open: no duplicate
    with env.repo.tx() as c:
        env.q.resolve(c, WS, item.code, "NOT_YET", human=True)
    assert env.run(started=t2 + timedelta(minutes=5)) == counts()  # answered for C2 already
    with env.repo.tx() as c:
        env.exchange(c, D16, [LineInput("a", 4000)], at=t4)
    env.now = T0 + timedelta(hours=5)
    assert env.run(started=t4 + timedelta(minutes=5)) == counts(asked=2)
    with env.repo.read() as c:
        assert env.item(c, f"PREVIOUS_UNPAID:{c1.id}").payload["after_ref"] == "C3"
        assert env.item(c, f"PREVIOUS_UNPAID:{c2.id}").resolved_at is None


def test_previous_unpaid_pick_learns_partner_iban(tmp_path):
    env = make(tmp_path)
    t1, t2 = T0 + timedelta(hours=1), T0 + timedelta(hours=2)
    with env.repo.tx() as c:
        c1 = env.exchange(c, at=t1)
        env.move(c, "x1", -27600, D14, iban=NEW_IBAN)
        c2 = env.exchange(c, D15, [LineInput("a", 10000)], at=t2)
    env.now = t2 + timedelta(hours=1)
    assert env.run(started=t2 + timedelta(minutes=30)) == counts(asked=1)
    with env.repo.tx() as c:
        item = env.item(c, f"PREVIOUS_UNPAID:{c1.id}")
        assert "M:x1" in item.options
        assert link_choice(env.repo, c, WS, None, "M:x1", env.q, env.now, exchange_ref="C1") == {
            "ok": True, "status": "linked", "funding_ref": "F1"}
        env.q.resolve(c, WS, item.code, "M:x1", human=True)
        env.move(c, "x2", -9200, D16, iban=NEW_IBAN)
    assert env.run(started=env.now) == counts(linked=1)
    with env.repo.read() as c:
        assert env.repo.live_funding_for_movement(c, "x2").exchange_ids == (c2.id,)
        assert env.questions(c) == []


def test_waiting_payment_becomes_question_on_next_run(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        env.move(c, "m1", -15000, D14)  # 0.50 EUR per USD: no exchange is compatible
    assert env.run() == counts(waiting=1)
    with env.repo.read() as c:
        assert env.questions(c) == []
    assert env.run() == counts(asked=1)
    with env.repo.read() as c:
        [item] = env.questions(c)
        assert (item.dedupe_key, item.options) == (
            "LINK_FUNDING:m1", ("C1", "REGISTER", "NOT_EXCHANGE"))
    assert env.run() == counts()
    with env.repo.tx() as c:
        env.move(c, "m2", -12600, D15)  # together: 276.00 for 300 USD
    assert env.run() == counts(linked=1)
    with env.repo.read() as c:
        assert env.repo.live_funding_for_movement(c, "m1").movement_ids == ("m1", "m2")
        closed = env.repo.pending_by_code(c, WS, item.code)
        assert closed.resolved_at is not None and closed.resolution == "auto:settled"
        assert env.questions(c) == []
        assert env.repo.interventions_in_month(c, WS, 2026, 11) == 0


def test_fund_low_notice_once_per_crossing(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.add(c, "f", "Fondo F", CounterpartyKind.FUND, opening=Opening.UNKNOWN)
        env.exchange(c, lines=[LineInput("a", 12000), LineInput("f", 6000),
                               LineInput(OWNER, 12000)])

    def lows():
        with env.repo.tx() as c:
            env.q.for_delivery(c, WS)  # delivery resolves notices
            return [p.dedupe_key for p in env.repo.pending_by_prefix(c, WS, "INFO:fund_low:")]

    env.run()
    assert lows() == []  # an unknown opening never warns
    with env.repo.tx() as c:
        opening = record_opening(env.repo, c, WS, "f", "USD", 50000, Opening.APPROXIMATE,
                                 "segun el dueno, a fecha 20/11", env.now)
    env.run()
    assert lows() == [f"INFO:fund_low:f:E{opening.number}"]
    with env.repo.read() as c:
        assert env.item(c, f"INFO:fund_low:f:E{opening.number}").payload == {
            "counterparty": "Fondo F", "currency": "USD", "held": "440.00",
            "alert": "500.00", "entry_ref": f"E{opening.number}",
            "text_key": f"fund_low:f:E{opening.number}"}
    env.run()
    assert len(lows()) == 1
    with env.repo.tx() as c:
        record_receipt(env.repo, c, WS, kind=ReceiptKind.CASH, payer_id="f", currency="USD",
                       amount_minor=20000, received_on=D15,
                       verification=Verification.OWNER_CONFIRMED, queue=env.q, now=env.now)
    env.run()
    assert len(lows()) == 1  # 640 held: above the alert again
    with env.repo.tx() as c:
        env.exchange(c, D15, [LineInput("f", 30000)])
        charge = [e for e in env.repo.entries(c, WS, "f") if e.kind is EntryKind.CHARGE][-1]
    env.run()
    env.run()
    assert lows() == [f"INFO:fund_low:f:E{opening.number}", f"INFO:fund_low:f:E{charge.number}"]


def test_review_opening_weekly_for_first_four_weeks(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.add(c, "f", "Fondo F", CounterpartyKind.FUND, opening=Opening.UNKNOWN)
        opening = record_opening(env.repo, c, WS, "a", "USD", 3000, Opening.APPROXIMATE,
                                 "segun el dueno, a fecha 20/11", env.now)
    assert env.run() == counts(asked=2)
    with env.repo.read() as c:
        a_item = env.item(c, "REVIEW_OPENING:a:2026-W47")
        assert (a_item.kind, a_item.options) == (PendingKind.REVIEW_OPENING, ("CONFIRM", "LATER"))
        assert a_item.payload == {
            "counterparty": "Familiar A", "kind": "PERSON", "opening": "APPROXIMATE",
            "openings": [{"entry_ref": f"E{opening.number}", "currency": "USD",
                          "amount": "30.00"}]}
        assert env.item(c, "REVIEW_OPENING:f:2026-W47").payload["opening"] == "UNKNOWN"
    assert env.run() == counts()
    env.resolve_all()
    assert env.run() == counts()  # once per ISO week, answered or not
    for days, asked in ((7, 2), (14, 2), (21, 2), (28, 0), (35, 0)):
        env.now = T0 + timedelta(days=days)
        assert env.run() == counts(asked=asked), days
        env.resolve_all()


def test_reopen_explain_undoes_the_answer_and_asks_again(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        env.move(c, "s1", 250000, iban=EMPLOYER_IBAN, name="Empresa")
        env.move(c, "in1", 12000, acc="acc-usd", iban=PAYER_IBAN, name="Familiar A")
    assert env.run() == counts(asked=2)
    with env.repo.tx() as c:
        salary, credit = env.item(c, "EXPLAIN_INCOMING:s1"), env.item(c, "EXPLAIN_INCOMING:in1")
        assert reopen_explain(env.repo, c, WS, salary.code, env.q, env.now) == {
            "ok": False, "error": "not_resolved"}
        resolve_explain_incoming(env.repo, c, WS, "s1", "NOT_EXCHANGE", env.q, env.now)
        resolve_explain_incoming(env.repo, c, WS, "in1", "CP:a", env.q, env.now)
        for item in (salary, credit):
            env.q.resolve(c, WS, item.code, "x", human=True)
        out = reopen_explain(env.repo, c, WS, salary.code, env.q, env.now)
        assert (out["ok"], out["status"]) == (True, "reopened")
        assert env.repo.movement_role(c, "s1") is None
        assert env.repo.rule_for(c, WS, env.repo.hash_key(EMPLOYER_IBAN)) is None
        assert env.item(c, "EXPLAIN_INCOMING:s1").code == out["question"] != salary.code
        out = reopen_explain(env.repo, c, WS, credit.code, env.q, env.now)
        assert (out["ok"], out["status"]) == (True, "reopened")
        assert env.repo.live_receipt_for_movement(c, "in1") is None
        assert env.repo.rule_for(c, WS, env.repo.hash_key(PAYER_IBAN)) is None
        assert env.repo.balance(c, WS, "a", "USD") == 12000
        assert env.item(c, "EXPLAIN_INCOMING:in1").options[0] == "CP:a"
        env.move(c, "s2", 250000, D16, iban=EMPLOYER_IBAN, name="Empresa")
    assert env.run() == counts(asked=1)


def test_resolve_explain_incoming_refuses_bad_choices_without_writes(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.move(c, "in1", 12000, acc="acc-usd", iban=PAYER_IBAN)
        env.move(c, "out1", -500, iban=PAYER_IBAN)
    env.run()
    tables = ("receipt", "payer_rule", "movement_role", "ledger_entry")
    before = {t: count_rows(env.repo.base, t) for t in tables}
    with env.repo.tx() as c:
        def resolve(mid, choice):
            return resolve_explain_incoming(env.repo, c, WS, mid, choice, env.q, env.now)
        assert resolve("in1", "CP:p") == {"ok": False, "error": "unknown_counterparty"}
        assert resolve("in1", "CP:nope") == {"ok": False, "error": "unknown_counterparty"}
        assert resolve("in1", "maybe") == {"ok": False, "error": "unknown_choice"}
        assert resolve("nope", "NOT_EXCHANGE") == {"ok": False, "error": "unknown_movement"}
        assert resolve("out1", "NOT_EXCHANGE") == {"ok": False, "error": "unknown_movement"}
        assert resolve("in1", "OTHER") == {"ok": True, "status": "needs_counterparty"}
    assert {t: count_rows(env.repo.base, t) for t in tables} == before
    with env.repo.tx() as c:
        assert resolve_explain_incoming(env.repo, c, WS, "in1", "CP:a", env.q,
                                        env.now)["status"] == "recorded"
        assert resolve_explain_incoming(env.repo, c, WS, "in1", "NOT_EXCHANGE", env.q,
                                        env.now) == {"ok": False, "error": "already_classified"}


def test_matcher_logs_counts_only(tmp_path, caplog):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        env.move(c, "m1", -27600, D14)
        env.move(c, "in1", 12000, acc="acc-usd", iban=None, text=ZELLE_1, name="Familiar A")
    with caplog.at_level(logging.INFO, logger="finance.matcher"):
        assert env.run() == counts(linked=1, asked=1)
    text = caplog.text
    assert "linked=1" in text and "asked=1" in text
    for secret in ("Familiar", "Socio", "276", "120", "ZELLE", PARTNER_IBAN,
                   env.repo.hash_key(PARTNER_IBAN)):
        assert secret not in text


# --- fix round 1 (R34-R37) ----------------------------------------------------------------
def test_register_answer_then_registration_links_on_next_run(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.move(c, "p1", -27600, D14)  # paid before its exchange is registered
        env.move(c, "p2", -9200, D14)  # another one, whose question the owner leaves open
    assert env.run() == counts(waiting=2)
    assert env.run() == counts(asked=2)
    with env.repo.tx() as c:
        q1, q2 = env.item(c, "LINK_FUNDING:p1"), env.item(c, "LINK_FUNDING:p2")
        assert link_choice(env.repo, c, WS, "p1", "REGISTER", env.q, env.now)["status"] == (
            "needs_exchange")
        env.q.resolve(c, WS, q1.code, "REGISTER", human=True)
        c1 = env.exchange(c)  # 300 USD: fits p1 only
        c2 = env.exchange(c, lines=[LineInput("a", 10000)])  # 100 USD: fits p2 only
    env.now = T0 + timedelta(hours=12)
    assert env.run(started=env.now) == counts(linked=2)
    with env.repo.read() as c:
        assert env.repo.live_funding_for_movement(c, "p1").exchange_ids == (c1.id,)
        assert env.repo.live_funding_for_movement(c, "p2").exchange_ids == (c2.id,)
        assert env.questions(c) == []
        assert env.repo.pending_by_code(c, WS, q1.code).resolution == "REGISTER"
        assert env.repo.pending_by_code(c, WS, q2.code).resolution == "auto:settled"
    assert env.run(started=env.now) == counts()


def test_answered_link_question_is_retried_link_only(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.move(c, "p1", -27600, D14)
    env.run()
    assert env.run() == counts(asked=1)
    with env.repo.tx() as c:
        q1 = env.item(c, "LINK_FUNDING:p1")
        env.q.resolve(c, WS, q1.code, "REGISTER", human=True)
        c1 = env.exchange(c)
        env.exchange(c)  # two compatible exchanges: a retry cannot choose
    env.now = T0 + timedelta(hours=12)
    assert env.run(started=env.now) == counts(asked=1)  # PREVIOUS_UNPAID for C1, no re-ask
    with env.repo.read() as c:
        [item] = env.questions(c)
        assert item.dedupe_key == f"PREVIOUS_UNPAID:{c1.id}"
        assert item.options[0] == "M:p1"
        assert env.repo.live_funding_for_movement(c, "p1") is None
    assert env.run(started=env.now) == counts()


def test_out_of_order_split_payment_links_both_halves(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)  # 300 USD delivered D13
        env.move(c, "late", -12600, D15)  # the later-dated half arrives first
    assert env.run() == counts(waiting=1)
    with env.repo.tx() as c:
        env.move(c, "early", -15000, D14)  # the earlier-dated half arrives next
    assert env.run() == counts(linked=1, waiting=1)
    with env.repo.read() as c:
        f = env.repo.live_funding_for_movement(c, "late")
        assert (f.movement_ids, f.eur_minor) == (("early", "late"), 27600)
        assert env.questions(c) == []
    assert env.run() == counts()


def test_previous_unpaid_ranks_partner_like_payments_first(tmp_path):
    env = make(tmp_path)
    t1, t2 = T0 + timedelta(hours=1), T0 + timedelta(hours=2)
    with env.repo.tx() as c:
        c1 = env.exchange(c, at=t1)
        env.move(c, "x1", -27600, D14, iban=NEW_IBAN)  # the partner payment, to a new IBAN
        env.move(c, "y1", -4000, D14, iban=PAYER_IBAN, name="Alquiler")  # a transfer
        for i in range(9):  # later card payments
            env.move(c, f"card{i}", -(1000 + i), D15 + timedelta(days=i % 3), iban=None,
                     name="Supermercado")
        env.exchange(c, D15, [LineInput("a", 10000)], at=t2)
    env.now = t2 + timedelta(hours=1)
    assert env.run(started=t2 + timedelta(minutes=30)) == counts(asked=1)
    with env.repo.read() as c:
        item = env.item(c, f"PREVIOUS_UNPAID:{c1.id}")
        assert item.options == ("M:x1", "M:y1", "M:card8", "M:card5", "M:card2", "M:card7",
                                "M:card4", "M:card1", "NOT_YET")
        assert list(item.payload["labels"]) == list(item.options[:-1])


def test_previous_unpaid_skips_a_candidate_of_an_open_link_question(tmp_path):
    env = make(tmp_path)
    t1, t2 = T0 + timedelta(hours=1), T0 + timedelta(hours=2)
    with env.repo.tx() as c:
        env.exchange(c, D13, E1, at=t1)
        env.move(c, "pN", -27600, D14)
        env.exchange(c, D14, E1, at=t2)  # N+1 delivered the day N was paid
    env.now = t2 + timedelta(hours=1)
    assert env.run(started=t2 + timedelta(minutes=5)) == counts(asked=1)
    with env.repo.read() as c:
        assert [q.dedupe_key for q in env.questions(c)] == ["LINK_FUNDING:pN"]


def test_reopen_ignore_rule_also_reasks_payments_it_hid(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        env.repo.insert_payer_rule(c, WS, env.repo.hash_key(EMPLOYER_IBAN), None)
        env.move(c, "a1", 6000, acc="acc-usd", iban=PAYER_IBAN, name="Familiar A")
    assert env.run() == counts(asked=1)
    with env.repo.tx() as c:
        item = env.item(c, "EXPLAIN_INCOMING:a1")
        resolve_explain_incoming(env.repo, c, WS, "a1", "NOT_EXCHANGE", env.q, env.now)  # mistake
        env.q.resolve(c, WS, item.code, "NOT_EXCHANGE", human=True)
        env.move(c, "a2", 6000, D15, acc="acc-usd", iban=PAYER_IBAN, name="Familiar A")
        env.move(c, "s1", 250000, D15, iban=EMPLOYER_IBAN, name="Empresa")
    assert env.run() == counts(ignored=2)  # both hidden by their IGNORE rules
    with env.repo.tx() as c:
        out = reopen_explain(env.repo, c, WS, item.code, env.q, env.now)
        a2 = env.item(c, "EXPLAIN_INCOMING:a2")
        assert out == {"ok": True, "status": "reopened",
                       "question": env.item(c, "EXPLAIN_INCOMING:a1").code,
                       "also_asked": [a2.code]}
        assert a2.resolved_at is None and a2.options[0] == "CP:a"
        assert env.repo.movement_role(c, "a2") is None
        assert env.repo.movement_role(c, "s1") is MovementRoleKind.NOT_EXCHANGE  # other sender
        assert resolve_explain_incoming(env.repo, c, WS, "a2", "CP:a", env.q,
                                        env.now)["status"] == "recorded"
        assert env.repo.balance(c, WS, "a", "USD") == 12000 - 6000


def test_booked_successor_refreshes_an_open_explain_question(tmp_path):
    env = make(tmp_path)
    with env.repo.tx() as c:
        env.move(c, "i1", 12000, D14, acc="acc-usd", iban=PAYER_IBAN,
                 status=domain.MovementStatus.PENDING)
    assert env.run() == counts(asked=1)
    with env.repo.tx() as c:
        code = env.item(c, "EXPLAIN_INCOMING:i1").code
        env.move(c, "i2", 11900, D15, acc="acc-usd", iban=PAYER_IBAN, supersedes="i1")
    assert env.run() == counts()
    with env.repo.read() as c:
        item = env.item(c, "EXPLAIN_INCOMING:i1")
        assert (item.code, item.payload["amount"], item.payload["booking_date"]) == (
            code, "119.00", "2026-11-15")


def test_sender_drops_the_payment_rail_and_keeps_forty_characters():
    from app.receivables.explain import sender_text
    assert sender_text("", ZELLE_1) == "FAMILIAR A"
    assert sender_text("", "ZELLE PAYMENT FROM FAMILIAR B CONF# X9") == "FAMILIAR B"
    assert sender_text("", "ONLINE BANKING TRANSFER FROM FAMILIAR C 12") == "FAMILIAR C"
    assert sender_text("Familiar con un nombre compuesto muy largo y sintetico 4521", "x") == (
        "FAMILIAR CON UN NOMBRE COMPUESTO MUY LAR")
    assert sender_text("", "") == ""


def test_explain_question_lives_in_its_own_module():
    from app.receivables import corrections, explain, matcher
    assert matcher.ask_explain_incoming is explain.ask_explain_incoming
    assert ".matcher" not in inspect.getsource(corrections)


def test_old_cursor_table_is_upgraded_and_asks_no_history(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        env.move(c, "hist", -15000, D14)  # unlinked partner payment from before the upgrade
        top = env.repo.max_movement_rowid(c, WS)
    base = env.repo.base
    raw_execute(base, "DROP TABLE matcher_cursor")
    raw_execute(base, "CREATE TABLE matcher_cursor(workspace_id TEXT PRIMARY KEY, "
                      "movement_rowid INTEGER NOT NULL)")
    raw_execute(base, "INSERT INTO matcher_cursor VALUES(?,?)", (WS, top))
    upgraded = FinanceRepository(base.path, pepper=PEPPER)  # opening the file upgrades it
    assert column_names(upgraded, "matcher_cursor") == [
        "workspace_id", "movement_rowid", "start_rowid"]
    assert raw_execute(upgraded, "SELECT movement_rowid, start_rowid FROM matcher_cursor") == [
        (top, top)]
    FinanceRepository(base.path, pepper=PEPPER)  # a second open changes nothing
    for _ in range(3):
        assert env.run() == counts()
    raw_execute(base, "UPDATE matcher_cursor SET start_rowid=NULL")
    with env.repo.read() as c:  # NULL never reads as 0 (R37)
        assert env.repo.cursor_state(c, WS) == (top, top)
