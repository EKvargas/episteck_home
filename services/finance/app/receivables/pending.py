"""Pending queue: questions for the owner and notices. The caller owns the transaction."""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from ..store.receivables_repo import ReceivablesRepository
from .model import RESURFACE_AFTER, PendingItem, PendingKind


class UnknownPending(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AlreadyResolved(Exception):
    def __init__(self, resolution: str | None) -> None:
        super().__init__(resolution)
        self.resolution = resolution


class PendingQueue:
    def __init__(self, repo: ReceivablesRepository, clock: Callable[[], datetime]) -> None:
        self._repo = repo
        self._clock = clock

    def add(self, conn, ws: str, kind: PendingKind, options: Sequence[str],
            payload: dict[str, Any], dedupe_key: str,
            requires_answer: bool = True) -> PendingItem:
        try:
            json.dumps(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON-serialisable") from exc
        existing = self._repo.pending_by_dedupe(conn, ws, dedupe_key)
        if existing is not None:
            return existing
        item = PendingItem(
            f"P{self._repo.next_number(conn, ws, 'P')}", ws, kind, requires_answer,
            tuple(options), dict(payload), dedupe_key, self._clock())
        self._repo.insert_pending(conn, item)
        return item

    def notice(self, conn, ws: str, text_key: str, payload: dict[str, Any]) -> PendingItem:
        return self.add(conn, ws, PendingKind.INFO, [], {**payload, "text_key": text_key},
                        f"INFO:{text_key}", requires_answer=False)

    def get(self, conn, ws: str, code: str) -> PendingItem | None:
        return self._repo.pending_by_code(conn, ws, code)

    def open_items(self, conn, ws: str) -> list[PendingItem]:
        return self._repo.pending_open(conn, ws)

    def for_delivery(self, conn, ws: str) -> list[PendingItem]:
        now = self._clock()
        due = [
            i for i in self._repo.pending_open(conn, ws)
            if i.delivered_at is None
            or (i.requires_answer and i.delivered_at <= now - RESURFACE_AFTER
                and (i.snooze_until is None or i.snooze_until <= now))
        ]
        out = []
        for i in due:
            self._repo.mark_pending_delivered(conn, ws, i.code, now,
                                              resolve=not i.requires_answer)
            out.append(self._repo.pending_by_code(conn, ws, i.code))
        return out

    def resolve(self, conn, ws: str, code: str, resolution: str, *, human: bool) -> PendingItem:
        item = self.get(conn, ws, code)
        if item is None:
            raise UnknownPending(code)
        if item.resolved_at is not None:
            raise AlreadyResolved(item.resolution)
        now = self._clock()
        self._repo.mark_pending_resolved(conn, ws, code, resolution, now)
        if human:
            self._repo.log_intervention(conn, ws, item.kind.value, now)
        return self._repo.pending_by_code(conn, ws, code)

    def snooze(self, conn, ws: str, code: str, until: datetime) -> PendingItem:
        if self.get(conn, ws, code) is None:
            raise UnknownPending(code)
        self._repo.set_pending_snooze(conn, ws, code, until)
        return self._repo.pending_by_code(conn, ws, code)
