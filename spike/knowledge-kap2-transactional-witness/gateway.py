"""Disconnected, socket-only KAP-2 witness gateway candidate.

No Home endpoint, listener, persistent credential or production admission path uses this.
The live process lock and CLOSED bit are deliberately outside restorable DB rows.
"""

from __future__ import annotations

import fcntl
import os
import secrets
from pathlib import Path
from typing import Any

import pymysql


class GatewayBusy(RuntimeError):
    """Another gateway owns the local witness instance."""


class GatewayClosed(RuntimeError):
    """Admission or the pinned witness connection is uncertain."""


class Gateway:
    def __init__(self, *, socket: str, lock_path: str, reader_password: str,
                 writer_password: str, recovery_password: str) -> None:
        self.socket = socket
        self.lock_path = Path(lock_path)
        self._passwords = (reader_password, writer_password, recovery_password)
        self._lock_fd: int | None = None
        self._reader: pymysql.Connection | None = None
        self._writer: pymysql.Connection | None = None
        self._incarnation: str | None = None
        self.closed = True
        self._lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise GatewayBusy("witness gateway instance is already owned") from exc
        try:
            self._reader = self._connect("gw_reader", reader_password)
        except Exception:
            self.close()
            raise

    def _connect(self, user: str, password: str) -> pymysql.Connection:
        return pymysql.connect(unix_socket=self.socket, user=user, password=password,
                               database="witness", autocommit=True,
                               connect_timeout=2, read_timeout=2, write_timeout=2)

    def _check_lock(self) -> None:
        try:
            if self._lock_fd is None:
                raise OSError("lock descriptor is closed")
            held = os.fstat(self._lock_fd)
            current = self.lock_path.stat()
            if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
                raise OSError("lock path was replaced")
        except OSError as exc:
            self.closed = True
            raise GatewayClosed("gateway instance lock was lost") from exc

    @staticmethod
    def _call(connection: pymysql.Connection, name: str,
              args: tuple[Any, ...]) -> tuple[Any, ...] | None:
        placeholders = ",".join(["%s"] * len(args))
        with connection.cursor() as cursor:
            cursor.execute(f"CALL witness.{name}({placeholders})", args)
            row = cursor.fetchone() if cursor.description else None
            while cursor.nextset():
                pass
            return row

    def _read_current(self, partition: str) -> tuple[Any, ...] | None:
        assert self._reader is not None
        self._reader.ping(reconnect=False)
        return self._call(self._reader, "read_current", (partition,))

    def _require_open(self, incarnation: str) -> None:
        if self.closed or incarnation != self._incarnation:
            raise GatewayClosed("incarnation is not admitted")
        self._check_lock()

    def recover(self, partition: str) -> str:
        """Install a fresh default-deny incarnation; never trust a restored READY row."""
        self.closed = True
        self._incarnation = None
        self._check_lock()
        candidate = secrets.token_hex(32)
        recovery = self._connect("gw_recovery", self._passwords[2])
        try:
            self._call(recovery, "recover_e2", (partition, candidate))
        finally:
            recovery.close()
        if self._reader is not None:
            self._reader.close()
        if self._writer is not None:
            self._writer.close()
        self._reader = self._connect("gw_reader", self._passwords[0])
        self._writer = self._connect("gw_writer2", self._passwords[1])
        row = self._read_current(partition)
        if row != (candidate, 0, 2, 2, "COMMITTED", None, "DENY_ALL"):
            raise GatewayClosed("fresh default-deny recovery readback failed")
        self._incarnation = candidate
        self.closed = False
        return candidate

    def authorize(self, partition: str, incarnation: str, revision: int,
                  digest: str) -> bool:
        if self.closed or incarnation != self._incarnation:
            return False
        try:
            self._check_lock()
            row = self._read_current(partition)
        except (GatewayClosed, pymysql.MySQLError, OSError):
            self.closed = True
            return False
        return bool(row and row[0] == incarnation and row[1] == revision
                    and row[4] == "COMMITTED" and row[6] == digest
                    and digest != "DENY_ALL")

    def prepare(self, partition: str, incarnation: str, event: str,
                expected_revision: int, digest: str) -> None:
        self._require_open(incarnation)
        assert self._writer is not None
        try:
            self._writer.ping(reconnect=False)
            self._call(self._writer, "prepare_e2",
                       (partition, incarnation, event, expected_revision, digest))
        except pymysql.MySQLError as exc:
            if not exc.args or exc.args[0] != 1644:  # 1644 is the procedure's legal rejection
                self.closed = True
            raise

    def commit(self, partition: str, incarnation: str, event: str,
               digest: str) -> None:
        self._require_open(incarnation)
        assert self._writer is not None
        try:
            self._writer.ping(reconnect=False)
            self._call(self._writer, "commit_e2",
                       (partition, incarnation, event, digest))
        except pymysql.MySQLError as exc:
            if not exc.args or exc.args[0] != 1644:
                self.closed = True
            raise

    def event_outcome(self, partition: str, incarnation: str,
                      event: str) -> tuple[str, int, str] | None:
        self._require_open(incarnation)
        try:
            assert self._reader is not None
            self._reader.ping(reconnect=False)
            row = self._call(self._reader, "read_event",
                             (partition, incarnation, event))
        except pymysql.MySQLError:
            self.closed = True
            raise
        return row

    def close(self) -> None:
        self.closed = True
        self._incarnation = None
        for connection in (self._reader, self._writer):
            if connection is not None:
                try:
                    connection.close()
                except pymysql.MySQLError:
                    pass
        self._reader = self._writer = None
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def __enter__(self) -> Gateway:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
