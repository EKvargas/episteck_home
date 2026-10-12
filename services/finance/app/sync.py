"""Sync engine: pull balances and movements from connectors into the store.

Rules (proposal §5.1, §6.7, §6.8):
* a failed fetch never writes a balance, so a failure can never look like zero;
* balances and movements are ingested in separate atomic transactions per account;
* one failing account or connection never blocks the others;
* provider rate limits are a budget stop, not a failure, and are never retried in-run;
* every run is audited (``sync_run``) as channel ``sync``.

``python -m app.sync`` performs one pass and exits non-zero if any connection failed, so
systemd records the failure.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import domain
from .connectors.base import Connector, ConnectorError, ErrorKind, RawMovement
from .connectors.ecb import refresh_rates
from .store.repo import FinanceRepository

logger = logging.getLogger("finance.sync")

MACHINE_CALLER = "svc-finance-sync"
CHANNEL = "sync"
_AUTH_KINDS = (ErrorKind.AUTH_REQUIRED, ErrorKind.CONSENT_EXPIRED)


@dataclass
class ConnectionResult:
    connection_id: str
    status: str  # OK | FAILED | SKIPPED | RATE_LIMITED
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncReport:
    results: list[ConnectionResult] = field(default_factory=list)

    @property
    def any_failed(self) -> bool:
        return any(r.status == "FAILED" for r in self.results)


def fingerprint(m: RawMovement, ordinal: int) -> str:
    """Stable identity for movements without a provider id. Excludes status on purpose."""
    parts = [m.booking_date.isoformat() if m.booking_date else "", str(m.amount_minor),
             m.currency, m.counterparty_name, m.remittance, str(ordinal)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


class SyncEngine:
    def __init__(self, repo: FinanceRepository, connectors: Mapping[str, Connector], *,
                 ecb=None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 lookback_days: int = 30) -> None:
        self._repo = repo
        self._connectors = connectors
        self._ecb = ecb
        self._clock = clock
        self._lookback = timedelta(days=lookback_days)

    # --- public -------------------------------------------------------------------
    def run(self, workspace_id: str) -> SyncReport:
        report = SyncReport()
        workspace = self._repo.get_workspace(workspace_id)
        if workspace is None or workspace.status is not domain.WorkspaceStatus.ACTIVE:
            return report
        if self._ecb is not None:
            refresh_rates(self._repo, self._ecb)  # never raises; old rates simply stay
        accounts = self._repo.list_accounts(workspace_id)
        for connection in self._repo.list_connections(workspace_id):
            report.results.append(self._sync_connection(connection, accounts))
        return report

    # --- one connection -----------------------------------------------------------
    def _sync_connection(self, connection: domain.Connection,
                         accounts: list[domain.Account]) -> ConnectionResult:
        if connection.status is domain.ConnectionStatus.PAUSED:
            return ConnectionResult(connection.id, "SKIPPED")
        connector = self._connectors.get(connection.id)
        if connector is None:
            logger.warning("sync failed: no connector for a connection")
            return ConnectionResult(connection.id, "FAILED", ["no_connector"])
        run_id = uuid.uuid4().hex
        now = self._clock()
        self._repo.start_sync_run(run_id, connection.workspace_id, connection.id, now,
                                  MACHINE_CALLER, CHANNEL)
        errors: list[str] = []
        auth_failed = rate_limited = False
        for account in (a for a in accounts if a.connection_id == connection.id):
            outcome = self._sync_account(connector, account, run_id, now)
            errors += outcome.errors
            rate_limited = rate_limited or outcome.rate_limited
            if outcome.auth_failed:
                auth_failed = True
                break  # the remaining accounts of this connection would fail the same way
        ws = connection.workspace_id
        if auth_failed:
            self._repo.set_connection_status(ws, connection.id, domain.ConnectionStatus.REAUTH_REQUIRED)
        elif errors:
            self._repo.set_connection_status(ws, connection.id, domain.ConnectionStatus.FAILING)
        elif not rate_limited:
            self._repo.set_connection_status(ws, connection.id, domain.ConnectionStatus.OK, now)
        failed = bool(errors)
        self._repo.finish_sync_run(run_id, self._clock(), "FAILED" if failed else "OK",
                                   ",".join(sorted(set(errors))))
        status = "FAILED" if failed else ("RATE_LIMITED" if rate_limited else "OK")
        return ConnectionResult(connection.id, status, errors)

    # --- one account --------------------------------------------------------------
    @dataclass
    class _Outcome:
        errors: list[str] = field(default_factory=list)
        auth_failed: bool = False
        rate_limited: bool = False

    def _sync_account(self, connector: Connector, account: domain.Account, run_id: str,
                      now: datetime) -> "_Outcome":
        outcome = self._Outcome()
        ref = account.provider_account_ref or ""
        try:
            raw = connector.fetch_balances(ref)
            self._repo.ingest_balances([
                domain.BalanceObservation(uuid.uuid4().hex, account.workspace_id, account.id,
                                          b.amount_minor, b.currency, b.kind, b.as_of, now, run_id)
                for b in raw])
        except ConnectorError as error:
            self._record(outcome, error.kind)
            return outcome  # no balance means no point asking for movements
        except Exception:
            logger.warning("sync account failed: balance_ingest_error")
            outcome.errors.append("ingest_error")
            return outcome
        try:
            since = (now - self._lookback).date()
            moves = self._build_movements(account, connector.fetch_movements(ref, since))
            self._repo.ingest_movements(account.workspace_id, account.id, moves)
        except ConnectorError as error:
            self._record(outcome, error.kind)
        except Exception:
            logger.warning("sync account failed: movement_ingest_error")
            outcome.errors.append("ingest_error")
        return outcome

    @staticmethod
    def _record(outcome: "SyncEngine._Outcome", kind: ErrorKind) -> None:
        logger.warning("sync account not synced: %s", kind.value)
        if kind in _AUTH_KINDS:
            outcome.auth_failed = True
            outcome.errors.append(kind.value)
        elif kind is ErrorKind.RATE_LIMITED:
            outcome.rate_limited = True
        else:
            outcome.errors.append(kind.value)

    def _build_movements(self, account: domain.Account,
                         raws: list[RawMovement]) -> list[domain.Movement]:
        seen: Counter = Counter()
        out = []
        for m in raws:
            key = (m.booking_date, m.amount_minor, m.currency, m.counterparty_name, m.remittance)
            ordinal = seen[key]
            seen[key] += 1
            out.append(domain.Movement(
                uuid.uuid4().hex, account.workspace_id, account.id, m.provider_tx_id,
                fingerprint(m, ordinal), m.status, m.booking_date, m.value_date,
                m.amount_minor, m.currency, m.counterparty_name,
                self._repo.hash_iban(m.counterparty_iban) if m.counterparty_iban else None,
                m.remittance))
        return out


def _default_ecb():
    from .connectors.ecb import EcbRates
    return EcbRates()


def main() -> int:
    """One sync pass for the configured workspace; non-zero exit if any connection failed."""
    from .config import Settings
    from .wiring import build_connectors

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    if not settings.secrets_dir:
        raise SystemExit("FINANCE_SECRETS_DIR is required")
    repo = FinanceRepository(settings.db_path, pepper=settings.pepper)
    engine = SyncEngine(repo, build_connectors(repo, settings.workspace_id, settings.secrets_dir,
                                           eb_access_cap=settings.eb_access_cap),
                        ecb=_default_ecb())
    report = engine.run(settings.workspace_id)
    for result in report.results:  # statuses only: no ids of people, no amounts
        logger.info("connection %s: %s", result.connection_id, result.status)
    return 1 if report.any_failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
