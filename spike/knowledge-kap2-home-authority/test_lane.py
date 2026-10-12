"""Real disposable MariaDB checks for the disconnected Home authority lane."""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pymysql
import pytest

GATEWAY_DIR = Path(__file__).parents[1] / "knowledge-kap2-transactional-witness"
sys.path.insert(0, str(GATEWAY_DIR))
from test_gateway import PrivateDB, new_gateway  # noqa: E402

from episteck_home.knowledge_authority.lane import (
    ActivationRequest, HomeAuthorityStore, KnowledgeMutationLane,
)


@pytest.fixture
def authority_db(db):
    db.sql("CREATE DATABASE home_auth")
    schema = Path(__file__).with_name("home_schema.sql").read_text()
    db.run("mariadb", "--no-defaults", f"--socket={db.socket}", "-uroot", input_text=schema)
    db.sql("CREATE USER 'home_auth_writer'@'localhost' IDENTIFIED BY 'synthetic-home-write';"
           "CREATE USER 'home_auth_reader'@'localhost' IDENTIFIED BY 'synthetic-home-read';"
           "CREATE USER 'site_runtime'@'localhost' IDENTIFIED BY 'synthetic-site';"
           "GRANT EXECUTE ON PROCEDURE home_auth.apply_event TO 'home_auth_writer'@'localhost';"
           "GRANT EXECUTE ON PROCEDURE home_auth.read_head TO 'home_auth_reader'@'localhost';"
           "GRANT SELECT ON home_auth.activations TO 'home_auth_reader'@'localhost';"
           "GRANT SELECT ON home_auth.events TO 'home_auth_reader'@'localhost'")
    return db


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory(prefix="kap2-home-auth-") as directory:
        server = PrivateDB(Path(directory))
        try:
            yield server
        finally:
            server.stop()


def request(incarnation, event="grant-1"):
    return ActivationRequest(
        partition_id="p1", incarnation=incarnation, event_id=event,
        kind="GRANT", actor_person_id="actor", resource_type="PERSON",
        resource_id="subject", domain="KNOWLEDGE", actions=frozenset({"VIEW"}),
        source_grant_id="source-1", issuer_person_id="subject",
    )


def test_witness_pending_gap_exact_retry_and_guarded_revision(authority_db):
    with new_gateway(authority_db) as witness:
        inc = witness.recover("p1")
        authority_db.sql(f"INSERT INTO home_auth.head VALUES ('p1','{inc}',0,'DENY_ALL')")
        store = HomeAuthorityStore(str(authority_db.socket), "synthetic-home-write",
                                   "synthetic-home-read")
        try:
            lane = KnowledgeMutationLane(witness, store, lambda: "subject", lambda _: True)
            req = request(inc)
            prepared = lane.prepare(req, expected_revision=0)
            assert witness.authorize("p1", inc, 1, prepared.digest) is False
            assert store.apply(prepared) == (1, prepared.digest)
            assert witness.authorize("p1", inc, 1, prepared.digest) is False
            witness.commit("p1", inc, req.event_id, prepared.digest)
            assert witness.authorize("p1", inc, 1, prepared.digest) is True
            assert lane.reauthorize(req, expected_revision=0) == (1, prepared.digest)
            assert store.current("p1") == (inc, 1, prepared.digest)
            assert authority_db.sql("SELECT COUNT(*) FROM home_auth.activations") == "1"
            with pytest.raises((ValueError, pymysql.MySQLError)):
                lane.reauthorize(request(inc, "grant-2"), expected_revision=0)
        finally:
            store.close()


def test_principals_direct_dml_and_old_incarnation_denied(authority_db):
    with new_gateway(authority_db) as witness:
        inc = witness.recover("p1")
        authority_db.sql(f"INSERT INTO home_auth.head VALUES ('p1','{inc}',0,'DENY_ALL')")
        for user, password in (("site_runtime", "synthetic-site"),
                               ("home_auth_writer", "synthetic-home-write"),
                               ("home_auth_reader", "synthetic-home-read")):
            with pymysql.connect(unix_socket=str(authority_db.socket), user=user,
                                 password=password, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    with pytest.raises(pymysql.MySQLError):
                        cursor.execute("UPDATE home_auth.head SET digest='FORGED'")
                    with pytest.raises(pymysql.MySQLError):
                        cursor.execute("INSERT INTO home_auth.activations VALUES "
                                       "('p1','old','e','GRANT','actor','PERSON','subject',"
                                       "'KNOWLEDGE','VIEW','source','subject',1)")
                    if user == "site_runtime":
                        with pytest.raises(pymysql.MySQLError):
                            cursor.execute("CALL home_auth.apply_event(" + ",".join(["%s"] * 15) + ")",
                                           ("p1", inc, "forged", 0, "FORGED", "a" * 64,
                                            "GRANT", "actor", "PERSON", "subject",
                                            "KNOWLEDGE", "VIEW", "source", "subject", 2))
        store = HomeAuthorityStore(str(authority_db.socket), "synthetic-home-write",
                                   "synthetic-home-read")
        try:
            with pytest.raises(pymysql.MySQLError):
                store.apply(lane_prepared(request("old"), 0, "digest"))
        finally:
            store.close()


def test_authenticated_issuer_dependency_and_person_self_activation(authority_db):
    with new_gateway(authority_db) as witness:
        inc = witness.recover("p1")
        authority_db.sql(f"INSERT INTO home_auth.head VALUES ('p1','{inc}',0,'DENY_ALL')")
        store = HomeAuthorityStore(str(authority_db.socket), "synthetic-home-write",
                                   "synthetic-home-read")
        try:
            grant = request(inc)
            wrong_issuer = KnowledgeMutationLane(witness, store, lambda: "other", lambda _: True)
            with pytest.raises(PermissionError):
                wrong_issuer.reauthorize(grant, 0)
            invalid_dependency = KnowledgeMutationLane(witness, store, lambda: "subject", lambda _: False)
            with pytest.raises(PermissionError):
                invalid_dependency.reauthorize(grant, 0)
            assert store.current("p1") == (inc, 0, "DENY_ALL")
            self_request = replace(grant, event_id="self-1", kind="SELF",
                                   actor_person_id="subject", resource_id="subject",
                                   source_grant_id="")
            self_lane = KnowledgeMutationLane(witness, store, lambda: "subject", lambda _: False)
            revision, digest = self_lane.reauthorize(self_request, 0)
            assert revision == 1 and witness.authorize("p1", inc, revision, digest) is True
            assert authority_db.sql("SELECT kind FROM home_auth.activations") == "SELF"
            with pytest.raises(ValueError):
                self_lane.reauthorize(replace(self_request, event_id="circle-self",
                                              resource_type="CIRCLE"), 1)
        finally:
            store.close()


def lane_prepared(req, revision, digest):
    from episteck_home.knowledge_authority.lane import PreparedActivation
    return PreparedActivation(req, revision, digest, "a" * 64)
