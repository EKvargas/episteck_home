"""Real disposable two-MariaDB acceptance for the limited PERSON vertical."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pymysql

GATEWAY_DIR = Path(__file__).parents[1] / "knowledge-kap2-transactional-witness"
sys.path.insert(0, str(GATEWAY_DIR))
from gateway import Gateway  # noqa: E402
from test_gateway import PrivateDB  # noqa: E402

from episteck_home.knowledge_authority.integrated import PersonAuthority
from episteck_home.policy.typed_access import AccessRequirement


@dataclass
class Binding:
    site: str = "kap2-probe-person"
    user: str = "owner-user"
    service: str = "home-probe"

    def site_name(self) -> str:
        return self.site

    def user_name(self) -> str:
        return self.user

    def service_name(self) -> str:
        return self.service


@pytest.fixture
def services():
    with tempfile.TemporaryDirectory(prefix="kap2-person-home-") as home_dir:
        with tempfile.TemporaryDirectory(prefix="kap2-person-witness-") as witness_dir:
            home = PrivateDB(Path(home_dir))
            witness_db = PrivateDB(Path(witness_dir))
            try:
                install_home(home)
                yield home, witness_db
            finally:
                home.stop()
                witness_db.stop()


def install_home(db: PrivateDB) -> None:
    db.sql("CREATE DATABASE _aaaaaaaaaaaaaaaa; CREATE DATABASE home_auth;"
           "CREATE TABLE _aaaaaaaaaaaaaaaa.`tabUser` (name VARCHAR(140) PRIMARY KEY, enabled INT, first_name VARCHAR(140));"
           "CREATE TABLE _aaaaaaaaaaaaaaaa.`tabPerson` (name VARCHAR(140) PRIMARY KEY, linked_user VARCHAR(140), notes TEXT);"
           "CREATE TABLE _aaaaaaaaaaaaaaaa.`tabConsent Grant` (name VARCHAR(140) PRIMARY KEY,"
           "actor_person VARCHAR(140), subject_person VARCHAR(140), domain VARCHAR(32),"
           "actions VARCHAR(80), state VARCHAR(16), valid_from DATETIME NULL,"
           "valid_until DATETIME NULL, granted_by VARCHAR(140), note TEXT);"
           "INSERT INTO _aaaaaaaaaaaaaaaa.`tabUser` VALUES ('owner-user',1,'Owner'),('actor-user',1,'Actor');"
           "INSERT INTO _aaaaaaaaaaaaaaaa.`tabPerson` VALUES ('owner','owner-user',NULL),('actor','actor-user',NULL);"
           "INSERT INTO _aaaaaaaaaaaaaaaa.`tabConsent Grant` VALUES "
           "('grant-1','actor','owner','KNOWLEDGE','VIEW','ACTIVE',NULL,NULL,'owner',NULL)")
    schema = Path(__file__).with_name("integrated_schema.sql").read_text()
    db.run("mariadb", "--no-defaults", f"--socket={db.socket}", "-uroot", input_text=schema)
    install_procedures(db, "_aaaaaaaaaaaaaaaa")
    db.sql("INSERT INTO home_auth.binding VALUES "
           "('kap2-probe-person','home-probe','p1','_aaaaaaaaaaaaaaaa',1);"
           "INSERT INTO home_auth.head VALUES ('p1','old-incarnation',0,'OLD_ALLOW');"
           "INSERT INTO home_auth.dependency VALUES ('p1','grant-1',1);"
           "CREATE USER 'ha_mutator'@'localhost' IDENTIFIED BY 'synthetic-mutator';"
           "CREATE USER 'ha_reader'@'localhost' IDENTIFIED BY 'synthetic-reader';"
           "CREATE USER 'ha_recovery'@'localhost' IDENTIFIED BY 'synthetic-home-recover';"
           "CREATE USER 'ha_fixture'@'localhost' IDENTIFIED BY 'synthetic-fixture';"
           "CREATE USER 'site_runtime'@'localhost' IDENTIFIED BY 'synthetic-site';"
           "CREATE USER 'ha_old'@'localhost' IDENTIFIED BY 'synthetic-old';"
           "GRANT SELECT ON home_auth.* TO 'ha_mutator'@'localhost';"
           "GRANT SELECT ON _aaaaaaaaaaaaaaaa.`tabUser` TO 'ha_mutator'@'localhost';"
           "GRANT SELECT ON _aaaaaaaaaaaaaaaa.`tabPerson` TO 'ha_mutator'@'localhost';"
           "GRANT SELECT ON _aaaaaaaaaaaaaaaa.`tabConsent Grant` TO 'ha_mutator'@'localhost';"
           "GRANT EXECUTE ON PROCEDURE home_auth.stage_person_mutation TO 'ha_mutator'@'localhost';"
           "GRANT EXECUTE ON PROCEDURE home_auth.record_person_event TO 'ha_mutator'@'localhost';"
           "GRANT SELECT ON home_auth.* TO 'ha_reader'@'localhost';"
           "GRANT SELECT ON _aaaaaaaaaaaaaaaa.`tabUser` TO 'ha_reader'@'localhost';"
           "GRANT SELECT ON _aaaaaaaaaaaaaaaa.`tabPerson` TO 'ha_reader'@'localhost';"
           "GRANT SELECT ON _aaaaaaaaaaaaaaaa.`tabConsent Grant` TO 'ha_reader'@'localhost';"
           "GRANT SELECT ON home_auth.binding TO 'ha_recovery'@'localhost';"
           "GRANT SELECT ON home_auth.head TO 'ha_recovery'@'localhost';"
           "GRANT EXECUTE ON PROCEDURE home_auth.reset_person_incarnation TO 'ha_recovery'@'localhost';"
           "GRANT SELECT,INSERT,UPDATE,DELETE ON home_auth.* TO 'ha_fixture'@'localhost';"
           "GRANT SELECT,INSERT,UPDATE,DELETE ON _aaaaaaaaaaaaaaaa.* TO 'ha_fixture'@'localhost';"
           "GRANT SELECT,INSERT,UPDATE,DELETE ON _aaaaaaaaaaaaaaaa.* TO 'site_runtime'@'localhost'")
    install_guards(db, "_aaaaaaaaaaaaaaaa")


def install_procedures(db: PrivateDB, site_database: str,
                       root_password: str = "") -> None:
    if not re.fullmatch(r"_[0-9a-f]{16}", site_database):
        raise ValueError("invalid disposable Frappe database")
    sql = Path(__file__).with_name("integrated_procedures.sql").read_text().replace(
        "__SITE_DB__", site_database)
    credentials = [f"-p{root_password}"] if root_password else []
    db.run("mariadb", "--no-defaults", f"--socket={db.socket}", "-uroot",
           *credentials, input_text=sql)


def install_guards(db: PrivateDB, site_database: str, root_password: str = "") -> None:
    root = pymysql.connect(unix_socket=str(db.socket), user="root",
                           password=root_password, autocommit=True)
    protected = {
        "User": ("name", "enabled"),
        "Person": ("name", "linked_user"),
        "Consent Grant": ("name", "actor_person", "subject_person", "domain", "actions",
                          "state", "valid_from", "valid_until", "granted_by"),
    }
    try:
        with root.cursor() as cursor:
            for number, (doctype, fields) in enumerate(protected.items()):
                table = f"`{site_database}`.`tab{doctype}`"
                changed = " OR ".join(f"NOT (OLD.`{field}` <=> NEW.`{field}`)" for field in fields)
                cursor.execute(f"CREATE TRIGGER `{site_database}`.kap2_person_{number}_u BEFORE UPDATE ON {table} "
                               f"FOR EACH ROW BEGIN IF USER() NOT IN ('ha_mutator@localhost',"
                               f"'ha_fixture@localhost') AND ({changed}) "
                               "THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_PERSON_GUARD'; END IF; END")
                cursor.execute(f"CREATE TRIGGER `{site_database}`.kap2_person_{number}_d BEFORE DELETE ON {table} "
                               "FOR EACH ROW BEGIN IF USER() NOT IN ('ha_mutator@localhost',"
                               "'ha_fixture@localhost') "
                               "THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_PERSON_GUARD'; END IF; END")
            cursor.execute(f"CREATE TRIGGER `{site_database}`.kap2_person_grant_i BEFORE INSERT ON "
                           f"`{site_database}`.`tabConsent Grant` FOR EACH ROW BEGIN "
                           "IF USER() NOT IN ('ha_mutator@localhost','ha_fixture@localhost') "
                           "THEN SIGNAL SQLSTATE '45000' "
                           "SET MESSAGE_TEXT='KAP2_PERSON_GUARD'; END IF; END")
            cursor.execute(f"CREATE TRIGGER `{site_database}`.kap2_person_link_i BEFORE INSERT ON "
                           f"`{site_database}`.`tabPerson` FOR EACH ROW BEGIN "
                           "IF USER() NOT IN ('ha_mutator@localhost','ha_fixture@localhost') "
                           "AND NEW.linked_user IS NOT NULL "
                           "THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='KAP2_PERSON_GUARD'; END IF; END")
    finally:
        root.close()


def new_authority(home, witness_db, binding):
    gateway = Gateway(socket=str(witness_db.socket),
                      lock_path=str(witness_db.root / "person.lock"),
                      reader_password="synthetic-read", writer_password="synthetic-two",
                      recovery_password="synthetic-recover")
    service = PersonAuthority(home_socket=str(home.socket), witness=gateway,
                              binding=binding, reader_password="synthetic-reader",
                              mutator_password="synthetic-mutator")
    return gateway, service


def person_requirement(person: str):
    return (AccessRequirement("PERSON", person, "KNOWLEDGE", "VIEW"),)


def test_trusted_binding_recovery_grant_and_self(services):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    try:
        assert not authority.authorize(person_requirement("owner")).allow
        incarnation = authority.recover(recovery_password="synthetic-home-recover")
        assert len(incarnation) == 64
        assert authority.open
        assert not authority.authorize(person_requirement("owner")).allow
        assert authority.open
        with pytest.raises(PermissionError):
            authority.activate_grant("grant-1", "event-forged", caller_partition="p2")
        assert authority.open
        with pytest.raises(PermissionError):
            authority.activate_grant("grant-1", "event-forged", caller_issuer="actor")
        assert authority.open
        assert not authority.authorize(person_requirement("owner"), caller_partition="p2").allow
        binding.service = "unbound-service"
        assert not authority.authorize(person_requirement("owner")).allow
        binding.service = "home-probe"
        binding.user = "actor-user"
        with pytest.raises(PermissionError):
            authority.activate_grant("grant-1", "actor-cannot-issue", caller_issuer="owner")
        with pytest.raises(PermissionError):
            authority.activate_grant("grant-1", "actor-cannot-issue")
        binding.user = "owner-user"
        authority.activate_grant("grant-1", "event-grant")
        assert authority.activate_grant("grant-1", "event-grant")[0] == 1
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        assert not authority.authorize(person_requirement("owner")).allow
        authority.activate_self("KNOWLEDGE", "VIEW", "event-self")
        assert authority.authorize(person_requirement("owner")).allow
        assert not authority.authorize((AccessRequirement("CIRCLE", "owner", "KNOWLEDGE", "VIEW"),)).allow
    finally:
        authority.close()
        gateway.close()


def test_revocation_and_dependency_mutations_deny_with_new_revision(services):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    try:
        authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "grant-event")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        authority.invalidate_dependency("grant-1", "dependency-off")
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        authority.revoke_grant("grant-1", "revoke-event")
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        assert home.sql("SELECT revision FROM home_auth.head WHERE partition_id='p1'") == "3"
        assert home.sql("SELECT state FROM _aaaaaaaaaaaaaaaa.`tabConsent Grant` WHERE name='grant-1'") == "REVOKED"
    finally:
        authority.close()
        gateway.close()


@pytest.mark.parametrize("issuer_change", ["disable", "unlink"])
def test_expiry_and_issuer_invalidation_deny(services, issuer_change):
    home, witness_db = services
    start = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    with pymysql.connect(unix_socket=str(home.socket), user="ha_fixture",
                         password="synthetic-fixture", autocommit=True) as privileged:
        with privileged.cursor() as cursor:
            cursor.execute("UPDATE _aaaaaaaaaaaaaaaa.`tabConsent Grant` "
                           "SET valid_until='2026-10-09 13:00:00' WHERE name='grant-1'")
    current = [start]
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    authority.clock = lambda: current[0]
    try:
        authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "grant-event")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        current[0] = start + timedelta(hours=2)
        assert not authority.authorize(person_requirement("owner")).allow
        assert authority.open
        binding.user = "owner-user"
        if issuer_change == "disable":
            authority.disable_issuer("owner-user", "disable-event")
        else:
            authority.unlink_issuer("owner", "unlink-event")
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        assert authority.open
    finally:
        authority.close()
        gateway.close()


def test_site_and_old_principals_cannot_bypass_guard(services):
    home, witness_db = services
    with pymysql.connect(unix_socket=str(home.socket), user="site_runtime",
                         password="synthetic-site", database="_aaaaaaaaaaaaaaaa",
                         autocommit=True) as site:
        with site.cursor() as cursor:
            for statement in (
                "UPDATE `tabConsent Grant` SET state='REVOKED' WHERE name='grant-1'",
                "UPDATE `tabUser` SET enabled=0 WHERE name='owner-user'",
                "UPDATE `tabPerson` SET linked_user=NULL WHERE name='owner'",
                "UPDATE `tabPerson` SET name='owner-renamed' WHERE name='owner'",
                "UPDATE `tabConsent Grant` SET name='grant-renamed' WHERE name='grant-1'",
                "DELETE FROM `tabConsent Grant` WHERE name='grant-1'",
            ):
                with pytest.raises(pymysql.MySQLError, match="KAP2_PERSON_GUARD"):
                    cursor.execute(statement)
            cursor.execute("UPDATE `tabPerson` SET notes='ordinary' WHERE name='actor'")
            assert cursor.rowcount == 1
            with pytest.raises(pymysql.MySQLError):
                cursor.execute("UPDATE home_auth.head SET digest='FORGED'")


def test_serving_and_recovery_principals_have_no_direct_authority_dml(services):
    home, _ = services
    with pymysql.connect(unix_socket=str(home.socket), user="ha_mutator",
                         password="synthetic-mutator", autocommit=True) as serving:
        with serving.cursor() as cursor:
            for statement in (
                "UPDATE home_auth.head SET revision=99 WHERE partition_id='p1'",
                "UPDATE home_auth.binding SET partition_id='p2'",
                "INSERT INTO home_auth.events VALUES ('p1','x','fake','x',99,'x','GRANT')",
                "DELETE FROM home_auth.activations WHERE partition_id='p1'",
                "UPDATE home_auth.dependency SET current_state=1 WHERE grant_id='grant-1'",
                "UPDATE _aaaaaaaaaaaaaaaa.`tabConsent Grant` SET state='REVOKED'",
                "UPDATE _aaaaaaaaaaaaaaaa.`tabUser` SET enabled=0",
                "UPDATE _aaaaaaaaaaaaaaaa.`tabPerson` SET linked_user=NULL",
            ):
                with pytest.raises(pymysql.MySQLError, match="command denied"):
                    cursor.execute(statement)
            with pytest.raises(pymysql.MySQLError):
                cursor.execute("CALL home_auth.reset_person_incarnation('p1',REPEAT('a',64))")
            with pytest.raises(pymysql.MySQLError, match="KAP2_LANE_REQUIRED"):
                cursor.execute("CALL home_auth.stage_person_mutation(" + ",".join(["%s"] * 12) + ")",
                               ("p1", "old-incarnation", 0, "fake", "SELF", "", "owner",
                                "owner", "KNOWLEDGE", "VIEW", "owner", "owner-user"))
    with pymysql.connect(unix_socket=str(home.socket), user="ha_recovery",
                         password="synthetic-home-recover", autocommit=True) as recovery:
        with recovery.cursor() as cursor:
            with pytest.raises(pymysql.MySQLError):
                cursor.execute("UPDATE home_auth.head SET digest='FORGED'")
            with pytest.raises(pymysql.MySQLError):
                cursor.execute("CALL home_auth.record_person_event(" + ",".join(["%s"] * 7) + ")",
                               ("p1", "x", 0, "fake", "x" * 64, "DENY_ALL", "SELF"))
    with pymysql.connect(unix_socket=str(home.socket), user="ha_old",
                         password="synthetic-old", autocommit=True) as old:
        with old.cursor() as cursor:
            with pytest.raises(pymysql.MySQLError):
                cursor.execute("UPDATE home_auth.head SET digest='FORGED'")


@pytest.mark.parametrize("order", ["reader-first", "writer-first"])
def test_reader_first_and_writer_first_revocation_races(services, order):
    home, witness_db = services

    class ThreadBinding(Binding):
        def user_name(self) -> str:
            return "actor-user" if threading.current_thread().name == "reader" else "owner-user"

    gateway, authority = new_authority(home, witness_db, ThreadBinding())
    try:
        authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "grant-event")
        errors: list[BaseException] = []
        results: list[bool] = []

        # Reader owns the Home lane and the consistent transaction while the
        # revocation writer waits. This decision may linearize before revoke.
        entered = threading.Event()
        release = threading.Event()
        original_state = authority._state

        def held_state(*args):
            value = original_state(*args)
            if threading.current_thread().name == "reader":
                entered.set()
                assert release.wait(4)
            return value

        if order == "reader-first":
            authority._state = held_state

        def read():
            try:
                results.append(authority.authorize(person_requirement("owner")).allow)
            except BaseException as exc:
                errors.append(exc)

        def revoke(event):
            try:
                authority.revoke_grant("grant-1", event)
            except BaseException as exc:
                errors.append(exc)

        reader = threading.Thread(target=read, name="reader")
        writer = threading.Thread(target=revoke, args=("revoke-event",), name="writer")
        if order == "reader-first":
            reader.start()
            assert entered.wait(4)
            writer.start()
            time.sleep(0.1)
            assert writer.is_alive()
            release.set()
        else:
            original_prepare = gateway.prepare

            def held_prepare(*args):
                value = original_prepare(*args)
                if args[2] == "revoke-event":
                    entered.set()
                    assert release.wait(4)
                return value

            gateway.prepare = held_prepare
            initial = threading.Thread(target=read, name="reader")
            initial.start()
            initial.join(5)
            assert results == [True]
            results.clear()
            writer.start()
            assert entered.wait(4)
            reader.start()
            time.sleep(0.1)
            assert reader.is_alive()
            release.set()
        reader.join(5)
        writer.join(5)
        assert not errors and results == [order == "reader-first"]
    finally:
        authority.close()
        gateway.close()


def test_commit_gap_unknown_ack_and_fresh_reauthorization(services):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    try:
        old_incarnation = authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "initial")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        original_commit = gateway.commit

        def lose_ack(*args):
            original_commit(*args)
            raise TimeoutError("synthetic lost COMMIT acknowledgement")

        gateway.commit = lose_ack
        with pytest.raises(TimeoutError):
            authority.revoke_grant("grant-1", "revocation")
        assert not authority.open
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        assert gateway.event_outcome("p1", old_incarnation, "revocation")[0] == "COMMITTED"
        gateway.commit = original_commit
        # A fresh incarnation defaults to deny even though an old activation
        # remains in Home. An explicit authenticated self activation restores
        # only that permission.
        binding.user = "owner-user"
        new_incarnation = authority.recover(recovery_password="synthetic-home-recover")
        assert new_incarnation != old_incarnation
        assert not authority.authorize(person_requirement("owner")).allow
        authority.activate_self("KNOWLEDGE", "VIEW", "fresh-self")
        assert authority.authorize(person_requirement("owner")).allow
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
    finally:
        authority.close()
        gateway.close()


def test_prepare_before_home_commit_keeps_reader_out(services):
    home, witness_db = services

    class ThreadBinding(Binding):
        def user_name(self) -> str:
            return "actor-user" if threading.current_thread().name == "reader" else "owner-user"

    gateway, authority = new_authority(home, witness_db, ThreadBinding())
    try:
        authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "initial")
        entered = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []
        original_prepare = gateway.prepare

        def hold_after_prepare(*args):
            original_prepare(*args)
            if args[2] == "revocation":
                entered.set()
                assert release.wait(8)

        gateway.prepare = hold_after_prepare

        def revoke():
            try:
                authority.revoke_grant("grant-1", "revocation")
            except BaseException as exc:
                errors.append(exc)

        writer = threading.Thread(target=revoke, name="writer")
        writer.start()
        assert entered.wait(4)
        assert gateway.event_outcome("p1", gateway._incarnation, "revocation")[0] == "PENDING"
        reader_result: list[bool] = []
        reader = threading.Thread(
            target=lambda: reader_result.append(authority.authorize(person_requirement("owner")).allow),
            name="reader")
        reader.start()
        reader.join(7)
        assert not reader.is_alive() and reader_result == [False]
        # The staged Home transaction has not committed while PENDING is visible.
        assert home.sql("SELECT revision FROM home_auth.head WHERE partition_id='p1'") == "1"
        release.set()
        writer.join(4)
        assert not errors
    finally:
        authority.close()
        gateway.close()


def test_pending_and_combined_restore_deny_first_read(services):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    try:
        incarnation = authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "initial")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        original_commit = gateway.commit

        def no_commit(*args):
            raise TimeoutError("synthetic missing COMMIT")

        gateway.commit = no_commit
        with pytest.raises(TimeoutError):
            authority.revoke_grant("grant-1", "revocation")
        gateway.commit = original_commit
        binding.user = "actor-user"
        # Even if a process incorrectly flips its volatile bit, PENDING denies.
        authority.open = True
        assert not authority.authorize(person_requirement("owner")).allow
        assert gateway.event_outcome("p1", incarnation, "revocation")[0] == "PENDING"
        # Simulate a Home backup from before revocation and retained witness
        # state: the old Home digest/revision is now behind the witness.
        home.sql("UPDATE home_auth.head SET revision=1,digest=(SELECT digest FROM home_auth.events "
                 "WHERE event_id='initial') WHERE partition_id='p1'")
        authority.open = True
        assert not authority.authorize(person_requirement("owner")).allow
        authority.close()
        gateway.close()
        new_gateway, restarted = new_authority(home, witness_db, binding)
        try:
            assert not restarted.authorize(person_requirement("owner")).allow
            binding.user = "owner-user"
            restarted.recover(recovery_password="synthetic-home-recover")
            assert not restarted.authorize(person_requirement("owner")).allow
        finally:
            restarted.close()
            new_gateway.close()
    finally:
        if authority.open:
            authority.close()
        if not gateway.closed:
            gateway.close()


def test_canonical_evaluated_state_digest_and_fresh_grant(services):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    try:
        authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "first-grant")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        # A privileged out-of-lane source edit cannot retain a valid witness
        # comparison: the digest covers the same source fields as evaluation.
        with pymysql.connect(unix_socket=str(home.socket), user="ha_fixture",
                             password="synthetic-fixture", autocommit=True) as privileged:
            with privileged.cursor() as cursor:
                cursor.execute("UPDATE _aaaaaaaaaaaaaaaa.`tabConsent Grant` "
                               "SET actions='CREATE' WHERE name='grant-1'")
        assert not authority.authorize(person_requirement("owner")).allow
        with pymysql.connect(unix_socket=str(home.socket), user="ha_fixture",
                             password="synthetic-fixture", autocommit=True) as privileged:
            with privileged.cursor() as cursor:
                cursor.execute("UPDATE _aaaaaaaaaaaaaaaa.`tabConsent Grant` "
                               "SET actions='VIEW' WHERE name='grant-1'")
        assert authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        authority.recover(recovery_password="synthetic-home-recover")
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        authority.activate_grant("grant-1", "explicit-fresh-grant")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
    finally:
        authority.close()
        gateway.close()


def test_combined_home_witness_row_restore_starts_closed(services):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    authority.recover(recovery_password="synthetic-home-recover")
    authority.activate_grant("grant-1", "initial")
    old_home = authority._head(authority.mutator, "p1")
    old_witness = gateway._read_current("p1")
    binding.user = "actor-user"
    assert authority.authorize(person_requirement("owner")).allow
    binding.user = "owner-user"
    authority.revoke_grant("grant-1", "revocation")
    authority.close()
    gateway.close()
    # A privileged synthetic backup restore replays *both* older heads and
    # grant source rows. It runs only after the active gateway is stopped.
    with pymysql.connect(unix_socket=str(home.socket), user="ha_fixture",
                         password="synthetic-fixture", autocommit=True) as restored:
        with restored.cursor() as cursor:
            cursor.execute("UPDATE home_auth.head SET incarnation=%s,revision=%s,digest=%s "
                           "WHERE partition_id='p1'", old_home)
            cursor.execute("UPDATE _aaaaaaaaaaaaaaaa.`tabConsent Grant` SET state='ACTIVE' "
                           "WHERE name='grant-1'")
    with pymysql.connect(unix_socket=str(witness_db.socket), user="root",
                         database="witness", autocommit=True) as restored:
        with restored.cursor() as cursor:
            cursor.execute("UPDATE witness.head SET incarnation=%s,revision=%s,writer_epoch=%s,"
                           "publisher_epoch=%s,state=%s,event_id=%s,digest=%s "
                           "WHERE partition_id='p1'", old_witness)
    new_gateway, restarted = new_authority(home, witness_db, binding)
    try:
        binding.user = "actor-user"
        assert not restarted.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        restarted.recover(recovery_password="synthetic-home-recover")
        binding.user = "actor-user"
        assert not restarted.authorize(person_requirement("owner")).allow
    finally:
        restarted.close()
        new_gateway.close()


def test_physical_restore_of_both_older_permissive_datadirs_starts_closed(services):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    try:
        old_incarnation = authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "old-grant")
        authority.activate_self("KNOWLEDGE", "VIEW", "old-self")
        old_home = authority._head(authority.mutator, "p1")
        old_witness = gateway._read_current("p1")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
    finally:
        authority.close()
        gateway.close()

    # Both copies are cold, consistent physical datadirs. Every source and
    # destination is checked to stay inside its own disposable test root.
    home.stop()
    witness_db.stop()
    for server in (home, witness_db):
        root = server.root.resolve()
        source = server.data.resolve()
        backup = (root / "permissive-backup").resolve()
        assert source.is_relative_to(root) and backup.is_relative_to(root)
        assert source.is_dir() and not backup.exists()
        shutil.copytree(source, backup)
    home.start()
    witness_db.start()

    gateway, authority = new_authority(home, witness_db, binding)
    try:
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        later_incarnation = authority.recover(recovery_password="synthetic-home-recover")
        assert later_incarnation != old_incarnation
        authority.activate_grant("grant-1", "later-grant")
        authority.activate_self("KNOWLEDGE", "VIEW", "later-self")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        authority.revoke_grant("grant-1", "later-revocation")
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        assert witness_db.sql("SELECT revision,state FROM witness.head WHERE partition_id='p1'") == "3\tCOMMITTED"
    finally:
        authority.close()
        gateway.close()

    home.stop()
    witness_db.stop()
    for server in (home, witness_db):
        root = server.root.resolve()
        current = server.data.resolve()
        old = (root / "permissive-backup").resolve()
        revoked = (root / "revoked-data").resolve()
        assert all(path.is_relative_to(root) for path in (current, old, revoked))
        assert current.is_dir() and old.is_dir() and not revoked.exists()
        current.rename(revoked)
        shutil.copytree(old, current)
    home.start()
    witness_db.start()

    gateway, authority = new_authority(home, witness_db, binding)
    try:
        assert authority._head(authority.reader, "p1") == old_home
        assert gateway._read_current("p1") == old_witness
        assert home.sql("SELECT state FROM _aaaaaaaaaaaaaaaa.`tabConsent Grant` "
                        "WHERE name='grant-1'") == "ACTIVE"
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        fresh = authority.recover(recovery_password="synthetic-home-recover")
        assert fresh not in (old_incarnation, later_incarnation)
        assert not authority.authorize(person_requirement("owner")).allow
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        authority.activate_self("KNOWLEDGE", "VIEW", "fresh-self")
        assert authority.authorize(person_requirement("owner")).allow
        binding.user = "actor-user"
        assert not authority.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        authority.activate_grant("grant-1", "fresh-grant")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        print("PHYSICAL_RESTORE_EVIDENCE: matching_older_heads=true; "
              "first_read_denied=true; old_activations_quarantined=true; "
              "selected_reauthorization=true; source=synthetic")
    finally:
        authority.close()
        gateway.close()


@pytest.mark.parametrize("stopped", ["home", "witness"])
def test_database_restart_denies_first_read(services, stopped):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    authority.recover(recovery_password="synthetic-home-recover")
    authority.activate_grant("grant-1", "initial")
    binding.user = "actor-user"
    assert authority.authorize(person_requirement("owner")).allow
    server = home if stopped == "home" else witness_db
    server.stop()
    try:
        assert not authority.authorize(person_requirement("owner")).allow
    finally:
        authority.close()
        gateway.close()
        server.start()
    new_gateway, restarted = new_authority(home, witness_db, binding)
    try:
        assert not restarted.authorize(person_requirement("owner")).allow
        binding.user = "owner-user"
        restarted.recover(recovery_password="synthetic-home-recover")
        binding.user = "actor-user"
        assert not restarted.authorize(person_requirement("owner")).allow
    finally:
        restarted.close()
        new_gateway.close()


@pytest.mark.parametrize("failure", ["connection", "lost_lock"])
def test_computed_allow_is_discarded_after_home_lane_failure(services, failure):
    home, witness_db = services
    binding = Binding()
    gateway, authority = new_authority(home, witness_db, binding)
    try:
        authority.recover(recovery_password="synthetic-home-recover")
        authority.activate_grant("grant-1", "initial")
        binding.user = "actor-user"
        assert authority.authorize(person_requirement("owner")).allow
        original = gateway.authorize

        def lose_home_after_witness(*args):
            assert original(*args) is True
            if failure == "connection":
                with authority.reader.cursor() as cursor:
                    cursor.execute("SELECT CONNECTION_ID()")
                    connection_id = cursor.fetchone()[0]
                home.sql(f"KILL CONNECTION {connection_id}")
            else:
                with authority.reader.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)",
                                   (authority._lane_name("p1"),))
                    assert cursor.fetchone() == (1,)
            return True

        gateway.authorize = lose_home_after_witness
        assert not authority.authorize(person_requirement("owner")).allow
        assert authority.open is False
    finally:
        authority.close()
        gateway.close()
