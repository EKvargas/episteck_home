"""Receivables (I2) schema. Only adds tables; never alters I1 tables.

Facts are append-only (immutability triggers). Undo is a ``revocation`` row and/or a
``REVERSAL`` ledger entry. Mutable tables hold working state only.
"""
from __future__ import annotations

import sqlite3

FACT_TABLES = (
    "exchange", "exchange_line", "funding", "funding_movement", "funding_exchange",
    "funding_share", "ledger_entry", "receipt", "allocation", "held_cash_statement",
    "payer_rule", "movement_role", "revocation", "intervention_log",
    "partner_identifier", "own_identifier",
)

_TABLES = """
CREATE TABLE IF NOT EXISTS counterparty(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT NOT NULL,
    label TEXT NOT NULL, status TEXT NOT NULL, pay_currency TEXT, settles_to TEXT,
    opening TEXT, alert_below_minor INTEGER);
CREATE TABLE IF NOT EXISTS counterparty_alias(
    workspace_id TEXT NOT NULL, alias TEXT NOT NULL, counterparty_id TEXT NOT NULL,
    PRIMARY KEY(workspace_id, alias));

CREATE TABLE IF NOT EXISTS exchange(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, number INTEGER NOT NULL,
    partner_id TEXT NOT NULL, total_usd_minor INTEGER NOT NULL, delivered_on TEXT NOT NULL,
    created_at TEXT NOT NULL, ves_amount_minor INTEGER, ves_reference_hash TEXT,
    UNIQUE(workspace_id, number));
CREATE INDEX IF NOT EXISTS ix_exchange_ves ON exchange(workspace_id, ves_reference_hash);
CREATE TABLE IF NOT EXISTS exchange_line(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, exchange_id TEXT NOT NULL,
    version INTEGER NOT NULL, position INTEGER NOT NULL, payer_id TEXT NOT NULL,
    usd_minor INTEGER NOT NULL, debt_currency TEXT NOT NULL, beneficiary_note TEXT,
    eur_override_minor INTEGER);
CREATE INDEX IF NOT EXISTS ix_exchange_line ON exchange_line(exchange_id, version);

CREATE TABLE IF NOT EXISTS funding(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, number INTEGER NOT NULL,
    eur_minor INTEGER NOT NULL, usd_minor INTEGER NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(workspace_id, number));
CREATE TABLE IF NOT EXISTS funding_movement(
    workspace_id TEXT NOT NULL, funding_id TEXT NOT NULL, movement_id TEXT NOT NULL,
    PRIMARY KEY(funding_id, movement_id));
CREATE INDEX IF NOT EXISTS ix_funding_movement ON funding_movement(workspace_id, movement_id);
CREATE TABLE IF NOT EXISTS funding_exchange(
    workspace_id TEXT NOT NULL, funding_id TEXT NOT NULL, exchange_id TEXT NOT NULL,
    PRIMARY KEY(funding_id, exchange_id));
CREATE INDEX IF NOT EXISTS ix_funding_exchange ON funding_exchange(workspace_id, exchange_id);
-- Shares are replaced (E11) by revoking the live set and inserting a new one.
CREATE TABLE IF NOT EXISTS funding_share(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, funding_id TEXT NOT NULL,
    payer_id TEXT NOT NULL, eur_minor INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_funding_share ON funding_share(funding_id);

CREATE TABLE IF NOT EXISTS ledger_entry(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, number INTEGER NOT NULL,
    counterparty_id TEXT NOT NULL, currency TEXT NOT NULL, amount_minor INTEGER NOT NULL,
    kind TEXT NOT NULL, effective_on TEXT NOT NULL, source_ref TEXT NOT NULL,
    note TEXT NOT NULL, basis TEXT, reverses_id TEXT,
    UNIQUE(workspace_id, number));
CREATE INDEX IF NOT EXISTS ix_ledger_cp ON ledger_entry(workspace_id, counterparty_id, currency);
CREATE INDEX IF NOT EXISTS ix_ledger_source ON ledger_entry(workspace_id, source_ref);
CREATE INDEX IF NOT EXISTS ix_ledger_reverses ON ledger_entry(reverses_id);

CREATE TABLE IF NOT EXISTS receipt(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, number INTEGER NOT NULL,
    kind TEXT NOT NULL, payer_id TEXT NOT NULL, currency TEXT NOT NULL,
    amount_minor INTEGER NOT NULL, received_on TEXT NOT NULL, verification TEXT NOT NULL,
    movement_id TEXT, description TEXT NOT NULL,
    UNIQUE(workspace_id, number));
-- movement_id is the ROOT movement. One LIVE receipt per root is enforced in code: a
-- revoked receipt must not block re-recording the same movement (Task 8 -> Task 9).
CREATE INDEX IF NOT EXISTS ix_receipt_movement ON receipt(movement_id);
CREATE TABLE IF NOT EXISTS allocation(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, receipt_id TEXT NOT NULL,
    line_id TEXT NOT NULL, amount_minor INTEGER NOT NULL, method TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_allocation_line ON allocation(line_id);
CREATE INDEX IF NOT EXISTS ix_allocation_receipt ON allocation(receipt_id);

CREATE TABLE IF NOT EXISTS held_cash_statement(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, counterparty_id TEXT NOT NULL,
    currency TEXT NOT NULL, amount_minor INTEGER NOT NULL, stated_on TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payer_rule(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, key_hash TEXT NOT NULL,
    counterparty_id TEXT);
CREATE INDEX IF NOT EXISTS ix_payer_rule ON payer_rule(workspace_id, key_hash);
-- movement_id is the ROOT movement (PENDING and its BOOKED successor share one role).
CREATE TABLE IF NOT EXISTS movement_role(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, movement_id TEXT NOT NULL,
    role TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_movement_role ON movement_role(movement_id);
CREATE TABLE IF NOT EXISTS revocation(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, table_name TEXT NOT NULL,
    target_id TEXT NOT NULL, reason TEXT NOT NULL, at TEXT NOT NULL,
    UNIQUE(table_name, target_id));
CREATE TABLE IF NOT EXISTS intervention_log(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL);
-- funding_id: the funding whose owner pick taught this IBAN (R60); NULL when set otherwise.
CREATE TABLE IF NOT EXISTS partner_identifier(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, iban_hash TEXT NOT NULL,
    counterparty_id TEXT NOT NULL, funding_id TEXT);
CREATE INDEX IF NOT EXISTS ix_partner_identifier ON partner_identifier(workspace_id);
CREATE TABLE IF NOT EXISTS own_identifier(
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, iban_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_own_identifier ON own_identifier(workspace_id);

CREATE TABLE IF NOT EXISTS account_watch(
    workspace_id TEXT NOT NULL, account_id TEXT NOT NULL, PRIMARY KEY(workspace_id, account_id));
CREATE TABLE IF NOT EXISTS pending_item(
    workspace_id TEXT NOT NULL, code TEXT NOT NULL, kind TEXT NOT NULL,
    requires_answer INTEGER NOT NULL, options TEXT NOT NULL, payload TEXT NOT NULL,
    dedupe_key TEXT NOT NULL, created_at TEXT NOT NULL, delivered_at TEXT,
    resolved_at TEXT, resolution TEXT, snooze_until TEXT, shown_digest TEXT,
    PRIMARY KEY(workspace_id, code));
CREATE INDEX IF NOT EXISTS ix_pending_dedupe ON pending_item(workspace_id, dedupe_key);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_open_dedupe ON pending_item(workspace_id, dedupe_key)
    WHERE resolved_at IS NULL;
CREATE TABLE IF NOT EXISTS ref_counter(
    workspace_id TEXT NOT NULL, prefix TEXT NOT NULL, last INTEGER NOT NULL,
    PRIMARY KEY(workspace_id, prefix));
CREATE TABLE IF NOT EXISTS matcher_cursor(
    workspace_id TEXT PRIMARY KEY, movement_rowid INTEGER NOT NULL, start_rowid INTEGER);
"""

