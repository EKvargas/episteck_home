"""Pending queue and intervention log (synthetic data only)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.receivables.model import PendingItem, PendingKind, options_digest
from app.receivables.pending import AlreadyResolved, PendingQueue, UnknownPending
from app.store.receivables_repo import ReceivablesRepository
from app.store.repo import FinanceRepository
from tests.support import PEPPER, T0, column_names, make_repo, raw_execute, seed_workspace

WS = "ws-1"


class Clock:
    def __init__(self) -> None:
        self.now: datetime = T0

    def __call__(self) -> datetime:
        return self.now


def make(tmp_path):
    repo = make_repo(tmp_path)
    seed_workspace(repo)
    rrepo = ReceivablesRepository(repo)
    clock = Clock()
    return rrepo, PendingQueue(rrepo, clock), clock


def ask(q, conn, key="k1", **kw):
    return q.add(conn, WS, PendingKind.LINK_FUNDING, ["yes", "no"], {"ref": "X1"}, key, **kw)


def test_dedupe_returns_same_open_item(tmp_path):
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        a = ask(q, conn)
        b = ask(q, conn)
        assert a.code == b.code
        q.resolve(conn, WS, a.code, "yes", human=True)
        c = ask(q, conn)
        assert c.code != a.code


def test_codes_are_p1_p2_sequential(tmp_path):
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        assert ask(q, conn, "a").code == "P1"
        assert ask(q, conn, "b").code == "P2"
        n = q.notice(conn, WS, "funding_closed:F3", {"ref": "F3"})
        assert n.code == "P3" and n.kind is PendingKind.INFO
        assert n.requires_answer is False and n.payload["text_key"] == "funding_closed:F3"
        assert q.notice(conn, WS, "funding_closed:F3", {"ref": "F3"}).code == "P3"


def test_for_delivery_marks_delivered_and_resolves_info(tmp_path):
    repo, q, clock = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        q.notice(conn, WS, "n:1", {})
        items = q.for_delivery(conn, WS)
        assert [i.code for i in items] == ["P1", "P2"]
        assert q.get(conn, WS, "P1").delivered_at == T0
        info = q.get(conn, WS, "P2")
        assert info.resolved_at == T0 and info.resolution == "delivered"
        assert [i.code for i in q.open_items(conn, WS)] == ["P1"]
        assert q.for_delivery(conn, WS) == []
        assert repo.interventions_in_month(conn, WS, 2026, 10) == 0


def test_unanswered_question_resurfaces_after_20h_not_before(tmp_path):
    repo, q, clock = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        assert len(q.for_delivery(conn, WS)) == 1
        clock.now = T0 + timedelta(hours=19)
        assert q.for_delivery(conn, WS) == []
        clock.now = T0 + timedelta(hours=21)
        assert [i.code for i in q.for_delivery(conn, WS)] == ["P1"]


def test_snooze_blocks_resurfacing_until_due(tmp_path):
    repo, q, clock = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        q.for_delivery(conn, WS)
        item = q.snooze(conn, WS, "P1", T0 + timedelta(days=7))
        assert item.snooze_until == T0 + timedelta(days=7)
        clock.now = T0 + timedelta(days=3)
        assert q.for_delivery(conn, WS) == []
        clock.now = T0 + timedelta(days=7, hours=1)
        assert [i.code for i in q.for_delivery(conn, WS)] == ["P1"]


def test_snooze_holds_back_an_item_never_delivered(tmp_path):
    repo, q, clock = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        q.snooze(conn, WS, "P1", T0 + timedelta(days=7))
        assert q.for_delivery(conn, WS) == []
        clock.now = T0 + timedelta(days=7, hours=1)
        assert [i.code for i in q.for_delivery(conn, WS)] == ["P1"]


def test_delivery_stores_the_options_digest_and_old_tables_gain_it(tmp_path):
    repo, _, clock = make(tmp_path)
    base = repo.base
    raw_execute(base, "DROP TABLE pending_item")  # the table as an earlier build made it
    raw_execute(base, "CREATE TABLE pending_item(workspace_id TEXT NOT NULL, "
                      "code TEXT NOT NULL, kind TEXT NOT NULL, requires_answer INTEGER NOT NULL, "
                      "options TEXT NOT NULL, payload TEXT NOT NULL, dedupe_key TEXT NOT NULL, "
                      "created_at TEXT NOT NULL, delivered_at TEXT, resolved_at TEXT, "
                      "resolution TEXT, snooze_until TEXT, PRIMARY KEY(workspace_id, code))")
    upgraded = ReceivablesRepository(FinanceRepository(base.path, pepper=PEPPER))
    assert column_names(base, "pending_item")[-1] == "shown_digest"
    FinanceRepository(base.path, pepper=PEPPER)  # a second open changes nothing
    q = PendingQueue(upgraded, clock)
    with upgraded.tx() as conn:
        ask(q, conn)
        assert q.get(conn, WS, "P1").shown_digest is None
        [item] = q.for_delivery(conn, WS)
        assert item.shown_digest == options_digest(("yes", "no"))
        assert not item.options_changed()
        upgraded.refresh_pending(conn, WS, "P1", ["no", "yes"], {"ref": "X1"})
        assert q.get(conn, WS, "P1").options_changed()


def test_resolve_twice_raises_already_resolved_with_first_resolution(tmp_path):
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        q.resolve(conn, WS, "P1", "Familiar A", human=True)
        with pytest.raises(AlreadyResolved) as e:
            q.resolve(conn, WS, "P1", "no", human=True)
        assert e.value.resolution == "Familiar A"
        assert "familiar" not in str(e.value).lower()  # messages never carry resolutions
        with pytest.raises(UnknownPending):
            q.resolve(conn, WS, "P9", "no", human=True)
        assert q.get(conn, WS, "P9") is None


def test_repo_resolution_never_overwrites_an_earlier_one(tmp_path):
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        assert repo.mark_pending_resolved(conn, WS, "P1", "yes", T0) is True
        assert repo.mark_pending_resolved(conn, WS, "P1", "no", T0 + timedelta(hours=1)) is False
        item = q.get(conn, WS, "P1")
        assert (item.resolution, item.resolved_at) == ("yes", T0)


def test_codes_match_case_insensitively(tmp_path):
    repo, q, clock = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        assert q.get(conn, WS, "p1").code == "P1"
        assert q.get(conn, WS, " p1 ").code == "P1"
        q.for_delivery(conn, WS)
        until = T0 + timedelta(days=1)
        assert q.snooze(conn, WS, "p1", until).snooze_until == until
        assert q.resolve(conn, WS, "p1", "yes", human=True).resolution == "yes"
        with pytest.raises(AlreadyResolved):
            q.resolve(conn, WS, "P1", "no", human=True)


def test_dedupe_can_include_resolved_items(tmp_path):
    # Task 9: once per crossing / per ISO week, even after the owner answered.
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        a = ask(q, conn, "week:2026-W42", dedupe_include_resolved=True)
        assert ask(q, conn, "week:2026-W42", dedupe_include_resolved=True).code == a.code
        q.resolve(conn, WS, a.code, "yes", human=True)
        again = ask(q, conn, "week:2026-W42", dedupe_include_resolved=True)
        assert (again.code, again.resolution) == (a.code, "yes")
        fresh = ask(q, conn, "week:2026-W42")  # default: only open items dedupe
        assert fresh.code != a.code
        assert ask(q, conn, "week:2026-W42", dedupe_include_resolved=True).code == fresh.code
        n = q.notice(conn, WS, "fund_low:cp-f:1", {}, dedupe_include_resolved=True)
        q.for_delivery(conn, WS)  # delivering resolves the notice
        seen = q.notice(conn, WS, "fund_low:cp-f:1", {}, dedupe_include_resolved=True)
        assert (seen.code, seen.resolution) == (n.code, "delivered")
        assert [i.code for i in q.open_items(conn, WS)] == [fresh.code]


def test_only_one_open_item_per_dedupe_key(tmp_path):
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        clash = q.get(conn, WS, "P1")
        with pytest.raises(sqlite3.IntegrityError):
            repo.insert_pending(conn, PendingItem(
                "P2", WS, clash.kind, True, (), {}, clash.dedupe_key, T0))


def test_naive_datetimes_are_rejected(tmp_path):
    repo, q, clock = make(tmp_path)
    naive = T0.replace(tzinfo=None)
    with repo.tx() as conn:
        ask(q, conn)
        with pytest.raises(ValueError):
            q.snooze(conn, WS, "P1", naive)
        clock.now = naive
        with pytest.raises(ValueError):
            ask(q, conn, "other")
        with pytest.raises(ValueError):
            q.for_delivery(conn, WS)
        with pytest.raises(ValueError):
            q.resolve(conn, WS, "P1", "yes", human=True)
        item = q.get(conn, WS, "P1")
        assert (item.delivered_at, item.resolved_at, item.snooze_until) == (None, None, None)
        assert [i.code for i in q.open_items(conn, WS)] == ["P1"]
        assert repo.next_number(conn, WS, "P") == 2  # the refused add took no code


def test_human_resolution_logs_one_intervention_and_system_none(tmp_path):
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn, "a")
        ask(q, conn, "b")
        q.resolve(conn, WS, "P1", "yes", human=True)
        assert repo.interventions_in_month(conn, WS, 2026, 10) == 1
        q.resolve(conn, WS, "P2", "auto", human=False)
        assert repo.interventions_in_month(conn, WS, 2026, 10) == 1


def test_non_serialisable_payload_rejected(tmp_path):
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        with pytest.raises(ValueError):
            q.add(conn, WS, PendingKind.CONFIRM, [], {"when": datetime.now(timezone.utc)}, "k")
        assert q.open_items(conn, WS) == []
