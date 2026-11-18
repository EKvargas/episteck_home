"""Funding: partner payments linked to exchanges, implied rate, EUR shares (synthetic data only)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app import domain
from app.receivables import funding
from app.receivables.funding import (
    ask_link_funding, link_choice, reverse_funding, try_link,
)
from app.receivables.ledger import Evidence, LineInput, record_exchange
from app.receivables.model import (
    OWNER, Allocation, AllocationMethod, Counterparty, CounterpartyKind, EntryKind,
    MovementRoleKind, PendingKind, Receipt, ReceiptKind, Verification,
)
from app.receivables.pending import PendingQueue
from app.store.receivables_repo import ReceivablesRepository
from tests.support import count_rows, make_account, make_repo, seed_connection, seed_workspace

WS = "ws-1"
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
D13, D14, D15, D16, D20 = (date(2026, 11, d) for d in (13, 14, 15, 16, 20))
ECB = Decimal("1.0870")  # USD per EUR: 0.9200 EUR per USD is within 0.01 % of it
PARTNER_IBAN = "XX00 SYNTHETIC PARTNER 0001"
NEW_IBAN = "XX00 SYNTHETIC PARTNER 0002"
OTHER_IBAN = "XX00 SYNTHETIC OTHER 0003"
E1_LINES = [LineInput("a", 12000), LineInput("b", 8000), LineInput(OWNER, 4000),
            LineInput("f", 6000)]
FUNDING_TABLES = ("funding", "funding_movement", "funding_exchange", "funding_share",
                  "ledger_entry", "movement_role", "revocation", "pending_item",
                  "partner_identifier", "ref_counter")


def make(tmp_path, ecb=ECB):
    base = make_repo(tmp_path)
    seed_workspace(base)
    seed_connection(base)
    base.add_account(make_account(aid="acc-eur", currency="EUR"))
    if ecb is not None:
        base.store_fx_rates(D13, {"USD": ecb})
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


def pay(repo, c, mid, eur, day, iban=PARTNER_IBAN, status=domain.MovementStatus.BOOKED,
        supersedes=None, currency="EUR"):
    """An outgoing transfer of ``eur`` minor units (a negative ``eur`` is incoming)."""
    m = domain.Movement(mid, WS, "acc-eur", f"tx-{mid}", f"fp-{mid}", status, day, day, -eur,
                        currency, "Socio", repo.hash_key(iban), "transfer", supersedes)
    repo.base.insert_movement_in_tx(c, m)
    return m


def questions(repo, c):
    return [p for p in repo.pending_open(c, WS) if p.requires_answer]


def counts(repo):
    return {t: count_rows(repo.base, t) for t in FUNDING_TABLES}


def test_e1_single_open_exchange_links_automatically(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c, D13)
        m = pay(repo, c, "m1", 27600, D14)
        assert try_link(repo, c, WS, m, q, NOW) == "LINKED"
        f = repo.live_funding_for_exchange(c, ex.id)
        assert (f.number, f.movement_ids, f.eur_minor, f.usd_minor) == (1, ("m1",), 27600, 30000)
        assert repo.funding_shares(c, f.id) == {"a": 11040, "b": 7360, OWNER: 3680, "f": 5520}
        b_line = repo.current_lines(c, ex.id)[1]
        [charge] = repo.entries(c, WS, "b")
        assert (charge.kind, charge.currency, charge.amount_minor, charge.source_ref,
                charge.effective_on) == (EntryKind.CHARGE, "EUR", 7360, b_line.id, D14)
        assert [e.currency for e in repo.entries(c, WS, "a")] == ["USD"]
        assert [e.currency for e in repo.entries(c, WS, "f")] == ["USD"]
        assert repo.entries(c, WS, OWNER) == []
        assert repo.movement_role(c, "m1") is MovementRoleKind.EXCHANGE_FUNDING
        assert repo.open_exchanges(c, WS) == []
        notice = repo.pending_by_dedupe(c, WS, "INFO:funding_closed:F1")
        assert notice.payload == {
            "funding_ref": "F1", "exchange_refs": ["C1"], "rate": "0.9200", "eur": "276.00",
            "usd": "300.00", "text_key": "funding_closed:F1"}
        assert repo.pending_by_dedupe(c, WS, "INFO:rate_outlier:F1") is None
        assert questions(repo, c) == []


def test_e17_next_exchange_registered_before_sync_does_not_block_link(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13)
        c2 = exchange(repo, c, D20, [LineInput("a", 20000)])
        m = pay(repo, c, "m1", 27600, D20)
        assert try_link(repo, c, WS, m, q, NOW) == "LINKED"
        assert repo.live_funding_for_movement(c, "m1").exchange_ids == (c1.id,)
        assert [ex.id for ex in repo.open_exchanges(c, WS)] == [c2.id]
        assert questions(repo, c) == []


def test_e4_two_compatible_open_exchanges_ask(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        c2 = exchange(repo, c, D14)
        m = pay(repo, c, "m1", 27600, D15)
        assert try_link(repo, c, WS, m, q, NOW) == "AMBIGUOUS"
        [item] = questions(repo, c)
        assert item.kind is PendingKind.LINK_FUNDING and item.dedupe_key == "LINK_FUNDING:m1"
        assert item.options == ("C1", "C2", "ALL", "REGISTER", "NOT_EXCHANGE")
        assert item.payload == {"movement_id": "m1", "booking_date": "2026-11-15",
                                "eur": "276.00", "candidates": ["C1", "C2"]}
        assert repo.live_funding_for_movement(c, "m1") is None
        assert link_choice(repo, c, WS, "m1", "C2", q, NOW) == {
            "ok": True, "status": "linked", "funding_ref": "F1"}
        assert repo.live_funding_for_movement(c, "m1").exchange_ids == (c2.id,)
        assert [ex.number for ex in repo.open_exchanges(c, WS)] == [1]
        assert try_link(repo, c, WS, m, q, NOW) == "ALREADY_LINKED"


def test_without_ecb_rate_every_candidate_is_compatible_and_all_funds_both(tmp_path):
    repo, q = make(tmp_path, ecb=None)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13, [LineInput("a", 6000), LineInput("b", 9000)])
        c2 = exchange(repo, c, D14, [LineInput("b", 5000), LineInput(OWNER, 10000)])
        m = pay(repo, c, "m1", 27600, D15)
        assert try_link(repo, c, WS, m, q, NOW) == "AMBIGUOUS"
        assert link_choice(repo, c, WS, "m1", "ALL", q, NOW)["funding_ref"] == "F1"
        f = repo.live_funding_for_movement(c, "m1")
        assert (f.exchange_ids, f.eur_minor, f.usd_minor) == ((c1.id, c2.id), 27600, 30000)
        assert repo.funding_shares(c, f.id) == {"a": 5520, "b": 12880, OWNER: 9200}
        assert [e.amount_minor for e in repo.entries(c, WS, "b")] == [8280, 4600]
        assert repo.pending_by_dedupe(c, WS, "INFO:funding_closed:F1").payload["exchange_refs"] \
            == ["C1", "C2"]
        assert repo.pending_by_dedupe(c, WS, "INFO:rate_outlier:F1") is None


def test_e12_outlier_links_with_notice_and_far_outlier_waits(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        m1 = pay(repo, c, "m1", 28980, D14)  # +5 % over the ECB rate
        assert try_link(repo, c, WS, m1, q, NOW) == "LINKED"
        outlier = repo.pending_by_dedupe(c, WS, "INFO:rate_outlier:F1")
        assert outlier.payload["rate"] == "0.9660"
        assert outlier.payload["reference_rate"] == "0.9200"
        c2 = exchange(repo, c, D14)
        m2 = pay(repo, c, "m2", 24288, D15)  # -12 %
        assert try_link(repo, c, WS, m2, q, NOW) == "WAITING"
        assert questions(repo, c) == []
        assert repo.live_funding_for_movement(c, "m2") is None
        m3 = pay(repo, c, "m3", 3312, D16)  # completes the sum
        assert try_link(repo, c, WS, m3, q, NOW) == "LINKED"
        f = repo.live_funding_for_exchange(c, c2.id)
        assert (f.movement_ids, f.eur_minor) == (("m2", "m3"), 27600)


def test_split_payment_links_when_pool_is_compatible(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c, D13)
        m1 = pay(repo, c, "m1", 13800, D14)
        assert try_link(repo, c, WS, m1, q, NOW) == "WAITING"
        m2 = pay(repo, c, "m2", 13800, D15)
        assert try_link(repo, c, WS, m2, q, NOW) == "LINKED"
        f = repo.live_funding_for_exchange(c, ex.id)
        assert (f.movement_ids, f.eur_minor) == (("m1", "m2"), 27600)
        assert repo.funding_shares(c, f.id) == {"a": 11040, "b": 7360, OWNER: 3680, "f": 5520}
        assert repo.movement_role(c, "m1") is repo.movement_role(c, "m2") \
            is MovementRoleKind.EXCHANGE_FUNDING
        assert try_link(repo, c, WS, m1, q, NOW) == "ALREADY_LINKED"


def test_eur_override_wins_over_share(tmp_path):
    repo, q = make(tmp_path)
    lines = [LineInput("a", 12000), LineInput("b", 8000, eur_override_minor=7350),
             LineInput(OWNER, 4000), LineInput("f", 6000)]
    with repo.tx() as c:
        ex = exchange(repo, c, D13, lines)
        assert try_link(repo, c, WS, pay(repo, c, "m1", 27600, D14), q, NOW) == "LINKED"
        assert repo.balance(c, WS, "b", "EUR") == 7350
        f = repo.live_funding_for_exchange(c, ex.id)
        assert repo.funding_shares(c, f.id)["b"] == 7360


def test_eur_charges_and_their_reversal_consume_credits_per_payer(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(funding, "consume_credits",
                        lambda repo, conn, ws, payer, cur: calls.append((payer, cur)))
    repo, q = make(tmp_path)
    with repo.tx() as c:
        ex = exchange(repo, c, D13, E1_LINES + [LineInput("b", 1000)])
        assert try_link(repo, c, WS, pay(repo, c, "m1", 28520, D14), q, NOW) == "LINKED"
        assert calls == [("b", "EUR")]
        reverse_funding(repo, c, WS, repo.live_funding_for_exchange(c, ex.id).id, "x", q, NOW)
        assert calls == [("b", "EUR"), ("b", "EUR")]


def test_link_of_already_linked_movement_is_refused_without_side_effects(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        exchange(repo, c, D20)
        m1 = pay(repo, c, "m1", 13800, D14)
        assert try_link(repo, c, WS, m1, q, NOW) == "WAITING"
        ask_link_funding(repo, c, WS, "m1", q)  # the owner is asked about m1 ...
        m2 = pay(repo, c, "m2", 13800, D15)
        assert try_link(repo, c, WS, m2, q, NOW) == "LINKED"  # ... and the matcher links both
    before = counts(repo)
    with repo.tx() as c:
        for choice in ("C1", "C2", "ALL", "ADD_TO:C1", "NOT_EXCHANGE", "REGISTER"):
            assert link_choice(repo, c, WS, "m1", choice, q, NOW) == {
                "ok": False, "error": "already_linked"}
        assert link_choice(repo, c, WS, None, "M:m2", q, NOW, exchange_ref="C2") == {
            "ok": False, "error": "already_linked"}
        assert try_link(repo, c, WS, m1, q, NOW) == "ALREADY_LINKED"
    assert counts(repo) == before
    with repo.read() as c:
        assert repo.live_funding_for_movement(c, "m1").movement_ids == ("m1", "m2")
        assert [ex.number for ex in repo.open_exchanges(c, WS)] == [2]


def test_reverse_funding_restores_open_state_and_asks_again(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13)
        exchange(repo, c, D14)
        m = pay(repo, c, "m1", 27600, D15)
        assert try_link(repo, c, WS, m, q, NOW) == "AMBIGUOUS"
        [first] = questions(repo, c)
        q.resolve(c, WS, first.code, "C1", human=True)
        link_choice(repo, c, WS, "m1", "C1", q, NOW)
        b_line = repo.current_lines(c, c1.id)[1]
        [charge] = repo.effective_charges_for_exchange(c, WS, c1.id, "EUR")
        assert (charge.counterparty_id, charge.amount_minor) == ("b", 7360)
        repo.insert_receipt(c, Receipt("r1", WS, 1, ReceiptKind.CASH, "b", "EUR", 7360, D15,
                                       Verification.OWNER_CONFIRMED))
        repo.insert_allocation(c, Allocation("al1", WS, "r1", b_line.id, 7360,
                                             AllocationMethod.AUTO_EXACT))
        assert repo.live_allocation_ids_for_line(c, WS, b_line.id) == ["al1"]
        f = repo.live_funding_for_movement(c, "m1")
        assert repo.funding_by_id(c, WS, f.id) == f

        reverse_funding(repo, c, WS, f.id, "wrong exchange", q, NOW)

        assert repo.funding_by_id(c, WS, f.id) is None
        assert [ex.number for ex in repo.open_exchanges(c, WS)] == [1, 2]
        assert [(e.kind, e.amount_minor) for e in repo.entries(c, WS, "b")] == [
            (EntryKind.CHARGE, 7360), (EntryKind.REVERSAL, -7360)]
        assert repo.balance(c, WS, "b", "EUR") == 0
        assert repo.effective_charges_for_exchange(c, WS, c1.id, "EUR") == []
        assert repo.live_allocation_ids_for_line(c, WS, b_line.id) == []
        assert repo.funding_shares(c, f.id) == {}
        assert repo.movement_role(c, "m1") is None
        [again] = questions(repo, c)
        assert again.code != first.code and again.dedupe_key == "LINK_FUNDING:m1"
        assert again.options == ("C1", "C2", "ALL", "REGISTER", "NOT_EXCHANGE")
        assert try_link(repo, c, WS, m, q, NOW) == "AMBIGUOUS"
        assert questions(repo, c) == [again]


def test_add_to_recreates_the_paid_exchange_with_the_extra_payment(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        c1 = exchange(repo, c, D13)
        assert try_link(repo, c, WS, pay(repo, c, "m1", 27000, D14), q, NOW) == "LINKED"
        old = repo.live_funding_for_exchange(c, c1.id)
        assert repo.balance(c, WS, "b", "EUR") == 7200
        assert try_link(repo, c, WS, pay(repo, c, "m2", 600, D15), q, NOW) == "WAITING"
        assert repo.latest_funded_exchange(c, WS, D15) == c1
        assert repo.latest_funded_exchange(c, WS, date(2026, 11, 12)) is None
        assert ask_link_funding(repo, c, WS, "m2", q).options == (
            "ADD_TO:C1", "REGISTER", "NOT_EXCHANGE")
        assert link_choice(repo, c, WS, "m2", "ADD_TO:C1", q, NOW) == {
            "ok": True, "status": "linked", "funding_ref": "F2"}
        new = repo.live_funding_for_exchange(c, c1.id)
        assert (new.movement_ids, new.eur_minor) == (("m1", "m2"), 27600)
        assert repo.funding_by_id(c, WS, old.id) is None
        assert repo.balance(c, WS, "b", "EUR") == 7360
        assert repo.pending_by_dedupe(c, WS, "LINK_FUNDING:m1") is None


def test_previous_unpaid_pick_links_and_learns_the_partner_iban(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        exchange(repo, c, D13)
        pay(repo, c, "m1", 27600, D14, iban=NEW_IBAN)
        assert repo.unlinked_partner_payments(c, WS) == []
        assert link_choice(repo, c, WS, None, "NOT_YET", q, NOW) == {
            "ok": True, "status": "not_yet"}
        assert link_choice(repo, c, WS, None, "M:m1", q, NOW, exchange_ref="C1") == {
            "ok": True, "status": "linked", "funding_ref": "F1"}
        assert repo.partner_hashes(c, WS)[repo.hash_key(NEW_IBAN)] == "p"
        assert repo.balance(c, WS, "b", "EUR") == 7360


def test_register_writes_nothing_and_not_exchange_classifies(tmp_path):
    repo, q = make(tmp_path)
    with repo.tx() as c:
        m = pay(repo, c, "m1", 5000, D14)
        assert try_link(repo, c, WS, m, q, NOW) == "WAITING"
        assert ask_link_funding(repo, c, WS, "m1", q).options == ("REGISTER", "NOT_EXCHANGE")
    before = counts(repo)
    with repo.tx() as c:
        assert link_choice(repo, c, WS, "m1", "REGISTER", q, NOW) == {
            "ok": True, "status": "needs_exchange"}
        assert link_choice(repo, c, WS, "m1", "BOGUS", q, NOW) == {
            "ok": False, "error": "unknown_choice"}
    assert counts(repo) == before
    with repo.tx() as c:
        assert link_choice(repo, c, WS, "m1", "NOT_EXCHANGE", q, NOW) == {
            "ok": True, "status": "not_exchange"}
        assert repo.movement_role(c, "m1") is MovementRoleKind.NOT_EXCHANGE
        assert try_link(repo, c, WS, m, q, NOW) == "ALREADY_LINKED"
        assert repo.unlinked_partner_payments(c, WS) == []
        assert link_choice(repo, c, WS, "m1", "NOT_EXCHANGE", q, NOW) == {
            "ok": False, "error": "already_classified"}


def test_unlinked_partner_payments_and_current_movement(tmp_path):
    repo, _ = make(tmp_path)
    with repo.tx() as c:
        pay(repo, c, "m1", 5000, D14, status=domain.MovementStatus.PENDING)
        pay(repo, c, "m2", 5000, D15, supersedes="m1")
        pay(repo, c, "m3", -5000, D15)  # incoming
        pay(repo, c, "m4", 5000, D15, iban=OTHER_IBAN)
        pay(repo, c, "m5", 5000, D15, currency="USD")
        pay(repo, c, "m6", 5000, D13)
        repo.insert_movement_role(c, WS, "m6", MovementRoleKind.NOT_EXCHANGE)
        pay(repo, c, "m7", 4000, D13)
        assert [m.id for m in repo.unlinked_partner_payments(c, WS)] == ["m7", "m2"]
        assert repo.movement_current(c, WS, "m1").id == "m2"
        assert repo.movement_current(c, WS, "m2").amount_minor == -5000
        assert repo.movement_current(c, WS, "nope") is None
        assert repo.movement_current(c, "ws-2", "m1") is None
