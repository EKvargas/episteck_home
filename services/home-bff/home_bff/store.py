"""Durable server-side store for BFF sessions and OAuth transactions (G1.6).

WHY SQLITE
----------
Two things must survive a restart: the in-flight authorization transaction (a user
mid-login when the service reloads) and the browser session (so a deploy does not log
everyone out). Both are small, single-writer, and local to one node.

Nutrition already runs SQLite on a service-owned volume on this node, so this adds
**no new infrastructure dependency** (proposal §F: prefer the smallest maintainable
solution; do not add Redis).

WHAT LIVES HERE AND WHAT NEVER LEAVES
-------------------------------------
This file holds OAuth access/refresh tokens and PKCE verifiers. It is therefore
treated as a secret: it lives on a service-owned volume with restrictive permissions,
is never logged, never rendered into a response, and never reaches the model. The
browser only ever receives ``session_id``, an opaque random string.

SINGLE USE
----------
``consume_transaction`` deletes the row and returns it in one step, inside a
transaction, so a replayed ``state`` finds nothing. This is what makes authorization
code / state replay a denial rather than a second successful login.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .runtime import BindResult

# An in-flight login should complete in seconds; minutes is already generous.
TRANSACTION_TTL_SECONDS = 600

# Browser session lifetime. Matches the Control Plane's Home Delegated Session TTL.
SESSION_TTL_SECONDS = 12 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_transaction (
    state          TEXT PRIMARY KEY,
    code_verifier  TEXT NOT NULL,
    nonce          TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    expires_at     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bff_session (
    session_id           TEXT PRIMARY KEY,
    home_session_id      TEXT NOT NULL,
    access_token         TEXT NOT NULL,
    refresh_token        TEXT,
    created_at           INTEGER NOT NULL,
    expires_at           INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_binding (
    runtime_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    bound_at   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES bff_session(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_tx_expiry ON oauth_transaction(expires_at);
CREATE INDEX IF NOT EXISTS ix_session_expiry ON bff_session(expires_at);
"""

_BUSY_TIMEOUT_MS = 1_000


@dataclass(frozen=True)
class Transaction:
    state: str
    code_verifier: str
    nonce: str
    redirect_uri: str


@dataclass(frozen=True)
class Session:
    session_id: str
    home_session_id: str
    access_token: str
    refresh_token: str | None
    expires_at: int


def _now() -> int:
    return int(time.time())


