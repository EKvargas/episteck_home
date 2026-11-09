"""Disposable MariaDB integration tests for disconnected Task 1 gateway."""

from __future__ import annotations

import shutil
import os
import fcntl
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymysql
import pytest

from gateway import Gateway, GatewayBusy, GatewayClosed, writer_principal

# Synthetic operator-provisioned writer principals, one never-reused account per
# epoch. Epoch 1 is the pre-recovery writer with a known synthetic password; later
# accounts start locked with an unknown password until a recovery mints theirs.
# The two-host matrix performs about 20 recoveries; keep ample headroom.
WRITER_POOL = 64
PRE_RECOVERY_WRITER_PASSWORD = "synthetic-writer-1"


def current_writer(gateway: Gateway) -> tuple[str, str]:
    """The credential the gateway minted at its latest recovery (tests only)."""
    assert gateway._writer_credential is not None
    return gateway._writer_credential


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
        writers = []
        for epoch in range(1, WRITER_POOL + 1):
            user = f"'{writer_principal(epoch)}'@'localhost'"
            state = "ACTIVE" if epoch == 1 else "UNUSED"
            password = (PRE_RECOVERY_WRITER_PASSWORD if epoch == 1
                        else f"unknown-{os.urandom(16).hex()}")
            lock = "" if epoch == 1 else " ACCOUNT LOCK"
            writers.append(
                f"CREATE USER {user} IDENTIFIED BY '{password}'{lock};"
                f"GRANT EXECUTE ON PROCEDURE witness.prepare_event TO {user};"
                f"GRANT EXECUTE ON PROCEDURE witness.commit_event TO {user};"
                f"INSERT INTO witness.writer_principals VALUES "
                f"('p1',{epoch},'{writer_principal(epoch)}@localhost','{state}');")
        self.sql("CREATE USER 'gw_reader'@'localhost' IDENTIFIED BY 'synthetic-read';"
                 "CREATE USER 'gw_recovery'@'localhost' IDENTIFIED BY 'synthetic-recover';"
                 "GRANT EXECUTE ON PROCEDURE witness.read_current TO 'gw_reader'@'localhost';"
                 "GRANT EXECUTE ON PROCEDURE witness.read_event TO 'gw_reader'@'localhost';"
                 "GRANT EXECUTE ON PROCEDURE witness.recover_partition TO 'gw_recovery'@'localhost';"
                 + "".join(writers))

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
                   reader_password="synthetic-read", recovery_password="synthetic-recover")


@pytest.mark.parametrize("history", ["events", "empty", "initial", "event-only"])
def test_recovery_rejects_retained_incarnation_collision(db, monkeypatch, history):
    candidate = "a" * 64
    with new_gateway(db) as gateway:
        monkeypatch.setattr("gateway.secrets.token_hex", lambda _: candidate)
        if history == "initial":
            db.sql(f"UPDATE witness.head SET incarnation='{candidate}'")
        elif history == "event-only":
            db.sql(f"INSERT INTO witness.events VALUES "
                   f"('p1','{candidate}','retained',0,1,'OLD_ALLOW','COMMITTED')")
        else:
            assert gateway.recover("p1") == candidate
            if history == "events":
                with db.connect(*current_writer(gateway)) as writer:
                    Gateway._call(writer, "prepare_event", ("p1", candidate, "e1", 0, "ALLOW_A"))
                    Gateway._call(writer, "commit_event", ("p1", candidate, "e1", "ALLOW_A"))
        monkeypatch.setattr("gateway.secrets.token_hex", lambda _: "b" * 64)
        gateway.recover("p1")
        before = db.sql("SELECT * FROM witness.head")
        monkeypatch.setattr("gateway.secrets.token_hex", lambda _: candidate)
        with pytest.raises(pymysql.MySQLError, match="reused incarnation"):
            gateway.recover("p1")
        assert gateway.closed
        assert db.sql("SELECT * FROM witness.head") == before


