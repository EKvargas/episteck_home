"""Pending queue and intervention log (synthetic data only)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.receivables.model import PendingKind
from app.receivables.pending import AlreadyResolved, PendingQueue, UnknownPending
from app.store.receivables_repo import ReceivablesRepository
from tests.support import T0, make_repo, seed_workspace

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


def test_resolve_twice_raises_already_resolved_with_first_resolution(tmp_path):
    repo, q, _ = make(tmp_path)
    with repo.tx() as conn:
        ask(q, conn)
        q.resolve(conn, WS, "P1", "yes", human=True)
        with pytest.raises(AlreadyResolved) as e:
            q.resolve(conn, WS, "P1", "no", human=True)
        assert e.value.resolution == "yes"
        with pytest.raises(UnknownPending):
            q.resolve(conn, WS, "P9", "no", human=True)
        assert q.get(conn, WS, "P9") is None


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
