"""Disposable MariaDB integration tests for disconnected Task 1 gateway."""

from __future__ import annotations

import shutil
import os
import fcntl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pymysql
import pytest

from gateway import Gateway, GatewayBusy, GatewayClosed


class PrivateDB:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.data = root / "data"
        self.socket = root / "db.sock"
        self.process: subprocess.Popen[bytes] | None = None
        self.data.mkdir()
        self.run("mariadb-install-db", "--no-defaults", f"--datadir={self.data}",
                 "--auth-root-authentication-method=normal", "--skip-test-db")
        self.start()
        self.sql("CREATE DATABASE witness")
        schema = Path(__file__).with_name("gateway_schema.sql").read_text()
        self.run("mariadb", "--no-defaults", f"--socket={self.socket}", "-uroot",
                 input_text=schema)
        self.sql("INSERT INTO witness.head VALUES ('p1','old-incarnation',0,1,1,"
                 "'COMMITTED',NULL,'OLD_ALLOW',1)")
        self.sql("CREATE USER 'gw_reader'@'localhost' IDENTIFIED BY 'synthetic-read';"
                 "CREATE USER 'gw_writer1'@'localhost' IDENTIFIED BY 'synthetic-one';"
                 "CREATE USER 'gw_writer2'@'localhost' IDENTIFIED BY 'synthetic-two';"
                 "CREATE USER 'gw_recovery'@'localhost' IDENTIFIED BY 'synthetic-recover';"
                 "GRANT EXECUTE ON PROCEDURE witness.read_current TO 'gw_reader'@'localhost';"
                 "GRANT EXECUTE ON PROCEDURE witness.read_event TO 'gw_reader'@'localhost';"
                 "GRANT EXECUTE ON PROCEDURE witness.prepare_e1 TO 'gw_writer1'@'localhost';"
                 "GRANT EXECUTE ON PROCEDURE witness.commit_e1 TO 'gw_writer1'@'localhost';"
                 "GRANT EXECUTE ON PROCEDURE witness.prepare_e2 TO 'gw_writer2'@'localhost';"
                 "GRANT EXECUTE ON PROCEDURE witness.commit_e2 TO 'gw_writer2'@'localhost';"
                 "GRANT EXECUTE ON PROCEDURE witness.recover_e2 TO 'gw_recovery'@'localhost'")

    @staticmethod
    def run(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(args, input=input_text, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result

    def sql(self, statement: str) -> str:
        return self.run("mariadb", "--no-defaults", f"--socket={self.socket}",
                        "-uroot", "-N", "-B", "-e", statement).stdout.strip()

    def start(self) -> None:
        self.process = subprocess.Popen(
            ["mariadbd", "--no-defaults", f"--datadir={self.data}",
             f"--socket={self.socket}", f"--pid-file={self.root / 'pid'}",
             f"--log-error={self.root / 'log'}", "--skip-networking"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            ping = subprocess.run(
                ["mariadb-admin", "--no-defaults", f"--socket={self.socket}",
                 "-uroot", "ping"], capture_output=True,
            )
            if ping.returncode == 0:
                return
            if self.process.poll() is not None:
                raise RuntimeError((self.root / "log").read_text()[-2000:])
            time.sleep(0.1)
        raise TimeoutError("private MariaDB startup")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.run("mariadb-admin", "--no-defaults", f"--socket={self.socket}",
                     "-uroot", "shutdown")
            self.process.wait(timeout=10)

    def connect(self, user: str, password: str) -> pymysql.Connection:
        return pymysql.connect(unix_socket=str(self.socket), user=user,
                               password=password, database="witness", autocommit=True)


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory(prefix="kap2-gateway-") as directory:
        server = PrivateDB(Path(directory))
        try:
            yield server
        finally:
            server.stop()


def new_gateway(db: PrivateDB) -> Gateway:
    return Gateway(socket=str(db.socket), lock_path=str(db.root / "gateway.lock"),
                   reader_password="synthetic-read", writer_password="synthetic-two",
                   recovery_password="synthetic-recover")


def test_closed_first_read_and_competing_instance(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        assert gateway.authorize("p1", "old-incarnation", 0, "OLD_ALLOW") is False
        with pytest.raises(GatewayBusy):
            new_gateway(db)
        contender = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,sys.argv[1]); "
             "from gateway import Gateway, GatewayBusy; "
             "\ntry: Gateway(socket=sys.argv[2],lock_path=sys.argv[3],"
             "reader_password='synthetic-read',writer_password='synthetic-two',"
             "recovery_password='synthetic-recover')\n"
             "except GatewayBusy: sys.exit(0)\n"
             "sys.exit(1)",
             str(Path(__file__).parent), str(db.socket), str(db.root / "gateway.lock")],
            capture_output=True, text=True,
        )
        assert contender.returncode == 0, contender.stderr
        incarnation = gateway.recover("p1")
        assert incarnation != "old-incarnation"
        assert len(incarnation) == 64
        assert gateway.authorize("p1", incarnation, 0, "DENY_ALL") is False
        assert db.sql("SELECT ready_hint,digest FROM witness.head WHERE partition_id='p1'") == "0\tDENY_ALL"


def test_pending_commit_idempotency_and_unknown_ack_readback(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        # Model an application-level lost acknowledgement after DB commit: the
        # gateway receives no return value and must read back the exact event.
        with db.connect("gw_writer2", "synthetic-two") as writer:
            with writer.cursor() as cursor:
                cursor.execute("CALL witness.prepare_e2(%s,%s,%s,%s,%s)",
                               ("p1", incarnation, "grant-1", 0, "ALLOW_A"))
        assert gateway.event_outcome("p1", incarnation, "grant-1") == ("PENDING", 1, "ALLOW_A")
        assert gateway.event_outcome("p1", incarnation, "missing") is None
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is False
        gateway.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")
        with pytest.raises(pymysql.MySQLError):
            gateway.prepare("p1", incarnation, "grant-1", 0, "ALTERED")
        assert gateway.event_outcome("p1", incarnation, "grant-1") == ("PENDING", 1, "ALLOW_A")
        with db.connect("gw_writer2", "synthetic-two") as writer:
            with writer.cursor() as cursor:
                cursor.execute("CALL witness.commit_e2(%s,%s,%s,%s)",
                               ("p1", incarnation, "grant-1", "ALLOW_A"))
        gateway.commit("p1", incarnation, "grant-1", "ALLOW_A")
        assert gateway.event_outcome("p1", incarnation, "grant-1") == ("COMMITTED", 1, "ALLOW_A")
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is True


def test_database_principals_and_old_epoch_are_enforced(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        with db.connect("gw_writer1", "synthetic-one") as old:
            with old.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("CALL witness.prepare_e1(%s,%s,%s,%s,%s)",
                                   ("p1", incarnation, "old-try", 0, "ALLOW_OLD"))
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("CALL witness.prepare_e2(%s,%s,%s,%s,%s)",
                                   ("p1", incarnation, "wrong-proc", 0, "ALLOW_OLD"))
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("UPDATE witness.head SET digest='FORGED' WHERE partition_id='p1'")
        with db.connect("gw_reader", "synthetic-read") as reader:
            with reader.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("UPDATE witness.head SET digest='FORGED' WHERE partition_id='p1'")
        with db.connect("gw_writer2", "synthetic-two") as current_writer:
            with current_writer.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("CALL witness.recover_e2(%s,%s)",
                                   ("p1", "a" * 64))
        with db.connect("gw_recovery", "synthetic-recover") as recovery:
            with recovery.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("UPDATE witness.head SET ready_hint=1 WHERE partition_id='p1'")
        assert gateway.authorize("p1", incarnation, 0, "FORGED") is False


def test_gateway_and_database_restart_deny_before_recovery(db: PrivateDB) -> None:
    with new_gateway(db) as first:
        incarnation = first.recover("p1")
        first.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")
        first.commit("p1", incarnation, "grant-1", "ALLOW_A")
        assert first.authorize("p1", incarnation, 1, "ALLOW_A") is True
    with new_gateway(db) as restarted:
        assert restarted.authorize("p1", incarnation, 1, "ALLOW_A") is False
        new_incarnation = restarted.recover("p1")
        assert restarted.authorize("p1", incarnation, 1, "ALLOW_A") is False
        restarted.prepare("p1", new_incarnation, "grant-2", 0, "ALLOW_B")
        restarted.commit("p1", new_incarnation, "grant-2", "ALLOW_B")
        assert restarted.authorize("p1", new_incarnation, 1, "ALLOW_B") is True
        db.stop()
        assert restarted.authorize("p1", new_incarnation, 1, "ALLOW_B") is False
        assert restarted.closed is True
    db.start()
    with new_gateway(db) as after_database_restart:
        assert after_database_restart.authorize("p1", incarnation, 1, "ALLOW_A") is False


def test_lost_process_lock_closes_admission(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        gateway.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")
        gateway.commit("p1", incarnation, "grant-1", "ALLOW_A")
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is True
        assert gateway._lock_fd is not None
        os.close(gateway._lock_fd)  # synthetic lock-loss injection
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is False
        assert gateway.closed is True


def test_released_flock_with_open_descriptor_closes_admission(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        gateway.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")
        gateway.commit("p1", incarnation, "grant-1", "ALLOW_A")
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is True
        assert gateway._lock_fd is not None
        fcntl.flock(gateway._lock_fd, fcntl.LOCK_UN)
        assert os.fstat(gateway._lock_fd)
        contender = subprocess.Popen(
            [sys.executable, "-c",
             "import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDWR); "
             "fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); "
             "print('ACQUIRED',flush=True); sys.stdin.read(1)",
             str(db.root / "gateway.lock")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert contender.stdout is not None
            assert contender.stdout.readline().strip() == "ACQUIRED"
            assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is False
            assert gateway.closed is True
            with pytest.raises(GatewayClosed):
                gateway.prepare("p1", incarnation, "grant-2", 1, "ALLOW_B")
            with pytest.raises(GatewayClosed):
                gateway.commit("p1", incarnation, "grant-1", "ALLOW_A")
        finally:
            assert contender.stdin is not None
            contender.stdin.write("x")
            contender.stdin.close()
            assert contender.wait(timeout=5) == 0


def test_replaced_lock_path_closes_admission(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        lock_path = db.root / "gateway.lock"
        lock_path.rename(db.root / "replaced.lock")
        lock_path.touch()
        assert gateway.authorize("p1", incarnation, 0, "DENY_ALL") is False
        assert gateway.closed is True
        with pytest.raises(GatewayClosed):
            gateway.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")


def test_writer_connection_loss_closes_admission_with_usable_reader(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        gateway.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")
        gateway.commit("p1", incarnation, "grant-1", "ALLOW_A")
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is True
        assert gateway._reader is not None and gateway._writer is not None
        db.sql(f"KILL CONNECTION {gateway._writer.thread_id()}")
        gateway._reader.ping(reconnect=False)
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is False
        assert gateway.closed is True
        with pytest.raises(GatewayClosed):
            gateway.prepare("p1", incarnation, "grant-2", 1, "ALLOW_B")
        new_incarnation = gateway.recover("p1")
        assert new_incarnation != incarnation
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is False


def test_restored_committed_ready_rows_cannot_open_gate(db: PrivateDB) -> None:
    db.stop()
    snapshot = db.root / "snapshot"
    shutil.copytree(db.data, snapshot)
    db.start()
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        gateway.prepare("p1", incarnation, "revoke-1", 0, "DENY_ALL")
        gateway.commit("p1", incarnation, "revoke-1", "DENY_ALL")
    db.stop()
    shutil.rmtree(db.data)
    shutil.copytree(snapshot, db.data)
    db.start()
    assert db.sql("SELECT state,ready_hint,digest FROM witness.head WHERE partition_id='p1'") == (
        "COMMITTED\t1\tOLD_ALLOW")
    with new_gateway(db) as restored:
        assert restored.authorize("p1", "old-incarnation", 0, "OLD_ALLOW") is False
        fresh = restored.recover("p1")
        assert fresh != "old-incarnation"
        assert restored.authorize("p1", "old-incarnation", 0, "OLD_ALLOW") is False
        assert restored.authorize("p1", fresh, 0, "DENY_ALL") is False