def test_witness_recovery_alone_cannot_admit_serving_mutation(db):
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        assert gateway.closed
        with pytest.raises(GatewayClosed):
            gateway.prepare("p1", incarnation, "premature", 0, "ALLOW_A")


@pytest.mark.parametrize("proof", ["wrong-partition", "wrong-head", "stale", "no-confirmation"])
def test_recovery_rejects_invalid_home_confirmation(db, proof):
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        with pytest.raises(GatewayClosed):
            if proof == "wrong-partition":
                gateway.confirm_home("p2", incarnation, (incarnation, 0, "DENY_ALL"))
            elif proof == "wrong-head":
                gateway.confirm_home("p1", incarnation, (incarnation, 1, "ALLOW_A"))
            elif proof == "stale":
                gateway.recover("p1")
                gateway.confirm_home("p1", incarnation, (incarnation, 0, "DENY_ALL"))
            else:
                gateway.open_admission("p1", incarnation)
        assert gateway.closed


@pytest.mark.parametrize("change", ["none", "head", "writer", "lock"])
def test_reauth_only_denies_and_opening_rechecks_witness(db, change):
    with new_gateway(db) as gateway:
        incarnation = gateway.recover("p1")
        gateway.confirm_home("p1", incarnation, (incarnation, 0, "DENY_ALL"))
        assert gateway.closed
        assert not gateway.authorize("p1", incarnation, 0, "DENY_ALL")
        with pytest.raises(GatewayClosed):
            gateway.prepare("p1", incarnation, "early", 0, "ALLOW_A")
        if change == "head":
            db.sql("UPDATE witness.head SET digest='CHANGED'")
        elif change == "writer":
            db.sql(f"KILL CONNECTION {gateway._writer.thread_id()}")
        elif change == "lock":
            fcntl.flock(gateway._lock_fd, fcntl.LOCK_UN)
        if change != "none":
            with pytest.raises(GatewayClosed):
                gateway.open_admission("p1", incarnation)
            assert gateway.closed
        else:
            gateway.open_admission("p1", incarnation)
            gateway.prepare("p1", incarnation, "fresh", 0, "ALLOW_A")
            gateway.commit("p1", incarnation, "fresh", "ALLOW_A")
            assert gateway.authorize("p1", incarnation, 1, "ALLOW_A")


def test_recovery_rejects_known_collision_in_another_partition(db, monkeypatch):
    candidate = "c" * 64
    db.sql(f"INSERT INTO witness.events VALUES "
           f"('p2','{candidate}','retained',0,1,'OLD_ALLOW','COMMITTED')")
    with new_gateway(db) as gateway:
        monkeypatch.setattr("gateway.secrets.token_hex", lambda _: candidate)
        with pytest.raises(pymysql.MySQLError, match="reused incarnation"):
            gateway.recover("p1")
        assert gateway.closed


def recover_and_admit(gateway):
    """Synthetic coordinator proof for standalone gateway tests only."""
    incarnation = gateway.recover("p1")
    gateway.confirm_home("p1", incarnation, (incarnation, 0, "DENY_ALL"))
    gateway.open_admission("p1", incarnation)
    return incarnation


