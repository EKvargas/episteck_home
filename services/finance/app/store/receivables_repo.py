"""Receivables SQL. Every method takes an open connection first. Facts are never edited.

Scoping: reads that take ``ws`` are workspace-scoped. Reads keyed by a globally unique id
are id-scoped and take no workspace: ``current_lines``, ``live_funding_for_exchange``,
``live_funding_for_movement``, ``funding_shares``, ``live_receipt_for_movement``,
``movement_role``, ``live_role_ids_for_movement``, ``movement_root`` and ``is_live``.
``usd_per_eur_on`` reads the global ECB table. Callers pass only ids they obtained from a
workspace-scoped read.

"Live" means no ``revocation`` row for ``(table_name, target_id)``. Readers of revocable
tables return live rows only, except ``entries`` (full history, by design) and the ref
lookups asked for history (``include_revoked=True`` / ``include_undone=True``). Human refs
``C<n>``/``F<n>``/``R<n>``/``E<n>`` match case-insensitively. An "effective" ledger entry
is live and not undone by a live ``REVERSAL`` (``_effective``). Movement ids in
``funding_movement``, ``receipt`` and ``movement_role`` are ROOT ids (``movement_root``), so
a PENDING movement and its BOOKED successor share one funding, receipt and role.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from .. import domain
from ..receivables.allocation import OpenLine
from ..receivables.model import (
    Allocation, AllocationMethod, Counterparty, CounterpartyKind, EntryKind, Exchange,
    ExchangeLine, Funding, LedgerEntry, MovementRoleKind, Opening, PendingItem, PendingKind,
    Receipt, ReceiptKind, Verification,
)
from ..receivables.text import normalize_alias
from . import db
from .repo import FinanceRepository, _d, _dt, _ts

IGNORE: Literal["IGNORE"] = "IGNORE"

REVOCABLE_TABLES = frozenset({
    "exchange", "funding", "funding_share", "ledger_entry", "receipt", "allocation",
    "payer_rule", "movement_role", "partner_identifier",
})


MAX_REF_DIGITS = 9  # "C<n>" refs; longer digit strings are not refs (and overflow SQLite)
MAX_LINE_POSITION = 99  # open-line order is exchange number * 100 + position


class DuplicateAlias(Exception):
    """An alias is already used by another counterparty in the workspace.

    The alias stays on ``.alias``; the message is generic so logs never carry it (§6.9).
    """

    def __init__(self, alias: str) -> None:
        super().__init__("alias already in use in this workspace")
        self.alias = alias


class DuplicateReceipt(Exception):
    """A live receipt already exists for this bank movement (root-aware)."""

    def __init__(self, movement_id: str, receipt_id: str) -> None:
        super().__init__("a live receipt already exists for this movement")
        self.movement_id = movement_id
        self.receipt_id = receipt_id


class AlreadyRevoked(Exception):
    """The target row already carries a revocation."""


def _live(table: str, alias: str, id_col: str = "id") -> str:
    return (f"NOT EXISTS (SELECT 1 FROM revocation rv WHERE rv.table_name='{table}' "
            f"AND rv.target_id={alias}.{id_col})")


def _reversed(alias: str) -> str:
    """The ledger entry ``alias`` is undone by a live ``REVERSAL``."""
    return (f"EXISTS (SELECT 1 FROM ledger_entry rx WHERE rx.reverses_id={alias}.id "
            f"AND rx.kind='REVERSAL' AND {_live('ledger_entry', 'rx')})")


def _effective(alias: str) -> str:
    """The ledger entry ``alias`` still counts: live and not undone by a live REVERSAL.

    The one definition of an effective entry; reuse it in every query that must not count
    an undone CHARGE/PAYMENT/OPENING (balances stay sums of live entries, reversals included).
    """
    return f"{_live('ledger_entry', alias)} AND NOT {_reversed(alias)}"


def _new_id() -> str:
    return uuid.uuid4().hex


def _ref_number(ref: str, prefix: str) -> int | None:
    """``"<prefix><n>"`` (case-insensitive, surrounding spaces ignored) -> n, else ``None``."""
    text = ref.strip()
    digits = text[1:]
    if (len(text) < 2 or text[0].upper() != prefix or not digits.isascii()
            or not digits.isdigit() or len(digits) > MAX_REF_DIGITS):
        return None
    return int(digits)


def _code(code: str) -> str:
    """Pending codes are matched case-insensitively: " p3" finds "P3"."""
    return code.strip().upper()


def _cp(r: sqlite3.Row) -> Counterparty:
    return Counterparty(
        r["id"], r["workspace_id"], CounterpartyKind(r["kind"]), r["label"], r["status"],
        r["pay_currency"], r["settles_to"], Opening(r["opening"]) if r["opening"] else None,
        r["alert_below_minor"])


def _exchange(r: sqlite3.Row) -> Exchange:
    return Exchange(
        r["id"], r["workspace_id"], r["number"], r["partner_id"], r["total_usd_minor"],
        _d(r["delivered_on"]), _dt(r["created_at"]), r["ves_amount_minor"],
        r["ves_reference_hash"])


def _line(r: sqlite3.Row) -> ExchangeLine:
    return ExchangeLine(
        r["id"], r["exchange_id"], r["version"], r["position"], r["payer_id"], r["usd_minor"],
        r["debt_currency"], r["beneficiary_note"], r["eur_override_minor"])


def _entry(r: sqlite3.Row) -> LedgerEntry:
    return LedgerEntry(
        r["id"], r["workspace_id"], r["number"], r["counterparty_id"], r["currency"],
        r["amount_minor"], EntryKind(r["kind"]), _d(r["effective_on"]), r["source_ref"],
        r["note"], r["basis"], r["reverses_id"])


def _receipt(r: sqlite3.Row) -> Receipt:
    return Receipt(
        r["id"], r["workspace_id"], r["number"], ReceiptKind(r["kind"]), r["payer_id"],
        r["currency"], r["amount_minor"], _d(r["received_on"]), Verification(r["verification"]),
        r["movement_id"], r["description"])


def _allocation(r: sqlite3.Row) -> Allocation:
    return Allocation(r["id"], r["workspace_id"], r["receipt_id"], r["line_id"],
                      r["amount_minor"], AllocationMethod(r["method"]))


def _pending(r: sqlite3.Row) -> PendingItem:
    return PendingItem(
        r["code"], r["workspace_id"], PendingKind(r["kind"]), bool(r["requires_answer"]),
        tuple(json.loads(r["options"])), json.loads(r["payload"]), r["dedupe_key"],
        _dt(r["created_at"]), _dt(r["delivered_at"]), _dt(r["resolved_at"]), r["resolution"],
        _dt(r["snooze_until"]))


def _movement(r: sqlite3.Row) -> domain.Movement:
    return domain.Movement(
        r["id"], r["workspace_id"], r["account_id"], r["provider_tx_id"], r["fingerprint"],
        domain.MovementStatus(r["status"]), _d(r["booking_date"]), _d(r["value_date"]),
        r["amount_minor"], r["currency"], r["counterparty_name"], r["counterparty_iban_hash"],
        r["remittance"], r["supersedes_id"])


class ReceivablesRepository:
    def __init__(self, base: FinanceRepository) -> None:
        self.base = base  # constructing FinanceRepository already created the I2 schema

    # --- connections -------------------------------------------------------------
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.base.connection() as conn, db.write_tx(conn):
            yield conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self.base.connection() as conn:
            yield conn

    def hash_key(self, text: str) -> str:
        return self.base.hash_iban(text)

    def next_number(self, conn, ws: str, prefix: str) -> int:
        conn.execute(
            "INSERT INTO ref_counter(workspace_id,prefix,last) VALUES(?,?,1) "
            "ON CONFLICT(workspace_id,prefix) DO UPDATE SET last=last+1", (ws, prefix))
        return conn.execute("SELECT last FROM ref_counter WHERE workspace_id=? AND prefix=?",
                            (ws, prefix)).fetchone()["last"]

    # --- counterparties ----------------------------------------------------------
    def insert_counterparty(self, conn, cp: Counterparty, aliases: Sequence[str]) -> None:
        keys = [normalize_alias(a) for a in aliases]
        if not all(keys):
            raise ValueError("an alias is empty once normalised")
        for key in keys:
            taken = conn.execute(
                "SELECT 1 FROM counterparty_alias WHERE workspace_id=? AND alias=?",
                (cp.workspace_id, key)).fetchone()
            if taken is not None:
                raise DuplicateAlias(key)
        conn.execute(
            "INSERT INTO counterparty(id,workspace_id,kind,label,status,pay_currency,settles_to,"
            "opening,alert_below_minor) VALUES(?,?,?,?,?,?,?,?,?)",
            (cp.id, cp.workspace_id, cp.kind.value, cp.label, cp.status, cp.pay_currency,
             cp.settles_to, cp.opening.value if cp.opening else None, cp.alert_below_minor))
        for key in dict.fromkeys(keys):
            conn.execute(
                "INSERT INTO counterparty_alias(workspace_id,alias,counterparty_id) VALUES(?,?,?)",
                (cp.workspace_id, key, cp.id))

    def find_by_alias(self, conn, ws: str, text: str) -> list[Counterparty]:
        key = normalize_alias(text)
        if not key:
            return []
        rows = conn.execute(
            "SELECT c.* FROM counterparty c JOIN counterparty_alias a "
            "ON a.counterparty_id=c.id AND a.workspace_id=c.workspace_id "
            "WHERE a.workspace_id=? AND a.alias=? ORDER BY c.rowid",
            (ws, key)).fetchall()
        return [_cp(r) for r in rows]

    def get_counterparty(self, conn, ws: str, cp_id: str) -> Counterparty | None:
        r = conn.execute("SELECT * FROM counterparty WHERE workspace_id=? AND id=?",
                         (ws, cp_id)).fetchone()
        return _cp(r) if r else None

    def list_counterparties(self, conn, ws: str) -> list[Counterparty]:
        rows = conn.execute("SELECT * FROM counterparty WHERE workspace_id=? ORDER BY rowid",
                            (ws,)).fetchall()
        return [_cp(r) for r in rows]

    def set_opening(self, conn, ws: str, cp_id: str, opening: Opening | None) -> None:
        """``counterparty`` is working state (mutable); the OPENING entries are the facts."""
        conn.execute("UPDATE counterparty SET opening=? WHERE workspace_id=? AND id=?",
                     (opening.value if opening else None, ws, cp_id))

    # --- exchanges and fundings --------------------------------------------------
    def insert_exchange(self, conn, ex: Exchange, lines: Sequence[ExchangeLine]) -> None:
        self._check_lines(ex.id, lines)
        conn.execute(
            "INSERT INTO exchange(id,workspace_id,number,partner_id,total_usd_minor,delivered_on,"
            "created_at,ves_amount_minor,ves_reference_hash) VALUES(?,?,?,?,?,?,?,?,?)",
            (ex.id, ex.workspace_id, ex.number, ex.partner_id, ex.total_usd_minor,
             ex.delivered_on.isoformat(), _ts(ex.created_at), ex.ves_amount_minor,
             ex.ves_reference_hash))
        self.insert_lines(conn, ex.workspace_id, ex.id, lines)

    def insert_lines(self, conn, ws: str, exchange_id: str,
                     lines: Sequence[ExchangeLine]) -> None:
        """Lines of an exchange; a correction inserts a new ``version`` (§6.8)."""
        self._check_lines(exchange_id, lines)
        for ln in lines:
            conn.execute(
                "INSERT INTO exchange_line(id,workspace_id,exchange_id,version,position,payer_id,"
                "usd_minor,debt_currency,beneficiary_note,eur_override_minor) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ln.id, ws, ln.exchange_id, ln.version, ln.position, ln.payer_id,
                 ln.usd_minor, ln.debt_currency, ln.beneficiary_note, ln.eur_override_minor))

    @staticmethod
    def _check_lines(exchange_id: str, lines: Sequence[ExchangeLine]) -> None:
        for ln in lines:
            if ln.exchange_id != exchange_id:
                raise ValueError("every line must belong to the exchange being inserted")
            if not 0 <= ln.position <= MAX_LINE_POSITION:
                raise ValueError(f"line position must be between 0 and {MAX_LINE_POSITION}")

    def current_lines(self, conn, exchange_id: str) -> list[ExchangeLine]:
        rows = conn.execute(
            "SELECT * FROM exchange_line WHERE exchange_id=? AND version="
            "(SELECT MAX(version) FROM exchange_line WHERE exchange_id=?) ORDER BY position, rowid",
            (exchange_id, exchange_id)).fetchall()
        return [_line(r) for r in rows]

    def open_exchanges(self, conn, ws: str) -> list[Exchange]:
        rows = conn.execute(
            f"SELECT e.* FROM exchange e WHERE e.workspace_id=? AND {_live('exchange', 'e')} "
            "AND NOT EXISTS (SELECT 1 FROM funding_exchange fe JOIN funding f ON f.id=fe.funding_id "
            f"WHERE fe.exchange_id=e.id AND {_live('funding', 'f')}) ORDER BY e.number",
            (ws,)).fetchall()
        return [_exchange(r) for r in rows]

    def exchange_by_ref(self, conn, ws: str, ref: str, *,
                        include_revoked: bool = False) -> Exchange | None:
        """``C<n>`` -> the live exchange; ``include_revoked`` also finds a revoked one (history)."""
        number = _ref_number(ref, "C")
        if number is None:
            return None
        live = "" if include_revoked else f" AND {_live('exchange', 'e')}"
        r = conn.execute(f"SELECT e.* FROM exchange e WHERE e.workspace_id=? AND e.number=?{live}",
                         (ws, number)).fetchone()
        return _exchange(r) if r else None

    def exchange_by_id(self, conn, ws: str, exchange_id: str) -> Exchange | None:
        """The live exchange; ``None`` if unknown, of another workspace or revoked."""
        r = conn.execute(f"SELECT e.* FROM exchange e WHERE e.workspace_id=? AND e.id=? "
                         f"AND {_live('exchange', 'e')}", (ws, exchange_id)).fetchone()
        return _exchange(r) if r else None

    def exchange_by_ves_hash(self, conn, ws: str, h: str) -> Exchange | None:
        r = conn.execute(
            f"SELECT e.* FROM exchange e WHERE e.workspace_id=? AND e.ves_reference_hash=? "
            f"AND {_live('exchange', 'e')} ORDER BY e.number LIMIT 1", (ws, h)).fetchone()
        return _exchange(r) if r else None

    def insert_funding(self, conn, f: Funding, shares: Mapping[str, int]) -> None:
        """Stores ``f.movement_ids`` as ROOT ids (deduplicated); reads return the roots."""
        conn.execute(
            "INSERT INTO funding(id,workspace_id,number,eur_minor,usd_minor,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (f.id, f.workspace_id, f.number, f.eur_minor, f.usd_minor, _ts(f.created_at)))
        for mid in dict.fromkeys(self.movement_root(conn, m) for m in f.movement_ids):
            conn.execute("INSERT INTO funding_movement(workspace_id,funding_id,movement_id) "
                         "VALUES(?,?,?)", (f.workspace_id, f.id, mid))
        for eid in f.exchange_ids:
            conn.execute("INSERT INTO funding_exchange(workspace_id,funding_id,exchange_id) "
                         "VALUES(?,?,?)", (f.workspace_id, f.id, eid))
        self._insert_shares(conn, f.workspace_id, f.id, shares)

    def _insert_shares(self, conn, ws: str, funding_id: str, shares: Mapping[str, int]) -> None:
        for payer, eur in shares.items():
            conn.execute(
                "INSERT INTO funding_share(id,workspace_id,funding_id,payer_id,eur_minor) "
                "VALUES(?,?,?,?,?)", (_new_id(), ws, funding_id, payer, eur))

    def _funding(self, conn, row: sqlite3.Row | None) -> Funding | None:
        """Read-back: ``movement_ids`` are ROOT movement ids, whatever ids were inserted."""
        if row is None:
            return None
        fid = row["id"]
        mids = tuple(r["movement_id"] for r in conn.execute(
            "SELECT movement_id FROM funding_movement WHERE funding_id=? ORDER BY rowid", (fid,)))
        eids = tuple(r["exchange_id"] for r in conn.execute(
            "SELECT exchange_id FROM funding_exchange WHERE funding_id=? ORDER BY rowid", (fid,)))
        return Funding(fid, row["workspace_id"], row["number"], mids, eids, row["eur_minor"],
                       row["usd_minor"], _dt(row["created_at"]))

    def live_funding_for_exchange(self, conn, exchange_id: str) -> Funding | None:
        """The live funding of an exchange; its ``movement_ids`` are ROOT ids."""
        r = conn.execute(
            "SELECT f.* FROM funding f JOIN funding_exchange fe ON fe.funding_id=f.id "
            f"WHERE fe.exchange_id=? AND {_live('funding', 'f')} ORDER BY f.rowid LIMIT 1",
            (exchange_id,)).fetchone()
        return self._funding(conn, r)

    def live_funding_for_movement(self, conn, movement_id: str) -> Funding | None:
        """Root-aware lookup; the returned ``movement_ids`` are ROOT ids."""
        root = self.movement_root(conn, movement_id)
        r = conn.execute(
            "SELECT f.* FROM funding f JOIN funding_movement fm ON fm.funding_id=f.id "
            f"WHERE fm.movement_id=? AND {_live('funding', 'f')} ORDER BY f.rowid LIMIT 1",
            (root,)).fetchone()
        return self._funding(conn, r)

    def funding_shares(self, conn, funding_id: str) -> dict[str, int]:
        """Live shares, in insertion order (the order the caller computed them in)."""
        rows = conn.execute(
            f"SELECT s.payer_id, s.eur_minor FROM funding_share s WHERE s.funding_id=? "
            f"AND {_live('funding_share', 's')} ORDER BY s.rowid", (funding_id,)).fetchall()
        return {r["payer_id"]: r["eur_minor"] for r in rows}

    def replace_funding_shares(self, conn, ws: str, funding_id: str, shares: Mapping[str, int],
                               reason: str, at: datetime) -> None:
        """Revokes the live shares of a live funding and inserts ``shares`` (E11)."""
        funding = conn.execute(
            f"SELECT 1 FROM funding f WHERE f.workspace_id=? AND f.id=? "
            f"AND {_live('funding', 'f')}", (ws, funding_id)).fetchone()
        if funding is None:
            raise ValueError("shares can only be replaced on a live funding")
        live = conn.execute(
            f"SELECT s.id FROM funding_share s WHERE s.workspace_id=? AND s.funding_id=? "
            f"AND {_live('funding_share', 's')} ORDER BY s.rowid", (ws, funding_id)).fetchall()
        for r in live:
            self.revoke(conn, ws, "funding_share", r["id"], reason, at)
        self._insert_shares(conn, ws, funding_id, shares)

    def funding_by_id(self, conn, ws: str, funding_id: str) -> Funding | None:
        """The live funding; ``None`` if unknown, of another workspace or revoked."""
        r = conn.execute(f"SELECT f.* FROM funding f WHERE f.workspace_id=? AND f.id=? "
                         f"AND {_live('funding', 'f')}", (ws, funding_id)).fetchone()
        return self._funding(conn, r)

    def funding_by_ref(self, conn, ws: str, ref: str, *,
                       include_revoked: bool = False) -> Funding | None:
        """``F<n>`` -> the live funding; ``include_revoked`` also finds a revoked one."""
        number = _ref_number(ref, "F")
        if number is None:
            return None
        live = "" if include_revoked else f" AND {_live('funding', 'f')}"
        r = conn.execute(f"SELECT f.* FROM funding f WHERE f.workspace_id=? AND f.number=?{live}",
                         (ws, number)).fetchone()
        return self._funding(conn, r)

    def latest_funded_exchange(self, conn, ws: str, day: date) -> Exchange | None:
        """The live exchange with a live funding delivered last on or before ``day``."""
        r = conn.execute(
            f"SELECT e.* FROM exchange e WHERE e.workspace_id=? AND e.delivered_on<=? "
            f"AND {_live('exchange', 'e')} AND EXISTS (SELECT 1 FROM funding_exchange fe "
            f"JOIN funding f ON f.id=fe.funding_id WHERE fe.exchange_id=e.id "
            f"AND {_live('funding', 'f')}) ORDER BY e.delivered_on DESC, e.number DESC LIMIT 1",
            (ws, day.isoformat())).fetchone()
        return _exchange(r) if r else None

    # --- ledger and receipts -----------------------------------------------------
    def insert_entry(self, conn, e: LedgerEntry) -> None:
        """A ``REVERSAL`` must undo exactly one effective, non-REVERSAL entry (no double undo)."""
        if e.kind is EntryKind.REVERSAL:
            self._check_reversal_target(conn, e)
        elif e.reverses_id is not None:
            raise ValueError("only a REVERSAL may reference another entry")
        conn.execute(
            "INSERT INTO ledger_entry(id,workspace_id,number,counterparty_id,currency,"
            "amount_minor,kind,effective_on,source_ref,note,basis,reverses_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.id, e.workspace_id, e.number, e.counterparty_id, e.currency, e.amount_minor,
             e.kind.value, e.effective_on.isoformat(), e.source_ref, e.note, e.basis,
             e.reverses_id))

    def _check_reversal_target(self, conn, e: LedgerEntry) -> None:
        if e.reverses_id is None:
            raise ValueError("a REVERSAL must reference the entry it undoes")
        target = conn.execute(
            f"SELECT l.kind, l.counterparty_id, l.currency, l.amount_minor FROM ledger_entry l "
            f"WHERE l.workspace_id=? AND l.id=? AND {_effective('l')}",
            (e.workspace_id, e.reverses_id)).fetchone()
        if target is None:
            raise ValueError("the reversed entry is unknown, revoked or already reversed")
        if target["kind"] == EntryKind.REVERSAL.value:
            raise ValueError("a REVERSAL cannot itself be reversed")
        if (target["counterparty_id"] != e.counterparty_id or target["currency"] != e.currency
                or e.amount_minor != -target["amount_minor"]):
            raise ValueError("a REVERSAL must negate its target for the same party and currency")

    def balance(self, conn, ws: str, cp_id: str, currency: str) -> int:
        return conn.execute(
            f"SELECT COALESCE(SUM(amount_minor),0) AS s FROM ledger_entry l WHERE l.workspace_id=? "
            f"AND l.counterparty_id=? AND l.currency=? AND {_live('ledger_entry', 'l')}",
            (ws, cp_id, currency)).fetchone()["s"]

    def balances(self, conn, ws: str) -> dict[tuple[str, str], int]:
        rows = conn.execute(
            f"SELECT counterparty_id, currency, SUM(amount_minor) AS s FROM ledger_entry l "
            f"WHERE l.workspace_id=? AND {_live('ledger_entry', 'l')} "
            "GROUP BY counterparty_id, currency", (ws,)).fetchall()
        return {(r["counterparty_id"], r["currency"]): r["s"] for r in rows}

    def entries(self, conn, ws: str, cp_id: str) -> list[LedgerEntry]:
        rows = conn.execute(
            "SELECT * FROM ledger_entry WHERE workspace_id=? AND counterparty_id=? "
            "ORDER BY number", (ws, cp_id)).fetchall()
        return [_entry(r) for r in rows]

    def entry_by_ref(self, conn, ws: str, ref: str, *,
                     include_undone: bool = False) -> LedgerEntry | None:
        """``E<n>`` -> the effective entry; ``include_undone`` also finds a revoked or
        reversed one (history)."""
        number = _ref_number(ref, "E")
        if number is None:
            return None
        effective = "" if include_undone else f" AND {_effective('l')}"
        r = conn.execute(f"SELECT l.* FROM ledger_entry l WHERE l.workspace_id=? "
                         f"AND l.number=?{effective}", (ws, number)).fetchone()
        return _entry(r) if r else None

    def receipt_by_ref(self, conn, ws: str, ref: str) -> Receipt | None:
        """``R<n>`` -> the live receipt."""
        number = _ref_number(ref, "R")
        if number is None:
            return None
        r = conn.execute(f"SELECT r.* FROM receipt r WHERE r.workspace_id=? AND r.number=? "
                         f"AND {_live('receipt', 'r')}", (ws, number)).fetchone()
        return _receipt(r) if r else None

    def insert_receipt(self, conn, r: Receipt) -> None:
        """Stores the ROOT movement id; raises ``DuplicateReceipt`` if that root already has a
        live receipt. A revoked receipt does not block re-recording the movement."""
        movement_id = None
        if r.movement_id is not None:
            movement_id = self.movement_root(conn, r.movement_id)
            existing = self.live_receipt_for_movement(conn, movement_id)
            if existing is not None:
                raise DuplicateReceipt(movement_id, existing.id)
        conn.execute(
            "INSERT INTO receipt(id,workspace_id,number,kind,payer_id,currency,amount_minor,"
            "received_on,verification,movement_id,description) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (r.id, r.workspace_id, r.number, r.kind.value, r.payer_id, r.currency,
             r.amount_minor, r.received_on.isoformat(), r.verification.value, movement_id,
             r.description))

    def live_receipt_for_movement(self, conn, movement_id: str) -> Receipt | None:
        """Root-aware: the live receipt of this movement or of its PENDING/BOOKED sibling."""
        row = conn.execute(
            f"SELECT r.* FROM receipt r WHERE r.movement_id=? AND {_live('receipt', 'r')} "
            "ORDER BY r.rowid LIMIT 1", (self.movement_root(conn, movement_id),)).fetchone()
        return _receipt(row) if row else None

    def insert_allocation(self, conn, a: Allocation) -> None:
        conn.execute(
            "INSERT INTO allocation(id,workspace_id,receipt_id,line_id,amount_minor,method) "
            "VALUES(?,?,?,?,?,?)",
            (a.id, a.workspace_id, a.receipt_id, a.line_id, a.amount_minor, a.method.value))

    def open_lines(self, conn, ws: str, payer_id: str, currency: str) -> list[OpenLine]:
        """One row per line: Σ effective CHARGEs − Σ live allocations + Σ effective
        ADJUSTMENT/FORGIVE entries sourced to the line, kept when > 0.

        A CHARGE undone by a live REVERSAL no longer counts, so a re-charged line (funding
        re-created) or a corrected exchange (new line version) is never counted twice.
        """
        rows = conn.execute(
            "SELECT line_id, outstanding, ord FROM ("
            " SELECT c.line_id, c.ord, c.first_number, c.charged - COALESCE(("
            "  SELECT SUM(a.amount_minor) FROM allocation a WHERE a.workspace_id=? "
            f"  AND a.line_id=c.line_id AND {_live('allocation', 'a')}), 0)"
            " + COALESCE((SELECT SUM(j.amount_minor) FROM ledger_entry j WHERE j.workspace_id=?"
            "  AND j.kind IN ('ADJUSTMENT','FORGIVE') AND j.source_ref=c.line_id"
            f"  AND {_effective('j')}), 0)"
            " AS outstanding"
            " FROM (SELECT l.source_ref AS line_id, x.number * 100 + el.position AS ord,"
            "  MIN(l.number) AS first_number, SUM(l.amount_minor) AS charged"
            "  FROM ledger_entry l JOIN exchange_line el ON el.id=l.source_ref"
            "  JOIN exchange x ON x.id=el.exchange_id"
            "  WHERE l.workspace_id=? AND l.counterparty_id=? AND l.currency=? AND l.kind='CHARGE'"
            f"  AND {_effective('l')} AND {_live('exchange', 'x')}"
            "  GROUP BY l.source_ref) c"
            ") WHERE outstanding > 0 ORDER BY ord, first_number",
            (ws, ws, ws, payer_id, currency)).fetchall()
        return [OpenLine(r["line_id"], r["outstanding"], r["ord"]) for r in rows]

    def line_with_exchange(self, conn, ws: str,
                           line_id: str) -> tuple[ExchangeLine, Exchange] | None:
        """A line (any version) and its live exchange; ``None`` if unknown or revoked."""
        r = conn.execute(
            "SELECT el.* FROM exchange_line el JOIN exchange x ON x.id=el.exchange_id "
            f"WHERE el.workspace_id=? AND el.id=? AND {_live('exchange', 'x')}",
            (ws, line_id)).fetchone()
        if r is None:
            return None
        x = conn.execute("SELECT * FROM exchange WHERE id=?", (r["exchange_id"],)).fetchone()
        return _line(r), _exchange(x)

    def effective_adjustments_for_lines(self, conn, ws: str,
                                        line_ids: Sequence[str]) -> list[LedgerEntry]:
        """Effective ADJUSTMENTs whose ``source_ref`` is one of ``line_ids``, oldest first."""
        return self.effective_adjustments_for_refs(conn, ws, line_ids)

    def effective_adjustments_for_receipts(self, conn, ws: str,
                                           receipt_ids: Sequence[str]) -> list[LedgerEntry]:
        """Effective ADJUSTMENTs whose ``source_ref`` is one of ``receipt_ids``."""
        return self.effective_adjustments_for_refs(conn, ws, receipt_ids)

    def effective_adjustments_for_refs(self, conn, ws: str,
                                       refs: Sequence[str]) -> list[LedgerEntry]:
        """Effective ADJUSTMENTs whose ``source_ref`` is one of ``refs`` (line or receipt ids,
        which are globally unique), oldest first."""
        return self.effective_entries_for_refs(conn, ws, refs, (EntryKind.ADJUSTMENT,))

    def effective_entries_for_refs(self, conn, ws: str, refs: Sequence[str],
                                   kinds: Sequence[EntryKind]) -> list[LedgerEntry]:
        """Effective entries of ``kinds`` whose ``source_ref`` is one of ``refs``, oldest first."""
        ids, names = list(dict.fromkeys(refs)), [k.value for k in dict.fromkeys(kinds)]
        if not ids or not names:
            return []
        rows = conn.execute(
            f"SELECT l.* FROM ledger_entry l WHERE l.workspace_id=? "
            f"AND l.kind IN ({','.join('?' * len(names))}) "
            f"AND l.source_ref IN ({','.join('?' * len(ids))}) AND {_effective('l')} "
            "ORDER BY l.number", (ws, *names, *ids)).fetchall()
        return [_entry(r) for r in rows]

    def effective_charges_for_exchange(self, conn, ws: str, exchange_id: str,
                                       currency: str) -> list[LedgerEntry]:
        """Effective CHARGEs in ``currency`` on any line version of one exchange, oldest first."""
        rows = conn.execute(
            "SELECT l.* FROM ledger_entry l JOIN exchange_line el ON el.id=l.source_ref "
            "WHERE l.workspace_id=? AND el.exchange_id=? AND l.currency=? AND l.kind='CHARGE' "
            f"AND {_effective('l')} ORDER BY l.number", (ws, exchange_id, currency)).fetchall()
        return [_entry(r) for r in rows]

    def live_allocation_ids_for_line(self, conn, ws: str, line_id: str) -> list[str]:
        return [a.id for a in self.live_allocations_for_lines(conn, ws, [line_id])]

    def live_allocations_for_lines(self, conn, ws: str,
                                   line_ids: Sequence[str]) -> list[Allocation]:
        """Live allocations on these lines, oldest first."""
        ids = list(dict.fromkeys(line_ids))
        if not ids:
            return []
        rows = conn.execute(
            f"SELECT a.* FROM allocation a WHERE a.workspace_id=? "
            f"AND a.line_id IN ({','.join('?' * len(ids))}) AND {_live('allocation', 'a')} "
            "ORDER BY a.rowid", (ws, *ids)).fetchall()
        return [_allocation(r) for r in rows]

    def live_allocations_for_receipt(self, conn, ws: str, receipt_id: str) -> list[Allocation]:
        """Live allocations of one receipt, oldest first."""
        rows = conn.execute(
            f"SELECT a.* FROM allocation a WHERE a.workspace_id=? AND a.receipt_id=? "
            f"AND {_live('allocation', 'a')} ORDER BY a.rowid", (ws, receipt_id)).fetchall()
        return [_allocation(r) for r in rows]

    def line_charged(self, conn, ws: str, line_id: str) -> int:
        """Σ effective CHARGEs booked against one exchange line."""
        return conn.execute(
            "SELECT COALESCE(SUM(l.amount_minor),0) AS s FROM ledger_entry l "
            "WHERE l.workspace_id=? AND l.source_ref=? AND l.kind='CHARGE' "
            f"AND {_effective('l')}", (ws, line_id)).fetchone()["s"]

    def flows_since_creation(self, conn, ws: str, cp_id: str,
                             currency: str) -> tuple[int, int, date | None]:
        """(Σ effective CHARGEs, Σ effective PAYMENTs as a positive figure, earliest date)."""
        r = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN l.kind='CHARGE' THEN l.amount_minor END),0) AS out_, "
            "COALESCE(SUM(CASE WHEN l.kind='PAYMENT' THEN -l.amount_minor END),0) AS in_, "
            "MIN(l.effective_on) AS since FROM ledger_entry l WHERE l.workspace_id=? "
            f"AND l.counterparty_id=? AND l.currency=? AND {_effective('l')} "
            "AND l.kind<>'REVERSAL'", (ws, cp_id, currency)).fetchone()
        return r["out_"], r["in_"], _d(r["since"]) if r["since"] else None

    def receipt_remainders(self, conn, ws: str, payer_id: str,
                           currency: str) -> list[tuple[Receipt, int]]:
        rows = conn.execute(
            "SELECT r.*, r.amount_minor - COALESCE((SELECT SUM(a.amount_minor) FROM allocation a "
            f"WHERE a.receipt_id=r.id AND {_live('allocation', 'a')}),0) "
            f"- COALESCE((SELECT SUM(j.amount_minor) FROM ledger_entry j WHERE j.source_ref=r.id "
            f"AND j.kind='ADJUSTMENT' AND {_effective('j')}),0) AS remainder "
            f"FROM receipt r WHERE r.workspace_id=? AND r.payer_id=? AND r.currency=? "
            f"AND {_live('receipt', 'r')} AND remainder > 0 ORDER BY r.received_on, r.number",
            (ws, payer_id, currency)).fetchall()
        return [(_receipt(r), r["remainder"]) for r in rows]

    # --- revocation and rules ----------------------------------------------------
    def revoke(self, conn, ws: str, table: str, target_id: str, reason: str,
               at: datetime) -> None:
        if table not in REVOCABLE_TABLES:
            raise ValueError(f"table is not revocable: {table}")
        if table == "ledger_entry" and conn.execute(
                f"SELECT 1 FROM ledger_entry t WHERE t.id=? AND {_reversed('t')}",
                (target_id,)).fetchone() is not None:
            # Revoking it as well would subtract it twice; revoke the REVERSAL instead.
            raise ValueError("entry is already undone by a live REVERSAL")
        try:
            conn.execute(
                "INSERT INTO revocation(id,workspace_id,table_name,target_id,reason,at) "
                "VALUES(?,?,?,?,?,?)", (_new_id(), ws, table, target_id, reason, _ts(at)))
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE":
                raise AlreadyRevoked(f"{table}:{target_id}") from exc
            raise

    def is_live(self, conn, table: str, target_id: str) -> bool:
        if table not in REVOCABLE_TABLES:
            raise ValueError(f"table is not revocable: {table}")
        return conn.execute("SELECT 1 FROM revocation WHERE table_name=? AND target_id=?",
                            (table, target_id)).fetchone() is None

    def insert_payer_rule(self, conn, ws: str, key_hash: str, counterparty_id: str | None) -> str:
        rule_id = _new_id()
        conn.execute("INSERT INTO payer_rule(id,workspace_id,key_hash,counterparty_id) "
                     "VALUES(?,?,?,?)", (rule_id, ws, key_hash, counterparty_id))
        return rule_id

    def live_rule_ids(self, conn, ws: str, key_hash: str) -> list[str]:
        """Live payer-rule ids for a key, oldest first (the last one wins in ``rule_for``)."""
        rows = conn.execute(
            f"SELECT p.id FROM payer_rule p WHERE p.workspace_id=? AND p.key_hash=? "
            f"AND {_live('payer_rule', 'p')} ORDER BY p.rowid", (ws, key_hash)).fetchall()
        return [r["id"] for r in rows]

    def live_rule_ids_for_counterparty(self, conn, ws: str, cp_id: str) -> list[str]:
        """Live payer-rule ids that send a key to this counterparty, oldest first."""
        rows = conn.execute(
            f"SELECT p.id FROM payer_rule p WHERE p.workspace_id=? AND p.counterparty_id=? "
            f"AND {_live('payer_rule', 'p')} ORDER BY p.rowid", (ws, cp_id)).fetchall()
        return [r["id"] for r in rows]

    def rule_for(self, conn, ws: str, key_hash: str) -> str | None:
        r = conn.execute(
            f"SELECT p.counterparty_id FROM payer_rule p WHERE p.workspace_id=? AND p.key_hash=? "
            f"AND {_live('payer_rule', 'p')} ORDER BY p.rowid DESC LIMIT 1",
            (ws, key_hash)).fetchone()
        if r is None:
            return None
        return r["counterparty_id"] if r["counterparty_id"] is not None else IGNORE

    def add_partner_identifier(self, conn, ws: str, iban_hash: str, cp_id: str) -> str:
        identifier_id = _new_id()
        conn.execute("INSERT INTO partner_identifier(id,workspace_id,iban_hash,counterparty_id) "
                     "VALUES(?,?,?,?)", (identifier_id, ws, iban_hash, cp_id))
        return identifier_id

    def partner_hashes(self, conn, ws: str) -> dict[str, str]:
        rows = conn.execute(
            f"SELECT p.iban_hash, p.counterparty_id FROM partner_identifier p "
            f"WHERE p.workspace_id=? AND {_live('partner_identifier', 'p')} ORDER BY p.rowid",
            (ws,)).fetchall()
        return {r["iban_hash"]: r["counterparty_id"] for r in rows}

    def add_own_identifier(self, conn, ws: str, iban_hash: str) -> None:
        conn.execute("INSERT INTO own_identifier(id,workspace_id,iban_hash) VALUES(?,?,?)",
                     (_new_id(), ws, iban_hash))

    def own_hashes(self, conn, ws: str) -> set[str]:
        return {r["iban_hash"] for r in conn.execute(
            "SELECT iban_hash FROM own_identifier WHERE workspace_id=?", (ws,))}

    def set_watch(self, conn, ws: str, account_id: str, on: bool) -> None:
        if on:
            conn.execute("INSERT OR IGNORE INTO account_watch(workspace_id,account_id) "
                         "VALUES(?,?)", (ws, account_id))
        else:
            conn.execute("DELETE FROM account_watch WHERE workspace_id=? AND account_id=?",
                         (ws, account_id))

    def watched_accounts(self, conn, ws: str) -> set[str]:
        return {r["account_id"] for r in conn.execute(
            "SELECT account_id FROM account_watch WHERE workspace_id=?", (ws,))}

    # --- movements ---------------------------------------------------------------
    def insert_movement_role(self, conn, ws: str, movement_id: str,
                             role: MovementRoleKind) -> str:
        """Stores the role on the ROOT movement; returns the role id (for revocation)."""
        role_id = _new_id()
        conn.execute("INSERT INTO movement_role(id,workspace_id,movement_id,role) "
                     "VALUES(?,?,?,?)",
                     (role_id, ws, self.movement_root(conn, movement_id), role.value))
        return role_id

    def movement_role(self, conn, movement_id: str) -> MovementRoleKind | None:
        """Root-aware: the latest live role of this movement or its PENDING/BOOKED sibling."""
        r = conn.execute(
            f"SELECT m.role FROM movement_role m WHERE m.movement_id=? "
            f"AND {_live('movement_role', 'm')} ORDER BY m.rowid DESC LIMIT 1",
            (self.movement_root(conn, movement_id),)).fetchone()
        return MovementRoleKind(r["role"]) if r else None

    def live_role_ids_for_movement(self, conn, movement_id: str) -> list[str]:
        """Root-aware: ids of the live roles, oldest first (what a reversal must revoke)."""
        rows = conn.execute(
            f"SELECT m.id FROM movement_role m WHERE m.movement_id=? "
            f"AND {_live('movement_role', 'm')} ORDER BY m.rowid",
            (self.movement_root(conn, movement_id),)).fetchall()
        return [r["id"] for r in rows]

    def movement_root(self, conn, movement_id: str) -> str:
        current, seen = movement_id, {movement_id}
        while True:
            r = conn.execute("SELECT supersedes_id FROM movement WHERE id=?",
                             (current,)).fetchone()
            nxt = r["supersedes_id"] if r else None
            if nxt is None or nxt in seen:
                return current
            seen.add(nxt)
            current = nxt

    def movement_current(self, conn, ws: str, movement_id: str) -> domain.Movement | None:
        """The latest version of a movement (follows BOOKED successors); ``None`` if unknown."""
        r = conn.execute("SELECT * FROM movement WHERE workspace_id=? AND id=?",
                         (ws, movement_id)).fetchone()
        seen = set()
        while r is not None and r["id"] not in seen:
            seen.add(r["id"])
            nxt = conn.execute("SELECT * FROM movement WHERE workspace_id=? AND supersedes_id=? "
                               "ORDER BY rowid LIMIT 1", (ws, r["id"])).fetchone()
            if nxt is None:
                return _movement(r)
            r = nxt
        return _movement(r) if r is not None else None

    def unlinked_partner_payments(self, conn, ws: str) -> list[domain.Movement]:
        """Current outgoing EUR movements to a live partner IBAN whose root has no live role
        and no live funding, oldest first. A superseded PENDING row shows as its successor."""
        rows = conn.execute(
            "SELECT m.* FROM movement m WHERE m.workspace_id=? AND m.currency='EUR' "
            "AND m.amount_minor<0 AND NOT EXISTS (SELECT 1 FROM movement s "
            "WHERE s.supersedes_id=m.id) AND EXISTS (SELECT 1 FROM partner_identifier p "
            "WHERE p.workspace_id=m.workspace_id AND p.iban_hash=m.counterparty_iban_hash "
            f"AND {_live('partner_identifier', 'p')}) ORDER BY m.booking_date, m.rowid",
            (ws,)).fetchall()
        return [m for m in map(_movement, rows)
                if self.movement_role(conn, m.id) is None
                and self.live_funding_for_movement(conn, m.id) is None]

    def movements_after(self, conn, ws: str, rowid: int) -> list[tuple[int, domain.Movement]]:
        rows = conn.execute("SELECT rowid AS rid, * FROM movement WHERE workspace_id=? "
                            "AND rowid>? ORDER BY rowid", (ws, rowid)).fetchall()
        return [(r["rid"], _movement(r)) for r in rows]

    def get_cursor(self, conn, ws: str) -> int:
        r = conn.execute("SELECT movement_rowid FROM matcher_cursor WHERE workspace_id=?",
                         (ws,)).fetchone()
        return r["movement_rowid"] if r else 0

    def set_cursor(self, conn, ws: str, rowid: int) -> None:
        conn.execute(
            "INSERT INTO matcher_cursor(workspace_id,movement_rowid) VALUES(?,?) "
            "ON CONFLICT(workspace_id) DO UPDATE SET movement_rowid=excluded.movement_rowid",
            (ws, rowid))

    # --- other -------------------------------------------------------------------
    def insert_held_cash(self, conn, ws: str, cp_id: str, currency: str, amount_minor: int,
                         stated_on: date) -> None:
        conn.execute(
            "INSERT INTO held_cash_statement(id,workspace_id,counterparty_id,currency,"
            "amount_minor,stated_on) VALUES(?,?,?,?,?,?)",
            (_new_id(), ws, cp_id, currency, amount_minor, stated_on.isoformat()))

    def latest_held_cash(self, conn, ws: str, cp_id: str,
                         currency: str) -> tuple[int, date] | None:
        r = conn.execute(
            "SELECT amount_minor, stated_on FROM held_cash_statement WHERE workspace_id=? "
            "AND counterparty_id=? AND currency=? ORDER BY stated_on DESC, rowid DESC LIMIT 1",
            (ws, cp_id, currency)).fetchone()
        return (r["amount_minor"], _d(r["stated_on"])) if r else None

    def usd_per_eur_on(self, conn, day: date) -> Decimal | None:
        r = conn.execute("SELECT rate FROM fx_rate WHERE currency='USD' AND date<=? "
                         "ORDER BY date DESC LIMIT 1", (day.isoformat(),)).fetchone()
        return Decimal(r["rate"]) if r else None

    def log_intervention(self, conn, ws: str, kind: str, at: datetime) -> None:
        conn.execute("INSERT INTO intervention_log(id,workspace_id,kind,at) VALUES(?,?,?,?)",
                     (_new_id(), ws, kind, _ts(at)))

    def interventions_in_month(self, conn, ws: str, year: int, month: int) -> int:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM intervention_log WHERE workspace_id=? "
            "AND substr(at,1,7)=?", (ws, f"{year:04d}-{month:02d}")).fetchone()["n"]

    def member_role(self, conn, ws: str, person_id: str) -> str | None:
        r = conn.execute("SELECT role FROM workspace_member WHERE workspace_id=? AND person_id=?",
                         (ws, person_id)).fetchone()
        return r["role"] if r else None

    # --- pending queue (mutable table) ----------------------------------------------
    def insert_pending(self, conn, p: PendingItem) -> None:
        conn.execute(
            "INSERT INTO pending_item(workspace_id,code,kind,requires_answer,options,payload,"
            "dedupe_key,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (p.workspace_id, p.code, p.kind.value, int(p.requires_answer),
             json.dumps(list(p.options)), json.dumps(p.payload), p.dedupe_key,
             _ts(p.created_at)))

    def pending_by_code(self, conn, ws: str, code: str) -> PendingItem | None:
        r = conn.execute("SELECT * FROM pending_item WHERE workspace_id=? AND code=?",
                         (ws, _code(code))).fetchone()
        return _pending(r) if r else None

    def pending_by_dedupe(self, conn, ws: str, key: str, *,
                          include_resolved: bool = False) -> PendingItem | None:
        """The open item for ``key``; with ``include_resolved``, else the latest resolved one."""
        open_only = "" if include_resolved else "AND resolved_at IS NULL "
        r = conn.execute(
            f"SELECT * FROM pending_item WHERE workspace_id=? AND dedupe_key=? {open_only}"
            "ORDER BY resolved_at IS NULL DESC, rowid DESC LIMIT 1", (ws, key)).fetchone()
        return _pending(r) if r else None

    def pending_open(self, conn, ws: str) -> list[PendingItem]:
        rows = conn.execute("SELECT * FROM pending_item WHERE workspace_id=? "
                            "AND resolved_at IS NULL", (ws,)).fetchall()
        return sorted((_pending(r) for r in rows), key=lambda p: int(p.code[1:]))

    def mark_pending_delivered(self, conn, ws: str, code: str, at: datetime,
                               resolve: bool) -> None:
        if resolve:
            conn.execute(
                "UPDATE pending_item SET delivered_at=?, resolved_at=?, resolution='delivered' "
                "WHERE workspace_id=? AND code=? AND resolved_at IS NULL",
                (_ts(at), _ts(at), ws, _code(code)))
        else:
            conn.execute("UPDATE pending_item SET delivered_at=? WHERE workspace_id=? AND code=?",
                         (_ts(at), ws, _code(code)))

    def mark_pending_resolved(self, conn, ws: str, code: str, resolution: str,
                              at: datetime) -> bool:
        """True if this call resolved the item; an earlier resolution is never overwritten."""
        cur = conn.execute("UPDATE pending_item SET resolved_at=?, resolution=? "
                           "WHERE workspace_id=? AND code=? AND resolved_at IS NULL",
                           (_ts(at), resolution, ws, _code(code)))
        return cur.rowcount == 1

    def set_pending_snooze(self, conn, ws: str, code: str, until: datetime) -> None:
        conn.execute("UPDATE pending_item SET snooze_until=? WHERE workspace_id=? AND code=?",
                     (_ts(until), ws, _code(code)))
