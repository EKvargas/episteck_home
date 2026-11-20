"""Bulk interpretation facts and movement reads agree with the single-row lookups."""
from __future__ import annotations

import re
from datetime import date

from app import domain
from app.receivables.explain import ask_explain_incoming
from app.receivables.funding import ask_link_funding, link_choice, reverse_funding
from app.receivables.model import (
    MovementRoleKind, Receipt, ReceiptKind, Verification,
)
from tests.test_receivables_matcher import (
    D13, D14, D15, D16, D17, NEW_IBAN, OWN_IBAN, PARTNER_IBAN, T0, WS, Env, make,
)


def _receipt(rid, number, mid, day=D15):
    return Receipt(rid, WS, number, ReceiptKind.BANK, "a", "USD", 12000, day,
                   Verification.BANK_POSTED, mid)


def test_facts_agree_with_single_row_lookups(tmp_path):
    env = make(tmp_path)
    repo, q = env.repo, env.q
    with repo.tx() as c:
        env.exchange(c)
        env.exchange(c)
        env.move(c, "f1", -27600, D14)
        env.move(c, "f2", -27600, D15)
        link_choice(repo, c, WS, "f1", "C1", q, T0)
        link_choice(repo, c, WS, "f2", "C2", q, T0)
        reverse_funding(repo, c, WS, repo.live_funding_for_movement(c, "f2").id, "wrong", q, T0)
        env.move(c, "r1", 12000, D15, acc="acc-usd", iban=None)
        env.move(c, "r2", 12000, D15, acc="acc-usd", iban=None)
        repo.insert_receipt(c, _receipt("rc1", 1, "r1"))
        repo.insert_receipt(c, _receipt("rc2", 2, "r2"))
        repo.revoke(c, WS, "receipt", "rc2", "undo", T0)
        env.move(c, "o1", -5000, D15, iban=OWN_IBAN)
        env.move(c, "o2", -5000, D15, iban=OWN_IBAN)
        repo.insert_movement_role(c, WS, "o1", MovementRoleKind.NOT_EXCHANGE)
        role2 = repo.insert_movement_role(c, WS, "o2", MovementRoleKind.NOT_EXCHANGE)
        repo.revoke(c, WS, "movement_role", role2, "undo", T0)
        env.move(c, "e1", 3000, D16, iban=None, text="x one")
        env.move(c, "e2", 3000, D16, iban=None, text="x two")
        q1 = ask_explain_incoming(repo, c, WS, env.move(c, "e3", 3000, D16, iban=None, text="x 3"), q)
        ask_explain_incoming(repo, c, WS, repo.movement_by_id(c, WS, "e2"), q)
        q.resolve(c, WS, repo.pending_by_dedupe(c, WS, "EXPLAIN_INCOMING:e2").code, "LATER",
                  human=True)
        # two rules on one key, the newer one revoked
        repo.insert_payer_rule(c, WS, "k1", "a")
        newer = repo.insert_payer_rule(c, WS, "k1", "b")
        repo.revoke(c, WS, "payer_rule", newer, "undo", T0)
        repo.insert_payer_rule(c, WS, "k2", None)
        repo.insert_payer_rule(c, WS, "k3", "a")
        repo.insert_payer_rule(c, WS, "k3", "c")
        # PENDING -> BOOKED
        env.move(c, "p1", -27600, D17, status=domain.MovementStatus.PENDING)
        env.move(c, "p2", -27600, D17, supersedes="p1")
        ask_link_funding(repo, c, WS, "p1", q)
    with repo.read() as c:
        facts = repo.interpretation_facts(c, WS)
        ids = ["f1", "f2", "r1", "r2", "o1", "o2", "e1", "e2", "e3", "p1", "p2"]
        for mid in ids:
            root = facts.root(mid)
            assert root == repo.movement_root(c, mid)
            fund = repo.live_funding_for_movement(c, mid)
            assert facts.fundings.get(root) == fund
            assert facts.receipts.get(root) == repo.live_receipt_for_movement(c, mid)
            assert facts.roles.get(root) == repo.movement_role(c, mid)
            codes = []
            for kind in ("LINK_FUNDING", "EXPLAIN_INCOMING"):
                item = repo.pending_by_dedupe(c, WS, f"{kind}:{root}")
                if item:
                    codes.append(item.code)
            assert ([facts.questions[root]] if root in facts.questions else []) == codes
        assert facts.fundings["f1"] is not None and "f2" not in facts.fundings
        assert "r1" in facts.receipts and "r2" not in facts.receipts
        assert "o1" in facts.roles and "o2" not in facts.roles
        assert "e3" in facts.questions and "e2" not in facts.questions
        assert facts.questions["p1"] == repo.pending_by_dedupe(c, WS, "LINK_FUNDING:p1").code
        assert q1.code == facts.questions["e3"]
        for key in ("k1", "k2", "k3", "none"):
            assert facts.rules.get(key) == repo.rule_for(c, WS, key)
        assert facts.rules["k1"] == "a" and facts.rules["k2"] == "IGNORE"
        assert facts.partner_hashes == repo.partner_hashes(c, WS)
        assert facts.own_hashes == frozenset(repo.own_hashes(c, WS))
        assert set(facts.counterparties) == {"p", "a", "b", "c"}
        assert facts.person_names == {"familiar a": "a", "familiar b": "b", "familiar c": "c"}