def test_repeated_recovery_retires_previous_writer_principal(db: PrivateDB) -> None:
    """R2: each recovery rotates the writer epoch/principal and retires the old one."""
    with new_gateway(db) as gateway:
        first = recover_and_admit(gateway)
        assert db.sql("SELECT writer_epoch,publisher_epoch FROM witness.head "
                      "WHERE partition_id='p1'") == "2\t2"
        # A writer session authenticated before the next recovery models a
        # delayed or leaked pre-recovery credential.
        old_user, old_password = current_writer(gateway)
        assert old_user == "gw_writer2"
        old_session = db.connect(old_user, old_password)
        try:
            second = recover_and_admit(gateway)
            assert second != first
            assert db.sql("SELECT writer_epoch,publisher_epoch FROM witness.head "
                          "WHERE partition_id='p1'") == "3\t3"
            with pytest.raises(pymysql.MySQLError):
                old_session.ping(reconnect=False)
        finally:
            try:
                old_session.close()
            except pymysql.MySQLError:
                pass
        with pytest.raises(pymysql.MySQLError) as locked:
            db.connect(old_user, old_password)
        assert locked.value.args[0] == 4151
        # Even if the retired account were re-enabled, its calls carrying the
        # current incarnation are rejected by the witness procedures.
        db.sql("ALTER USER 'gw_writer2'@'localhost' ACCOUNT UNLOCK")
        with db.connect(old_user, old_password) as late:
            with pytest.raises(pymysql.MySQLError) as rejected:
                Gateway._call(late, "prepare_event", ("p1", second, "late-old-writer", 0, "FORGED"))
            assert rejected.value.args[0] == 1644
        gateway.prepare("p1", second, "grant-1", 0, "ALLOW_A")
        gateway.commit("p1", second, "grant-1", "ALLOW_A")
        assert gateway.authorize("p1", second, 1, "ALLOW_A") is True
        third = recover_and_admit(gateway)
        assert db.sql("SELECT writer_epoch FROM witness.head WHERE partition_id='p1'") == "4"
        assert gateway.authorize("p1", second, 1, "ALLOW_A") is False
        assert gateway.authorize("p1", third, 0, "DENY_ALL") is False


@pytest.mark.parametrize("unavailable", ["retired", "missing-row", "already-active"])
def test_recovery_without_fresh_writer_principal_stays_closed(db: PrivateDB, unavailable):
    with new_gateway(db) as gateway:
        incarnation = recover_and_admit(gateway)
        if unavailable == "retired":
            db.sql("UPDATE witness.writer_principals SET state='RETIRED' WHERE epoch=3")
        elif unavailable == "missing-row":
            db.sql("DELETE FROM witness.writer_principals WHERE epoch=3")
        else:
            db.sql("UPDATE witness.writer_principals SET state='ACTIVE' WHERE epoch=3")
        before = db.sql("SELECT * FROM witness.head")
        with pytest.raises((pymysql.MySQLError, GatewayClosed)):
            gateway.recover("p1")
        assert gateway.closed
        assert db.sql("SELECT * FROM witness.head") == before
        assert db.sql("SELECT state FROM witness.writer_principals WHERE epoch=2") == "ACTIVE"
        assert gateway.authorize("p1", incarnation, 0, "DENY_ALL") is False
        with pytest.raises(GatewayClosed):
            gateway.prepare("p1", incarnation, "after-failed-recovery", 0, "ALLOW_A")


def test_writer_call_queued_behind_recovery_cannot_reach_new_incarnation(db: PrivateDB) -> None:
    """R2: a delayed pre-recovery writer call never commits into the new incarnation."""
    with new_gateway(db) as gateway:
        first = recover_and_admit(gateway)
        root = pymysql.connect(unix_socket=str(db.socket), user="root", autocommit=False)
        old_writer = db.connect(*current_writer(gateway))
        old_result: list[object] = []
        recovered: list[object] = []
        try:
            with root.cursor() as cursor:
                cursor.execute("SELECT * FROM witness.head WHERE partition_id='p1' FOR UPDATE")

            def delayed_old_call():
                try:
                    Gateway._call(old_writer, "prepare_event",
                                  ("p1", first, "delayed", 0, "ALLOW_OLD"))
                    old_result.append("accepted")
                except pymysql.MySQLError as exc:
                    old_result.append(exc.args[0])

            def recovery():
                try:
                    recovered.append(recover_and_admit(gateway))
                except BaseException as exc:  # pragma: no cover - asserted below
                    recovered.append(exc)

            caller = threading.Thread(target=delayed_old_call)
            caller.start()
            time.sleep(0.3)
            recoverer = threading.Thread(target=recovery)
            recoverer.start()
            time.sleep(0.3)
            assert caller.is_alive() and recoverer.is_alive()
            root.commit()
            caller.join(10)
            recoverer.join(10)
            assert not caller.is_alive() and not recoverer.is_alive()
        finally:
            root.close()
            try:
                old_writer.close()
            except pymysql.MySQLError:
                pass
        assert len(recovered) == 1 and isinstance(recovered[0], str), recovered
        second = recovered[0]
        # Whichever got the head lock first, the old call is rejected, killed, or
        # confined to the old incarnation; the new one stays default-deny.
        assert old_result and old_result[0] in {"accepted", 1644, 2013}
        assert db.sql(f"SELECT COUNT(*) FROM witness.events WHERE incarnation='{second}'") == "0"
        assert db.sql("SELECT revision,writer_epoch,state,digest FROM witness.head") == (
            "0\t3\tCOMMITTED\tDENY_ALL")
        assert gateway.authorize("p1", first, 1, "ALLOW_OLD") is False


