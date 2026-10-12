"""The only module that issues SQL. Every read is scoped by ``workspace_id``."""
from __future__ import annotations

import hmac
import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal

from .. import domain
from ..overview import FxRates
from . import db


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@dataclass(frozen=True)
class WorkspaceScope:
    status: domain.WorkspaceStatus
    owner_person_ids: tuple[str, ...]


class IdempotencyConflict(Exception):
    """The idempotency key was already used with different content."""


class FinanceRepository:
    def __init__(self, path: str, *, pepper: bytes) -> None:
        if not pepper:
            raise ValueError("an IBAN-hash pepper is required")
        self.path = path
        self._pepper = pepper
        with self.connection() as conn:
            db.init_schema(conn)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = db.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()

    # --- hashing -----------------------------------------------------------------
    def hash_iban(self, iban: str) -> str:
        """Keyed hash: a bare hash of an IBAN is brute-forceable."""
        normalised = "".join(iban.split()).upper().encode()
        return hmac.new(self._pepper, normalised, hashlib.sha256).hexdigest()

    # --- workspace ---------------------------------------------------------------
    def create_workspace(self, ws: domain.Workspace) -> None:
        with self.connection() as conn, db.write_tx(conn):
            conn.execute(
                "INSERT INTO workspace(id,name,kind,status) VALUES(?,?,?,?)",
                (ws.id, ws.name, ws.kind, ws.status.value))

    def get_workspace(self, workspace_id: str) -> domain.Workspace | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM workspace WHERE id=?", (workspace_id,)).fetchone()
        if row is None:
            return None
        return domain.Workspace(row["id"], row["name"], row["kind"],
                                domain.WorkspaceStatus(row["status"]))

    def add_member(self, workspace_id: str, person_id: str, role: str) -> None:
        with self.connection() as conn, db.write_tx(conn):
            conn.execute(
                "INSERT INTO workspace_member(workspace_id,person_id,role) VALUES(?,?,?)",
                (workspace_id, person_id, role))

    def is_member(self, workspace_id: str, person_id: str) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM workspace_member WHERE workspace_id=? AND person_id=?",
                (workspace_id, person_id)).fetchone()
        return row is not None

    # --- connections -------------------------------------------------------------
    def add_connection(self, c: domain.Connection) -> None:
        with self.connection() as conn, db.write_tx(conn):
            conn.execute(
                "INSERT INTO connection(id,workspace_id,provider,owner_person_id,status,"
                "consent_expires_at,last_success_at) VALUES(?,?,?,?,?,?,?)",
                (c.id, c.workspace_id, c.provider.value, c.owner_person_id, c.status.value,
                 _ts(c.consent_expires_at), _ts(c.last_success_at)))

    # --- accounts ----------------------------------------------------------------
    def add_account(self, a: domain.Account) -> None:
        with self.connection() as conn, db.write_tx(conn):
            conn.execute(
                "INSERT INTO account(id,workspace_id,institution,type,currency,liquidity,"
                "balance_authority,movement_authority,preferred_balance_kind,"
                "freshness_sla_hours,connection_id,provider_account_ref) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.id, a.workspace_id, a.institution, a.type.value, a.currency,
                 a.liquidity.value, a.balance_authority.value, a.movement_authority.value,
                 a.preferred_balance_kind.value, a.freshness_sla_hours, a.connection_id,
                 a.provider_account_ref))
            for position, person in enumerate(a.owner_person_ids):
                conn.execute(
                    "INSERT INTO account_owner(account_id,workspace_id,person_id,position) "
                    "VALUES(?,?,?,?)", (a.id, a.workspace_id, person, position))

    def list_accounts(self, workspace_id: str) -> list[domain.Account]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account WHERE workspace_id=? ORDER BY id", (workspace_id,)
            ).fetchall()
            owners: dict[str, list[str]] = {}
            for o in conn.execute(
                "SELECT account_id, person_id FROM account_owner WHERE workspace_id=? "
                "ORDER BY account_id, position", (workspace_id,)
            ):
                owners.setdefault(o["account_id"], []).append(o["person_id"])
        return [
            domain.Account(
                id=r["id"], workspace_id=r["workspace_id"],
                owner_person_ids=tuple(owners[r["id"]]), institution=r["institution"],
                type=domain.AccountType(r["type"]), currency=r["currency"],
                liquidity=domain.Liquidity(r["liquidity"]),
                balance_authority=domain.BalanceAuthority(r["balance_authority"]),
                movement_authority=domain.Provider(r["movement_authority"]),
                preferred_balance_kind=domain.BalanceKind(r["preferred_balance_kind"]),
                freshness_sla_hours=r["freshness_sla_hours"],
                connection_id=r["connection_id"],
                provider_account_ref=r["provider_account_ref"])
            for r in rows
        ]

    # --- balance observations (immutable facts) ----------------------------------
    def record_balance(self, o: domain.BalanceObservation) -> bool:
        """Insert a balance fact. Returns False when the same observation already exists."""
        with self.connection() as conn, db.write_tx(conn):
            cur = conn.execute(
                "INSERT OR IGNORE INTO balance_observation(id,workspace_id,account_id,"
                "amount_minor,currency,kind,as_of,observed_at,source_ref) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (o.id, o.workspace_id, o.account_id, o.amount_minor, o.currency,
                 o.kind.value, _ts(o.as_of), _ts(o.observed_at), o.source_ref))
            return cur.rowcount == 1

    def latest_balance(self, workspace_id: str, account_id: str,
                       kind: domain.BalanceKind) -> domain.BalanceObservation | None:
        with self.connection() as conn:
            r = conn.execute(
                "SELECT * FROM balance_observation WHERE workspace_id=? AND account_id=? "
                "AND kind=? ORDER BY as_of DESC, observed_at DESC, rowid DESC LIMIT 1",
                (workspace_id, account_id, kind.value)).fetchone()
        if r is None:
            return None
        return domain.BalanceObservation(
            r["id"], r["workspace_id"], r["account_id"], r["amount_minor"], r["currency"],
            domain.BalanceKind(r["kind"]), _dt(r["as_of"]), _dt(r["observed_at"]),
            r["source_ref"])

    # --- movements (immutable facts) ---------------------------------------------
    def insert_movement(self, m: domain.Movement) -> bool:
        """Insert a movement fact. Returns False when it is a duplicate (no effect)."""
        with self.connection() as conn, db.write_tx(conn):
            cur = conn.execute(
                "INSERT OR IGNORE INTO movement(id,workspace_id,account_id,provider_tx_id,"
                "fingerprint,status,booking_date,value_date,amount_minor,currency,"
                "counterparty_name,counterparty_iban_hash,remittance,supersedes_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m.id, m.workspace_id, m.account_id, m.provider_tx_id, m.fingerprint,
                 m.status.value, m.booking_date.isoformat() if m.booking_date else None,
                 m.value_date.isoformat() if m.value_date else None, m.amount_minor,
                 m.currency, m.counterparty_name, m.counterparty_iban_hash, m.remittance,
                 m.supersedes_id))
            return cur.rowcount == 1

    def current_movements(self, workspace_id: str, account_id: str) -> list[domain.Movement]:
        """Movements not superseded by a later fact (a BOOKED row hides its PENDING)."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM movement WHERE workspace_id=? AND account_id=? AND id NOT IN "
                "(SELECT supersedes_id FROM movement WHERE supersedes_id IS NOT NULL) "
                "ORDER BY booking_date, rowid", (workspace_id, account_id)).fetchall()
        return [
            domain.Movement(
                r["id"], r["workspace_id"], r["account_id"], r["provider_tx_id"],
                r["fingerprint"], domain.MovementStatus(r["status"]), _d(r["booking_date"]),
                _d(r["value_date"]), r["amount_minor"], r["currency"],
                r["counterparty_name"], r["counterparty_iban_hash"], r["remittance"],
                r["supersedes_id"])
            for r in rows
        ]

    # --- scope, connections, reference rates -------------------------------------
    def workspace_scope(self, workspace_id: str) -> WorkspaceScope | None:
        """Status and distinct owner ids only: no balances, no names, no movements.

        This is the one read the service may do BEFORE Home authorizes, because it needs
        the owner ids to ask Home about them.
        """
        with self.connection() as conn:
            ws = conn.execute("SELECT status FROM workspace WHERE id=?",
                              (workspace_id,)).fetchone()
            if ws is None:
                return None
            owners = conn.execute(
                "SELECT DISTINCT person_id FROM account_owner WHERE workspace_id=? "
                "ORDER BY person_id", (workspace_id,)).fetchall()
        return WorkspaceScope(domain.WorkspaceStatus(ws["status"]),
                              tuple(o["person_id"] for o in owners))

    def list_connections(self, workspace_id: str) -> list[domain.Connection]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM connection WHERE workspace_id=? ORDER BY id",
                                (workspace_id,)).fetchall()
        return [
            domain.Connection(
                r["id"], r["workspace_id"], domain.Provider(r["provider"]),
                r["owner_person_id"], domain.ConnectionStatus(r["status"]),
                _dt(r["consent_expires_at"]), _dt(r["last_success_at"]))
            for r in rows
        ]

    def store_fx_rates(self, day: date, per_eur: Mapping[str, Decimal]) -> None:
        """Store one day of ECB rates. Same value again is a no-op; a different one fails."""
        with self.connection() as conn, db.write_tx(conn):
            for currency, rate in per_eur.items():
                existing = conn.execute(
                    "SELECT rate FROM fx_rate WHERE date=? AND currency=?",
                    (day.isoformat(), currency)).fetchone()
                if existing is None:
                    conn.execute("INSERT INTO fx_rate(date,currency,rate) VALUES(?,?,?)",
                                 (day.isoformat(), currency, str(rate)))
                elif Decimal(existing["rate"]) != rate:
                    raise ValueError(f"conflicting {currency} rate for {day}")

    def latest_fx_rates(self) -> FxRates | None:
        with self.connection() as conn:
            newest = conn.execute("SELECT MAX(date) AS d FROM fx_rate").fetchone()["d"]
            if newest is None:
                return None
            rows = conn.execute("SELECT currency, rate FROM fx_rate WHERE date=?",
                                (newest,)).fetchall()
        return FxRates(date.fromisoformat(newest),
                       {r["currency"]: Decimal(r["rate"]) for r in rows})

    # --- idempotent commands -----------------------------------------------------
    def run_command(self, workspace_id: str, key: str, command_type: str, payload: dict,
                    effect: Callable[[sqlite3.Connection], dict], *,
                    human_actor: str | None, machine_caller: str, channel: str) -> dict:
        """Run ``effect`` at most once per (workspace, key).

        The effect and its log row commit in ONE transaction, so a crash leaves neither.
        Same key + same payload returns the stored result without running the effect;
        same key + different payload is rejected.
        """
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        payload_hash = hashlib.sha256(f"{command_type}:{canonical}".encode()).hexdigest()
        with self.connection() as conn, db.write_tx(conn):
            row = conn.execute(
                "SELECT payload_hash, result_json FROM command_log "
                "WHERE workspace_id=? AND key=?", (workspace_id, key)).fetchone()
            if row is not None:
                if row["payload_hash"] != payload_hash:
                    raise IdempotencyConflict(key)
                return json.loads(row["result_json"])
            result = effect(conn)
            conn.execute(
                "INSERT INTO command_log(workspace_id,key,command_type,payload_hash,"
                "result_json,human_actor,machine_caller,channel,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (workspace_id, key, command_type, payload_hash, json.dumps(result),
                 human_actor, machine_caller, channel,
                 datetime.now(timezone.utc).isoformat()))
            return result
