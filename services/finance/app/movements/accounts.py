"""Per-account state shown beside movements and used for completeness (spec 5.3, 5.4)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from .. import domain
from ..overview import TAINTED, account_status, observation_kind
from ..store.repo import FinanceRepository


def needs_reauth(link: domain.Connection | None, now: datetime) -> bool:
    """The connection asks for a new consent, or the consent has run out."""
    if link is None:
        return False
    expired = link.consent_expires_at is not None and link.consent_expires_at <= now
    return link.status is domain.ConnectionStatus.REAUTH_REQUIRED or expired


def account_rows(repo: FinanceRepository, ws: str, accounts: Sequence[domain.Account],
                 history: Mapping[str, date], now: datetime) -> tuple[list[dict], bool]:
    """The rows of ``accounts`` and whether some account's history is known to be missing:
    an account with no stored movement whose connection never synced (a dormant account
    that does sync is not flagged)."""
    connections = {c.id: c for c in repo.list_connections(ws)}
    out: list[dict] = []
    unsynced_empty = False
    for a in accounts:
        kind = observation_kind(a)
        obs = repo.latest_balance(ws, a.id, kind) if kind else None
        link = connections.get(a.connection_id or "")
        first = history.get(a.id)
        synced = link.last_success_at if link else None
        unsynced_empty = unsynced_empty or (first is None and synced is None)
        stale = account_status(a, obs, link, now) in TAINTED or needs_reauth(link, now)
        out.append({"id": a.id, "institution": a.institution, "currency": a.currency,
                    "synced_at": synced.isoformat() if synced else None,
                    "history_from": first.isoformat() if first else None,
                    "stale": stale})
    return out, unsynced_empty