def test_physical_restore_cannot_revive_any_writer_credential(db: PrivateDB) -> None:
    """R2: restoring an older datadir restores old accounts, never a usable writer."""
    with new_gateway(db) as gateway:
        recover_and_admit(gateway)
        snapshot_user, snapshot_password = current_writer(gateway)
    db.stop()
    snapshot = db.root / "snapshot"
    shutil.copytree(db.data, snapshot)
    db.start()
    with new_gateway(db) as gateway:
        recover_and_admit(gateway)
        later_user, later_password = current_writer(gateway)
        assert (snapshot_user, later_user) == ("gw_writer2", "gw_writer3")
    db.stop()
    shutil.rmtree(db.data)
    shutil.copytree(snapshot, db.data)
    db.start()
    # The restored datadir shows epoch 2 ACTIVE and epoch 3 UNUSED again.
    assert db.sql("SELECT epoch,state FROM witness.writer_principals WHERE epoch IN (2,3) "
                  "ORDER BY epoch") == "2\tACTIVE\n3\tUNUSED"
    with new_gateway(db) as restored:
        assert restored.authorize("p1", "old-incarnation", 0, "OLD_ALLOW") is False
        fresh = recover_and_admit(restored)
        assert current_writer(restored)[0] == "gw_writer3"
        assert db.sql("SELECT writer_epoch FROM witness.head") == "3"
        # Neither the snapshot-era nor the lost-history credential authenticates.
        for user, password in ((snapshot_user, snapshot_password),
                               (later_user, later_password)):
            with pytest.raises(pymysql.MySQLError) as refused:
                db.connect(user, password)
            assert refused.value.args[0] in {1045, 4151}
        restored.prepare("p1", fresh, "grant-1", 0, "ALLOW_A")
        restored.commit("p1", fresh, "grant-1", "ALLOW_A")
        assert restored.authorize("p1", fresh, 1, "ALLOW_A") is True


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
             "reader_password='synthetic-read',"
             "recovery_password='synthetic-recover')\n"
             "except GatewayBusy: sys.exit(0)\n"
             "sys.exit(1)",
             str(Path(__file__).parent), str(db.socket), str(db.root / "gateway.lock")],
            capture_output=True, text=True,
        )
        assert contender.returncode == 0, contender.stderr
        incarnation = recover_and_admit(gateway)
        assert incarnation != "old-incarnation"
        assert len(incarnation) == 64
        assert gateway.authorize("p1", incarnation, 0, "DENY_ALL") is False
        assert db.sql("SELECT ready_hint,digest FROM witness.head WHERE partition_id='p1'") == "0\tDENY_ALL"


