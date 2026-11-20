"""The owner's confirmation contract: "yes" executes exactly what the echo showed, and a tap
means exactly the option the owner saw (rulings R42-R46).

Synthetic data only ("Familiar A", "Fondo F", "Socio").
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from app.receivables import commands
from app.receivables.corrections import correct_exchange, record_opening, reverse
from app.receivables.explain import ask_explain_incoming
from app.receivables.funding import try_link
from app.receivables.ledger import LineInput
from app.receivables.matcher import Matcher
from app.receivables.model import MovementRoleKind, Opening, PendingKind, ReceiptKind, Verification
from app.receivables.receipts import record_receipt
from tests.support import count_rows, raw_execute
from tests.test_receivables_service import (
    D14, D15, DELEG, E1, EMPLOYER_IBAN, EVIDENCE, NOW, PAYER_IBAN, WS, Env,
)

CHANGED = {"ok": False, "error": "validation_error", "field": "target",
           "detail": {"reason": "changed"}}
TOKEN = re.compile(r"O[0-9a-f]{8}")


def cash(env, c, payer, minor, currency="USD"):
    return record_receipt(env.repo, c, WS, kind=ReceiptKind.CASH, payer_id=payer,
                          currency=currency, amount_minor=minor, received_on=D14,
                          verification=Verification.OWNER_CONFIRMED, queue=env.q, now=NOW)


# --- C1 / R42: "yes" executes the stored figures --------------------------------------
def test_forgive_yes_forgives_exactly_what_the_echo_showed(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c, [LineInput("a", 5000)])  # C1: Familiar A owes 50 (E1)
    out = env.svc.propose_forgive(DELEG, "Familiar A", None, "regalo")
    assert (out["echo"]["amount"], out["echo"]["lines"]) == (
        "50.00", [{"exchange_ref": "C1", "entry_ref": None, "amount": "50.00"}])
    with env.repo.tx() as c:  # a new exchange is registered before the owner taps Sí
        env.exchange(c, [LineInput("a", 12000)], day=D14)  # C2 (E2)
    assert env.yes(out) == {"ok": True, "status": "forgiven", "currency": "USD",
                            "amount": "50.00", "entries": ["E3"]}
    with env.repo.read() as c:
        assert env.repo.balance(c, WS, "a", "USD") == 12000


def test_forgive_yes_refuses_when_the_plan_changed(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c, [LineInput("a", 5000)])  # C1: 50
    out = env.svc.propose_forgive(DELEG, "Familiar A", None, "regalo")
    with env.repo.tx() as c:  # an opening is an older item: it would take the first 30
        record_opening(env.repo, c, WS, "a", "USD", 3000, Opening.CONFIRMED, "según el dueño",
                       NOW, queue=env.q)
    before = env.facts()
    assert env.yes(out) == CHANGED
    assert env.facts() == before and env.item(out["code"]).resolved_at is None
    assert env.svc.resolve(DELEG, out["code"], "cancel")["status"] == "cancelled"
    on_c1 = env.svc.propose_forgive(DELEG, "C1:Familiar A", None, "regalo")
    assert on_c1["echo"]["amount"] == "50.00"
    with env.repo.tx() as c:  # 50 in cash: 30 settle the opening, 20 settle C1
        cash(env, c, "a", 5000)
    assert env.yes(on_c1) == CHANGED  # C1 owes 30 now: forgiving 50 there is impossible
    assert count_rows(env.base, "ledger_entry") == 3  # E1 charge, E2 opening, E3 payment


def test_rule_answer_and_undo_reversals_refuse_when_what_they_showed_changed(tmp_path):
    env = Env(tmp_path)
    payer, employer = env.repo.hash_key(PAYER_IBAN), env.repo.hash_key(EMPLOYER_IBAN)
    with env.repo.tx() as c:
        env.repo.insert_payer_rule(c, WS, payer, "a")
    rule = env.svc.propose_reverse(DELEG, "Familiar A rule", "x")
    assert rule["echo"]["rules"] == 1
    with env.repo.tx() as c:  # a second rule for Familiar A before the yes
        env.repo.insert_payer_rule(c, WS, employer, "a")
    assert env.yes(rule) == CHANGED
    both = env.svc.propose_reverse(DELEG, "Familiar A rule", "x")
    assert both["code"] != rule["code"] and both["echo"]["rules"] == 2
    assert env.yes(both) == {"ok": True, "status": "reversed", "rules": 2}

    with env.repo.tx() as c:  # an answer: R1 for Familiar A, with a rule
        env.exchange(c)
        mv = env.move(c, "in1", 12000, currency="USD", acc="acc-usd", iban=PAYER_IBAN)
        asked = ask_explain_incoming(env.repo, c, WS, mv, env.q)
    assert env.svc.resolve(DELEG, asked.code, "Familiar A")["receipt_ref"] == "R1"
    undo = env.svc.propose_reverse(DELEG, asked.code, "no era de A")
    assert undo["echo"]["receipt_ref"] == "R1"
    with env.repo.tx() as c:  # R1 is reversed another way before the yes
        reverse(env.repo, c, WS, "R1", "x", env.q, NOW)
    assert env.yes(undo) == CHANGED

    with env.repo.tx() as c:  # a payment an IGNORE rule never classified, then a rule appears
        env.move(c, "in2", 250000, day=D15, iban=EMPLOYER_IBAN, name="EMPLEADOR SINTETICO")
        env.repo.insert_movement_role(c, WS, "in2", MovementRoleKind.NOT_EXCHANGE)
    [row] = env.svc.explain(DELEG, "ignored")["movements"]
    unignore = env.svc.propose_reverse(DELEG, row["undo_ref"], "es de un familiar")
    assert unignore["echo"]["rule"] is False
    with env.repo.tx() as c:
        env.repo.insert_payer_rule(c, WS, employer, None)
    assert env.yes(unignore) == CHANGED
    with env.repo.read() as c:
        assert env.repo.movement_role(c, "in2") is MovementRoleKind.NOT_EXCHANGE


def test_opening_correction_and_reallocation_refuse_when_what_they_replace_changed(tmp_path):
    env = Env(tmp_path)
    op = env.svc.propose_opening(DELEG, "Familiar A", "30", "USD", "APPROXIMATE", "n")
    assert op["echo"]["replaces"] == []
    with env.repo.tx() as c:  # another opening is stated before the yes
        record_opening(env.repo, c, WS, "a", "USD", 1000, Opening.APPROXIMATE, "n0", NOW,
                       queue=env.q)  # E1
    assert env.yes(op) == CHANGED

    with env.repo.tx() as c:
        c1 = env.exchange(c, [LineInput("a", 12000), LineInput("b", 8000)])  # C1
    lines = [{"payer": "Familiar A", "usd": "100"}, {"payer": "Familiar B", "usd": "100"}]
    fix = env.svc.propose_correction(DELEG, "C1", lines, None, "eran 100 y 100")
    with env.repo.tx() as c:  # corrected another way first
        correct_exchange(env.repo, c, WS, c1.id, [LineInput("a", 11000), LineInput("b", 9000)],
                         None, "x", NOW, queue=env.q)
    assert env.yes(fix) == CHANGED
    again = env.svc.propose_correction(DELEG, "C1", lines, None, "eran 100 y 100")
    assert again["code"] != fix["code"]
    with env.repo.tx() as c:  # C1 is paid before the yes: its EUR would be split again
        assert try_link(env.repo, c, WS, env.move(c, "m1", -18400), env.q, NOW) == "LINKED"
    assert env.yes(again) == CHANGED

    with env.repo.tx() as c:
        env.exchange(c, [LineInput("a", 5000)], day=D14)  # C2
        cash(env, c, "a", 4500)  # R1 (no exact match): 10 settle the opening E1, 35 C1
    move = env.svc.propose_reallocate(DELEG, "R1", [{"exchange": "C2", "amount": "45"}])
    assert [b["item"] for b in move["echo"]["before"]] == ["E1", "C1"]
    with env.repo.tx() as c:  # E1 is reversed: R1's 10 go to C1 instead
        reverse(env.repo, c, WS, "E1", "x", env.q, NOW)
    assert env.yes(move) == CHANGED


# --- I1 / R43: a possible duplicate needs an explicit "Es otro" ---------------------------
def test_possible_duplicate_executes_only_on_an_explicit_es_otro(tmp_path):
    env = Env(tmp_path)
    args = (DELEG, "Familiar A", "50", "USD", "CASH")
    env.yes(env.svc.propose_receipt(*args))
    dup = env.svc.propose_receipt(*args)
    assert dup["status"] == "possible_duplicate"
    for word in ("yes", "sí", "ok", "confirmar", "1", "2"):
        assert env.svc.resolve(DELEG, dup["code"], word) == {
            "ok": False, "error": "unknown_choice", "expected": ["other", "same"]}
    assert count_rows(env.base, "receipt") == 1 and env.item(dup["code"]).resolved_at is None
    assert env.svc.resolve(DELEG, dup["code"], "Es otro")["receipt_ref"] == "R2"
    again = env.svc.propose_receipt(*args)
    assert env.svc.resolve(DELEG, again["code"], "es el mismo")["status"] == "not_recorded"
    normal = env.svc.propose_receipt(DELEG, "Familiar A", "60", "USD", "CASH")
    for word in ("other", "Es otro", "same"):
        assert env.svc.resolve(DELEG, normal["code"], word)["expected"] == [
            "yes", "correct", "cancel"]
    assert count_rows(env.base, "receipt") == 2


# --- I2 / R43: the VES reference at proposal (open CONFIRMs) and at "yes" ---------------------
def test_ves_reference_is_checked_against_open_confirms_and_again_at_yes(tmp_path):
    env = Env(tmp_path)
    p1 = env.svc.propose_exchange(DELEG, "300", E1, EVIDENCE)
    lines = [dict(x) for x in E1]
    lines[0]["usd"] = "110"  # the owner restates one line; the agent proposes again
    p2 = env.svc.propose_exchange(DELEG, "290", lines, EVIDENCE)
    assert (p2["status"], p2["echo"]["duplicate_of"], p2["options"]) == (
        "possible_duplicate", "P1", ["other", "same"])
    assert env.yes(p2, "other")["exchange_ref"] == "C1"
    before = env.facts()
    assert env.yes(p1) == {"ok": False, "error": "possible_duplicate", "duplicate_of": "C1"}
    assert env.facts() == before and env.item(p1["code"]).resolved_at is None
    assert env.svc.resolve(DELEG, p1["code"], "cancel")["status"] == "cancelled"
    assert count_rows(env.base, "exchange") == 1


# --- I3 / R44: private choices are stable tokens ------------------------------------------
def test_private_choices_are_stable_tokens_and_numbers_after_a_refresh_are_refused(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c, [LineInput("a", 2000), LineInput("b", 3000, "USD")])
        mv = env.move(c, "in1", 7000, currency="USD", acc="acc-usd", iban=PAYER_IBAN)
        item = ask_explain_incoming(env.repo, c, WS, mv, env.q)
    [shown] = env.svc.pending(DELEG, for_delivery=True)["items"]
    tokens = {o["label"]: o["choice"] for o in shown["options"]}
    assert TOKEN.fullmatch(tokens["Familiar A"]) and TOKEN.fullmatch(tokens["Familiar B"])
    assert env.svc.pending(DELEG)["items"][0]["options"] == shown["options"]
    with env.repo.tx() as c:  # Familiar A pays cash; the refreshed question drops A
        cash(env, c, "a", 2000)
        ask_explain_incoming(env.repo, c, WS, mv, env.q)
    assert env.svc.resolve(DELEG, item.code, "1") == {
        "ok": False, "error": "unknown_choice", "reason": "options_changed",
        "expected": [tokens["Familiar B"], "OTHER", "NOT_EXCHANGE", "PARTNER"]}
    now = env.svc.pending(DELEG)["items"][0]  # the owner is shown the new options
    assert [o["label"] for o in now["options"]] == [
        "Familiar B", "OTHER", "NOT_EXCHANGE", "Socio"]
    assert now["options"][0]["choice"] == tokens["Familiar B"]  # same value, same token
    assert env.svc.resolve(DELEG, item.code, tokens["Familiar A"])["error"] == "unknown_choice"
    assert count_rows(env.base, "receipt") == 1
    out = env.svc.resolve(DELEG, item.code, tokens["Familiar B"].lower())
    assert (out["status"], out["receipt_ref"]) == ("recorded", "R2")
    assert raw_execute(env.base, "SELECT payer_id FROM receipt ORDER BY number") == [
        ("a",), ("b",)]


# --- I4 / R45: "not an exchange" on a partner payment can be undone ----------------------------
def test_link_funding_answered_not_exchange_can_be_undone(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        env.exchange(c)
        assert try_link(env.repo, c, WS, env.move(c, "m1", -27600), env.q, NOW) == "AMBIGUOUS"
        item = env.repo.pending_by_dedupe(c, WS, "LINK_FUNDING:m1")
    assert env.svc.resolve(DELEG, item.code, "NOT_EXCHANGE")["status"] == "not_exchange"
    out = env.svc.propose_reverse(DELEG, item.code, "me equivoqué")
    assert (out["status"], out["echo"]["what"], out["echo"]["movement"]["amount"]) == (
        "confirmation_required", "answer", "-276.00")
    done = env.yes(out)
    assert (done["status"], done["ref"], done["funding_ref"]) == ("reopened", item.code, None)
    asked = env.item(done["question"])
    assert asked.kind is PendingKind.LINK_FUNDING and asked.resolved_at is None
    assert asked.code != item.code
    with env.repo.read() as c:
        assert env.repo.movement_role(c, "m1") is None

    env.svc.resolve(DELEG, asked.code, "NOT_EXCHANGE")  # again: the ignored list offers the undo
    [row] = env.svc.explain(DELEG, "ignored")["movements"]
    assert (row["date"], row["amount"], row["currency"]) == ("2026-11-14", "-276.00", "EUR")
    again = env.yes(env.svc.propose_reverse(DELEG, row["undo_ref"], "es un cambio"))
    assert (again["status"], again["rules_revoked"]) == ("reopened", 0)
    assert env.item(again["question"]).kind is PendingKind.LINK_FUNDING
    assert env.svc.explain(DELEG, "ignored")["movements"] == []

    assert env.svc.resolve(DELEG, again["question"], "C1")["status"] == "linked"
    assert env.svc.propose_reverse(DELEG, again["question"], "x") == {
        "ok": False, "error": "already_linked"}  # undo it through F1


# --- R46 minor items -------------------------------------------------------------------
def test_an_open_confirm_is_returned_across_midnight(tmp_path):  # m1
    env = Env(tmp_path)
    env.now = datetime(2026, 11, 20, 23, 59, tzinfo=timezone.utc)
    args = (DELEG, "Familiar A", "50", "USD", "CASH")
    first = env.svc.propose_receipt(*args)
    env.now = datetime(2026, 11, 21, 0, 1, tzinfo=timezone.utc)  # the agent retries
    assert env.svc.propose_receipt(*args) == first
    assert env.yes(first)["status"] == "recorded"
    assert raw_execute(env.base, "SELECT received_on FROM receipt") == [("2026-11-20",)]


def test_amounts_above_the_cap_are_validation_errors(tmp_path):  # m2
    env = Env(tmp_path)
    huge = env.svc.propose_receipt(DELEG, "Familiar A", "99999999999999999999", "USD", "CASH")
    assert (huge["error"], huge["field"], huge["detail"]) == (
        "validation_error", "amount", {"max": "10000000000.00"})
    assert env.svc.propose_receipt(DELEG, "Familiar A", "10000000000.01", "USD", "CASH")[
        "field"] == "amount"
    assert env.svc.propose_receipt(DELEG, "Familiar A", "10000000000.00", "USD", "CASH")["ok"]
    assert env.svc.propose_exchange(DELEG, "300", [
        {"payer": "Familiar A", "usd": "99999999999999"}])["field"] == "lines[0].usd"
    assert env.svc.propose_opening(DELEG, "Familiar A", "-99999999999999", "USD",
                                   "APPROXIMATE", "n")["field"] == "amount"
    assert env.svc.mark_held_cash(DELEG, "Familiar A", "99999999999999", "USD")[
        "field"] == "amount"


def test_classified_or_vanished_answers_are_stale(tmp_path):  # m3
    env = Env(tmp_path)
    with env.repo.tx() as c:
        c1 = env.exchange(c)
        env.move(c, "m1", -27600)
        prev = env.q.add(c, WS, PendingKind.PREVIOUS_UNPAID, ["M:m1", "NOT_YET"], {
            "exchange_ref": "C1", "delivered_on": "2026-11-13", "usd": "300.00",
            "after_ref": "C2", "labels": {"M:m1": "14/11 · 276.00 · X"}},
            f"PREVIOUS_UNPAID:{c1.id}")
        env.repo.insert_movement_role(c, WS, "m1", MovementRoleKind.NOT_EXCHANGE)
        env.move(c, "m2", -27500, day=D15)
    env.svc.pending(DELEG)  # the owner is shown the question
    out = env.svc.resolve(DELEG, prev.code, "1")  # m1 was classified meanwhile; C1 still open
    assert out["status"] == "asked_again" and out["code"] != prev.code
    assert env.item(prev.code).resolution == "stale"
    fresh = env.item(out["code"])
    assert (fresh.kind, fresh.payload["exchange_ref"]) == (PendingKind.PREVIOUS_UNPAID, "C1")
    assert "M:m1" not in fresh.options and "M:m2" in fresh.options

    with env.repo.tx() as c:  # ADD_TO an exchange whose funding was reversed meanwhile
        assert try_link(env.repo, c, WS, env.move(c, "m3", -27600), env.q, NOW) == "LINKED"
        env.exchange(c, day=D14)
        env.exchange(c, day=D14)
        assert try_link(env.repo, c, WS, env.move(c, "m4", -27600, day=D15), env.q,
                        NOW) == "AMBIGUOUS"
        link = env.repo.pending_by_dedupe(c, WS, "LINK_FUNDING:m4")
        assert "ADD_TO:C1" in link.options
        reverse(env.repo, c, WS, "F1", "x", env.q, NOW)
    out = env.svc.resolve(DELEG, link.code, "ADD_TO:C1")
    assert out["status"] == "asked_again" and env.item(link.code).resolution == "stale"
    assert env.item(out["code"]).kind is PendingKind.LINK_FUNDING

    with env.repo.tx() as c:  # an incoming payment classified before the answer
        mv = env.move(c, "in1", 5000, currency="USD", acc="acc-usd", iban=None, name="")
        explain = ask_explain_incoming(env.repo, c, WS, mv, env.q)
        env.repo.insert_movement_role(c, WS, "in1", MovementRoleKind.NOT_EXCHANGE)
    assert env.svc.resolve(DELEG, explain.code, "NOT_EXCHANGE") == {
        "ok": True, "status": "already_settled"}
    assert env.item(explain.code).resolution == "stale"
    assert count_rows(env.base, "intervention_log") == 0


def test_review_opening_confirms_only_what_it_showed_and_closes_once_confirmed(tmp_path):  # m4
    env = Env(tmp_path)
    with env.repo.tx() as c:
        record_opening(env.repo, c, WS, "a", "USD", 3000, Opening.APPROXIMATE, "n", NOW,
                       queue=env.q)  # E1
        record_opening(env.repo, c, WS, "b", "EUR", 2000, Opening.APPROXIMATE, "n", NOW,
                       queue=env.q)  # E2
        review = {cp: env.q.add(c, WS, PendingKind.REVIEW_OPENING, ["CONFIRM", "LATER"], {
            "counterparty": label, "openings": [
                {"entry_ref": ref, "currency": cur, "amount": amount}]},
            f"REVIEW_OPENING:{cp}:2026-W47")
            for cp, label, ref, cur, amount in (("a", "Familiar A", "E1", "USD", "30.00"),
                                                ("b", "Familiar B", "E2", "EUR", "20.00"))}
    # the owner's new opening for A closes A's question at once: it showed E1 (R64)
    env.yes(env.svc.propose_opening(DELEG, "Familiar A", "45", "USD", "APPROXIMATE", "n2"))
    before = env.facts()
    assert env.svc.resolve(DELEG, review["a"].code, "CONFIRM") == {
        "ok": False, "error": "already_resolved", "resolution": "auto:settled"}
    assert env.facts() == before and env.item(review["b"].code).resolved_at is None
    env.yes(env.svc.propose_opening(DELEG, "Familiar B", "20", "EUR", "CONFIRMED", "extracto"))
    assert env.item(review["b"].code).resolution == "auto:settled"


def test_label_is_unique_even_when_it_is_not_an_alias(tmp_path):  # m6
    env = Env(tmp_path)
    raw_execute(env.base, "DELETE FROM counterparty_alias WHERE alias='familiar a'")
    out = env.svc.propose_counterparty(DELEG, "FAMILIAR  Á", "PERSON", ["otra"])
    assert (out["error"], out["field"]) == ("validation_error", "aliases")


def test_dismissing_a_delivered_notice_is_idempotent(tmp_path):  # m7
    env = Env(tmp_path)
    with env.repo.tx() as c:
        notice = env.q.notice(c, WS, "funding_closed:F9", {"funding_ref": "F9"})
    env.svc.pending(DELEG, for_delivery=True)
    for _ in range(2):
        assert env.svc.resolve(DELEG, notice.code, "ok") == {
            "ok": True, "status": "dismissed", "code": notice.code}
    assert env.item(notice.code).resolution == "delivered"


def test_reallocation_echo_shows_the_remaining_credit(tmp_path):  # m8
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c, [LineInput("a", 12000)])
        cash(env, c, "a", 12000)
    out = env.svc.propose_reallocate(DELEG, "R1", [{"exchange": "C1", "amount": "20"}])
    assert (out["echo"]["after"], out["echo"]["credit"]) == (
        [{"item": "C1", "amount": "20.00"}], "100.00")


def test_echoes_show_a_fund_opening_as_held_and_name_the_rate(tmp_path):  # m9
    env = Env(tmp_path)
    op = env.svc.propose_opening(DELEG, "Fondo F", "500", "USD", "APPROXIMATE", "según el dueño")
    assert op["echo"]["held"] == "500.00" and "amount" not in op["echo"]
    assert env.yes(op)["entry_ref"] == "E1"
    undo = env.svc.propose_reverse(DELEG, "E1", "x")
    assert undo["echo"]["held"] == "500.00" and "amount" not in undo["echo"]
    with env.repo.tx() as c:
        env.exchange(c)
        assert try_link(env.repo, c, WS, env.move(c, "m1", -27600), env.q, NOW) == "LINKED"
    funding = env.svc.propose_reverse(DELEG, "F1", "x")
    assert funding["echo"]["eur_per_usd"] == "0.9200" and "rate" not in funding["echo"]


def test_future_dates_are_refused_beyond_the_owners_local_today(tmp_path):  # m10, R48
    env = Env(tmp_path)
    env.now = datetime(2026, 11, 20, 23, 30, tzinfo=timezone.utc)  # already the 21st in Europe
    tomorrow, later = "2026-11-21", "2026-11-22"
    assert env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH", tomorrow)["ok"]
    assert env.svc.propose_exchange(DELEG, "300", E1, None, tomorrow)["ok"]
    assert env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH", later) == {
        "ok": False, "error": "validation_error", "field": "received_on",
        "detail": {"reason": "future"}}
    assert env.svc.propose_exchange(DELEG, "300", E1, None, later)["field"] == "delivered_on"
    assert env.svc.propose_exchange(DELEG, "300", E1, {**EVIDENCE, "date": later})[
        "field"] == "evidence.date"
    assert count_rows(env.base, "pending_item") == 2


def test_an_explain_answer_can_skip_the_payer_rule(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        mv = env.move(c, "in1", 12000, currency="USD", acc="acc-usd", iban=PAYER_IBAN)
        item = ask_explain_incoming(env.repo, c, WS, mv, env.q)
    assert env.svc.resolve(DELEG, item.code, "Familiar A", {"remember": "no"})[
        "field"] == "details"
    out = env.svc.resolve(DELEG, item.code, "Familiar A", {"remember": False})
    assert (out["status"], out["receipt_ref"], out["rule"]) == ("recorded", "R1", False)
    with env.repo.read() as c:
        assert env.repo.rule_for(c, WS, env.repo.hash_key(PAYER_IBAN)) is None


def test_client_key_makes_a_proposal_idempotent(tmp_path):
    env = Env(tmp_path)
    first = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH", client_key="k-1")
    assert env.svc.propose_receipt(DELEG, " familiar a ", "50.00", "usd", "cash",
                                   client_key="k-1") == first
    assert env.svc.propose_receipt(DELEG, "Familiar A", "60", "USD", "CASH",
                                   client_key="k-1") == {"ok": False,
                                                         "error": "idempotency_conflict"}
    env.yes(first)
    assert env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH",
                                   client_key="k-1") == first
    other = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH", client_key="k-2")
    assert other["status"] == "possible_duplicate"
    assert env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH",
                                   client_key=" ")["field"] == "client_key"
    held = env.svc.mark_held_cash(DELEG, "Familiar A", "10", "USD", client_key="h-1")
    assert env.svc.mark_held_cash(DELEG, "Familiar A", "10", "USD", client_key="h-1") == held
    assert env.svc.mark_held_cash(DELEG, "Familiar A", "20", "USD", client_key="h-1") == {
        "ok": False, "error": "idempotency_conflict"}
    assert count_rows(env.base, "held_cash_statement") == 1 and count_rows(env.base, "receipt") == 1


def test_an_unexpected_error_is_a_generic_refusal(tmp_path, monkeypatch, caplog):
    env = Env(tmp_path)
    caplog.set_level(logging.DEBUG, logger="finance")
    out = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH")

    def broken(ctx, conn, payload):
        raise RuntimeError("Familiar A 50.00")

    monkeypatch.setitem(commands.EFFECTS, "receipt", broken)
    assert env.yes(out) == {"ok": False, "error": "internal_error"}
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in text and "Familiar" not in text and "50.00" not in text
    assert env.item(out["code"]).resolved_at is None and count_rows(env.base, "receipt") == 0


# --- R49 / R44 residual: every read that shows private options binds them -----------------
def _explain_question(env):
    with env.repo.tx() as c:
        env.exchange(c, [LineInput("a", 2000), LineInput("b", 3000, "USD")])
        mv = env.move(c, "in1", 7000, currency="USD", acc="acc-usd", iban=PAYER_IBAN)
        return ask_explain_incoming(env.repo, c, WS, mv, env.q), mv


def _refresh_without_a(env, mv):
    with env.repo.tx() as c:  # Familiar A pays cash; the refreshed question drops A
        cash(env, c, "a", 2000)
        ask_explain_incoming(env.repo, c, WS, mv, env.q)


def _payers(env):
    return raw_execute(env.base, "SELECT payer_id FROM receipt ORDER BY number")


def test_a_number_on_private_options_never_shown_is_refused_but_tokens_work(tmp_path):
    env = Env(tmp_path)
    item, _ = _explain_question(env)
    out = env.svc.resolve(DELEG, item.code, "1")
    assert (out["error"], out["reason"]) == ("unknown_choice", "options_changed")
    assert all(TOKEN.fullmatch(t) for t in out["expected"][:2])
    assert count_rows(env.base, "receipt") == 0
    token = out["expected"][1]  # Familiar B
    assert env.svc.resolve(DELEG, item.code, token)["status"] == "recorded"
    assert _payers(env) == [("b",)]


def test_pending_binds_the_options_it_shows(tmp_path):
    env = Env(tmp_path)
    item, mv = _explain_question(env)
    [shown] = [i for i in env.svc.pending(DELEG)["items"] if i["code"] == item.code]
    assert shown["options"][0]["label"] == "Familiar A"
    _refresh_without_a(env, mv)
    out = env.svc.resolve(DELEG, item.code, "1")
    assert (out["error"], out["reason"]) == ("unknown_choice", "options_changed")
    assert count_rows(env.base, "receipt") == 1  # only the cash receipt: no wrong payer
    [now] = [i for i in env.svc.pending(DELEG)["items"] if i["code"] == item.code]
    assert now["options"][0]["label"] == "Familiar B"
    assert env.svc.resolve(DELEG, item.code, "1")["status"] == "recorded"
    assert _payers(env) == [("a",), ("b",)]


def test_explain_binds_the_options_it_shows(tmp_path):
    env = Env(tmp_path)
    item, mv = _explain_question(env)
    shown = env.svc.explain(DELEG, item.code)["pending"]
    assert shown["options"][0]["label"] == "Familiar A"
    _refresh_without_a(env, mv)
    assert env.svc.resolve(DELEG, item.code, "1")["reason"] == "options_changed"
    again = env.svc.explain(DELEG, item.code.lower())["pending"]
    assert again["options"][0]["label"] == "Familiar B"
    assert env.svc.resolve(DELEG, item.code, "1")["status"] == "recorded"
    assert _payers(env) == [("a",), ("b",)]


# --- R49: a REVIEW_OPENING refused "changed" is closed so the matcher asks again --------------
def test_review_opening_refused_changed_is_resolved_stale_and_asked_again(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        record_opening(env.repo, c, WS, "a", "USD", 3000, Opening.APPROXIMATE, "n", NOW,
                       queue=env.q)  # E1
        Matcher(env.repo, env.q, lambda: env.now, False)._openings(c, WS, env.now, {"asked": 0})
        [item] = [i for i in env.repo.pending_open(c, WS)
                  if i.dedupe_key.startswith("REVIEW_OPENING:a:")]
        # a write that does not close it (an owner command would, R64): refused "changed"
        record_opening(env.repo, c, WS, "a", "USD", 4500, Opening.APPROXIMATE, "n2", NOW,
                       queue=env.q)
    out = env.svc.resolve(DELEG, item.code, "CONFIRM")
    assert out == {"ok": False, "error": "validation_error", "field": "target",
                   "detail": {"reason": "changed", "question": "stale"}}
    stale = env.item(item.code)
    assert stale.resolution == "stale" and stale.resolved_at is not None
    assert env.svc.resolve(DELEG, item.code, "CONFIRM")["error"] == "already_resolved"
    env.now = env.now + timedelta(days=8)
    counts = {"asked": 0}
    with env.repo.tx() as c:
        Matcher(env.repo, env.q, lambda: env.now, False)._openings(c, WS, env.now, counts)
        [new] = [i for i in env.repo.pending_open(c, WS)
                 if i.dedupe_key.startswith("REVIEW_OPENING:a:")]
    assert counts == {"asked": 1} and new.code != item.code
    assert new.payload["openings"][0]["amount"] == "45.00"
    assert env.svc.resolve(DELEG, new.code, "CONFIRM")["status"] == "confirmed"


# --- R49: the open CONFIRM is matched only while its defaulted date is current ---------------
def test_an_old_open_confirm_with_a_defaulted_date_is_not_returned_days_later(tmp_path):
    env = Env(tmp_path)
    args = (DELEG, "Familiar A", "50", "USD", "CASH")
    old = env.svc.propose_receipt(*args)
    env.now = env.now + timedelta(days=5)
    new = env.svc.propose_receipt(*args)
    assert new["code"] != old["code"]
    assert new["echo"]["received_on"] == env.now.date().isoformat()
    assert env.svc.propose_receipt(*args) == new  # the same day: the new one again
    gone = env.item(old["code"])  # R63: replaced, so only one of them can record
    assert (gone.resolution, gone.resolved_at is not None) == ("superseded", True)
    assert count_rows(env.base, "intervention_log") == 0
    assert env.yes(new)["status"] == "recorded"
    assert raw_execute(env.base, "SELECT received_on FROM receipt") == [
        (env.now.date().isoformat(),)]