def test_current_movements_between_skips_superseded_dateless_and_out_of_range(tmp_path):
    env = make(tmp_path)
    repo = env.repo
    with repo.tx() as c:
        env.move(c, "p1", -100, D14, status=domain.MovementStatus.PENDING)
        env.move(c, "p2", -100, D14, supersedes="p1")
        env.move(c, "late", -300, D17)
        env.move(c, "early", -200, D13)
        env.move(c, "usd", -400, D14, acc="acc-usd")
        env.move(c, "other", -500, D14, acc="acc-other")
        env.move(c, "old", -600, date(2026, 1, 1))
        dateless = domain.Movement("nd", WS, "acc-eur", "tx-nd", "fp-nd",
                                   domain.MovementStatus.BOOKED, None, None, -1, "EUR",
                                   "n", None, "t", None)
        repo.base.insert_movement_in_tx(c, dateless)
    with repo.read() as c:
        got = repo.current_movements_between(c, WS, ["acc-eur", "acc-usd"], D13, D17)
        assert [m.id for _, m in got] == ["early", "p2", "usd", "late"]
        rids = [rid for rid, _ in got]
        assert rids[1] < rids[2]  # same day: by rowid
        assert repo.current_movements_between(c, WS, ["acc-eur"], D14, D14)[0][1].id == "p2"
        assert [m.id for _, m in repo.current_movements_between(c, WS, ["acc-eur"], D13, D13)] \
            == ["early"]
        assert repo.current_movements_between(c, WS, [], D13, D17) == []
        assert repo.current_movements_between(c, WS, ["acc-eur"], date(2026, 1, 1),
                                              date(2026, 1, 1))[0][1].id == "old"


def test_history_from_is_the_earliest_dated_movement_per_account(tmp_path):
    env = make(tmp_path)
    repo = env.repo
    with repo.tx() as c:
        env.move(c, "a1", -100, D15)
        env.move(c, "a2", 100, D13)
        env.move(c, "u1", 100, D16, acc="acc-usd", iban=None)
        env.move(c, "x", -5, D13, status=domain.MovementStatus.PENDING)
        env.move(c, "x2", -5, D17, supersedes="x")  # the current row is dated D17
        env.move(c, "inc", 700, D14, iban=None)
        repo.base.insert_movement_in_tx(c, domain.Movement(
            "nd", WS, "acc-other", "tx-nd", "fp-nd", domain.MovementStatus.BOOKED, None, None,
            -1, "EUR", "n", None, "t", None))
    with repo.read() as c:
        assert repo.history_from(c, WS) == {"acc-eur": D13, "acc-usd": D16}
        inc = repo.current_incoming(c, WS, ["acc-eur", "acc-usd", "acc-other"])
        assert [m.id for m in inc] == ["a2", "inc", "u1"]
        assert repo.current_incoming(c, WS, []) == []


class _Spy:
    """Wraps a connection and records the SQL of every execute."""
    def __init__(self, conn):
        self._c, self.sql = conn, []

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        return self._c.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._c, name)


def test_supersedes_filters_use_no_correlated_subquery(tmp_path):
    """A correlated NOT EXISTS scans the movement table per row (quadratic with history);
    indexed correlated lookups (the partner check) are fine."""
    env = make(tmp_path)
    repo = env.repo
    with repo.read() as c:
        spy = _Spy(c)
        repo.current_movements_between(spy, WS, ["acc-eur"], D13, D17)
        repo.current_incoming(spy, WS, ["acc-eur"])
        repo.history_from(spy, WS)
        repo.unlinked_partner_payments(spy, WS)
        repo.recent_outgoing(spy, WS, "EUR", D13)
        assert len(spy.sql) >= 5
        for sql, params in spy.sql:
            if not sql.lstrip().upper().startswith("SELECT"):
                continue
            plan = " ".join(str(r[3]) for r in c.execute("EXPLAIN QUERY PLAN " + sql, params))
            assert not re.search(r"CORRELATED SCALAR SUBQUERY \d+ SCAN", plan.upper()), sql