def test_pending_commit_idempotency_and_unknown_ack_readback(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = recover_and_admit(gateway)
        # Model an application-level lost acknowledgement after DB commit: the
        # gateway receives no return value and must read back the exact event.
        with db.connect(*current_writer(gateway)) as writer:
            with writer.cursor() as cursor:
                cursor.execute("CALL witness.prepare_event(%s,%s,%s,%s,%s)",
                               ("p1", incarnation, "grant-1", 0, "ALLOW_A"))
        assert gateway.event_outcome("p1", incarnation, "grant-1") == ("PENDING", 1, "ALLOW_A")
        assert gateway.event_outcome("p1", incarnation, "missing") is None
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is False
        gateway.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")
        with pytest.raises(pymysql.MySQLError):
            gateway.prepare("p1", incarnation, "grant-1", 0, "ALTERED")
        assert gateway.event_outcome("p1", incarnation, "grant-1") == ("PENDING", 1, "ALLOW_A")
        with db.connect(*current_writer(gateway)) as writer:
            with writer.cursor() as cursor:
                cursor.execute("CALL witness.commit_event(%s,%s,%s,%s)",
                               ("p1", incarnation, "grant-1", "ALLOW_A"))
        gateway.commit("p1", incarnation, "grant-1", "ALLOW_A")
        assert gateway.event_outcome("p1", incarnation, "grant-1") == ("COMMITTED", 1, "ALLOW_A")
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is True


def test_database_principals_and_old_epoch_are_enforced(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = recover_and_admit(gateway)
        # The pre-recovery epoch-1 principal is retired: its account is locked ...
        with pytest.raises(pymysql.MySQLError) as locked:
            db.connect("gw_writer1", PRE_RECOVERY_WRITER_PASSWORD)
        assert locked.value.args[0] == 4151
        # ... and, even if re-enabled, the witness rejects its calls.
        db.sql("ALTER USER 'gw_writer1'@'localhost' ACCOUNT UNLOCK")
        with db.connect("gw_writer1", PRE_RECOVERY_WRITER_PASSWORD) as old:
            with old.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError) as rejected:
                    cursor.execute("CALL witness.prepare_event(%s,%s,%s,%s,%s)",
                                   ("p1", incarnation, "old-try", 0, "ALLOW_OLD"))
                assert rejected.value.args[0] == 1644
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("UPDATE witness.head SET digest='FORGED' WHERE partition_id='p1'")
        # A provisioned but not yet activated principal is locked; even if it were
        # misprovisioned with a known password, the witness rejects its calls.
        with pytest.raises(pymysql.MySQLError):
            db.connect("gw_writer3", "guessed")
        db.sql("ALTER USER 'gw_writer3'@'localhost' IDENTIFIED BY 'misprovisioned' ACCOUNT UNLOCK")
        with db.connect("gw_writer3", "misprovisioned") as future:
            with future.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError) as early:
                    cursor.execute("CALL witness.prepare_event(%s,%s,%s,%s,%s)",
                                   ("p1", incarnation, "future-try", 0, "ALLOW_F"))
                assert early.value.args[0] == 1644
        with db.connect("gw_reader", "synthetic-read") as reader:
            with reader.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("UPDATE witness.head SET digest='FORGED' WHERE partition_id='p1'")
        with db.connect(*current_writer(gateway)) as active_writer:
            with active_writer.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("CALL witness.recover_partition(%s,%s,%s)",
                                   ("p1", "a" * 64, "gw_writer3@localhost"))
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("CALL witness._retire_writers('p1')")
        with db.connect("gw_recovery", "synthetic-recover") as recovery:
            with recovery.cursor() as cursor:
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("UPDATE witness.head SET ready_hint=1 WHERE partition_id='p1'")
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("UPDATE witness.writer_principals SET state='UNUSED'")
                with pytest.raises(pymysql.MySQLError):
                    cursor.execute("CALL witness._retire_writers('p1')")
        assert gateway.authorize("p1", incarnation, 0, "FORGED") is False


