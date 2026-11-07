"""Disconnected, socket-only KAP-2 witness gateway candidate.

No Home endpoint, listener, persistent credential or production admission path uses this.
The live process lock and CLOSED bit are deliberately outside restorable DB rows.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import secrets
import threading
from functools import wraps
from pathlib import Path
from typing import Any

import pymysql


def writer_principal(epoch: int) -> str:
    """Operator naming convention for the one DB principal bound to a writer epoch."""
    return f"gw_writer{epoch}"


def native_password_hash(password: str) -> str:
    """MariaDB ``mysql_native_password`` stored form; not usable to authenticate."""
    stage1 = hashlib.sha1(password.encode("utf-8")).digest()
    return "*" + hashlib.sha1(stage1).hexdigest().upper()


class GatewayBusy(RuntimeError):
    """Another gateway owns the local witness instance."""


class GatewayClosed(RuntimeError):
    """Admission or the pinned witness connection is uncertain."""


def serialized(method):
    """Keep recovery transitions and serving DB sessions in one process order."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._admission_lock:
            return method(self, *args, **kwargs)
    return call


class Gateway:
    def __init__(self, *, socket: str, lock_path: str, reader_password: str,
                 recovery_password: str) -> None:
        """No writer credential is configured: each recovery mints a fresh one.

        Recovery moves to the next epoch's never-used principal, installs a newly
        generated credential for it (only its stored hash crosses to the witness) and
        retires every earlier principal, so no writer credential outlives the
        recovery after it, even if an older datadir is physically restored.
        """
        self.socket = socket
        self.lock_path = Path(lock_path)
        self._passwords = (reader_password, recovery_password)
        self._writer_credential: tuple[str, str] | None = None
        self._lock_fd: int | None = None
        self._reader: pymysql.Connection | None = None
        self._writer: pymysql.Connection | None = None
        self._incarnation: str | None = None
        self._partition: str | None = None
        self._writer_epoch: int | None = None
        self._recovery_phase = "CLOSED"
        self._admission_lock = threading.RLock()
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
            # Linux fdinfo reports locks owned by this open file description.
            # A still-open descriptor does not prove flock ownership after LOCK_UN.
            fdinfo = Path(f"/proc/self/fdinfo/{self._lock_fd}").read_text()
            own_lock = any(
                parts[0] == "lock:" and parts[2:5] == ["FLOCK", "ADVISORY", "WRITE"]
                and parts[5] == str(os.getpid())
                for line in fdinfo.splitlines()
                if (parts := line.split()) and len(parts) >= 6
            )
            if not own_lock:
                raise OSError("lock descriptor no longer owns flock")
        except OSError as exc:
            self.closed = True
            raise GatewayClosed("gateway instance lock was lost") from exc

    def _check_connections(self) -> None:
        """Both pinned sessions must survive; neither may reconnect silently."""
        try:
            if self._reader is None or self._writer is None:
                raise OSError("pinned witness connection is missing")
            self._reader.ping(reconnect=False)
            self._writer.ping(reconnect=False)
        except (pymysql.MySQLError, OSError) as exc:
            self.closed = True
            raise GatewayClosed("pinned witness connection was lost") from exc

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
        self._check_connections()

    @serialized
    def close_admission(self) -> None:
        self.closed = True
        self._recovery_phase = "CLOSED"
        self._incarnation = None
        self._partition = None
        self._writer_epoch = None

    @property
    def writer_epoch(self) -> int | None:
        """The writer epoch installed by the current recovery generation, if any."""
        return self._writer_epoch

    @staticmethod
    def _close_quietly(connection: pymysql.Connection | None) -> None:
        if connection is not None:
            try:
                connection.close()
            except (pymysql.MySQLError, OSError):
                pass

    @serialized
    def recover(self, partition: str) -> str:
        """Install default-deny under a fresh writer principal, keeping serving closed.

        The previous writer session is dropped before rotation; the witness then
        locks and disconnects every retired writer principal of the partition.
        """
        self.close_admission()
        self._check_lock()
        for connection in (self._writer, self._reader):
            self._close_quietly(connection)
        self._writer = None
        self._reader = self._connect("gw_reader", self._passwords[0])
        current = self._read_current(partition)
        if not current or type(current[2]) is not int:
            raise GatewayClosed("partition head is missing")
        next_epoch = current[2] + 1
        principal = writer_principal(next_epoch)
        password = secrets.token_urlsafe(32)
        self._writer_credential = None
        candidate = secrets.token_hex(32)
        recovery = self._connect("gw_recovery", self._passwords[1])
        try:
            self._call(recovery, "recover_partition",
                       (partition, candidate, f"{principal}@localhost",
                        native_password_hash(password)))
        finally:
            recovery.close()
        self._writer = self._connect(principal, password)
        self._writer_credential = (principal, password)
        row = self._read_current(partition)
        self._check_connections()
        if row != (candidate, 0, next_epoch, next_epoch, "COMMITTED", None, "DENY_ALL"):
            raise GatewayClosed("fresh default-deny recovery readback failed")
        self._incarnation = candidate
        self._partition = partition
        self._writer_epoch = next_epoch
        return candidate

    def _verify_recovery(self, partition: str, incarnation: str, phase: str) -> None:
        if (not self.closed or self._recovery_phase != phase
                or partition != self._partition or incarnation != self._incarnation
                or self._incarnation is None or self._writer_epoch is None):
            raise GatewayClosed("recovery generation is not awaiting this transition")
        self._check_lock()
        self._check_connections()
        epoch = self._writer_epoch
        if self._read_current(partition) != (
            incarnation, 0, epoch, epoch, "COMMITTED", None, "DENY_ALL"
        ):
            raise GatewayClosed("default-deny recovery readback changed")

    @serialized
    def confirm_home(self, partition: str, incarnation: str,
                     home_head: tuple[str, int, str]) -> None:
        """Accept exact readback from the trusted Home recovery coordinator."""
        try:
            self._verify_recovery(partition, incarnation, "CLOSED")
            if (type(home_head) is not tuple or len(home_head) != 3
                    or type(home_head[1]) is not int
                    or home_head != (incarnation, 0, "DENY_ALL")):
                raise GatewayClosed("Home default-deny readback mismatch")
            self._recovery_phase = "REAUTH_ONLY"
        except Exception:
            self.close_admission()
            raise

    @serialized
    def open_admission(self, partition: str, incarnation: str) -> None:
        try:
            self._verify_recovery(partition, incarnation, "REAUTH_ONLY")
            self._recovery_phase = "OPEN"
            self.closed = False
        except Exception:
            self.close_admission()
            raise

    @serialized
    def authorize(self, partition: str, incarnation: str, revision: int,
                  digest: str) -> bool:
        if self.closed or incarnation != self._incarnation:
            return False
        try:
            self._check_lock()
            self._check_connections()
            row = self._read_current(partition)
        except (GatewayClosed, pymysql.MySQLError, OSError):
            self.closed = True
            return False
        return bool(row and row[0] == incarnation and row[1] == revision
                    and row[4] == "COMMITTED" and row[6] == digest
                    and digest != "DENY_ALL")

    @serialized
    def prepare(self, partition: str, incarnation: str, event: str,
                expected_revision: int, digest: str) -> None:
        self._require_open(incarnation)
        assert self._writer is not None
        try:
            self._writer.ping(reconnect=False)
            self._call(self._writer, "prepare_event",
                       (partition, incarnation, event, expected_revision, digest))
        except pymysql.MySQLError as exc:
            if not exc.args or exc.args[0] != 1644:  # 1644 is the procedure's legal rejection
                self.closed = True
            raise

    @serialized
    def commit(self, partition: str, incarnation: str, event: str,
               digest: str) -> None:
        self._require_open(incarnation)
        assert self._writer is not None
        try:
            self._writer.ping(reconnect=False)
            self._call(self._writer, "commit_event",
                       (partition, incarnation, event, digest))
        except pymysql.MySQLError as exc:
            if not exc.args or exc.args[0] != 1644:
                self.closed = True
            raise

    @serialized
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

    @serialized
    def close(self) -> None:
        self.close_admission()
        for connection in (self._reader, self._writer):
            if connection is not None:
                try:
                    connection.close()
                except pymysql.MySQLError:
                    pass
        self._reader = self._writer = None
        self._writer_credential = None
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
