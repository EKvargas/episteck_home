"""Interpretation rules 1-10, transfer pairing and text helpers: pure logic, synthetic facts."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app import domain
from app.movements.interpret import family_senders, interpret, pair_transfers
from app.movements.model import Interpretation, InterpretationFacts, Kind
from app.movements.text import (
    display_text, display_who, is_undescribed, matches, same_person, zelle_recipient,
)
from app.receivables.model import (
    Counterparty, CounterpartyKind, Funding, MovementRoleKind, Receipt, ReceiptKind,
    Verification,
)
from app.store.receivables_repo import IGNORE
from tests.support import make_account, make_movement

TODAY = date(2026, 11, 10)
D = date(2026, 11, 3)
PERSON = Counterparty("cp-p", "ws-1", CounterpartyKind.PERSON, "Familiar A", "ACTIVE")
PARTNER = Counterparty("cp-x", "ws-1", CounterpartyKind.EXCHANGE_PARTNER, "Socio", "ACTIVE")
FUNDCP = Counterparty("cp-f", "ws-1", CounterpartyKind.FUND, "Fondo", "ACTIVE")
CPS = {c.id: c for c in (PERSON, PARTNER, FUNDCP)}
ACCOUNTS = {
    "eur": make_account(aid="eur"),
    "eur2": make_account(aid="eur2"),
    "usd": make_account(aid="usd", currency="USD"),
}


def facts(**over) -> InterpretationFacts:
    base = dict(supersedes={}, fundings={}, receipts={}, roles={}, questions={},
                partner_hashes={}, own_hashes=frozenset(), rules={}, counterparties=CPS,
                person_names={})
    base.update(over)
    return InterpretationFacts(**base)


def mv(mid="m1", amount=-1000, aid="eur", day=D, iban=None, name="", text="",
       currency="EUR", status=domain.MovementStatus.BOOKED):
    return domain.Movement(mid, "ws-1", aid, None, "fp-" + mid, status, day, day, amount,
                           currency, name, iban, text, None)


def run(movement, f=None, senders=None, key=None):
    f = f or facts()
    out = interpret([(1, movement)], ACCOUNTS, f, lambda m: key, senders or {}, TODAY)
    return out[movement.id]


def receipt(payer="cp-p", number=2):
    return Receipt("r", "ws-1", number, ReceiptKind.BANK, payer, "USD", 100, D,
                   Verification.BANK_POSTED)


def test_rule_1_live_funding_is_exchange_with_ref():
    fund = Funding("fu1", "ws-1", 3, ("m1",), (), 100, 110,
                   datetime(2026, 11, 1, tzinfo=timezone.utc))
    r = run(mv(), facts(fundings={"m1": fund}))
    assert r == Interpretation(Kind.EXCHANGE, ref="F3", funding_id="fu1")


def test_rule_1_uses_the_root_of_a_superseding_movement():
    fund = Funding("fu1", "ws-1", 3, ("p1",), (), 100, 110,
                   datetime(2026, 11, 1, tzinfo=timezone.utc))
    r = run(mv("m1"), facts(supersedes={"m1": "p1"}, fundings={"p1": fund}))
    assert r.kind is Kind.EXCHANGE and r.ref == "F3"


def test_rule_2_bank_receipt_is_family_or_fund_by_payer_kind():
    r = run(mv(amount=500), facts(receipts={"m1": receipt()}))
    assert (r.kind, r.about, r.ref) == (Kind.FAMILY, "Familiar A", "R2")
    r = run(mv(amount=500), facts(receipts={"m1": receipt("cp-f", 5)}))
    assert (r.kind, r.about, r.ref) == (Kind.FUND, "Fondo", "R5")


@pytest.mark.parametrize("role,kind", [
    (MovementRoleKind.FUND_DEPOSIT, Kind.FUND),
    (MovementRoleKind.EXCHANGE_FUNDING, Kind.EXCHANGE),
    (MovementRoleKind.RECEIVABLE_PAYMENT, Kind.FAMILY),
    (MovementRoleKind.PARTNER_SIDE, Kind.PARTNER_FAVOR),
    (MovementRoleKind.NOT_EXCHANGE, Kind.OWN),
])
def test_rule_3_roles_map_to_kinds(role, kind):
    assert run(mv(), facts(roles={"m1": role})).kind is kind


def test_rule_4_open_question_is_unclear_with_code():
    r = run(mv(), facts(questions={"m1": "P7"}))
    assert (r.kind, r.ref) == (Kind.UNCLEAR, "P7")


def test_rule_5_partner_iban_is_exchange_even_with_not_exchange_role():
    f = facts(partner_hashes={"h-partner": "cp-x"},
              roles={"m4": MovementRoleKind.NOT_EXCHANGE})
    assert run(mv("m4", amount=300, iban="h-partner"), f).kind is Kind.EXCHANGE


def test_rule_6_own_iban_is_own_transfer():
    f = facts(own_hashes=frozenset({"h-own"}))
    assert run(mv("m3", iban="h-own"), f).kind is Kind.OWN_TRANSFER


def test_rule_7_payer_rule_maps_by_kind_and_not_exchange_skips_it():
    for target, kind, about in [("cp-p", Kind.FAMILY, "Familiar A"),
                                ("cp-x", Kind.PARTNER_FAVOR, "Socio"),
                                ("cp-f", Kind.FUND, "Fondo")]:
        r = run(mv(amount=500), facts(rules={"k": target}), key="k")
        assert (r.kind, r.about) == (kind, about)
    assert run(mv(amount=500), facts(rules={"k": IGNORE}), key="k").kind is Kind.OWN
    skipped = facts(rules={"k": "cp-p"}, roles={"m1": MovementRoleKind.NOT_EXCHANGE})
    assert run(mv(amount=500), skipped, key="k").kind is Kind.OWN
    # outgoing money never takes the payer rule
    assert run(mv(amount=-500), facts(rules={"k": "cp-p"}), key="k").kind is Kind.OWN


def test_rule_8_zelle_to_known_family_sender_is_family_help_else_own():
    senders = {"PERSONA UNO DOS": "Familiar A"}
    out = mv("m19", aid="usd", currency="USD",
             text="ZELLE PAYMENT TO PERSONA UNO DOS CONF# AB1")
    r = run(out, senders=senders)
    assert (r.kind, r.about) == (Kind.FAMILY_HELP, "Familiar A")
    stranger = mv("m20", aid="usd", currency="USD",
                  text="ZELLE PAYMENT TO OTRO NOMBRE CONF# AB2")
    assert run(stranger, senders=senders).kind is Kind.OWN
    # not a USD account: not recognised
    assert run(mv("m21", text="ZELLE PAYMENT TO PERSONA UNO DOS"), senders=senders).kind \
        is Kind.OWN


def test_rule_9_pairs_both_sides_across_month_edge():
    a = mv("m2", amount=-5000, aid="eur", day=date(2026, 10, 30))
    b = mv("m14", amount=5000, aid="eur2", day=date(2026, 11, 2))
    out = interpret([(1, a), (2, b)], ACCOUNTS, facts(), lambda m: None, {}, TODAY)
    assert out["m2"].kind is Kind.OWN_TRANSFER and out["m14"].kind is Kind.OWN_TRANSFER


def test_rule_10_rest_is_own():
    assert run(mv()) == Interpretation(Kind.OWN)
    assert run(mv(amount=900)) == Interpretation(Kind.OWN)


def test_two_identical_transfers_pair_one_to_one_and_extra_stays_own():
    rows = [(1, mv("o1", -5000, "eur", D)), (2, mv("o2", -5000, "eur", D)),
            (3, mv("i1", 5000, "eur2", D))]
    paired = pair_transfers(rows, TODAY)
    assert paired == {"o1", "i1"}  # lower rowid first; the second outflow stays unpaired


def test_closest_days_pair_first():
    rows = [(1, mv("o1", -5000, "eur", date(2026, 11, 1))),
            (2, mv("o2", -5000, "eur", date(2026, 11, 5))),
            (3, mv("i1", 5000, "eur2", date(2026, 11, 5)))]
    assert pair_transfers(rows, TODAY) == {"o2", "i1"}


def test_pairing_needs_window_distinct_accounts_and_same_currency():
    far = [(1, mv("o", -5000, "eur", date(2026, 11, 1))),
           (2, mv("i", 5000, "eur2", date(2026, 11, 7)))]
    assert pair_transfers(far, TODAY) == set()
    same_acc = [(1, mv("o", -5000)), (2, mv("i", 5000))]
    assert pair_transfers(same_acc, TODAY) == set()
    other_cur = [(1, mv("o", -5000)), (2, mv("i", 5000, "usd", currency="USD"))]
    assert pair_transfers(other_cur, TODAY) == set()


def test_stale_pending_never_pairs():
    old = date(2026, 11, 1)
    pend = domain.MovementStatus.PENDING
    rows = [(1, mv("o", -5000, "eur", old, status=pend)), (2, mv("i", 5000, "eur2", old))]
    assert pair_transfers(rows, TODAY) == set()
    fresh = [(1, mv("o", -5000, "eur", date(2026, 11, 8), status=pend)),
             (2, mv("i", 5000, "eur2", date(2026, 11, 8)))]
    assert pair_transfers(fresh, TODAY) == {"o", "i"}
    dateless = [(1, mv("o", -5000, "eur", None)), (2, mv("i", 5000, "eur2", None))]
    assert pair_transfers(dateless, TODAY) == set()


def test_family_senders_from_receipt_or_person_rule():
    inc = [mv("a", 500, name="PERSONA UNO DOS"), mv("b", 500, name="PERSONA TRES CUATRO"),
           mv("c", 500, name="PERSONA CINCO SEIS"), mv("d", 500, name="OTRO SOCIO X")]
    f = facts(receipts={"a": receipt()}, rules={"kb": "cp-p", "kc": IGNORE, "kd": "cp-x"})
    keys = {"a": None, "b": "kb", "c": "kc", "d": "kd"}
    got = family_senders(inc, f, lambda m: keys[m.id])
    assert got == {"PERSONA UNO DOS": "Familiar A", "PERSONA TRES CUATRO": "Familiar A"}


def test_matches_is_accent_and_case_blind_and_literal():
    assert matches("reembolso", "", "RËEMBOLSO pedido 302-123")
    assert matches("50%", "", "Rabatt 50% Aktion") and not matches("a_b", "", "axb")
    assert matches("(x", "", "(x) y")
    assert not matches("zzz", "abc", "def")


def test_display_drops_digit_tokens_rails_and_caps_length():
    assert display_text("Amazon 302-1234567 Erstattung") == "Amazon Erstattung"
    assert display_who("", "ZELLE PAYMENT TO PERSONA UNO CONF# AB12") == "PERSONA UNO"
    assert display_who("", "ZELLE FROM PERSONA UNO") == "PERSONA UNO"
    assert len(display_who("X " * 60, "")) <= 40 and len(display_text("y " * 90)) <= 80
    assert display_text("Ref CONF# AB1 gracias") == "Ref gracias"


def test_zelle_recipient():
    assert zelle_recipient("", "ZELLE TO PERSONA UNO CONF# AB1") == "PERSONA UNO"
    assert zelle_recipient("ZELLE PAYMENT TO PERSONA DOS", "") == "PERSONA DOS"
    assert zelle_recipient("Shop", "card payment") is None


def test_same_person_needs_two_words_and_containment():
    assert same_person("PERSONA UNO DOS", "PERSONA DOS")
    assert not same_person("UNO", "UNO")
    assert not same_person("PERSONA UNO", "PERSONA DOS")


def test_is_undescribed():
    assert is_undescribed(mv(name=" ", text=""))
    assert not is_undescribed(mv(text="x"))


def test_family_help_matches_a_sender_name_longer_than_the_display_cap():
    long_name = "PERSONA UNO DOS TRES CUATRO CINCO SEIS SIETE OCHO"
    assert len(long_name) > 40
    inc = [mv("a", 500, name=long_name, aid="usd", currency="USD")]
    senders = family_senders(inc, facts(receipts={"a": receipt()}), lambda m: None)
    out = mv("o", aid="usd", currency="USD", text=f"ZELLE PAYMENT TO {long_name} CONF# AB1")
    r = run(out, senders=senders)
    assert (r.kind, r.about) == (Kind.FAMILY_HELP, "Familiar A")


def test_family_help_prefers_the_exact_then_the_closest_sender():
    senders = {"JOSE GONZALEZ PEREZ": "Familiar B", "JOSE GONZALEZ": "Familiar A"}
    exact = mv("o1", aid="usd", currency="USD", text="ZELLE TO JOSE GONZALEZ")
    assert run(exact, senders=senders).about == "Familiar A"
    exact_long = mv("o2", aid="usd", currency="USD", text="ZELLE TO JOSE GONZALEZ PEREZ")
    assert run(exact_long, senders=senders).about == "Familiar B"
    senders = {"JOSE GONZALEZ": "Familiar A", "JOSE GONZALEZ PEREZ RUIZ": "Familiar B"}
    closest = mv("o3", aid="usd", currency="USD", text="ZELLE TO JOSE GONZALEZ PEREZ")
    assert run(closest, senders=senders).about == "Familiar B"