class SessionStore:
    """SQLite-backed store shared safely by independent BFF processes."""

    def __init__(self, path: str) -> None:
        self._path = path
        if path == ":memory:":
            raise ValueError("SessionStore requires a filesystem database path")
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            # WAL lets the mint process read the last committed binding while the
            # public process is preparing a short write transaction.
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(_SCHEMA)
            db.commit()
        # Tokens live here. Keep them unreadable to other service accounts even if
        # the parent directory is ever loosened.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        """Open one configured connection for exactly one store operation."""
        db = sqlite3.connect(
            self._path,
            timeout=_BUSY_TIMEOUT_MS / 1_000,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return db

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _mutation(self) -> Iterator[sqlite3.Connection]:
        """Serialize a short mutation and translate SQLite failures fail-closed."""
        db: sqlite3.Connection | None = None
        try:
            db = self._connect()
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except sqlite3.OperationalError:
            if db is not None:
                db.rollback()
            raise StoreUnavailableError("runtime store unavailable") from None
        except Exception:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    # ---------------------------------------------------------------- transactions

    def begin_transaction(
        self, *, state: str, code_verifier: str, nonce: str, redirect_uri: str
    ) -> None:
        now = _now()
        with self._mutation() as db:
            db.execute(
                "INSERT INTO oauth_transaction"
                " (state, code_verifier, nonce, redirect_uri, created_at, expires_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    state,
                    code_verifier,
                    nonce,
                    redirect_uri,
                    now,
                    now + TRANSACTION_TTL_SECONDS,
                ),
            )

    def consume_transaction(self, state: str) -> Transaction | None:
        """Atomically fetch-and-delete. A second call with the same state gets None."""
        if not state:
            return None
        with self._mutation() as db:
            row = db.execute(
                "SELECT * FROM oauth_transaction WHERE state = ?", (state,)
            ).fetchone()
            if row is None:
                return None
            # Delete before validating expiry: a stale state is spent either way, so
            # it can never be retried.
            db.execute("DELETE FROM oauth_transaction WHERE state = ?", (state,))
            if row["expires_at"] <= _now():
                return None
            return Transaction(
                state=row["state"],
                code_verifier=row["code_verifier"],
                nonce=row["nonce"],
                redirect_uri=row["redirect_uri"],
            )

    # -------------------------------------------------------------------- sessions

    def create_session(
        self,
        *,
        home_session_id: str,
        access_token: str,
        refresh_token: str | None,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> Session:
        session_id = secrets.token_urlsafe(32)
        now = _now()
        expires_at = now + ttl_seconds
        with self._mutation() as db:
            db.execute(
                "INSERT INTO bff_session"
                " (session_id, home_session_id, access_token, refresh_token,"
                "  created_at, expires_at) VALUES (?,?,?,?,?,?)",
                (
                    session_id,
                    home_session_id,
                    access_token,
                    refresh_token,
                    now,
                    expires_at,
                ),
            )
        return Session(
            session_id=session_id,
            home_session_id=home_session_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )

    def get_session(self, session_id: str | None) -> Session | None:
        """Return a live session, or nothing. Expiry is a denial, not a warning."""
        if not session_id:
            return None
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM bff_session WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= _now():
            self.delete_session(session_id)
            return None
        return Session(
            session_id=row["session_id"],
            home_session_id=row["home_session_id"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            expires_at=row["expires_at"],
        )

    def delete_session(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        with self._mutation() as db:
            cursor = db.execute(
                "DELETE FROM bff_session WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------- runtime binding

    def claim_runtime(self, runtime_id: str, session_id: str) -> BindResult:
        """Atomically bind a live session without replacing another live owner."""
        now = _now()
        with self._mutation() as db:
            candidate = db.execute(
                "SELECT session_id FROM bff_session"
                " WHERE session_id = ? AND expires_at > ?",
                (session_id, now),
            ).fetchone()
            if candidate is None:
                raise ValueError("runtime binding requires a live session")

            binding = db.execute(
                "SELECT rb.session_id, s.expires_at"
                " FROM runtime_binding AS rb"
                " LEFT JOIN bff_session AS s ON s.session_id = rb.session_id"
                " WHERE rb.runtime_id = ?",
                (runtime_id,),
            ).fetchone()
            if binding is None:
                db.execute(
                    "INSERT INTO runtime_binding (runtime_id, session_id, bound_at)"
                    " VALUES (?, ?, ?)",
                    (runtime_id, session_id, now),
                )
                return BindResult.BOUND

            if binding["session_id"] == session_id:
                return BindResult.SAME_SESSION

            if binding["expires_at"] is None or binding["expires_at"] <= now:
                db.execute(
                    "UPDATE runtime_binding SET session_id = ?, bound_at = ?"
                    " WHERE runtime_id = ?",
                    (session_id, now, runtime_id),
                )
                return BindResult.REPLACED_STALE

            return BindResult.ALREADY_BOUND

    def resolve_runtime(self, runtime_id: str) -> Session | None:
        """Return the committed live owner and discard a stale binding."""
        now = _now()
        with self._mutation() as db:
            row = db.execute(
                "SELECT s.* FROM runtime_binding AS rb"
                " LEFT JOIN bff_session AS s ON s.session_id = rb.session_id"
                " WHERE rb.runtime_id = ?",
                (runtime_id,),
            ).fetchone()
            if row is None:
                return None
            if row["session_id"] is None or row["expires_at"] <= now:
                db.execute(
                    "DELETE FROM runtime_binding WHERE runtime_id = ?", (runtime_id,)
                )
                return None
            return _session_from_row(row)

    def clear_runtime_for_session(self, session_id: str) -> bool:
        """Remove every runtime binding owned by this browser session."""
        if not session_id:
            return False
        with self._mutation() as db:
            cursor = db.execute(
                "DELETE FROM runtime_binding WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------- upkeep

    def purge_expired(self) -> int:
        """Drop expired rows so the file does not grow without bound."""
        now = _now()
        with self._mutation() as db:
            a = db.execute(
                "DELETE FROM oauth_transaction WHERE expires_at <= ?", (now,)
            ).rowcount
            b = db.execute(
                "DELETE FROM bff_session WHERE expires_at <= ?", (now,)
            ).rowcount
        return a + b

    def close(self) -> None:
        """Retained for callers; operations do not keep a connection open."""


class StoreUnavailableError(RuntimeError):
    """The bounded wait for a safe SQLite operation was exhausted."""


def _session_from_row(row: sqlite3.Row) -> Session:
    return Session(
        session_id=row["session_id"],
        home_session_id=row["home_session_id"],
        access_token=row["access_token"],
        refresh_token=row["refresh_token"],
        expires_at=row["expires_at"],
    )
