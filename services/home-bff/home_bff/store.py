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
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

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
CREATE INDEX IF NOT EXISTS ix_tx_expiry ON oauth_transaction(expires_at);
CREATE INDEX IF NOT EXISTS ix_session_expiry ON bff_session(expires_at);
"""


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
    """SQLite-backed store. Safe for the single-process uvicorn worker we deploy."""

    def __init__(self, path: str) -> None:
        self._path = path
        if path != ":memory:":
            parent = Path(path).parent
            parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: uvicorn serves requests from a threadpool, and
        # every write below is a short, serialized transaction.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.commit()
        if path != ":memory:":
            # Tokens live here. Keep them unreadable to other service accounts even
            # if the parent directory is ever loosened.
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    # ---------------------------------------------------------------- transactions

    def begin_transaction(
        self, *, state: str, code_verifier: str, nonce: str, redirect_uri: str
    ) -> None:
        now = _now()
        with self._db:
            self._db.execute(
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
        with self._db:
            row = self._db.execute(
                "SELECT * FROM oauth_transaction WHERE state = ?", (state,)
            ).fetchone()
            if row is None:
                return None
            # Delete before validating expiry: a stale state is spent either way, so
            # it can never be retried.
            self._db.execute("DELETE FROM oauth_transaction WHERE state = ?", (state,))
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
        with self._db:
            self._db.execute(
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
        row = self._db.execute(
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
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM bff_session WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------- upkeep

    def purge_expired(self) -> int:
        """Drop expired rows so the file does not grow without bound."""
        now = _now()
        with self._db:
            a = self._db.execute(
                "DELETE FROM oauth_transaction WHERE expires_at <= ?", (now,)
            ).rowcount
            b = self._db.execute(
                "DELETE FROM bff_session WHERE expires_at <= ?", (now,)
            ).rowcount
        return a + b

    def close(self) -> None:
        with closing(self._db):
            pass
