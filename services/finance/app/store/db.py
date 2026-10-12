"""SQLite connection profile, schema and immutability triggers.

Durability profile (same as the one validated for Knowledge): WAL, synchronous=FULL,
foreign keys on, a busy timeout, and ``BEGIN IMMEDIATE`` for every write so two
processes (API, MCP, sync timer) sharing the file serialise cleanly.

Facts (balance observations, movements) are immutable at the database level: a trigger
rejects UPDATE and DELETE, so immutability does not depend on callers behaving.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

BUSY_TIMEOUT_MS = 10_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace(
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS workspace_member(
    workspace_id TEXT NOT NULL REFERENCES workspace(id),
    person_id TEXT NOT NULL, role TEXT NOT NULL,
    PRIMARY KEY(workspace_id, person_id));

CREATE TABLE IF NOT EXISTS connection(
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspace(id),
    provider TEXT NOT NULL, owner_person_id TEXT NOT NULL, status TEXT NOT NULL,
    consent_expires_at TEXT, last_success_at TEXT,
    UNIQUE(id, workspace_id));

CREATE TABLE IF NOT EXISTS account(
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspace(id),
    institution TEXT NOT NULL, type TEXT NOT NULL, currency TEXT NOT NULL,
    liquidity TEXT NOT NULL, balance_authority TEXT NOT NULL,
    movement_authority TEXT NOT NULL, preferred_balance_kind TEXT NOT NULL,
    freshness_sla_hours INTEGER NOT NULL,
    connection_id TEXT, provider_account_ref TEXT,
    UNIQUE(id, workspace_id),
    UNIQUE(workspace_id, connection_id, provider_account_ref),
    FOREIGN KEY(connection_id, workspace_id) REFERENCES connection(id, workspace_id));

CREATE TABLE IF NOT EXISTS account_owner(
    account_id TEXT NOT NULL, workspace_id TEXT NOT NULL, person_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY(account_id, person_id),
    FOREIGN KEY(account_id, workspace_id) REFERENCES account(id, workspace_id));

CREATE TABLE IF NOT EXISTS balance_observation(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, account_id TEXT NOT NULL,
    amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, kind TEXT NOT NULL,
    as_of TEXT NOT NULL, observed_at TEXT NOT NULL, source_ref TEXT NOT NULL,
    UNIQUE(account_id, kind, as_of, amount_minor),
    FOREIGN KEY(account_id, workspace_id) REFERENCES account(id, workspace_id));
CREATE INDEX IF NOT EXISTS ix_balance_latest ON balance_observation(account_id, kind, as_of);

CREATE TABLE IF NOT EXISTS movement(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, account_id TEXT NOT NULL,
    provider_tx_id TEXT, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
    booking_date TEXT, value_date TEXT, amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL, counterparty_name TEXT NOT NULL,
    counterparty_iban_hash TEXT, remittance TEXT NOT NULL,
    supersedes_id TEXT REFERENCES movement(id),
    FOREIGN KEY(account_id, workspace_id) REFERENCES account(id, workspace_id));
CREATE UNIQUE INDEX IF NOT EXISTS ux_movement_provider
    ON movement(account_id, provider_tx_id) WHERE provider_tx_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_movement_fingerprint
    ON movement(account_id, fingerprint) WHERE provider_tx_id IS NULL;

CREATE TABLE IF NOT EXISTS command_log(
    workspace_id TEXT NOT NULL, key TEXT NOT NULL, command_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL, result_json TEXT NOT NULL,
    human_actor TEXT, machine_caller TEXT NOT NULL, channel TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, key));

-- ECB reference data is global by nature; it is the only table without a tenant.
CREATE TABLE IF NOT EXISTS fx_rate(
    date TEXT NOT NULL, currency TEXT NOT NULL, rate TEXT NOT NULL,
    PRIMARY KEY(date, currency));

CREATE TABLE IF NOT EXISTS sync_run(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, connection_id TEXT,
    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, detail TEXT);

CREATE TABLE IF NOT EXISTS access_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL, requested_at TEXT NOT NULL, kind TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_access_log ON access_log(account_id, requested_at);

CREATE TRIGGER IF NOT EXISTS balance_observation_no_update BEFORE UPDATE ON balance_observation
BEGIN SELECT RAISE(ABORT, 'facts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS balance_observation_no_delete BEFORE DELETE ON balance_observation
BEGIN SELECT RAISE(ABORT, 'facts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS movement_no_update BEFORE UPDATE ON movement
BEGIN SELECT RAISE(ABORT, 'facts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS movement_no_delete BEFORE DELETE ON movement
BEGIN SELECT RAISE(ABORT, 'facts are immutable'); END;
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One IMMEDIATE transaction: commit on success, roll back on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
