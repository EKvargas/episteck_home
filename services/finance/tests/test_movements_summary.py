"""Family help, line views and the per-period summary (synthetic data only)."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from app import domain
from app.movements.help import help_items
from app.movements.model import HelpItem, Interpretation, Kind, Period
from app.movements.summary import summarize
from app.movements.views import movement_line
from app.receivables.funding import create_funding
from app.receivables.ledger import LineInput
from app.receivables.model import OWNER, EntryKind, LedgerEntry
from tests.support import make_account
from tests.test_receivables_matcher import D13, D14, D15, WS, Env

TODAY = date(2026, 11, 20)
PERIOD = Period(date(2026, 11, 1), date(2026, 11, 30), "2026-11")
LINES = [LineInput(OWNER, 3000, beneficiary_note="Familiar B"), LineInput(OWNER, 1000),
         LineInput("a", 6000)]


def _funded(tmp_path, status=domain.MovementStatus.BOOKED, mid="m1", amount=-9100):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        ex = env.exchange(c, lines=LINES)
        env.move(c, mid, amount, D14, status=status)
        funding = create_funding(env.repo, c, WS, [mid], [ex.id], env.q, env.now)
    return env, funding


def _items(env):
    with env.repo.read() as c:
        facts = env.repo.interpretation_facts(c, WS)
        return facts, help_items(env.repo, c, WS, facts)


def test_exchange_parts_split_owner_share_by_usd_and_sum_exactly(tmp_path):
    env, funding = _funded(tmp_path)
    facts, items = _items(env)
    with env.repo.read() as c:
        owner = env.repo.funding_shares(c, funding.id)[OWNER]
    assert len(items) == 2
    assert sum(i.amount_minor for i in items) == owner
    assert [(i.source, i.about) for i in items] == [("exchange_help", "Familiar B"),
                                                   ("exchange_own", None)]
    assert {(i.currency, i.day, i.funding_ref) for i in items} == {("EUR", D14, "F1")}
    assert owner == 3640 and [i.amount_minor for i in items] == [2730, 910]


def test_exchange_parts_keep_the_remainder_at_both_levels(tmp_path):
    env, funding = _funded(tmp_path, amount=-9103)  # 91.03 EUR: nothing divides exactly
    _facts, items = _items(env)
    with env.repo.read() as c:
        assert env.repo.funding_shares(c, funding.id)[OWNER] == 3641  # a floor split gives 3640
    assert [(i.source, i.amount_minor) for i in items] == [
        ("exchange_help", 2731), ("exchange_own", 910)]


def test_exchange_parts_extra_cent_follows_exchange_number_then_line_order(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        one = env.exchange(c, lines=[LineInput(OWNER, 1000, beneficiary_note="Familiar B"),
                                     LineInput("a", 2000)])
        two = env.exchange(c, lines=[LineInput(OWNER, 1000), LineInput("a", 1000)])
        env.move(c, "m1", -1002, D14)
        # asked in reverse order: the funding still reads exchange 1 before exchange 2
        create_funding(env.repo, c, WS, ["m1"], [two.id, one.id], env.q, env.now)
    _facts, items = _items(env)
    # 1002 over 1000/2000/1000/1000 USD -> OWNER 401 (the extra cents go to line 2, then 1);
    # 401 over two equal OWNER lines -> the extra cent goes to the first (exchange 1)
    assert [(i.source, i.about, i.amount_minor) for i in items] == [
        ("exchange_help", "Familiar B", 201), ("exchange_own", None, 200)]


def test_exchange_parts_wait_for_booked_payments(tmp_path):
    env, _ = _funded(tmp_path, status=domain.MovementStatus.PENDING)
    assert _items(env)[1] == []


def test_forgive_counts_in_its_month_and_reversal_in_its_own(tmp_path):
    env = Env(tmp_path)
    with env.repo.tx() as c:
        env.repo.insert_entry(c, LedgerEntry("e1", WS, 1, "b", "EUR", -2500, EntryKind.FORGIVE,
                                             date(2026, 10, 30), "C1"))
        env.repo.insert_entry(c, LedgerEntry("e2", WS, 2, "b", "EUR", 2500, EntryKind.REVERSAL,
                                             date(2026, 11, 3), "E1", reverses_id="e1"))
        env.repo.insert_entry(c, LedgerEntry("e3", WS, 3, "b", "EUR", 900, EntryKind.CHARGE,
                                             date(2026, 11, 4), "C1"))
    facts, items = _items(env)
    assert [(i.source, i.amount_minor, i.day, i.about) for i in items] == [
        ("forgiven", 2500, date(2026, 10, 30), "Familiar B"),
        ("forgiven", -2500, date(2026, 11, 3), "Familiar B")]
    october = summarize(Period(date(2026, 10, 1), date(2026, 10, 31), "2026-10"), [], items,
                        {}, ["EUR"], TODAY)
    november = summarize(PERIOD, [], items, {}, ["EUR"], TODAY)
    assert october["currencies"][0]["spending"]["forgiven"]["amount_minor"] == 2500
    assert november["currencies"][0]["spending"]["forgiven"]["amount_minor"] == -2500


ACCOUNTS = {"eur": make_account(aid="eur"), "usd": make_account(aid="usd", currency="USD")}


def mv(mid, amount, day=date(2026, 11, 5), aid="eur", cur="EUR", name="Shop", text="card",
       status=domain.MovementStatus.BOOKED, iban=None, tx=None):
    return domain.Movement(mid, WS, aid, tx, "fp-" + mid, status, day, day, amount, cur, name,
                           iban, text, None)


def row(mid, amount, kind=Kind.OWN, about=None, **kw):
    return mv(mid, amount, **kw), Interpretation(kind, about=about)


def cur_block(result, cur="EUR"):
    return next(b for b in result["currencies"] if b["currency"] == cur)


def test_summary_income_spending_net_and_help_breakdown():
    rows = [row("i", 100000), row("s", -20000), row("z", -3000, Kind.FAMILY_HELP, "Familiar A",
                                                    aid="usd", cur="USD")]
    rows[2] = row("z", -3000, Kind.FAMILY_HELP, "Familiar A")
    helps = [HelpItem("exchange_help", "EUR", 2730, date(2026, 11, 14), "Familiar B", "F1"),
             HelpItem("exchange_own", "EUR", 910, date(2026, 11, 14), None, "F1"),
             HelpItem("forgiven", "EUR", 500, date(2026, 11, 20), "Familiar B", None),
             HelpItem("forgiven", "EUR", 999, date(2026, 12, 1), "Familiar B", None)]
    b = cur_block(summarize(PERIOD, rows, helps, ACCOUNTS, ["EUR"], TODAY))
    sp = b["spending"]
    parts = [sp[k]["amount_minor"] for k in
             ("bank", "zelle_help", "exchange_own", "exchange_help", "forgiven")]
    assert parts == [20000, 3000, 910, 2730, 500]
    assert sp["amount_minor"] == sum(parts) == 27140
    assert b["family_help"]["amount_minor"] == 3000 + 2730 + 500
    assert b["net"]["amount_minor"] == 100000 - 27140 and b["net"]["amount"] == "728.60"
    assert [(p["about"], p["amount_minor"]) for p in b["family_help"]["by_person"]] == [
        ("Familiar B", 3230), ("Familiar A", 3000)]
    assert set(b["excluded"]) == {"own_transfers", "exchange", "partner_favor", "family", "fund"}


def test_summary_never_mixes_currencies():
    rows = [row("e", -1000), row("u", -2500, aid="usd", cur="USD")]
    result = summarize(PERIOD, rows, [], ACCOUNTS, ["USD", "EUR"], TODAY)
    assert [b["currency"] for b in result["currencies"]] == ["EUR", "USD"]
    assert cur_block(result)["spending"]["amount_minor"] == 1000
    assert cur_block(result, "USD")["spending"]["amount_minor"] == 2500


def test_summary_unclear_pending_and_undescribed_are_separate():
    rows = [row("u", -700, Kind.UNCLEAR), row("p", -300, status=domain.MovementStatus.PENDING),
            row("n", -400, name="", text=""), row("n2", 900, name="", text=""),
            row("o", -1000)]
    b = cur_block(summarize(PERIOD, rows, [], ACCOUNTS, ["EUR"], TODAY))
    assert b["unclear"]["count"] == 1 and b["unclear"]["out"]["amount_minor"] == 700
    assert b["pending_bank"]["count"] == 1 and b["pending_bank"]["out"]["amount_minor"] == 300
    assert b["undescribed"]["count"] == 2
    assert (b["undescribed"]["in"]["amount_minor"], b["undescribed"]["out"]["amount_minor"]) == (900, 400)
    assert b["spending"]["amount_minor"] == 1400 and b["income"]["amount_minor"] == 900
    assert [t["amount_minor"] for t in b["top_spending"]] == [-1000, -400]


def test_summary_flags_exchanges_without_split():
    plain = [(mv("x", -5000), Interpretation(Kind.EXCHANGE, ref="F1", funding_id="f1"))]
    assert summarize(PERIOD, plain, [], ACCOUNTS, ["EUR"], TODAY)["exchanges_without_split"] is False
    bare = [(mv("x", -5000), Interpretation(Kind.EXCHANGE))]
    result = summarize(PERIOD, bare, [], ACCOUNTS, ["EUR"], TODAY)
    assert result["exchanges_without_split"] is True
    assert cur_block(result)["excluded"]["exchange"]["out"]["amount_minor"] == 5000
    assert cur_block(result)["spending"]["amount_minor"] == 0
    unanswered = [(mv("q", -5000), Interpretation(Kind.UNCLEAR, ref="Q1"))]
    assert summarize(PERIOD, unanswered, [], ACCOUNTS, ["EUR"], TODAY)["exchanges_without_split"] is True
    incoming = [(mv("in", 5000), Interpretation(Kind.EXCHANGE))]
    assert summarize(PERIOD, incoming, [], ACCOUNTS, ["EUR"], TODAY)["exchanges_without_split"] is False
    incoming_q = [(mv("iq", 5000), Interpretation(Kind.UNCLEAR, ref="Q2"))]
    assert summarize(PERIOD, incoming_q, [], ACCOUNTS, ["EUR"], TODAY)["exchanges_without_split"] is False


def test_year_equals_sum_of_months():
    rows = [row(f"m{m}{k}", amt, day=date(2026, m, 3 + k), aid=aid, cur=cur)
            for m in range(1, 13) for k, (amt, aid, cur) in enumerate(
                [(1000 * m, "eur", "EUR"), (-300 * m, "eur", "EUR"), (-111, "usd", "USD")])]
    rows += [(mv("t", -50, day=date(2026, 6, 9)), Interpretation(Kind.FAMILY_HELP, about="Familiar A"))]
    helps = [HelpItem("exchange_help", "EUR", 100 * m + 7, date(2026, m, 14), "Familiar B", "F1")
             for m in range(1, 13)]
    helps.append(HelpItem("forgiven", "EUR", 250, date(2026, 3, 2), "Familiar C", None))
    year = summarize(Period(date(2026, 1, 1), date(2026, 12, 31), "2026"), rows, helps,
                     ACCOUNTS, ["EUR", "USD"], TODAY)
    months = [summarize(Period(date(2026, m, 1), date(2026, m, 28), f"2026-{m:02d}"),
                        [r for r in rows if r[0].booking_date.month == m], helps, ACCOUNTS,
                        ["EUR", "USD"], TODAY) for m in range(1, 13)]

    def amounts(node, path=""):
        if isinstance(node, dict):
            if "amount_minor" in node:
                yield path, node["amount_minor"]
            for k, v in node.items():
                if k not in ("top_spending", "by_person"):
                    yield from amounts(v, f"{path}/{k}")

    for i, block in enumerate(year["currencies"]):
        for path, total in amounts(block):
            assert total == sum(dict(amounts(m["currencies"][i]))[path] for m in months), path
    assert cur_block(year)["family_help"]["amount_minor"] == sum(
        h.amount_minor for h in helps) + 50


def test_movement_line_has_no_ids_or_hashes():
    iban_hash = "9f8e7d6c5b4a39281716"
    movement = mv("mov-secret-id", -1250, tx="PROVIDER-TX-777", iban=iban_hash,
                  name="Tienda Sintetica", text="compra 123456")
    line = movement_line(movement, Interpretation(Kind.OWN), ACCOUNTS["eur"], TODAY)
    dump = json.dumps(line)
    for secret in ("mov-secret-id", "PROVIDER-TX-777", "fp-mov-secret-id", iban_hash):
        assert secret not in dump
    assert not re.search(r"[A-Z]{2}\d{2}[A-Z0-9 ]{10,}", dump)
    assert line["account"] == {"id": "eur", "institution": "Bank"}
    assert (line["date"], line["amount"], line["status"], line["kind"]) == (
        "2026-11-05", "-12.50", "BOOKED", "OWN")


def test_movement_line_marks_stale_pending():
    pend = domain.MovementStatus.PENDING

    def stale(day, status=pend):
        line = movement_line(mv("x", -100, day=day, status=status), Interpretation(Kind.OWN),
                             ACCOUNTS["eur"], TODAY)
        return line["stale_pending"]

    assert stale(TODAY - timedelta(days=9)) is True
    assert stale(TODAY - timedelta(days=2)) is False
    assert stale(TODAY - timedelta(days=9), domain.MovementStatus.BOOKED) is False


def test_exchange_line_shows_own_part_and_help():
    parts = [HelpItem("exchange_help", "EUR", 2730, D14, "Familiar B", "F1"),
             HelpItem("exchange_own", "EUR", 910, D14, None, "F1")]
    line = movement_line(mv("x", -9100), Interpretation(Kind.EXCHANGE, ref="F1"),
                         ACCOUNTS["eur"], TODAY, parts)
    assert line["own_part"]["amount_minor"] == 910
    assert line["help"] == [{"about": "Familiar B", "amount_minor": 2730, "amount": "27.30"}]