def test_gateway_and_database_restart_deny_before_recovery(db: PrivateDB) -> None:
    with new_gateway(db) as first:
        incarnation = recover_and_admit(first)
        first.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")
        first.commit("p1", incarnation, "grant-1", "ALLOW_A")
        assert first.authorize("p1", incarnation, 1, "ALLOW_A") is True
    with new_gateway(db) as restarted:
        assert restarted.authorize("p1", incarnation, 1, "ALLOW_A") is False
        new_incarnation = recover_and_admit(restarted)
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
        incarnation = recover_and_admit(gateway)
        gateway.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")
        gateway.commit("p1", incarnation, "grant-1", "ALLOW_A")
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is True
        assert gateway._lock_fd is not None
        os.close(gateway._lock_fd)  # synthetic lock-loss injection
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is False
        assert gateway.closed is True


def test_released_flock_with_open_descriptor_closes_admission(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = recover_and_admit(gateway)
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
        incarnation = recover_and_admit(gateway)
        lock_path = db.root / "gateway.lock"
        lock_path.rename(db.root / "replaced.lock")
        lock_path.touch()
        assert gateway.authorize("p1", incarnation, 0, "DENY_ALL") is False
        assert gateway.closed is True
        with pytest.raises(GatewayClosed):
            gateway.prepare("p1", incarnation, "grant-1", 0, "ALLOW_A")


def test_writer_connection_loss_closes_admission_with_usable_reader(db: PrivateDB) -> None:
    with new_gateway(db) as gateway:
        incarnation = recover_and_admit(gateway)
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
        new_incarnation = recover_and_admit(gateway)
        assert new_incarnation != incarnation
        assert gateway.authorize("p1", incarnation, 1, "ALLOW_A") is False


def test_restored_committed_ready_rows_cannot_open_gate(db: PrivateDB) -> None:
    db.stop()
    snapshot = db.root / "snapshot"
    shutil.copytree(db.data, snapshot)
    db.start()
    with new_gateway(db) as gateway:
        incarnation = recover_and_admit(gateway)
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
        fresh = recover_and_admit(restored)
        assert fresh != "old-incarnation"
        assert restored.authorize("p1", "old-incarnation", 0, "OLD_ALLOW") is False
        assert restored.authorize("p1", fresh, 0, "DENY_ALL") is False


def test_serving_thread_survives_writer_loss_and_later_recovery(db: PrivateDB) -> None:
    """Two-host attempt 03, A5 -> A6: the witness serves and recovers on different
    HTTP threads. A writer lost on the serving thread must not break the sessions
    that a later recovery pins and the serving thread then uses."""
    serving = ThreadPoolExecutor(max_workers=1)

    def serve(gateway: Gateway, method: str, *args):
        return serving.submit(getattr(gateway, method), *args).result(timeout=10)

    try:
        with new_gateway(db) as gateway:
            incarnation = recover_and_admit(gateway)
            serve(gateway, "prepare", "p1", incarnation, "grant-1", 0, "ALLOW_A")
            serve(gateway, "commit", "p1", incarnation, "grant-1", "ALLOW_A")
            assert gateway._writer is not None
            db.sql(f"KILL CONNECTION {gateway._writer.thread_id()}")
            assert serve(gateway, "authorize", "p1", incarnation, 1, "ALLOW_A") is False
            fresh = recover_and_admit(gateway)
            serve(gateway, "prepare", "p1", fresh, "grant-2", 0, "ALLOW_B")
            serve(gateway, "commit", "p1", fresh, "grant-2", "ALLOW_B")
            assert serve(gateway, "authorize", "p1", fresh, 1, "ALLOW_B") is True
    finally:
        serving.shutdown()


def test_pinned_sessions_never_negotiate_tls(db: PrivateDB) -> None:
    """The witness is socket-only; PyMySQL's default PREFERRED TLS must not wrap its
    sessions when the server offers TLS (MariaDB 11.4+ does so by default)."""
    with new_gateway(db) as gateway:
        recover_and_admit(gateway)
        for session in (gateway._reader, gateway._writer):
            assert session is not None
            with session.cursor() as cursor:
                cursor.execute("SELECT VARIABLE_VALUE FROM information_schema.SESSION_STATUS "
                               "WHERE VARIABLE_NAME='Ssl_version'")
                assert cursor.fetchone() in (None, ("",))
