"""Synthetic builders shared by the Finance tests. No real financial data anywhere."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

from app import domain
from app.store.repo import FinanceRepository

PEPPER = b"test-pepper-not-a-secret"
T0 = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


def make_repo(tmp_path, name: str = "finance.sqlite") -> FinanceRepository:
    return FinanceRepository(str(tmp_path / name), pepper=PEPPER)


def seed_workspace(repo: FinanceRepository, ws: str = "ws-1", owner: str = "PSN-1") -> None:
    repo.create_workspace(domain.Workspace(ws, "Test", "PERSONAL", domain.WorkspaceStatus.ACTIVE))
    repo.add_member(ws, owner, "OWNER")


def seed_connection(repo, ws="ws-1", cid="conn-1", owner="PSN-1",
                    provider=domain.Provider.SIMPLEFIN) -> domain.Connection:
    conn = domain.Connection(cid, ws, provider, owner, domain.ConnectionStatus.OK)
    repo.add_connection(conn)
    return conn


def make_account(ws="ws-1", aid="acc-1", **over) -> domain.Account:
    base = dict(
        id=aid, workspace_id=ws, owner_person_ids=("PSN-1",), institution="Bank",
        type=domain.AccountType.CURRENT, currency="EUR", liquidity=domain.Liquidity.AVAILABLE,
        balance_authority=domain.BalanceAuthority.PROVIDER,
        movement_authority=domain.Provider.SIMPLEFIN,
        preferred_balance_kind=domain.BalanceKind.BOOKED, freshness_sla_hours=36,
        connection_id="conn-1", provider_account_ref=f"ref-{aid}",
    )
    base.update(over)
    return domain.Account(**base)


def make_balance(oid="o1", ws="ws-1", aid="acc-1", amount=100000, currency="EUR",
                 kind=domain.BalanceKind.BOOKED, as_of=T0, observed_at=T0,
                 source_ref="sync-1") -> domain.BalanceObservation:
    return domain.BalanceObservation(oid, ws, aid, amount, currency, kind, as_of,
                                     observed_at, source_ref)


def make_movement(mid="m1", ws="ws-1", aid="acc-1", tx="tx-1", fp="fp-1", amount=-1250,
                  status=domain.MovementStatus.BOOKED, supersedes=None,
                  booking=date(2026, 10, 9)) -> domain.Movement:
    return domain.Movement(mid, ws, aid, tx, fp, status, booking, booking, amount, "EUR",
                           "Shop", None, "card payment", supersedes)


def _raw(repo, sql: str, params=()):
    conn = sqlite3.connect(repo.path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def raw_execute(repo, sql: str, params=()):
    return _raw(repo, sql, params)


def pragma(repo, name: str):
    # Most pragmas are per connection, so read them through the repository's own factory.
    with repo.connection() as c:
        return c.execute(f"PRAGMA {name}").fetchone()[0]


def table_names(repo) -> list[str]:
    rows = _raw(repo, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [r[0] for r in rows]


def column_names(repo, table: str) -> list[str]:
    return [r[1] for r in _raw(repo, f"PRAGMA table_info({table})")]


def count_rows(repo, table: str) -> int:
    return _raw(repo, f"SELECT COUNT(*) FROM {table}")[0][0]


def seeded_service(tmp_path, authorizer=None):
    """A FinanceService over one workspace with one fresh EUR account (1234.56)."""
    from app.service import FinanceService

    repo = make_repo(tmp_path)
    seed_workspace(repo)
    seed_connection(repo)
    repo.add_account(make_account(aid="acc-1"))
    repo.record_balance(make_balance("o1", aid="acc-1", amount=123456, as_of=T0, observed_at=T0))
    authz = authorizer or FakeAuthorizer()
    now = T0.replace(hour=10)
    return FinanceService(repo, authz, "ws-1", clock=lambda: now), authz


class FakeAuthorizer:
    """Scripted Home. Builds its answer through the real ``validate_batch``."""

    def __init__(self, actor="PSN-1", allow=None, mode="answer"):
        self.actor = actor
        self.allow = {"SELF": True} if allow is None else allow
        self.mode = mode
        self.calls: list = []

    def authorize(self, delegation, requirements):
        from app.authz import SESSION_INVALID, UNAVAILABLE, BatchDecision, validate_batch
        self.calls.append((delegation, tuple(requirements)))
        if self.mode == "raise":
            raise RuntimeError("home exploded")
        if self.mode == "session_invalid":
            return BatchDecision(SESSION_INVALID)
        if self.mode == "unavailable":
            return BatchDecision(UNAVAILABLE)
        decisions = [
            {"subject": r.subject, "domain": r.domain, "action": r.action,
             "allow": self.allow.get(r.subject, False), "reason": "scripted"}
            for r in requirements
        ]
        if self.mode == "malformed":
            decisions = decisions[:-1]
        return validate_batch(requirements, {"actor_person_id": self.actor, "decisions": decisions})


class SpyRepo:
    """Records every repository method the service touches."""

    def __init__(self, repo):
        self._repo = repo
        self.calls: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self._repo, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                self.calls.append(name)
                return attr(*args, **kwargs)
            return wrapper
        return attr
