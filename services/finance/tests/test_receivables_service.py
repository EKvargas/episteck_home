"""ReceivablesService: authorization, two-phase commands, duplicates and owner answers.

Synthetic data only ("Familiar A", "Fondo F", "Socio").
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import domain
from app.authz import Requirement
from app.config import Settings
from app.deps import build_receivables_service
from app.receivables import commands
from app.receivables.corrections import record_opening, reverse
from app.receivables.explain import ask_explain_incoming
from app.receivables.funding import create_funding, try_link
from app.receivables.ledger import Evidence, LineInput, record_exchange
from app.receivables.model import (
    OWNER, Counterparty, CounterpartyKind, EntryKind, MovementRoleKind, Opening, PendingKind,
    ReceiptKind, Verification,
)
from app.receivables.pending import PendingQueue
from app.receivables.receipts import record_receipt
from app.receivables.service import API_CALLER, ReceivablesService
from app.service import AccessDenied, FeatureOff, PolicyUnavailable, SessionInvalid
from app.store.receivables_repo import IGNORE, ReceivablesRepository
from app.store.receivables_schema import FACT_TABLES
from tests.support import (
    FakeAuthorizer, count_rows, make_account, make_repo, raw_execute, seed_connection,
    seed_workspace,
)

WS = "ws-1"
DELEG = "deleg-1"
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
D13, D14, D15 = (date(2026, 11, d) for d in (13, 14, 15))
ECB = Decimal("1.0870")  # USD per EUR, published for D13
PARTNER_IBAN = "XX00 SYNTHETIC PARTNER 0001"
PAYER_IBAN = "XX00 SYNTHETIC PAYER 0002"
EMPLOYER_IBAN = "XX00 SYNTHETIC EMPLOYER 0003"
E1 = [{"payer": "Familiar A", "usd": "120"}, {"payer": "Familiar B", "usd": "80.00"},
      {"payer": "owner", "usd": "40"}, {"payer": "Fondo F", "usd": "60"}]
EVIDENCE = {"ves_amount": "54321.00", "ves_reference": "REF-SYNTH-0001", "date": "2026-11-13"}
HEX = re.compile(r"[0-9a-f]{32}")
HOME_VARS = ("HOME_CONTROL_PLANE_URL", "HOME_API_KEY", "HOME_API_SECRET",
             "HOME_API_TIMEOUT_SECONDS")


class Env:
    def __init__(self, tmp_path, authorizer=None, **kw):
        self.base = base = make_repo(tmp_path)
        seed_workspace(base)
        seed_connection(base)
        base.add_account(make_account(aid="acc-eur", currency="EUR", institution="Banco Uno"))
        base.add_account(make_account(aid="acc-usd", currency="USD", institution="Bank Two"))
        base.store_fx_rates(D13, {"USD": ECB})
        self.repo = repo = ReceivablesRepository(base)
        self.now = NOW
        self.q = PendingQueue(repo, lambda: self.now)
        self.authz = authorizer or FakeAuthorizer()
        self.svc = ReceivablesService(base, self.authz, WS, clock=lambda: self.now, **kw)
        with repo.tx() as c:
            for cid, label, kind, extra in (
                    ("p", "Socio", CounterpartyKind.EXCHANGE_PARTNER, {}),
                    ("a", "Familiar A", CounterpartyKind.PERSON, {"pay_currency": "USD"}),
                    ("b", "Familiar B", CounterpartyKind.PERSON, {"pay_currency": "EUR"}),
                    ("f", "Fondo F", CounterpartyKind.FUND, {"opening": Opening.UNKNOWN})):
                repo.insert_counterparty(
                    c, Counterparty(cid, WS, kind, label, "ACTIVE", **extra), [label])
            repo.add_partner_identifier(c, WS, repo.hash_key(PARTNER_IBAN), "p")

    def facts(self) -> dict[str, int]:
        return {t: count_rows(self.base, t) for t in (*FACT_TABLES, "command_log")}

    def yes(self, out, choice="yes"):
        assert out["ok"], out
        return self.svc.resolve(DELEG, out["code"], choice)

    def item(self, code):
        with self.repo.read() as c:
            return self.repo.pending_by_code(c, WS, code)

    def exchange(self, c, lines=None, day=D13):
        lines = lines or [LineInput("a", 12000), LineInput("b", 8000), LineInput(OWNER, 4000),
                          LineInput("f", 6000)]
        return record_exchange(self.repo, c, WS, partner_id="p",
                               total_usd_minor=sum(ln.usd_minor for ln in lines), lines=lines,
                               evidence=Evidence(None, None, day), now=self.now)

    def move(self, c, mid, amount, day=D14, currency="EUR", acc="acc-eur", iban=PARTNER_IBAN,
             name="X"):
        m = domain.Movement(mid, WS, acc, f"tx-{mid}", f"fp-{mid}", domain.MovementStatus.BOOKED,
                            day, day, amount, currency, name,
                            self.repo.hash_key(iban) if iban else None, "transfer", None)
        self.base.insert_movement_in_tx(c, m)
        return m


def no_ids(out) -> bool:
    return not HEX.search(json.dumps(out))


# --- authorization ----------------------------------------------------------------------
def test_reads_authorize_view_self_once_and_writes_create_self_once(tmp_path):
    env = Env(tmp_path)
    svc = env.svc
    svc.receivables(DELEG)
    out = svc.propose_receipt(DELEG, "Familiar A", "50.00", "USD", "CASH")
    assert env.authz.calls == [(DELEG, (Requirement("SELF", "VIEW"),)),
                               (DELEG, (Requirement("SELF", "CREATE"),))]
    reads = [lambda: svc.receivables(DELEG, "Familiar A"), lambda: svc.exchanges(DELEG),
             lambda: svc.pending(DELEG), lambda: svc.pending(DELEG, for_delivery=True),
             lambda: svc.explain(DELEG, "C1")]
    writes = [lambda: svc.propose_exchange(DELEG, "300", E1, EVIDENCE),
              lambda: svc.propose_correction(DELEG, "C1", E1, None, "x"),
              lambda: svc.propose_forgive(DELEG, "Familiar A", None, "x"),
              lambda: svc.propose_opening(DELEG, "Familiar A", "10", "USD", "APPROXIMATE", "n"),
              lambda: svc.propose_counterparty(DELEG, "Familiar Z", "PERSON", []),
              lambda: svc.propose_reverse(DELEG, "R1", "x"),
              lambda: svc.propose_reallocate(DELEG, "R1", []),
              lambda: svc.mark_held_cash(DELEG, "Familiar A", "10", "USD"),
              lambda: svc.resolve(DELEG, out["code"], "cancel")]
    for call, action in [(r, "VIEW") for r in reads] + [(w, "CREATE") for w in writes]:
        before = len(env.authz.calls)
        call()
        assert env.authz.calls[before:] == [(DELEG, (Requirement("SELF", action),))]


def test_non_owner_member_is_denied(tmp_path):
    env = Env(tmp_path)
    env.base.add_member(WS, "PSN-2", "MEMBER")
    out = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH")
    before = env.facts()
    for authz in (FakeAuthorizer(actor="PSN-2"), FakeAuthorizer(actor="PSN-9"),
                  FakeAuthorizer(allow={"SELF": False})):
        svc = ReceivablesService(env.base, authz, WS, clock=lambda: NOW)
        for call in (lambda: svc.receivables(DELEG),
                     lambda: svc.propose_receipt(DELEG, "Familiar A", "60", "USD", "CASH"),
                     lambda: svc.resolve(DELEG, out["code"], "yes"),
                     lambda: svc.mark_held_cash(DELEG, "Familiar A", "10", "USD")):
            with pytest.raises(AccessDenied):
                call()
    assert env.facts() == before and count_rows(env.base, "pending_item") == 1
    assert env.item(out["code"]).resolved_at is None


def test_home_unavailable_writes_nothing(tmp_path):
    env = Env(tmp_path)
    out = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH")
    before = (env.facts(), count_rows(env.base, "pending_item"))
    for mode, error in (("unavailable", PolicyUnavailable), ("raise", PolicyUnavailable),
                        ("malformed", PolicyUnavailable), ("session_invalid", SessionInvalid)):
        env.authz.mode = mode
        for call in (lambda: env.svc.propose_exchange(DELEG, "300", E1, EVIDENCE),
                     lambda: env.svc.resolve(DELEG, out["code"], "yes"),
                     lambda: env.svc.mark_held_cash(DELEG, "Familiar A", "10", "USD"),
                     lambda: env.svc.pending(DELEG, for_delivery=True)):
            with pytest.raises(error):
                call()
    assert (env.facts(), count_rows(env.base, "pending_item")) == before
    assert env.item(out["code"]).resolved_at is None
    env.authz.mode = "answer"
    calls = len(env.authz.calls)
    with pytest.raises(SessionInvalid):
        env.svc.resolve(None, out["code"], "yes")
    assert len(env.authz.calls) == calls  # no delegation: Home is not even asked


def test_e15_feature_off_for_paused_workspace(tmp_path):
    env = Env(tmp_path)
    out = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH")
    raw_execute(env.base, "UPDATE workspace SET status='PAUSED'")
    svc = env.svc
    for call in (lambda: svc.receivables(DELEG), lambda: svc.exchanges(DELEG),
                 lambda: svc.pending(DELEG), lambda: svc.explain(DELEG, "C1"),
                 lambda: svc.propose_receipt(DELEG, "Familiar A", "60", "USD", "CASH"),
                 lambda: svc.resolve(DELEG, out["code"], "yes"),
                 lambda: svc.mark_held_cash(DELEG, "Familiar A", "10", "USD")):
        with pytest.raises(FeatureOff):
            call()
    denied = ReceivablesService(env.base, FakeAuthorizer(allow={"SELF": False}), WS,
                                clock=lambda: NOW)
    with pytest.raises(AccessDenied):  # an unauthorised caller learns nothing about status
        denied.receivables(DELEG)
    assert env.item(out["code"]).resolved_at is None and count_rows(env.base, "receipt") == 0


def test_build_receivables_service_fails_closed_without_home(tmp_path, monkeypatch):
    for name in HOME_VARS:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(db_path=str(tmp_path / "f.sqlite"), workspace_id=WS, pepper=b"p" * 16)
    svc = build_receivables_service(settings)
    assert isinstance(svc, ReceivablesService)
    with pytest.raises(PolicyUnavailable):
        svc.receivables(DELEG)
    assert build_receivables_service(settings, caller=API_CALLER)._caller == API_CALLER


# --- two phases, idempotency, duplicates -------------------------------------------------
def test_proposal_writes_nothing_until_yes(tmp_path):
    env = Env(tmp_path)
    before = env.facts()
    out = env.svc.propose_exchange(DELEG, "300.00", E1, EVIDENCE)
    assert {k: out[k] for k in ("ok", "status", "code", "high_value", "options")} == {
        "ok": True, "status": "confirmation_required", "code": "P1", "high_value": False,
        "options": ["yes", "correct", "cancel"]}
    assert out["echo"] == {
        "type": "exchange", "total_usd": "300.00", "delivered_on": "2026-11-13",
        "partner": "Socio", "ves": "54321.00", "lines": [
            {"payer": "Familiar A", "usd": "120.00", "debt_currency": "USD", "eur": None,
             "eur_pending": False, "note": None},
            {"payer": "Familiar B", "usd": "80.00", "debt_currency": "EUR", "eur": None,
             "eur_pending": True, "note": None},
            {"payer": "owner", "usd": "40.00", "debt_currency": None, "eur": None,
             "eur_pending": False, "note": None},
            {"payer": "Fondo F", "usd": "60.00", "debt_currency": "USD", "eur": None,
             "eur_pending": False, "note": None}]}
    text = json.dumps(out)
    assert "REF-SYNTH" not in text and no_ids(out) and not re.search(r"[0-9a-f]{40}", text)
    assert env.facts() == before and count_rows(env.base, "pending_item") == 1
    assert env.yes(out) == {"ok": True, "status": "recorded", "exchange_ref": "C1",
                            "delivered_on": "2026-11-13", "usd": "300.00"}
    assert count_rows(env.base, "exchange") == 1 and count_rows(env.base, "command_log") == 1
    with env.repo.read() as c:
        assert [(e.kind, e.amount_minor) for e in env.repo.entries(c, WS, "a")] == [
            (EntryKind.CHARGE, 12000)]
        assert env.repo.exchange_by_ves_hash(c, WS, env.repo.hash_key("REF-SYNTH-0001"))
    assert env.item("P1").resolution == "yes"


def test_agent_retry_returns_same_confirm(tmp_path):
    env = Env(tmp_path)
    first = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH")
    again = env.svc.propose_receipt(DELEG, " familiar a ", "50.00", "usd", "cash")
    assert again == first and first["status"] == "confirmation_required"
    assert count_rows(env.base, "pending_item") == 1


def test_identical_command_after_completion_is_possible_duplicate_and_es_otro_records_it(
        tmp_path):
    env = Env(tmp_path)
    args = (DELEG, "Familiar A", "50", "USD", "CASH")
    first = env.svc.propose_receipt(*args)
    assert env.yes(first)["receipt_ref"] == "R1"
    again = env.svc.propose_receipt(*args)
    assert again["status"] == "possible_duplicate" and again["code"] != first["code"]
    assert again["options"] == ["other", "same"] and again["echo"]["duplicate_of"] == "R1"
    assert env.svc.propose_receipt(*args) == again  # a retry returns the open question
    assert env.svc.resolve(DELEG, again["code"], "Es otro")["receipt_ref"] == "R2"
    keys = [r[0] for r in raw_execute(env.base, "SELECT key FROM command_log ORDER BY rowid")]
    assert len(keys) == 2 and keys[1].startswith(keys[0] + ":")
    third = env.svc.propose_receipt(*args)
    assert third["status"] == "possible_duplicate"
    assert env.svc.resolve(DELEG, third["code"], "same") == {
        "ok": True, "status": "not_recorded", "code": third["code"]}
    assert count_rows(env.base, "receipt") == 2
    env.now = NOW + timedelta(days=1)  # the same words another day are a new command
    assert env.svc.propose_receipt(*args)["status"] == "confirmation_required"


def test_same_ves_reference_is_possible_duplicate(tmp_path):
    env = Env(tmp_path)
    env.yes(env.svc.propose_exchange(DELEG, "300", E1, EVIDENCE))
    other = env.svc.propose_exchange(DELEG, "100", [{"payer": "Familiar A", "usd": "100"}],
                                     {"ves_reference": " ref-synth-0001 ", "date": "2026-11-14"})
    assert other["status"] == "possible_duplicate" and other["echo"]["duplicate_of"] == "C1"
    assert env.yes(other, "other")["exchange_ref"] == "C2"


def test_non_plain_amount_is_a_validation_error(tmp_path):
    env = Env(tmp_path)
    before = (env.facts(), count_rows(env.base, "pending_item"))
    for bad in ("1.250,50", "$275", "275$", "12,5", "1e3", "", "0.001", 12.5):
        out = env.svc.propose_receipt(DELEG, "Familiar A", bad, "USD", "CASH")
        assert (out["ok"], out["error"], out["field"]) == (False, "validation_error", "amount")
    assert env.svc.propose_exchange(DELEG, "1.250,50", E1)["field"] == "total_usd"
    out = env.svc.propose_exchange(DELEG, "300", [{"payer": "Familiar A", "usd": "1.250,50"}])
    assert out["field"] == "lines[0].usd"
    assert env.svc.propose_receipt(DELEG, "Familiar A", "50", "VES", "CASH")["field"] == "currency"
    assert (env.facts(), count_rows(env.base, "pending_item")) == before


def test_ambiguous_alias_returns_candidates(tmp_path):
    env = Env(tmp_path)
    assert env.svc.propose_receipt(DELEG, "Familiar", "50", "USD", "CASH") == {
        "ok": False, "error": "clarification_needed", "field": "payer",
        "candidates": ["Familiar A", "Familiar B"]}
    nobody = env.svc.propose_receipt(DELEG, "Nadie", "50", "USD", "CASH")
    assert nobody["candidates"] == ["Familiar A", "Familiar B", "Fondo F"]
    assert env.svc.propose_receipt(DELEG, "Socio", "50", "USD", "CASH")["error"] == \
        "clarification_needed"  # the partner owes nothing
    out = env.svc.propose_exchange(DELEG, "300", [{"payer": "Familiar A", "usd": "200"},
                                                  {"payer": "familiar", "usd": "100"}])
    assert (out["field"], out["candidates"]) == ("lines[1].payer", ["Familiar A", "Familiar B"])
    assert env.svc.receivables(DELEG, "Familiar")["candidates"] == ["Familiar A", "Familiar B"]
    assert count_rows(env.base, "pending_item") == 0


def test_high_value_cash_and_bank_reversal_are_flagged(tmp_path):
    env = Env(tmp_path)

    def high(*args):
        return env.svc.propose_receipt(DELEG, *args)["high_value"]

    assert high("Familiar A", "499.99", "USD", "CASH") is False
    assert high("Familiar A", "500.00", "USD", "CASH") is True
    assert high("Familiar B", "460.00", "EUR", "CASH", "2026-11-14") is True  # 500.02 USD
    assert high("Familiar B", "459.00", "EUR", "CASH", "2026-11-14") is False  # 498.93 USD
    assert high("Familiar B", "10.00", "EUR", "CASH", "2026-11-12") is True  # no ECB rate yet
    with env.repo.tx() as c:
        env.exchange(c)
        assert try_link(env.repo, c, WS, env.move(c, "m1", -27600), env.q, NOW) == "LINKED"
        env.move(c, "in1", 12000, currency="USD", acc="acc-usd", iban=PAYER_IBAN)
        record_receipt(env.repo, c, WS, kind=ReceiptKind.BANK, payer_id="a", currency="USD",
                       amount_minor=12000, received_on=D14,
                       verification=Verification.BANK_POSTED, movement_id="in1", queue=env.q,
                       now=NOW)
        record_receipt(env.repo, c, WS, kind=ReceiptKind.CASH, payer_id="b", currency="EUR",
                       amount_minor=1000, received_on=D14,
                       verification=Verification.OWNER_CONFIRMED, queue=env.q, now=NOW)
        env.repo.insert_payer_rule(c, WS, env.repo.hash_key(PAYER_IBAN), "a")

    def reversal(ref):
        out = env.svc.propose_reverse(DELEG, ref, "error de registro")
        assert out["ok"], out
        return out

    assert reversal("F1")["high_value"] is True
    bank = reversal("R1")
    assert bank["high_value"] is True and bank["echo"]["rule"] is True
    assert reversal("R2")["high_value"] is False
    assert reversal("Familiar A rule")["high_value"] is True
    charge = env.svc.propose_reverse(DELEG, "E1", "x")  # a CHARGE goes with its exchange
    assert (charge["field"], charge["detail"]) == ("entry", {"kind": "CHARGE"})


def test_resolve_logs_intervention_and_audit_actor(tmp_path):
    env = Env(tmp_path)
    env.yes(env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH"))
    assert raw_execute(env.base, "SELECT command_type, human_actor, machine_caller, channel "
                                 "FROM command_log") == [("receipt", "PSN-1", "finance-mcp",
                                                          "telegram")]
    assert raw_execute(env.base, "SELECT kind FROM intervention_log") == [("CONFIRM",)]
    (tmp_path / "api").mkdir()
    api = Env(tmp_path / "api", caller=API_CALLER)
    api.yes(api.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH"))
    assert raw_execute(api.base, "SELECT machine_caller, channel FROM command_log") == [
        ("finance-api", "web")]


def test_e7_cash_in_kind_and_high_value(tmp_path):
    env = Env(tmp_path)
    small = env.svc.propose_receipt(DELEG, "Familiar A", "150", "USD", "CASH")
    big = env.svc.propose_receipt(DELEG, "Familiar A", "600", "USD", "CASH")
    assert (small["status"], small["high_value"]) == ("confirmation_required", False)
    assert (big["status"], big["high_value"]) == ("confirmation_required", True)
    assert big["echo"]["amount"] == "600.00" and big["echo"]["kind"] == "CASH"
    assert env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "IN_KIND")["field"] == \
        "description"
    assert env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "BANK")["field"] == "kind"
    gift = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "in_kind", None,
                                   "gift card")
    assert gift["echo"]["description"] == "gift card" and gift["high_value"] is False
    for out in (small, big, gift):
        assert env.yes(out)["status"] == "recorded"
    rows = raw_execute(env.base, "SELECT kind, amount_minor, verification, description "
                                 "FROM receipt ORDER BY number")
    assert rows == [("CASH", 15000, "OWNER_CONFIRMED", ""), ("CASH", 60000, "OWNER_CONFIRMED", ""),
                    ("IN_KIND", 5000, "OWNER_CONFIRMED", "gift card")]


def test_e14_effect_failure_leaves_no_partial_rows(tmp_path, monkeypatch):
    env = Env(tmp_path)
    out = env.svc.propose_exchange(DELEG, "300", E1, EVIDENCE)
    before = env.facts()
    real = commands.EFFECTS["exchange"]

    def broken(ctx, conn, payload):
        real(ctx, conn, payload)  # the exchange, its lines and charges are written ...
        raise RuntimeError("process killed")  # ... and then the command dies

    monkeypatch.setitem(commands.EFFECTS, "exchange", broken)
    assert env.svc.resolve(DELEG, out["code"], "yes") == {"ok": False, "error": "internal_error"}
    assert env.facts() == before  # no command_log row, no fact, no intervention
    assert env.item(out["code"]).resolved_at is None
    monkeypatch.setitem(commands.EFFECTS, "exchange", real)
    assert env.yes(out)["exchange_ref"] == "C1"


def test_resolve_is_idempotent_by_code_and_choice(tmp_path):
    env = Env(tmp_path)
    out = env.svc.propose_receipt(DELEG, "Familiar A", "50", "USD", "CASH")
    first = env.yes(out)
    assert env.yes(out) == first and env.svc.resolve(DELEG, out["code"], "1") == first
    assert [count_rows(env.base, t) for t in ("receipt", "command_log", "intervention_log")] \
        == [1, 1, 1]
    assert env.svc.resolve(DELEG, out["code"], "cancel") == {
        "ok": False, "error": "already_resolved", "resolution": "yes"}
    assert env.svc.resolve(DELEG, "P99", "yes") == {"ok": False, "error": "unknown_pending"}
    other = env.svc.propose_receipt(DELEG, "Familiar A", "60", "USD", "CASH")
    assert env.svc.resolve(DELEG, other["code"], "maybe") == {
        "ok": False, "error": "unknown_choice", "expected": ["yes", "correct", "cancel"]}
    assert env.svc.resolve(DELEG, other["code"], "Cancelar") == {
        "ok": True, "status": "cancelled", "code": other["code"]}
    fix = env.svc.propose_receipt(DELEG, "Familiar A", "70", "USD", "CASH")
    assert env.svc.resolve(DELEG, fix["code"], "corregir")["status"] == "needs_correction"
    assert count_rows(env.base, "receipt") == 1


# --- owner answers to the matcher's questions ---------------------------------------------
def test_pending_hides_ids_and_numbered_choices_resolve(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)  # Familiar A owes 120 USD, Fondo F was charged 60 USD
        mv = env.move(c, "in1", 12000, currency="USD", acc="acc-usd", iban=PAYER_IBAN,
                      name="FAMILIAR A SINTETICO")
        item = ask_explain_incoming(env.repo, c, WS, mv, env.q)
        notice = env.q.notice(c, WS, "fund_low:0123456789abcdef0123456789abcdef:E9",
                              {"counterparty": "Fondo F", "entry_ref": "E9"})
    proposal = env.svc.propose_receipt(DELEG, "Familiar B", "10", "EUR", "CASH", "2026-11-14")
    listing = env.svc.pending(DELEG)
    rows = {r["code"]: r for r in listing["items"]}
    assert (rows[notice.code]["notice"], rows[notice.code]["details"]) == (
        "fund_low", {"counterparty": "Fondo F", "entry_ref": "E9"})
    explain = rows[item.code]
    tokens = [o.pop("choice") for o in explain["options"][:2]]  # stable, opaque (R44)
    assert all(re.fullmatch(r"O[0-9a-f]{8}", t) for t in tokens) and tokens[0] != tokens[1]
    assert explain["options"] == [
        {"n": 1, "label": "Familiar A"}, {"n": 2, "label": "Fondo F"},
        {"n": 3, "choice": "OTHER", "label": "OTHER"},
        {"n": 4, "choice": "NOT_EXCHANGE", "label": "NOT_EXCHANGE"},
        {"n": 5, "choice": "PARTNER", "label": "Socio"}]
    assert explain["suggested"] == 1
    assert explain["details"] == {"booking_date": "2026-11-14", "currency": "USD",
                                  "amount": "120.00", "sender": "FAMILIAR A SINTETICO"}
    confirm = rows[proposal["code"]]
    assert (confirm["kind"], confirm["status"], confirm["echo"]) == (
        "CONFIRM", "confirmation_required", proposal["echo"])
    text = json.dumps(listing)
    assert "CP:" not in text and "movement_id" not in text and '"payer_id"' not in text
    assert "in1" not in text and no_ids(listing)
    out = env.svc.resolve(DELEG, item.code, "1")
    assert out == {"ok": True, "status": "recorded", "receipt_ref": "R1", "rule": True,
                   "code": item.code}
    with env.repo.read() as c:
        assert env.repo.rule_for(c, WS, env.repo.hash_key(PAYER_IBAN)) == "a"
    assert raw_execute(env.base, "SELECT kind FROM intervention_log") == [("EXPLAIN_INCOMING",)]
    assert env.svc.resolve(DELEG, item.code, "2")["error"] == "already_resolved"


def test_explain_other_needs_a_counterparty_then_records_it(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        mv = env.move(c, "in2", 5000, currency="USD", acc="acc-usd", iban=None, name="")
        item = ask_explain_incoming(env.repo, c, WS, mv, env.q)
    assert env.svc.resolve(DELEG, item.code, "OTHER") == {
        "ok": True, "status": "needs_counterparty", "code": item.code}
    assert env.item(item.code).resolved_at is None
    assert env.svc.resolve(DELEG, item.code, "OTHER", {"counterparty": "Familiar"})[
        "candidates"] == ["Familiar A", "Familiar B"]
    out = env.svc.resolve(DELEG, item.code, "OTHER", {"counterparty": "Familiar B"})
    assert (out["status"], out["receipt_ref"], out["rule"]) == ("recorded", "R1", False)
    assert env.item(item.code).resolved_at is not None


def test_answers_close_settled_questions_and_payloads_carry_delivery_dates(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        c1 = env.exchange(c)
        env.exchange(c)
        assert try_link(env.repo, c, WS, env.move(c, "m1", -27600), env.q, NOW) == "AMBIGUOUS"
        link = env.repo.pending_by_dedupe(c, WS, "LINK_FUNDING:m1")
        prev = env.q.add(c, WS, PendingKind.PREVIOUS_UNPAID, ["M:m1", "NOT_YET"], {
            "exchange_ref": "C1", "delivered_on": "2026-11-13", "usd": "300.00",
            "after_ref": "C2", "labels": {"M:m1": "14/11 · 276.00 · X"}},
            f"PREVIOUS_UNPAID:{c1.id}")
    assert link.payload["delivered_on"] == {"C1": "2026-11-13", "C2": "2026-11-13"}
    env.svc.pending(DELEG)  # shown to the owner: a number now means what it showed
    assert env.svc.resolve(DELEG, prev.code, "1") == {
        "ok": True, "status": "linked", "funding_ref": "F1", "code": prev.code}
    assert env.item(link.code).resolution == "auto:settled"
    assert raw_execute(env.base, "SELECT kind FROM intervention_log") == [("PREVIOUS_UNPAID",)]
    with env.repo.read() as c:
        notice = env.repo.pending_by_dedupe(c, WS, "INFO:funding_closed:F1",
                                            include_resolved=True)
    assert notice.payload["delivered_on"] == {"C1": "2026-11-13"}


def test_stale_link_answer_asks_again_or_reports_settled(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        c1, c2 = env.exchange(c), env.exchange(c)
        assert try_link(env.repo, c, WS, env.move(c, "m1", -27600), env.q, NOW) == "AMBIGUOUS"
        first = env.repo.pending_by_dedupe(c, WS, "LINK_FUNDING:m1")
        create_funding(env.repo, c, WS, [env.move(c, "m2", -27600).id], [c1.id], env.q, NOW)
    out = env.svc.resolve(DELEG, first.code, "C1")  # C1 was paid meanwhile
    assert out["status"] == "asked_again" and out["code"] != first.code
    assert env.item(first.code).resolution == "stale"
    again = env.item(out["code"])
    assert again.kind is PendingKind.LINK_FUNDING and again.options[0] == "C2"
    assert count_rows(env.base, "intervention_log") == 0
    with env.repo.tx() as c:
        create_funding(env.repo, c, WS, ["m1"], [c2.id], env.q, NOW)
    assert env.svc.resolve(DELEG, out["code"], "C2") == {"ok": True, "status": "already_settled"}
    assert env.item(out["code"]).resolution == "stale"


def test_reversing_a_rule_made_bank_receipt_revokes_the_rule(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)
        mv = env.move(c, "in1", 12000, currency="USD", acc="acc-usd", iban=PAYER_IBAN)
        item = ask_explain_incoming(env.repo, c, WS, mv, env.q)
    env.svc.pending(DELEG)  # shown to the owner: a number now means what it showed
    assert env.svc.resolve(DELEG, item.code, "1")["receipt_ref"] == "R1"
    out = env.svc.propose_reverse(DELEG, "R1", "no era de A")
    assert out["high_value"] is True and out["echo"]["rule"] is True
    done = env.yes(out)
    assert (done["status"], done["ref"], done["rules_revoked"]) == ("reversed", "R1", 1)
    with env.repo.read() as c:
        assert env.repo.rule_for(c, WS, env.repo.hash_key(PAYER_IBAN)) is None
        assert env.repo.receipt_by_ref(c, WS, "R1") is None
        asked = env.repo.pending_by_code(c, WS, done["question"])
    assert asked.kind is PendingKind.EXPLAIN_INCOMING and asked.resolved_at is None


def test_not_an_exchange_is_undone_by_code_or_by_the_ignored_list(tmp_path):
    env = Env(tmp_path)
    key = env.repo.hash_key(EMPLOYER_IBAN)
    with env.repo.tx() as c:
        mv = env.move(c, "in1", 250000, iban=EMPLOYER_IBAN, name="EMPLEADOR SINTETICO")
        item = ask_explain_incoming(env.repo, c, WS, mv, env.q)
    assert env.svc.resolve(DELEG, item.code, "NOT_EXCHANGE")["status"] == "not_exchange"
    with env.repo.read() as c:
        assert env.repo.rule_for(c, WS, key) == IGNORE
    out = env.svc.propose_reverse(DELEG, item.code, "era de un familiar")
    assert out["high_value"] is True and out["echo"]["rule"] is True
    done = env.yes(out)
    assert done["status"] == "reopened" and done["question"] != item.code
    with env.repo.tx() as c:
        assert env.repo.rule_for(c, WS, key) is None
        assert env.repo.movement_role(c, "in1") is None
        # later: an IGNORE rule classified a payment on its own (no question, no P-code)
        env.repo.insert_payer_rule(c, WS, key, None)
        env.move(c, "in2", 250000, day=D15, iban=EMPLOYER_IBAN, name="EMPLEADOR SINTETICO")
        env.repo.insert_movement_role(c, WS, "in2", MovementRoleKind.NOT_EXCHANGE)
    listing = env.svc.explain(DELEG, "ignored")
    [row] = listing["movements"]
    assert {k: row[k] for k in ("date", "amount", "currency", "sender")} == {
        "date": "2026-11-15", "amount": "2500.00", "currency": "EUR",
        "sender": "EMPLEADOR SINTETICO"}
    assert row["undo_ref"].startswith("U") and "in2" not in json.dumps(listing)
    assert key not in json.dumps(listing)
    undo = env.svc.propose_reverse(DELEG, row["undo_ref"], "es de un familiar")
    assert undo["high_value"] is True
    done = env.yes(undo)
    assert (done["status"], done["rules_revoked"]) == ("reopened", 1)
    with env.repo.read() as c:
        assert env.repo.movement_role(c, "in2") is None
        assert env.repo.rule_for(c, WS, key) is None
        assert env.repo.pending_by_dedupe(c, WS, "EXPLAIN_INCOMING:in2") is not None
    assert env.svc.explain(DELEG, "ignored")["movements"] == []


def test_partner_favor_is_answered_and_undone_by_code_or_by_the_ignored_list(tmp_path):
    env = Env(tmp_path)
    key = env.repo.hash_key(PAYER_IBAN)
    with env.repo.tx() as c:
        mv = env.move(c, "in1", 12000, currency="USD", acc="acc-usd", iban=PAYER_IBAN)
        item = ask_explain_incoming(env.repo, c, WS, mv, env.q)
    assert item.options[-1] == "PARTNER"
    assert env.svc.resolve(DELEG, item.code, "PARTNER")["status"] == "partner_favor"
    with env.repo.read() as c:
        assert env.repo.movement_role(c, "in1") is MovementRoleKind.PARTNER_SIDE
        assert env.repo.rule_for(c, WS, key) == "p"
    out = env.svc.propose_reverse(DELEG, item.code, "era mío")
    assert out["high_value"] is True and out["echo"]["rule"] is True
    done = env.yes(out)
    assert done["status"] == "reopened" and done["question"] != item.code
    with env.repo.tx() as c:
        assert env.repo.rule_for(c, WS, key) is None
        assert env.repo.movement_role(c, "in1") is None
        # later: the partner rule set a payment aside on its own (no question, no P-code)
        env.repo.insert_payer_rule(c, WS, key, "p")
        env.move(c, "in2", 7000, day=D15, currency="USD", acc="acc-usd", iban=PAYER_IBAN)
        env.repo.insert_movement_role(c, WS, "in2", MovementRoleKind.PARTNER_SIDE)
    [row] = env.svc.explain(DELEG, "ignored")["movements"]
    assert (row["date"], row["amount"], row["currency"]) == ("2026-11-15", "70.00", "USD")
    undo = env.svc.propose_reverse(DELEG, row["undo_ref"], "era mío")
    assert undo["high_value"] is True
    done = env.yes(undo)
    assert (done["status"], done["rules_revoked"]) == ("reopened", 1)
    with env.repo.read() as c:
        assert env.repo.movement_role(c, "in2") is None
        assert env.repo.rule_for(c, WS, key) is None
        assert env.repo.pending_by_dedupe(c, WS, "EXPLAIN_INCOMING:in2") is not None
    assert env.svc.explain(DELEG, "ignored")["movements"] == []


def test_review_opening_confirm_needs_amount_and_later(tmp_path):
    env = Env(tmp_path)
    note = "según el dueño, 18/11"
    with env.repo.tx() as c:
        record_opening(env.repo, c, WS, "a", "USD", 3000, Opening.APPROXIMATE, note, NOW,
                       queue=env.q)
        record_opening(env.repo, c, WS, "f", "USD", 50000, Opening.APPROXIMATE, note, NOW,
                       queue=env.q)
        env.repo.insert_counterparty(c, Counterparty("g", WS, CounterpartyKind.FUND, "Fondo G",
                                                     "ACTIVE", opening=Opening.UNKNOWN),
                                     ["Fondo G"])
        shown = {"a": [{"entry_ref": "E1", "currency": "USD", "amount": "30.00"}],
                 "f": [{"entry_ref": "E2", "currency": "USD", "amount": "500.00"}], "g": []}
        items = {cp: env.q.add(c, WS, PendingKind.REVIEW_OPENING, ["CONFIRM", "LATER"],
                               {"counterparty": cp, "openings": shown[cp]},
                               f"REVIEW_OPENING:{cp}:2026-W47")
                 for cp in ("a", "f", "g")}
    out = env.svc.resolve(DELEG, items["a"].code, "Confirmar")
    assert out["status"] == "confirmed" and len(out["entries"]) == 1
    assert env.svc.resolve(DELEG, items["f"].code, "CONFIRM")["status"] == "confirmed"
    with env.repo.read() as c:
        hist = [(e.kind, e.amount_minor, e.basis) for e in env.repo.entries(c, WS, "a")]
        assert hist == [(EntryKind.OPENING, 3000, "APPROXIMATE"), (EntryKind.REVERSAL, -3000, None),
                        (EntryKind.OPENING, 3000, "CONFIRMED")]
        assert env.repo.entries(c, WS, "a")[-1].note == note
        assert env.repo.get_counterparty(c, WS, "a").opening is Opening.CONFIRMED
        assert env.repo.entries(c, WS, "f")[-1].amount_minor == -50000  # still holds 500
        assert env.repo.balance(c, WS, "f", "USD") == -50000
    before = env.facts()
    assert env.svc.resolve(DELEG, items["g"].code, "CONFIRM") == {
        "ok": True, "status": "needs_amount", "code": items["g"].code}
    assert env.facts() == before and env.item(items["g"].code).resolved_at is None
    assert env.svc.resolve(DELEG, items["g"].code, "LATER") == {
        "ok": True, "status": "snoozed", "until": "2026-11-27", "code": items["g"].code}
    later = env.item(items["g"].code)
    assert later.resolved_at is None and later.snooze_until == NOW + timedelta(days=7)


# --- corrections, forgiveness, reallocation, setup ---------------------------------------
def test_forgive_echo_and_result_list_every_entry(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        record_opening(env.repo, c, WS, "a", "USD", 3000, Opening.CONFIRMED, "según el dueño",
                       NOW, queue=env.q)  # E1
        env.exchange(c)  # Familiar A owes 120 more on C1
    assert env.svc.propose_forgive(DELEG, "Familiar A", "1.250,50", "regalo")["field"] == "amount"
    too_much = env.svc.propose_forgive(DELEG, "Familiar A", "200", "regalo")
    assert (too_much["field"], too_much["detail"]["outstanding"]) == ("amount", "150.00")
    out = env.svc.propose_forgive(DELEG, "Familiar A", None, "regalo")
    assert out["echo"] == {
        "type": "forgive", "counterparty": "Familiar A", "currency": "USD",
        "outstanding": "150.00", "amount": "150.00", "reason": "regalo", "lines": [
            {"exchange_ref": None, "entry_ref": "E1", "amount": "30.00"},
            {"exchange_ref": "C1", "entry_ref": None, "amount": "120.00"}]}
    assert env.yes(out) == {"ok": True, "status": "forgiven", "currency": "USD",
                            "amount": "150.00", "entries": ["E4", "E5"]}
    with env.repo.read() as c:
        assert env.repo.balance(c, WS, "a", "USD") == 0
    assert env.svc.propose_forgive(DELEG, "C1:Familiar A", None, "x")["field"] == "outstanding"


def test_reallocate_maps_exchange_refs_and_errors(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c, [LineInput("a", 12000)])  # C1
        env.exchange(c, [LineInput("a", 5000)], day=D14)  # C2
        record_receipt(env.repo, c, WS, kind=ReceiptKind.CASH, payer_id="a", currency="USD",
                       amount_minor=12000, received_on=D15,
                       verification=Verification.OWNER_CONFIRMED, queue=env.q, now=NOW)  # R1
    out = env.svc.propose_reallocate(DELEG, "R1", [{"exchange": "C2", "amount": "50"},
                                                   {"exchange": "c1", "amount": "70"}])
    assert out["echo"] == {
        "type": "reallocate", "receipt_ref": "R1", "payer": "Familiar A", "currency": "USD",
        "amount": "120.00", "before": [{"item": "C1", "amount": "120.00"}],
        "after": [{"item": "C2", "amount": "50.00"}, {"item": "C1", "amount": "70.00"}],
        "credit": "0.00"}
    assert env.svc.propose_reallocate(DELEG, "R1", [{"exchange": "C2", "amount": "80"}]) == {
        "ok": False, "error": "validation_error", "field": "allocations[0].amount",
        "detail": {"item": "C2", "outstanding": "50.00", "amount": "80.00"}}
    assert env.svc.propose_reallocate(DELEG, "R1", [{"exchange": "C9", "amount": "1"}])[
        "field"] == "allocations[0].exchange"
    with env.repo.tx() as c:  # C2 gets paid by another receipt before the owner says yes
        record_receipt(env.repo, c, WS, kind=ReceiptKind.CASH, payer_id="a", currency="USD",
                       amount_minor=5000, received_on=D15,
                       verification=Verification.OWNER_CONFIRMED, queue=env.q, now=NOW)  # R2
    stale = env.yes(out)
    assert (stale["error"], stale["field"], stale["detail"]["item"]) == (
        "validation_error", "allocations", "C2")
    assert no_ids(stale) and env.item(out["code"]).resolved_at is None
    with env.repo.tx() as c:
        reverse(env.repo, c, WS, "R2", "test", env.q, NOW)
    done = env.yes(out)
    assert done == {"ok": True, "status": "reallocated", "receipt_ref": "R1", "allocations": [
        {"item": "C2", "amount": "50.00", "method": "OWNER"},
        {"item": "C1", "amount": "70.00", "method": "OWNER"}]}


def test_setup_counterparty_opening_and_correction(tmp_path):
    env = Env(tmp_path)
    out = env.svc.propose_counterparty(DELEG, "Familiar D", "person", ["Fami D", "Prima D"],
                                       "eur", "Banco Uno")
    assert out["echo"] == {
        "type": "counterparty", "label": "Familiar D", "kind": "PERSON",
        "aliases": ["Familiar D", "Fami D", "Prima D"], "pay_currency": "EUR",
        "settles_to": "Banco Uno EUR", "alert_below": None, "opening": None}
    assert env.yes(out) == {"ok": True, "status": "created", "counterparty": "Familiar D",
                            "kind": "PERSON"}
    with env.repo.read() as c:
        [d] = env.repo.find_by_alias(c, WS, "prima d")
    assert (d.settles_to, d.pay_currency) == ("acc-eur", "EUR")
    dup = env.svc.propose_counterparty(DELEG, "Otra", "PERSON", ["familiar a"])
    assert (dup["error"], dup["field"]) == ("validation_error", "aliases")
    where = env.svc.propose_counterparty(DELEG, "Otra", "PERSON", [], None, "Banco")
    assert where["candidates"] == ["Banco Uno EUR", "Bank Two USD", "CASH_ABROAD"]
    fund = env.svc.propose_counterparty(DELEG, "Fondo G", "fund", [], None, "USD", "300")
    assert (fund["echo"]["settles_to"], fund["echo"]["alert_below"], fund["echo"]["opening"]) \
        == ("Bank Two USD", "300.00", "UNKNOWN")

    op = env.svc.propose_opening(DELEG, "Familiar D", "-20.00", "EUR", "approximate",
                                 "según el dueño, 18/11")
    assert op["echo"] == {"type": "opening", "counterparty": "Familiar D", "currency": "EUR",
                          "amount": "-20.00", "basis": "APPROXIMATE",
                          "note": "según el dueño, 18/11", "replaces": []}
    assert env.yes(op)["entry_ref"] == "E1"
    assert env.svc.propose_opening(DELEG, "Familiar D", "5", "EUR", "unknown", "n")[
        "field"] == "basis"
    assert env.svc.propose_opening(DELEG, "Familiar D", "5", "EUR", "CONFIRMED", " ")[
        "field"] == "note"

    with env.repo.tx() as c:
        env.exchange(c)  # C1
    lines = [{"payer": "Familiar A", "usd": "100"}, {"payer": "Familiar B", "usd": "100"},
             {"payer": "owner", "usd": "40"}, {"payer": "Fondo F", "usd": "60"}]
    fix = env.svc.propose_correction(DELEG, "C1", lines, None, "eran 100 y 100")
    assert (fix["echo"]["before"]["usd"], fix["echo"]["after"]["usd"]) == ("300.00", "300.00")
    assert fix["echo"]["after"]["lines"][0]["usd"] == "100.00"
    assert env.yes(fix) == {"ok": True, "status": "corrected", "exchange_ref": "C1",
                            "usd": "300.00"}
    assert env.svc.propose_correction(DELEG, "C9", lines, None, "x")["field"] == "exchange"
    assert env.svc.propose_correction(DELEG, "C1", lines, "250", "x")["field"] == "lines_total"
    assert env.svc.propose_correction(DELEG, "C1", lines, None, "")["field"] == "reason"


def test_mark_held_cash_is_direct_and_audited(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)  # Familiar A owes 120 USD
    out = env.svc.mark_held_cash(DELEG, "Familiar A", "150", "USD")
    assert out == {"ok": True, "status": "recorded", "counterparty": "Familiar A",
                   "currency": "USD", "amount": "150.00", "shown": "120.00"}
    assert env.svc.mark_held_cash(DELEG, "Familiar A", "100", "USD")["shown"] == "100.00"
    assert env.svc.mark_held_cash(DELEG, "Familiar A", "150", "USD")["shown"] == "120.00"
    assert count_rows(env.base, "held_cash_statement") == 3
    assert raw_execute(env.base, "SELECT DISTINCT command_type, channel FROM command_log") == [
        ("held_cash", "telegram")]
    assert count_rows(env.base, "pending_item") == 0
    assert env.svc.mark_held_cash(DELEG, "Fondo F", "10", "USD")["error"] == \
        "clarification_needed"
    assert env.svc.mark_held_cash(DELEG, "Familiar A", "1.250,50", "USD")["field"] == "amount"


# --- reads --------------------------------------------------------------------------------
def test_reads_exchanges_receivables_and_explain(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.exchange(c)  # C1: a 120 USD, b 80 (EUR), owner 40, f 60
        assert try_link(env.repo, c, WS, env.move(c, "m1", -27600), env.q, NOW) == "LINKED"
        env.exchange(c, [LineInput("a", 5000)], day=D14)  # C2, open
    ex = env.svc.exchanges(DELEG)
    assert [(e["exchange_ref"], e["status"], e["usd"]) for e in ex["exchanges"]] == [
        ("C1", "PAID", "300.00"), ("C2", "OPEN", "50.00")]
    c1 = ex["exchanges"][0]
    assert (c1["funding_ref"], c1["rate"]) == ("F1", "0.9200")
    assert c1["lines"][1] == {"payer": "Familiar B", "usd": "80.00", "debt_currency": "EUR",
                              "eur": "73.60", "note": None}
    assert [e["exchange_ref"] for e in env.svc.exchanges(DELEG, "open")["exchanges"]] == ["C2"]
    assert [e["exchange_ref"] for e in env.svc.exchanges(DELEG, since="2026-11-14")[
        "exchanges"]] == ["C2"]
    assert env.svc.exchanges(DELEG, "closed")["field"] == "status"
    assert env.svc.exchanges(DELEG, since="14/11")["field"] == "since"

    mine = env.svc.receivables(DELEG, "familiar a")
    assert [r["counterparty"] for r in mine["owed_to_you"]] == ["Familiar A"]
    assert mine["owed_to_partner"] is None and mine["held_for_others"] == []
    assert mine["subtotals"]["owed_to_you"] == {"USD": "170.00"}
    everyone = env.svc.receivables(DELEG)
    assert everyone["ok"] is True and len(everyone["owed_to_you"]) == 2
    assert everyone["owed_to_partner"]["amount"] == "50.00"

    c1x = env.svc.explain(DELEG, "C1")
    assert (c1x["status"], c1x["fundings"]) == ("PAID", [{"ref": "F1", "live": True}])
    assert [(e["ref"], e["entry_kind"], e["counterparty"], e["amount"])
            for e in c1x["entries"]] == [("E1", "CHARGE", "Familiar A", "120.00"),
                                         ("E2", "CHARGE", "Fondo F", "60.00"),
                                         ("E3", "CHARGE", "Familiar B", "73.60")]
    f1 = env.svc.explain(DELEG, "F1")
    assert (f1["rate"], f1["exchanges"], f1["payments"]) == (
        "0.9200", ["C1"], [{"date": "2026-11-14", "eur": "276.00"}])
    assert env.svc.explain(DELEG, "E1")["source"] == "C1"
    person = env.svc.explain(DELEG, "Familiar B")
    assert person["balances"] == {"EUR": "73.60"} and person["entries"][0]["ref"] == "E3"
    assert env.svc.explain(DELEG, "Z1")["error"] == "clarification_needed"
    assert env.svc.explain(DELEG, "C9")["field"] == "ref"
    for out in (ex, mine, everyone, c1x, f1, person):
        assert no_ids(out)


def test_logs_carry_no_labels_amounts_or_details(tmp_path, caplog):
    env = Env(tmp_path)
    caplog.set_level(logging.DEBUG, logger="finance")
    env.svc.propose_receipt(DELEG, "Familiar A", "1.250,50", "USD", "CASH")
    env.svc.propose_receipt(DELEG, "Familiar", "50", "USD", "CASH")
    env.yes(env.svc.propose_exchange(DELEG, "300", E1, EVIDENCE))
    env.svc.propose_exchange(DELEG, "250", E1)
    env.svc.mark_held_cash(DELEG, "Familiar A", "150", "USD")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "receivables" in text
    for secret in ("Familiar", "Fondo", "Socio", "300", "120", "150", "REF-SYNTH", "1.250"):
        assert secret not in text


def test_owner_line_is_never_a_debt(tmp_path):
    env = Env(tmp_path)
    out = env.svc.propose_exchange(DELEG, "40", [{"payer": "mío", "usd": "40"}])
    assert out["echo"]["lines"][0]["payer"] == "owner"
    assert env.yes(out)["exchange_ref"] == "C1"
    assert count_rows(env.base, "ledger_entry") == 0