_TRIGGERS = "\n".join(
    f"CREATE TRIGGER IF NOT EXISTS {t}_no_update BEFORE UPDATE ON {t}\n"
    f"BEGIN SELECT RAISE(ABORT, 'facts are immutable'); END;\n"
    f"CREATE TRIGGER IF NOT EXISTS {t}_no_delete BEFORE DELETE ON {t}\n"
    f"BEGIN SELECT RAISE(ABORT, 'facts are immutable'); END;"
    for t in FACT_TABLES
)

SCHEMA_I2 = _TABLES + _TRIGGERS + "\n"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def upgrade_i2(conn: sqlite3.Connection) -> None:
    """Brings I2 tables made by an earlier build up to date; idempotent, safe when several
    processes open the file at once (R37).

    ``matcher_cursor.start_rowid`` (the go-live mark): added when missing, and set to the
    row's cursor where NULL, so movements the matcher already passed stay history.
    ``pending_item.shown_digest`` (the options last delivered, R44): added when missing.
    ``partner_identifier.funding_id`` (the funding that taught the IBAN, R60): added when
    missing; identifiers learned before it stay NULL (no funding to undo them with).
    """
    _add_column(conn, "matcher_cursor", "start_rowid", "INTEGER")
    conn.execute("UPDATE matcher_cursor SET start_rowid=movement_rowid WHERE start_rowid IS NULL")
    _add_column(conn, "pending_item", "shown_digest", "TEXT")
    _add_column(conn, "partner_identifier", "funding_id", "TEXT")


def _add_column(conn: sqlite3.Connection, table: str, column: str, kind: str) -> None:
    if column not in _columns(conn, table):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        except sqlite3.OperationalError:
            if column not in _columns(conn, table):
                raise  # not another process adding it first
