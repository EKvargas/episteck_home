"""Journeys across the I2 features: the bank sync (real I1 ingest, PENDING -> BOOKED linking),
the matcher, and the owner's answers through ReceivablesService (final review, R57-R64).

Synthetic data only ("Familiar A", "Fondo F", "Socio"; IBAN-like strings are made up).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app import domain
from app.receivables.matcher import Matcher
from app.receivables.model import Counterparty, CounterpartyKind, Opening
from app.receivables.pending import PendingQueue
from app.receivables.service import ReceivablesService
from app.store.receivables_repo import ReceivablesRepository
from tests.support import (
    FakeAuthorizer, make_account, make_repo, seed_connection, seed_workspace,
)

WS, DELEG = "ws-1", "deleg-1"
ECB = Decimal("1.0870")  # USD per EUR: 0.9200 EUR per USD
IBANS = {"partner": "XX00 SYNTHETIC PARTNER 0001", "landlord": "XX00 SYNTHETIC RENT 0002",
         "other": "XX00 SYNTHETIC OTHER 0003"}
ZELLE_A = "ZELLE FROM FAMILIAR A CONF# AA11 1001"
ZELLE_C = "ZELLE FROM FAMILIAR C CONF# CC22 2002"
NOTHING = {"linked": 0, "waiting": 0, "asked": 0, "receipts": 0, "ignored": 0}
E1 = [("Familiar A", "120"), ("Familiar B", "80"), ("owner", "100")]  # 300 USD


def utc(month, day, hour=0, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def D(month, day):
    return date(2026, month, day)


def counts(**kw):
    return {**NOTHING, **kw}


class World:
    """One workspace, an EUR and a USD account, the matcher after every sync."""

    def __init__(self, tmp_path):
        base = make_repo(tmp_path)
        seed_workspace(base)
        seed_connection(base)
        for aid, cur in (("acc-eur", "EUR"), ("acc-usd", "USD")):
            base.add_account(make_account(aid=aid, currency=cur))
        base.store_fx_rates(D(10, 1), {"USD": ECB})
        self.base, self.rx = base, ReceivablesRepository(base)
        self.now = utc(11, 19, 6, 20)
        self.svc = ReceivablesService(base, FakeAuthorizer(), WS, clock=lambda: self.now,
                                      description_rules=True)
        self.matcher = Matcher(self.rx, PendingQueue(self.rx, lambda: self.now),
                               lambda: self.now, True)
        self.n = 0

    # --- bank ---------------------------------------------------------------------------
    def mv(self, acc, amount, day, *, iban=None, name="", text="", status="BOOKED", tx=None):
        self.n += 1
        st = domain.MovementStatus(status)
        cur = "USD" if acc == "acc-usd" else "EUR"
        booking = None if st is domain.MovementStatus.PENDING and cur == "USD" else day
        return domain.Movement(
            f"mv{self.n:03d}", WS, acc, tx or f"tx-{self.n}", f"fp-{self.n}", st, booking, day,
            amount, cur, name, self.rx.hash_key(IBANS[iban]) if iban else None, text)

    def sync(self, *moves, at):
        """The sync unit: ingest per account (real PENDING -> BOOKED linking), then match."""
        self.now = at
        by_account: dict[str, list] = {}
        for m in moves:
            by_account.setdefault(m.account_id, []).append(m)
        for acc, ms in by_account.items():
            self.base.ingest_movements(WS, acc, ms)
        return self.matcher.run(WS, at)

    def go_live(self, *history, partner_iban=True, fund=False):
        """The first matcher run marks go-live; then the first load and the watched accounts.
        A fund (its start unknown) brings a REVIEW_OPENING question at the next sync."""
        assert self.sync(*history, at=utc(11, 19, 6, 20)) == NOTHING
        parties = [("p", "Socio", CounterpartyKind.EXCHANGE_PARTNER, {}),
                   ("a", "Familiar A", CounterpartyKind.PERSON, {"pay_currency": "USD"}),
                   ("b", "Familiar B", CounterpartyKind.PERSON, {"pay_currency": "EUR"}),
                   ("c", "Familiar C", CounterpartyKind.PERSON, {"pay_currency": "USD"})]
        if fund:
            parties.append(("f", "Fondo F", CounterpartyKind.FUND, {"opening": Opening.UNKNOWN}))
        with self.rx.tx() as c:
            for cid, label, kind, extra in parties:
                self.rx.insert_counterparty(
                    c, Counterparty(cid, WS, kind, label, "ACTIVE", **extra), [label])
            if partner_iban:
                self.rx.add_partner_identifier(c, WS, self.rx.hash_key(IBANS["partner"]), "p")
            for acc in ("acc-eur", "acc-usd"):
                self.rx.set_watch(c, WS, acc, True)
        self.now = utc(11, 19, 8, 0)

    # --- owner ----------------------------------------------------------------------------
    def yes(self, out):
        assert out["ok"] and out["status"] == "confirmation_required", out
        done = self.svc.resolve(DELEG, out["code"], "yes")
        assert done["ok"], done
        return done

    def exchange(self, total, lines, day=None, ref=None):
        self.n += 1
        evidence = {"ves_reference": ref or f"REF-SYNTH-{self.n}"}
        if day:
            evidence["date"] = day
        out = self.svc.propose_exchange(DELEG, total, [{"payer": p, "usd": u} for p, u in lines],
                                        evidence)
        return self.yes(out)["exchange_ref"]

    def items(self, kind=None):
        return [i for i in self.svc.pending(DELEG)["items"] if kind in (None, i["kind"])]

    def choice(self, code, label):
        item = next(i for i in self.items() if i["code"] == code)
        return next(o["choice"] for o in item["options"] if o["label"] == label)

    def answer(self, code, label):
        return self.svc.resolve(DELEG, code, self.choice(code, label))

    def balance(self, cp_id, cur):
        with self.rx.read() as c:
            return self.rx.balance(c, WS, cp_id, cur)

    def funding_of(self, movement):
        with self.rx.read() as c:
            return self.rx.live_funding_for_movement(c, movement.id)

    def root(self, movement):
        """The row I1 linked this one to (its PENDING), else the movement itself."""
        with self.rx.read() as c:
            return self.rx.movement_root(c, movement.id)

    def paid(self, ref):
        with self.rx.read() as c:
            ex = self.rx.exchange_by_ref(c, WS, ref)
            return self.rx.live_funding_for_exchange(c, ex.id) is not None


# --- C1 (R57): a funding the owner reversed is linked again only by the owner's answer -----
def test_reversed_funding_stays_unlinked_and_its_question_open_until_answered(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.exchange("300", E1, "2026-11-17")
    pay = w.mv("acc-eur", -27600, D(11, 19), iban="partner", name="Socio SL")
    assert w.sync(pay, at=utc(11, 19, 18, 20)) == counts(linked=1)
    assert w.balance("b", "EUR") == 7360
    w.now = utc(11, 19, 20, 0)
    out = w.yes(w.svc.propose_reverse(DELEG, "F1", "no era para C1"))
    assert out["status"] == "reversed" and len(out["questions"]) == 1
    question = out["questions"][0]
    for at in (utc(11, 20, 6, 20), utc(11, 20, 18, 20)):  # the next syncs leave it alone
        assert w.sync(at=at) == NOTHING
        assert w.funding_of(pay) is None and not w.paid("C1")
        assert question in [i["code"] for i in w.items("LINK_FUNDING")]
    assert w.balance("b", "EUR") == 0
    w.now = utc(11, 20, 19, 0)
    done = w.svc.resolve(DELEG, question, "C1")
    assert (done["status"], done["funding_ref"]) == ("linked", "F2")
    assert w.balance("b", "EUR") == 7360


def test_reversed_payment_never_joins_a_split_pool(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.exchange("300", E1, "2026-11-17")
    half = w.mv("acc-eur", -15000, D(11, 18), iban="partner", name="Socio SL")
    assert w.sync(half, at=utc(11, 19, 18, 20)) == counts(waiting=1)
    assert w.sync(at=utc(11, 20, 6, 20)) == counts(asked=1)
    [link] = w.items("LINK_FUNDING")
    w.now = utc(11, 20, 9, 0)
    assert w.svc.resolve(DELEG, link["code"], "C1")["status"] == "linked"  # the owner's pick
    w.yes(w.svc.propose_reverse(DELEG, "F1", "no era para C1"))
    rest = w.mv("acc-eur", -12600, D(11, 20), iban="partner", name="Socio SL")
    # together they would make 276.00 EUR for C1: the reversed half is not pooled again
    assert w.sync(rest, at=utc(11, 20, 18, 20)) == counts(waiting=1)
    assert w.funding_of(half) is None and w.funding_of(rest) is None and not w.paid("C1")


def test_booked_row_of_a_reversed_pending_payment_is_not_linked_again(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.exchange("300", E1, "2026-11-17")
    pending = w.mv("acc-eur", -27600, D(11, 19), iban="partner", name="Socio SL",
                   status="PENDING", tx="eb-1")
    assert w.sync(pending, at=utc(11, 19, 18, 20)) == counts(linked=1)
    w.now = utc(11, 19, 20, 0)
    question = w.yes(w.svc.propose_reverse(DELEG, "F1", "no era para C1"))["questions"][0]
    booked = w.mv("acc-eur", -27600, D(11, 20), iban="partner", name="Socio SL", tx="eb-1")
    w.sync(booked, at=utc(11, 20, 18, 20))
    assert w.funding_of(booked) is None and not w.paid("C1")
    assert question in [i["code"] for i in w.items("LINK_FUNDING")]


# --- I2 (R58): incoming credits count only once BOOKED -------------------------------------
def test_pending_credits_are_skipped_and_their_booked_rows_counted_once(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.exchange("240", [("Familiar A", "120"), ("Familiar C", "120")], "2026-11-19")
    assert w.sync(w.mv("acc-usd", 12000, D(11, 20), text=ZELLE_A, status="PENDING", tx="p-a"),
                  w.mv("acc-usd", 12000, D(11, 20), text=ZELLE_C, status="PENDING", tx="p-c"),
                  at=utc(11, 20, 18, 20)) == NOTHING
    assert w.items("EXPLAIN_INCOMING") == []
    # posted under new ids: two open pendings of that amount, so I1 links neither
    assert w.sync(w.mv("acc-usd", 12000, D(11, 21), text=ZELLE_A, tx="b-a"),
                  w.mv("acc-usd", 12000, D(11, 21), text=ZELLE_C, tx="b-c"),
                  at=utc(11, 21, 6, 20)) == counts(asked=2)
    w.now = utc(11, 21, 9, 0)
    for item in w.items("EXPLAIN_INCOMING"):
        who = "Familiar A" if "FAMILIAR A" in item["details"]["sender"] else "Familiar C"
        assert w.answer(item["code"], who)["status"] == "recorded"
    assert (w.balance("a", "USD"), w.balance("c", "USD")) == (0, 0)
    assert w.sync(at=utc(11, 21, 18, 20)) == NOTHING


def test_a_pending_credit_that_never_posts_is_never_counted(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.exchange("120", [("Familiar A", "120")], "2026-11-19")
    for day in (20, 21, 22):
        moves = [w.mv("acc-usd", 12000, D(11, 20), text=ZELLE_A, status="PENDING",
                      tx="p-a")] if day == 20 else []
        assert w.sync(*moves, at=utc(11, day, 18, 20)) == NOTHING
    assert w.items("EXPLAIN_INCOMING") == []
    assert w.balance("a", "USD") == 12000  # still owed: the bank never posted it


# --- I3 (R59): history stays history ----------------------------------------------------------
def test_booked_row_of_a_pre_go_live_pending_credit_is_history(tmp_path):
    w = World(tmp_path)
    w.go_live(w.mv("acc-usd", 5000, D(11, 18), text=ZELLE_C, status="PENDING", tx="sf-p"))
    w.exchange("120", [("Familiar C", "120")], "2026-11-19")
    assert w.sync(w.mv("acc-usd", 5000, D(11, 19), text=ZELLE_C, tx="sf-p"),
                  at=utc(11, 19, 18, 20)) == NOTHING
    assert w.items("EXPLAIN_INCOMING") == []
    assert w.balance("c", "USD") == 12000


def test_booked_row_of_a_pre_go_live_partner_payment_is_history(tmp_path):
    w = World(tmp_path)
    w.go_live(w.mv("acc-eur", -27600, D(11, 18), iban="partner", name="Socio SL",
                   status="PENDING", tx="eb-h"))
    w.exchange("300", E1, "2026-11-17")
    booked = w.mv("acc-eur", -27600, D(11, 19), iban="partner", name="Socio SL", tx="eb-h")
    assert w.sync(booked, at=utc(11, 19, 18, 20)) == NOTHING
    assert w.sync(at=utc(11, 20, 6, 20)) == NOTHING
    assert w.funding_of(booked) is None and not w.paid("C1")


def test_a_pool_never_takes_a_payment_from_before_go_live(tmp_path):
    w = World(tmp_path)
    old = w.mv("acc-eur", -15000, D(11, 18), iban="partner", name="Socio SL")
    w.go_live(old)
    w.exchange("300", E1, "2026-11-17")
    new = w.mv("acc-eur", -12600, D(11, 19), iban="partner", name="Socio SL")
    assert w.sync(new, at=utc(11, 19, 18, 20)) == counts(waiting=1)
    assert w.funding_of(new) is None and w.funding_of(old) is None


def test_previous_unpaid_picks_skip_history_to_a_known_partner_iban(tmp_path):
    w = World(tmp_path)
    known = w.mv("acc-eur", -27600, D(11, 18), iban="partner", name="Socio SL")
    unknown = w.mv("acc-eur", -27600, D(11, 18), iban="other", name="Otro banco")
    w.go_live(known, unknown)
    w.exchange("300", E1, "2026-11-17")
    w.now = utc(11, 19, 9, 0)
    w.exchange("100", [("Familiar A", "100")], "2026-11-19")
    assert w.sync(at=utc(11, 19, 18, 20)) == counts(asked=1)
    [item] = w.items("PREVIOUS_UNPAID")
    labels = [o["label"] for o in item["options"]]
    assert labels == ["18/11 · 276.00 · Otro banco", "NOT_YET"]  # F8 may learn from this one


# --- R65: history only when the BOOKED row posted the pre-go-live PENDING -------------------
# I1 links a BOOKED row to the single open PENDING of the same amount, at any age, so a PENDING
# from before go-live that never posted can take a later, unrelated movement as its posting.
def test_a_stale_pre_go_live_pending_credit_does_not_hide_a_later_credit(tmp_path):
    w = World(tmp_path)
    stale = w.mv("acc-usd", 12000, D(11, 18), text=ZELLE_A, status="PENDING", tx="sf-stale")
    w.go_live(stale)  # A's PENDING credit never posts
    w.exchange("120", [("Familiar C", "120")], "2026-11-19")
    paid = w.mv("acc-usd", 12000, D(12, 5), text=ZELLE_C, tx="sf-c")
    assert w.sync(paid, at=utc(12, 5, 18, 20)) == counts(asked=1)
    assert w.root(paid) == stale.id  # I1 took C's credit for the stale PENDING's posting
    [item] = w.items("EXPLAIN_INCOMING")
    w.now = utc(12, 5, 19, 0)
    assert w.answer(item["code"], "Familiar C")["status"] == "recorded"
    assert w.balance("c", "USD") == 0
    assert w.sync(at=utc(12, 6, 6, 20)) == NOTHING


def test_a_stale_pre_go_live_pending_payment_does_not_hide_a_later_partner_payment(tmp_path):
    w = World(tmp_path)
    stale = w.mv("acc-eur", -27600, D(11, 18), iban="partner", name="Socio SL",
                 status="PENDING", tx="eb-stale")
    w.go_live(stale)  # never posts
    w.now = utc(11, 24, 9, 0)
    w.exchange("300", E1, "2026-11-24")
    paid = w.mv("acc-eur", -27600, D(11, 25), iban="partner", name="Socio SL", tx="eb-new")
    assert w.sync(paid, at=utc(11, 25, 18, 20)) == counts(linked=1)  # 7 days after the PENDING
    assert w.root(paid) == stale.id
    assert w.funding_of(paid) is not None and w.paid("C1")
    assert w.balance("b", "EUR") == 7360


def test_a_captured_partner_payment_waits_is_asked_and_offered_as_a_pick(tmp_path):
    w = World(tmp_path)
    stale = w.mv("acc-eur", -27600, D(11, 10), iban="partner", name="Socio SL",
                 status="PENDING", tx="eb-stale")
    w.go_live(stale)
    paid = w.mv("acc-eur", -27600, D(11, 20), iban="partner", name="Socio SL", tx="eb-new")
    assert w.sync(paid, at=utc(11, 20, 18, 20)) == counts(waiting=1)  # no exchange yet
    assert w.root(paid) == stale.id
    assert w.sync(at=utc(11, 21, 6, 20)) == counts(asked=1)  # R34: it keeps waiting, asked
    [link] = w.items("LINK_FUNDING")
    assert [o["choice"] for o in link["options"]] == ["REGISTER", "NOT_EXCHANGE"]
    w.now = utc(11, 21, 9, 0)
    w.exchange("300", E1)  # C1 and C2 delivered today, after the payment
    w.now = utc(11, 21, 10, 0)
    w.exchange("100", [("Familiar A", "100")])
    assert w.sync(at=utc(11, 21, 18, 20)) == counts(asked=1)
    [pick] = w.items("PREVIOUS_UNPAID")
    assert [o["label"] for o in pick["options"]] == ["20/11 · 276.00 · Socio SL", "NOT_YET"]
    w.now = utc(11, 21, 19, 0)
    assert w.answer(pick["code"], "20/11 · 276.00 · Socio SL")["status"] == "linked"
    assert w.paid("C1") and w.balance("b", "EUR") == 7360


def test_a_captured_partner_payment_joins_a_split_pool(tmp_path):
    w = World(tmp_path)
    stale = w.mv("acc-eur", -15000, D(11, 11), iban="partner", name="Socio SL",
                 status="PENDING", tx="eb-stale")
    w.go_live(stale)
    w.exchange("300", E1, "2026-11-17")
    half = w.mv("acc-eur", -15000, D(11, 20), iban="partner", name="Socio SL", tx="eb-half")
    assert w.sync(half, at=utc(11, 20, 18, 20)) == counts(waiting=1)
    assert w.root(half) == stale.id
    rest = w.mv("acc-eur", -12600, D(11, 21), iban="partner", name="Socio SL")
    assert w.sync(rest, at=utc(11, 21, 18, 20)) == counts(linked=1)
    funding = w.funding_of(rest)
    assert (funding.movement_ids, funding.eur_minor) == ((stale.id, rest.id), 27600)
    assert w.balance("b", "EUR") == 7360


def test_a_pre_go_live_pending_posted_weeks_later_under_its_own_id_stays_history(tmp_path):
    w = World(tmp_path)
    w.go_live(w.mv("acc-usd", 5000, D(11, 18), text=ZELLE_C, status="PENDING", tx="sf-p"),
              w.mv("acc-eur", -27600, D(11, 18), iban="partner", name="Socio SL",
                   status="PENDING", tx="eb-p"))
    w.exchange("300", E1, "2026-11-17")
    assert w.sync(w.mv("acc-usd", 5000, D(12, 9), text=ZELLE_C, tx="sf-p"),
                  w.mv("acc-eur", -27600, D(12, 9), iban="partner", name="Socio SL", tx="eb-p"),
                  at=utc(12, 9, 18, 20)) == NOTHING
    assert w.sync(at=utc(12, 10, 6, 20)) == NOTHING
    assert w.items("EXPLAIN_INCOMING") == w.items("LINK_FUNDING") == []
    assert not w.paid("C1")


def test_a_pre_go_live_pending_posted_within_the_week_under_a_new_id_stays_history(tmp_path):
    w = World(tmp_path)
    w.go_live(w.mv("acc-usd", 5000, D(11, 18), text=ZELLE_C, status="PENDING", tx="sf-p"),
              w.mv("acc-eur", -27600, D(11, 18), iban="partner", name="Socio SL",
                   status="PENDING", tx="eb-p"))
    w.exchange("300", E1, "2026-11-17")
    credit = w.mv("acc-usd", 5000, D(11, 24), text=ZELLE_C, tx="sf-posted")  # 6 days later
    payment = w.mv("acc-eur", -27600, D(11, 24), iban="partner", name="Socio SL", tx="eb-posted")
    assert w.sync(credit, payment, at=utc(11, 24, 18, 20)) == NOTHING
    assert w.sync(at=utc(11, 25, 6, 20)) == NOTHING
    assert w.root(credit) != credit.id and w.root(payment) != payment.id
    assert w.items("EXPLAIN_INCOMING") == w.items("LINK_FUNDING") == []
    assert not w.paid("C1")


# --- I4 (R60): reversing the funding a pick made also forgets the IBAN it taught ------------
def test_reversing_a_wrong_pick_forgets_the_partner_iban_it_taught(tmp_path):
    w = World(tmp_path)
    w.go_live(partner_iban=False)
    w.exchange("300", E1, "2026-11-17")
    rent = w.mv("acc-eur", -27600, D(11, 18), iban="landlord", name="Casero")
    real = w.mv("acc-eur", -27600, D(11, 18), iban="partner", name="Socio SL")
    assert w.sync(rent, real, at=utc(11, 19, 18, 20)) == NOTHING
    w.now = utc(11, 20, 9, 0)
    w.exchange("100", [("Familiar A", "100")], "2026-11-20")
    assert w.sync(at=utc(11, 20, 18, 20)) == counts(asked=1)
    [pick] = w.items("PREVIOUS_UNPAID")
    w.now = utc(11, 20, 19, 0)
    assert w.answer(pick["code"], "18/11 · 276.00 · Casero")["status"] == "linked"  # wrong one
    out = w.svc.propose_reverse(DELEG, "F1", "pago equivocado")
    assert out["echo"]["forgets_partner_iban"] is True
    done = w.yes(out)
    assert (done["status"], done["partner_ibans_forgotten"]) == ("reversed", 1)
    with w.rx.read() as c:
        assert w.rx.partner_hashes(c, WS) == {}
    # next month's rent to the same IBAN is not a partner payment
    rent2 = w.mv("acc-eur", -80000, D(12, 18), iban="landlord", name="Casero")
    assert w.sync(rent2, at=utc(12, 18, 18, 20)) == NOTHING
    assert w.sync(at=utc(12, 19, 6, 20)) == NOTHING
    asked = [i["details"]["eur"] for i in w.items("LINK_FUNDING")]
    assert asked == ["276.00"]  # only the reversed payment, asked again (R57)


def test_reversing_a_funding_that_taught_nothing_forgets_nothing(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.exchange("300", E1, "2026-11-17")
    w.sync(w.mv("acc-eur", -27600, D(11, 19), iban="partner", name="Socio SL"),
           at=utc(11, 19, 18, 20))
    w.now = utc(11, 19, 20, 0)
    out = w.svc.propose_reverse(DELEG, "F1", "probar")
    assert out["echo"]["forgets_partner_iban"] is False
    assert w.yes(out)["partner_ibans_forgotten"] == 0
    with w.rx.read() as c:
        assert len(w.rx.partner_hashes(c, WS)) == 1


# --- I5 (R61): after "register it", a newly registered exchange asks again -----------------
def test_register_answer_then_an_undated_exchange_asks_again_with_it(tmp_path):
    w = World(tmp_path)
    w.go_live()
    pay = w.mv("acc-eur", -27600, D(11, 20), iban="partner", name="Socio SL")
    assert w.sync(pay, at=utc(11, 20, 18, 20)) == counts(waiting=1)
    assert w.sync(at=utc(11, 21, 6, 20)) == counts(asked=1)
    [first] = w.items("LINK_FUNDING")
    assert [o["choice"] for o in first["options"]] == ["REGISTER", "NOT_EXCHANGE"]
    w.now = utc(11, 21, 9, 0)
    assert w.svc.resolve(DELEG, first["code"], "REGISTER")["status"] == "needs_exchange"
    # the screenshot's date never reached Finance: delivered_on defaults to today (21/11)
    assert w.exchange("300", E1) == "C1"
    assert w.sync(at=utc(11, 21, 18, 20)) == counts(asked=1)
    [again] = w.items("LINK_FUNDING")
    assert again["code"] != first["code"]
    assert [o["choice"] for o in again["options"]] == ["C1", "REGISTER", "NOT_EXCHANGE"]
    assert w.sync(at=utc(11, 22, 6, 20)) == NOTHING  # once per newly registered exchange
    w.now = utc(11, 22, 9, 0)
    assert w.svc.resolve(DELEG, again["code"], "C1")["status"] == "linked"
    assert w.funding_of(pay) is not None and w.balance("b", "EUR") == 7360
    assert w.sync(at=utc(11, 22, 18, 20)) == NOTHING


def test_register_again_waits_for_the_next_registered_exchange(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.sync(w.mv("acc-eur", -9200, D(11, 20), iban="partner", name="Socio SL"),
           at=utc(11, 20, 18, 20))
    w.sync(at=utc(11, 21, 6, 20))
    [first] = w.items("LINK_FUNDING")
    w.now = utc(11, 21, 9, 0)
    w.svc.resolve(DELEG, first["code"], "REGISTER")
    w.exchange("300", E1)  # not this payment's exchange
    w.sync(at=utc(11, 21, 18, 20))
    [second] = w.items("LINK_FUNDING")
    w.now = utc(11, 21, 19, 0)
    assert w.svc.resolve(DELEG, second["code"], "REGISTER")["status"] == "needs_exchange"
    assert w.sync(at=utc(11, 22, 6, 20)) == NOTHING
    w.now = utc(11, 22, 9, 0)
    w.exchange("100", [("Familiar A", "100")])
    # the new exchange is offered again; C1, still open, gets its PREVIOUS_UNPAID
    assert w.sync(at=utc(11, 22, 18, 20)) == counts(asked=2)
    [third] = w.items("LINK_FUNDING")
    assert [o["choice"] for o in third["options"]] == ["C2", "REGISTER", "NOT_EXCHANGE"]
    w.now = utc(11, 22, 19, 0)
    assert w.svc.resolve(DELEG, third["code"], "C2")["status"] == "linked"


def test_register_again_offers_the_exchange_registered_while_the_question_was_open(tmp_path):
    """R65: "registered since" counts from when the latest LINK_FUNDING was asked, so an
    exchange registered before the owner answers REGISTER again is still offered."""
    w = World(tmp_path)
    w.go_live()
    pay = w.mv("acc-eur", -27600, D(11, 20), iban="partner", name="Socio SL")
    w.sync(pay, at=utc(11, 20, 18, 20))
    w.sync(at=utc(11, 21, 6, 20))
    [first] = w.items("LINK_FUNDING")
    w.now = utc(11, 21, 9, 0)
    w.svc.resolve(DELEG, first["code"], "REGISTER")
    w.exchange("100", [("Familiar A", "100")])  # C1: not this payment's exchange
    assert w.sync(at=utc(11, 21, 18, 20)) == counts(asked=1)
    [second] = w.items("LINK_FUNDING")
    assert [o["choice"] for o in second["options"]] == ["C1", "REGISTER", "NOT_EXCHANGE"]
    w.now = utc(11, 22, 8, 0)
    assert w.exchange("300", E1) == "C2"  # the right one, registered while `second` is open
    w.now = utc(11, 22, 9, 0)
    assert w.svc.resolve(DELEG, second["code"], "REGISTER")["status"] == "needs_exchange"
    # C2 is offered; C1, still open and not offered, gets its PREVIOUS_UNPAID
    assert w.sync(at=utc(11, 22, 18, 20)) == counts(asked=2)
    [third] = w.items("LINK_FUNDING")
    assert [o["choice"] for o in third["options"]] == ["C2", "REGISTER", "NOT_EXCHANGE"]
    assert w.sync(at=utc(11, 23, 6, 20)) == NOTHING  # once per newly registered exchange
    w.now = utc(11, 23, 9, 0)
    assert w.svc.resolve(DELEG, third["code"], "C2")["status"] == "linked"
    assert w.paid("C2") and w.balance("b", "EUR") == 7360


def test_all_after_register_takes_the_exchanges_the_question_offered(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.sync(w.mv("acc-eur", -27600, D(11, 20), iban="partner", name="Socio SL"),
           at=utc(11, 20, 18, 20))
    w.sync(at=utc(11, 21, 6, 20))
    [first] = w.items("LINK_FUNDING")
    w.now = utc(11, 21, 9, 0)
    w.svc.resolve(DELEG, first["code"], "REGISTER")
    w.exchange("150", [("Familiar A", "120"), ("owner", "30")])
    w.exchange("150", [("Familiar B", "80"), ("owner", "70")])
    assert w.sync(at=utc(11, 21, 18, 20)) == counts(asked=1)
    [again] = w.items("LINK_FUNDING")
    assert [o["choice"] for o in again["options"]] == [
        "C1", "C2", "ALL", "REGISTER", "NOT_EXCHANGE"]
    w.now = utc(11, 21, 19, 0)
    assert w.svc.resolve(DELEG, again["code"], "ALL")["status"] == "linked"
    assert w.paid("C1") and w.paid("C2") and w.balance("b", "EUR") == 7360


# --- I6 (R62): a fund's opening echo shows the flows and what it holds after them ----------
def test_fund_opening_echo_shows_the_flows_since_and_the_held_amount_after(tmp_path):
    w = World(tmp_path)
    w.go_live(fund=True)
    w.exchange("100", [("Fondo F", "100")], "2026-11-19")  # 100 out of the fund
    w.sync(w.mv("acc-usd", 20000, D(11, 20), text="ONLINE TRANSFER FROM TITULAR FONDO REF 99"),
           at=utc(11, 20, 18, 20))
    [deposit] = w.items("EXPLAIN_INCOMING")
    w.now = utc(11, 21, 9, 0)
    assert w.answer(deposit["code"], "Fondo F")["status"] == "recorded"  # 200 in
    out = w.svc.propose_opening(DELEG, "Fondo F", "500", "USD", "APPROXIMATE", "segun el dueno")
    echo = out["echo"]
    assert (echo["held"], echo["held_after"]) == ("500.00", "600.00")
    assert (echo["since"], echo["out_since"], echo["in_since"]) == (
        "2026-11-19", "100.00", "200.00")
    w.yes(out)
    fund = next(r for r in w.svc.receivables(DELEG)["held_for_others"]
                if r["counterparty"] == "Fondo F")
    assert fund["amount"] == echo["held_after"]


def test_fund_opening_echo_without_flows_holds_what_is_stated(tmp_path):
    w = World(tmp_path)
    w.go_live(fund=True)
    echo = w.svc.propose_opening(DELEG, "Fondo F", "500", "USD", "APPROXIMATE", "x")["echo"]
    assert (echo["held"], echo["held_after"], echo["since"]) == ("500.00", "500.00", None)
    assert (echo["out_since"], echo["in_since"]) == ("0.00", "0.00")
    person = w.svc.propose_opening(DELEG, "Familiar A", "50", "USD", "APPROXIMATE", "x")["echo"]
    assert "held_after" not in person and person["amount"] == "50.00"


# --- I7 (R63): a re-proposal after a stale default supersedes the old echo ------------------
def test_a_stale_echo_is_superseded_by_its_re_proposal(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.exchange("300", [("Familiar A", "120"), ("Familiar C", "180")], "2026-11-19")
    w.now = utc(11, 20, 9, 0)
    old = w.svc.propose_receipt(DELEG, "Familiar C", "100", "USD", "CASH")  # never answered
    w.now = utc(11, 23, 9, 0)
    new = w.svc.propose_receipt(DELEG, "Familiar C", "100", "USD", "CASH")
    assert new["status"] == "confirmation_required" and new["code"] != old["code"]
    assert w.svc.propose_receipt(DELEG, "Familiar C", "100", "USD", "CASH")["code"] == new["code"]
    gone = w.svc.explain(DELEG, old["code"])
    assert gone["resolution"] == "superseded" and gone["resolved_at"] is not None
    assert w.svc.resolve(DELEG, new["code"], "yes")["status"] == "recorded"
    w.now = utc(11, 23, 18, 35)
    assert old["code"] not in [i["code"] for i in w.svc.pending(DELEG, for_delivery=True)["items"]]
    assert w.svc.resolve(DELEG, old["code"], "yes") == {
        "ok": False, "error": "already_resolved", "resolution": "superseded"}
    assert w.balance("c", "USD") == 8000  # recorded once


# --- M1 (R64): a review question closes when the openings it showed change ----------------
def test_review_opening_closes_when_the_openings_it_showed_change(tmp_path):
    w = World(tmp_path)
    w.go_live(fund=True)
    w.yes(w.svc.propose_opening(DELEG, "Familiar A", "30", "USD", "APPROXIMATE", "segun el dueno"))
    assert w.sync(at=utc(11, 19, 18, 20)) == counts(asked=2)
    reviews = {i["details"]["counterparty"]: i["code"] for i in w.items("REVIEW_OPENING")}
    w.now = utc(11, 20, 9, 0)
    w.yes(w.svc.propose_opening(DELEG, "Fondo F", "800", "USD", "APPROXIMATE", "segun el dueno"))
    w.yes(w.svc.propose_reverse(DELEG, "E1", "no debia nada"))  # Familiar A's opening
    assert w.items("REVIEW_OPENING") == []
    for code in reviews.values():
        assert w.svc.explain(DELEG, code)["resolution"] == "auto:settled"


# --- M2 (R64): "ALL" with no open exchange left is a stale answer ---------------------------
def test_link_answer_all_with_no_open_exchange_is_asked_again(tmp_path):
    w = World(tmp_path)
    w.go_live()
    w.exchange("300", E1, "2026-11-13")
    w.exchange("300", E1, "2026-11-13")
    assert w.sync(w.mv("acc-eur", -27600, D(11, 14), iban="partner", name="Socio SL"),
                  at=utc(11, 19, 18, 20)) == counts(asked=1)
    [link] = w.items("LINK_FUNDING")
    w.now = utc(11, 19, 19, 0)
    for ref in ("C1", "C2"):
        w.yes(w.svc.propose_reverse(DELEG, ref, "registrado por error"))
    out = w.svc.resolve(DELEG, link["code"], "ALL")
    assert (out["ok"], out["status"]) == (True, "asked_again") and out["code"] != link["code"]


def test_the_matchers_booked_change_is_a_system_unlink():
    """R57: a funding the matcher undoes for a changed BOOKED amount is not an owner undo."""
    from app.receivables import funding, matcher
    assert matcher._BOOKED_CHANGED in funding.SYSTEM_UNLINKS
    assert funding.ADD_TO in funding.SYSTEM_UNLINKS
