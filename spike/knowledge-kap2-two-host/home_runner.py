"""Finite Home-side synthetic PERSON acceptance against a remote mTLS witness.

This runs only on a disposable private MariaDB and does not register a Home
endpoint, migrate a site, or install any persistent service.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Callable

import pymysql

HERE = Path(__file__).resolve().parent
GATEWAY_DIR = HERE.parent / "knowledge-kap2-transactional-witness"
PERSON_DIR = HERE.parent / "knowledge-kap2-person-vertical"
sys.path[:0] = [str(GATEWAY_DIR), str(PERSON_DIR)]
from test_gateway import PrivateDB  # noqa: E402
from test_integrated import Binding, install_home, person_requirement  # noqa: E402
from episteck_home.knowledge_authority.integrated import PersonAuthority  # noqa: E402
from episteck_home.policy.typed_access import AccessRequirement  # noqa: E402

from transport import RemoteWitness, RequestLedger, WitnessClient, WitnessTransportError
from preflight import verify as verify_preflight

MARKER = "KAP2_PR71_DISPOSABLE_HOME"


def expect_sql_denial(cursor: pymysql.cursors.Cursor, sql: str,
                      expected_codes: frozenset[int]) -> None:
    try:
        cursor.execute(sql)
    except pymysql.MySQLError as exc:
        if not exc.args or exc.args[0] not in expected_codes:
            raise AssertionError(f"unexpected SQL failure {exc.args[0] if exc.args else '?'}") from exc
    else:
        raise AssertionError("protected SQL statement succeeded")


class Evidence:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a", encoding="utf-8")

    def write(self, **value: object) -> None:
        self.handle.write(json.dumps(value, sort_keys=True) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def close(self) -> None:
        self.handle.close()


@dataclass
class HomeCase:
    root: Path
    witness: RemoteWitness
    db: PrivateDB | None = None
    authority: PersonAuthority | None = None
    binding: Binding | None = None
    passwords: dict[str, str] | None = None

    def __enter__(self) -> HomeCase:
        self.root.mkdir(mode=0o700)
        db_root = self.root / "db"
        db_root.mkdir(mode=0o700)
        self.db = PrivateDB(db_root)
        install_home(self.db)
        self.passwords = {name: secrets.token_hex(24) for name in (
            "ha_reader", "ha_mutator", "ha_recovery", "ha_fixture",
            "ha_old", "site_runtime")}
        for name, password in self.passwords.items():
            self.db.sql(f"ALTER USER '{name}'@'localhost' IDENTIFIED BY '{password}'")
        self.binding = Binding()
        self._new_authority()
        return self

    def _new_authority(self) -> None:
        assert self.db is not None and self.binding is not None and self.passwords is not None
        self.authority = PersonAuthority(home_socket=str(self.db.socket),
                                         witness=self.witness, binding=self.binding,
                                         reader_password=self.passwords["ha_reader"],
                                         mutator_password=self.passwords["ha_mutator"])

    def recover(self) -> str:
        assert self.authority is not None and self.passwords is not None
        return self.authority.recover(recovery_password=self.passwords["ha_recovery"])

    def grant_allow(self) -> None:
        assert self.authority is not None and self.binding is not None
        self.binding.user = "owner-user"
        self.authority.activate_grant("grant-1", f"grant-{secrets.token_hex(6)}")
        self.binding.user = "actor-user"
        assert self.authority.authorize(person_requirement("owner")).allow

    def connect(self, user: str, database: str = "home_auth") -> pymysql.Connection:
        assert self.db is not None and self.passwords is not None
        return pymysql.connect(unix_socket=str(self.db.socket), user=user,
                               password=self.passwords[user], database=database,
                               autocommit=True)

    def snapshot(self) -> None:
        assert self.db is not None
        if self.authority is not None:
            self.authority.close()
            self.authority = None
        self.db.stop()
        target = self.root / "snapshot"
        if target.exists():
            raise RuntimeError("Home snapshot already exists")
        target.mkdir(mode=0o700)
        (target / MARKER).write_text("synthetic physical snapshot\n")
        shutil.copytree(self.db.data, target / "data")
        self.db.start()
        self._new_authority()

    def restore(self) -> None:
        assert self.db is not None
        snapshot = self.root / "snapshot"
        if not (snapshot / MARKER).is_file():
            raise RuntimeError("marked Home snapshot absent")
        if self.authority is not None:
            self.authority.close()
            self.authority = None
        self.db.stop()
        data = self.db.data.resolve()
        if data.parent != (self.root / "db").resolve() or not data.is_dir():
            raise RuntimeError("unsafe disposable Home datadir")
        shutil.rmtree(data)
        shutil.copytree(snapshot / "data", data)
        self.db.start()
        self._new_authority()

    def __exit__(self, *_: object) -> None:
        if self.authority is not None:
            try:
                self.authority.close()
            except Exception:
                pass
        if self.db is not None:
            self.db.stop()


class Matrix:
    def __init__(self, args: argparse.Namespace) -> None:
        if args.evidence.resolve().is_relative_to(args.root.resolve()):
            raise ValueError("evidence must be outside the disposable Home root")
        if (args.root.exists() or args.root.parent != Path("/tmp")
                or not args.root.name.startswith("kap2-pr71-twohost-")):
            raise ValueError("Home root must be a new marked /tmp/kap2-pr71-twohost-* path")
        self.args = args
        self.ledger = RequestLedger(cap=400)
        self.serving = WitnessClient(
            host=args.witness_host, port=args.port, ca=args.ca,
            cert=args.serving_cert, key=args.serving_key, role="serving",
            ledger=self.ledger)
        self.recovery = WitnessClient(
            host=args.witness_host, port=args.port, ca=args.ca,
            cert=args.recovery_cert, key=args.recovery_key, role="recovery",
            ledger=self.ledger)
        self.witness = RemoteWitness(self.serving, self.recovery)
        args.root.mkdir(mode=0o700)
        (args.root / MARKER).write_text("synthetic PERSON authority only\n")
        self.evidence = Evidence(args.evidence)
        self.steps: dict[str, str] = {}

    def case(self, name: str) -> HomeCase:
        return HomeCase(self.args.root / name, self.witness)

    def step(self, name: str, action: Callable[[], None]) -> None:
        started = time.perf_counter_ns()
        try:
            action()
        except Exception as exc:
            self.steps[name] = "FAIL"
            self.evidence.write(step=name, result="FAIL", error=type(exc).__name__,
                                duration_ms=round((time.perf_counter_ns()-started)/1e6, 3),
                                witness_requests=self.ledger.count())
            raise
        self.steps[name] = "PASS"
        self.evidence.write(step=name, result="PASS",
                            duration_ms=round((time.perf_counter_ns()-started)/1e6, 3),
                            witness_requests=self.ledger.count())

    def transport_and_principals(self) -> None:
        def verify() -> None:
            for client, operation, values in (
                (self.serving, "recover", ("p1",)),
                (self.recovery, "authorize", ("p1", "old-incarnation", 0, "OLD_ALLOW")),
            ):
                try:
                    client.call(operation, *values)
                except WitnessTransportError:
                    pass
                else:
                    raise AssertionError("wrong mTLS role was admitted")
            context = ssl.create_default_context(cafile=str(self.args.ca))
            without_cert = http.client.HTTPSConnection(self.args.witness_host,
                                                        self.args.port, context=context,
                                                        timeout=2)
            attempt = self.ledger.reserve("anonymous", "tls_handshake")
            started = time.perf_counter_ns()
            try:
                without_cert.request("POST", "/rpc", b"{}")
                without_cert.getresponse().read()
            except (ssl.SSLError, OSError, http.client.HTTPException):
                self.ledger.finish(attempt, (time.perf_counter_ns()-started)/1e6,
                                   "rejected")
            else:
                self.ledger.finish(attempt, (time.perf_counter_ns()-started)/1e6,
                                   "unexpected_allow")
                raise AssertionError("client without certificate was admitted")
            finally:
                without_cert.close()
            result = self.recovery.call("probe_privileges")
            assert type(result) is dict and result and all(value is True for value in result.values())
            assert self.recovery.call("status")["closed"] is True
        self.step("transport_credential_isolation_and_closed_start", verify)

    def basic_and_bypass(self) -> None:
        def verify() -> None:
            with self.case("basic") as case:
                service, binding, db = case.authority, case.binding, case.db
                assert service is not None and binding is not None and db is not None
                assert not service.authorize(person_requirement("owner")).allow
                case.recover()
                assert not service.authorize(person_requirement("owner")).allow
                privileges = self.recovery.call("probe_privileges")
                assert privileges.get("old_writer_epoch_denied") is True
                try:
                    service.activate_grant("grant-1", "forged-partition",
                                           caller_partition="p2")
                except PermissionError:
                    pass
                else:
                    raise AssertionError("caller partition activated authority")
                try:
                    service.activate_grant("grant-1", "forged-issuer",
                                           caller_issuer="actor")
                except PermissionError:
                    pass
                else:
                    raise AssertionError("caller issuer activated authority")
                case.grant_allow()
                assert not service.authorize(person_requirement("owner"),
                                             caller_partition="p2").allow
                with case.connect("ha_mutator") as serving:
                    with serving.cursor() as cursor:
                        for sql in (
                            "UPDATE home_auth.head SET digest='FORGED'",
                            "UPDATE home_auth.binding SET partition_id='p2'",
                            "INSERT INTO home_auth.events VALUES ('p1','x','fake','x',99,'x','GRANT')",
                            "DELETE FROM home_auth.activations",
                            "UPDATE home_auth.dependency SET current_state=1",
                            "UPDATE _aaaaaaaaaaaaaaaa.`tabConsent Grant` SET state='REVOKED'",
                            "UPDATE _aaaaaaaaaaaaaaaa.`tabPerson` SET linked_user=NULL",
                            "UPDATE _aaaaaaaaaaaaaaaa.`tabUser` SET enabled=0",
                            "DELETE FROM _aaaaaaaaaaaaaaaa.`tabPerson` WHERE name='owner'",
                        ):
                            expect_sql_denial(cursor, sql, frozenset({1142, 1143}))
                with case.connect("site_runtime", "_aaaaaaaaaaaaaaaa") as site:
                    with site.cursor() as cursor:
                        for sql in (
                            "UPDATE _aaaaaaaaaaaaaaaa.`tabConsent Grant` SET state='REVOKED'",
                            "UPDATE _aaaaaaaaaaaaaaaa.`tabPerson` SET linked_user=NULL",
                            "UPDATE _aaaaaaaaaaaaaaaa.`tabUser` SET enabled=0",
                        ):
                            expect_sql_denial(cursor, sql, frozenset({1644}))
                        cursor.execute("UPDATE _aaaaaaaaaaaaaaaa.`tabPerson` "
                                       "SET notes='ordinary' WHERE name='actor'")
                        assert cursor.rowcount == 1
                        expect_sql_denial(cursor,
                                          "UPDATE home_auth.head SET digest='FORGED'",
                                          frozenset({1044, 1142, 1143}))
                for principal in ("ha_recovery", "ha_old"):
                    try:
                        limited = case.connect(principal)
                    except pymysql.MySQLError as exc:
                        if principal != "ha_old" or not exc.args or exc.args[0] != 1044:
                            raise
                    else:
                        with limited:
                            with limited.cursor() as cursor:
                                expect_sql_denial(cursor,
                                                  "UPDATE home_auth.head SET digest='FORGED'",
                                                  frozenset({1044, 1142, 1143}))
                binding.user = "actor-user"
                assert service.authorize(person_requirement("owner")).allow
                binding.user = "owner-user"
                service.activate_self("KNOWLEDGE", "VIEW", "self-basic")
                assert service.authorize(person_requirement("owner")).allow
                assert not service.authorize((
                    AccessRequirement("CIRCLE", "owner", "KNOWLEDGE", "VIEW"),)).allow
        self.step("grant_self_bypass_and_ordinary_write", verify)

    def race(self, order: str) -> None:
        def verify() -> None:
            with self.case(f"race-{order}") as case:
                service = case.authority
                assert service is not None

                class ThreadBinding(Binding):
                    def user_name(self) -> str:
                        return ("actor-user" if threading.current_thread().name == "reader"
                                else "owner-user")

                service.binding = ThreadBinding()
                incarnation = case.recover()
                service.activate_grant("grant-1", f"grant-{order}")
                entered, release = threading.Event(), threading.Event()
                errors: list[BaseException] = []
                decisions: list[bool] = []

                def read() -> None:
                    try:
                        decisions.append(service.authorize(person_requirement("owner")).allow)
                    except BaseException as exc:
                        errors.append(exc)

                def revoke() -> None:
                    try:
                        service.revoke_grant("grant-1", f"revoke-{order}")
                    except BaseException as exc:
                        errors.append(exc)

                reader = threading.Thread(target=read, name="reader")
                writer = threading.Thread(target=revoke, name="writer")
                if order == "reader-first":
                    original_state = service._state

                    def held_state(*args):
                        value = original_state(*args)
                        if threading.current_thread().name == "reader":
                            entered.set()
                            if not release.wait(8):
                                raise TimeoutError("reader hold expired")
                        return value

                    service._state = held_state
                    reader.start()
                    assert entered.wait(5)
                    writer.start()
                    time.sleep(0.15)
                    assert writer.is_alive(), "writer did not wait for protected reader"
                    release.set()
                else:
                    initial = threading.Thread(target=read, name="reader")
                    initial.start()
                    initial.join(8)
                    assert decisions == [True], "fresh permissive baseline was not allowed"
                    decisions.clear()
                    original_prepare = self.witness.prepare

                    def held_prepare(*args):
                        original_prepare(*args)
                        if args[2] == f"revoke-{order}":
                            entered.set()
                            if not release.wait(8):
                                raise TimeoutError("writer hold expired")

                    self.witness.prepare = held_prepare
                    try:
                        writer.start()
                        assert entered.wait(5), "writer did not publish PENDING"
                        outcome = self.witness.event_outcome(
                            "p1", incarnation, f"revoke-{order}")
                        assert outcome is not None and outcome[0] == "PENDING"
                        reader.start()
                        time.sleep(0.15)
                        assert reader.is_alive(), "reader did not wait behind revocation lane"
                        release.set()
                    finally:
                        self.witness.prepare = original_prepare
                reader.join(10)
                writer.join(10)
                assert not reader.is_alive() and not writer.is_alive()
                assert not errors, [type(error).__name__ for error in errors]
                assert decisions == [order == "reader-first"]
                decisions.clear()
                after = threading.Thread(target=read, name="reader")
                after.start()
                after.join(8)
                assert decisions == [False], "revocation did not deny the grantee"
        self.step(f"{order}_revocation_order", verify)

    def authority_source_changes(self) -> None:
        def verify() -> None:
            for kind in ("dependency", "disable", "unlink", "expiry"):
                with self.case(f"source-{kind}") as case:
                    service, binding, db = case.authority, case.binding, case.db
                    assert service is not None and binding is not None and db is not None
                    if kind == "expiry":
                        with case.connect("ha_fixture", "_aaaaaaaaaaaaaaaa") as fixture:
                            with fixture.cursor() as cursor:
                                cursor.execute("UPDATE `tabConsent Grant` "
                                               "SET valid_until='2026-10-10 13:00:00' "
                                               "WHERE name='grant-1'")
                        current = [datetime(2026, 10, 10, 12, tzinfo=timezone.utc)]
                        service.clock = lambda: current[0]
                    case.recover()
                    case.grant_allow()
                    if kind == "expiry":
                        current[0] = datetime(2026, 10, 10, 14, tzinfo=timezone.utc)
                    else:
                        binding.user = "owner-user"
                        if kind == "dependency":
                            service.invalidate_dependency("grant-1", "dependency-off")
                        elif kind == "disable":
                            service.disable_issuer("owner-user", "issuer-disabled")
                        else:
                            service.unlink_issuer("owner", "issuer-unlinked")
                    binding.user = "actor-user"
                    assert not service.authorize(person_requirement("owner")).allow
        self.step("dependency_issuer_and_expiry_invalidation", verify)

    def connection_loss(self) -> None:
        def verify() -> None:
            with self.case("connection-loss") as case:
                service, binding = case.authority, case.binding
                assert service is not None and binding is not None
                incarnation = case.recover()
                case.grant_allow()
                assert self.recovery.call("kill_writer") == {"writer_killed": True}
                # The reader connection remains able to read the row, while
                # gateway authorization must close on writer continuity loss.
                assert self.witness._read_current("p1")[0] == incarnation
                assert not service.authorize(person_requirement("owner")).allow
                assert self.recovery.call("status")["closed"] is True
                binding.user = "owner-user"
                new_incarnation = case.recover()
                assert new_incarnation != incarnation
                binding.user = "actor-user"
                assert not service.authorize(person_requirement("owner")).allow
        self.step("writer_connection_loss_with_live_reader", verify)

    def uncertain(self, phase: str) -> None:
        def verify() -> None:
            with self.case(f"uncertain-{phase}") as case:
                service, binding = case.authority, case.binding
                assert service is not None and binding is not None
                incarnation = case.recover()
                case.grant_allow()
                binding.user = "owner-user"
                original = getattr(self.witness, phase)

                def lost_ack(*args):
                    original(*args)
                    if args[2] == f"revoke-{phase}":
                        raise TimeoutError(f"synthetic {phase} acknowledgement lost")

                setattr(self.witness, phase, lost_ack)
                try:
                    try:
                        service.revoke_grant("grant-1", f"revoke-{phase}")
                    except TimeoutError:
                        pass
                    else:
                        raise AssertionError("unknown publication outcome was accepted")
                finally:
                    setattr(self.witness, phase, original)
                assert not service.open
                outcome = self.witness.event_outcome("p1", incarnation, f"revoke-{phase}")
                expected = "PENDING" if phase == "prepare" else "COMMITTED"
                assert outcome is not None and outcome[0] == expected
                binding.user = "actor-user"
                assert not service.authorize(person_requirement("owner")).allow
                # A fresh process that only sees restorable rows must still
                # make the live witness comparison; force local OPEN in this
                # disposable probe to avoid a trivial local-flag denial.
                independent = PersonAuthority(
                    home_socket=str(case.db.socket), witness=self.witness, binding=binding,
                    reader_password=case.passwords["ha_reader"],
                    mutator_password=case.passwords["ha_mutator"])
                try:
                    independent.open = True
                    assert not independent.authorize(person_requirement("owner")).allow
                finally:
                    independent.close()
                binding.user = "owner-user"
                new_incarnation = case.recover()
                assert new_incarnation != incarnation
                service.activate_self("KNOWLEDGE", "VIEW", f"fresh-self-{phase}")
                assert service.authorize(person_requirement("owner")).allow
                binding.user = "actor-user"
                assert not service.authorize(person_requirement("owner")).allow
        self.step(f"unknown_{phase}_acknowledgement", verify)

    def gateway_restart(self) -> None:
        def verify() -> None:
            with self.case("gateway-restart") as case:
                service, binding = case.authority, case.binding
                assert service is not None and binding is not None
                old = case.recover()
                case.grant_allow()
                assert self.recovery.call("restart_gateway") == {"closed": True}
                assert not service.authorize(person_requirement("owner")).allow
                binding.user = "owner-user"
                fresh = case.recover()
                assert fresh != old
                binding.user = "actor-user"
                assert not service.authorize(person_requirement("owner")).allow
        self.step("gateway_restart_first_read_denial", verify)

    def physical_restore(self) -> None:
        def verify() -> None:
            with self.case("physical-restore") as case:
                service, binding, db = case.authority, case.binding, case.db
                assert service is not None and binding is not None and db is not None
                old = case.recover()
                case.grant_allow()
                binding.user = "owner-user"
                service.activate_self("KNOWLEDGE", "VIEW", "pre-snapshot-self")
                case.snapshot()
                assert self.recovery.call("snapshot") == {"closed": True}
                service = case.authority
                assert service is not None
                newer = case.recover()
                assert newer != old
                service.activate_grant("grant-1", "newer-grant")
                service.revoke_grant("grant-1", "newer-revocation")
                binding.user = "actor-user"
                assert not service.authorize(person_requirement("owner")).allow
                case.restore()
                service = case.authority
                assert service is not None
                # Restore Home first while the newer witness remains live.
                service.open = True
                assert not service.authorize(person_requirement("owner")).allow
                assert self.recovery.call("restore") == {"closed": True}
                restored_home = db.sql(
                    "SELECT incarnation,revision,digest FROM home_auth.head WHERE partition_id='p1'")
                restored_witness = self.witness._read_current("p1")
                assert restored_witness is not None
                assert restored_home.split("\t") == [str(restored_witness[0]),
                                                     str(restored_witness[1]),
                                                     str(restored_witness[6])]
                assert restored_witness[0] == old
                assert db.sql("SELECT state FROM _aaaaaaaaaaaaaaaa.`tabConsent Grant` "
                              "WHERE name='grant-1'") == "ACTIVE"
                # Force a protected read despite old matching permissive rows.
                # Only volatile CLOSED admission can make this deny.
                service.open = True
                assert not service.authorize(person_requirement("owner")).allow
                binding.user = "owner-user"
                fresh = case.recover()
                assert fresh not in {old, newer}
                binding.user = "actor-user"
                assert not service.authorize(person_requirement("owner")).allow
                binding.user = "owner-user"
                service.activate_self("KNOWLEDGE", "VIEW", "fresh-selected-self")
                assert service.authorize(person_requirement("owner")).allow
                binding.user = "actor-user"
                assert not service.authorize(person_requirement("owner")).allow
                binding.user = "owner-user"
                service.activate_grant("grant-1", "fresh-selected-grant")
                binding.user = "actor-user"
                assert service.authorize(person_requirement("owner")).allow
        self.step("dual_physical_restore_first_read_and_selected_reauthorization", verify)

    def latency_screen(self) -> None:
        def percentile(values: list[float], fraction: float) -> float:
            ordered = sorted(values)
            return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]

        def verify() -> None:
            with self.case("latency") as case:
                service = case.authority
                assert service is not None and case.binding is not None
                case.recover()
                case.grant_allow()
                for mode in ("warm", "cold"):
                    values: list[float] = []
                    pair_values: list[float] = []
                    for index in range(30):
                        if mode == "cold":
                            self.serving.close()  # new TCP/TLS per pair, same Home DB session
                        pair_started = time.perf_counter_ns()
                        before_pair = self.ledger.count()
                        for call_index in range(2):
                            before = self.ledger.count()
                            start = time.perf_counter_ns()
                            decision = service.authorize(person_requirement("owner"))
                            elapsed = (time.perf_counter_ns()-start) / 1e6
                            remote_calls = self.ledger.count() - before
                            assert decision.allow and remote_calls == 1
                            values.append(elapsed)
                            self.evidence.write(step="latency_sample", mode=mode,
                                                pair=index, call=call_index,
                                                duration_ms=round(elapsed, 3),
                                                witness_requests=remote_calls)
                        pair_ms = (time.perf_counter_ns()-pair_started) / 1e6
                        assert self.ledger.count() - before_pair == 2
                        pair_values.append(pair_ms)
                        self.evidence.write(step="latency_pair", mode=mode, pair=index,
                                            duration_ms=round(pair_ms, 3), witness_requests=2)
                    self.evidence.write(step="latency_distribution", mode=mode,
                                        calls=len(values), pairs=len(pair_values),
                                        call_p50_ms=round(median(values), 3),
                                        call_p95_ms=round(percentile(values, 0.95), 3),
                                        call_p99_ms=round(percentile(values, 0.99), 3),
                                        pair_p50_ms=round(median(pair_values), 3),
                                        pair_p95_ms=round(percentile(pair_values, 0.95), 3),
                                        pair_p99_ms=round(percentile(pair_values, 0.99), 3),
                                        pair_max_ms=round(max(pair_values), 3),
                                        status="PROPOSED_BUDGET_NOT_RATIFIED")
        self.step("kap2_policy_witness_latency_and_request_count", verify)

    def frappe_compatibility(self) -> None:
        def verify() -> None:
            if self.args.bench is None or not (self.args.bench / "apps" / "frappe").is_dir():
                raise RuntimeError("marked disposable Frappe 15.99.0 bench required")
            result_path = self.args.evidence.with_name("kap2-pr71-frappe-result.json")
            if result_path.exists():
                raise RuntimeError("refusing to overwrite prior Frappe result")
            runner = PERSON_DIR / "run_frappe.py"
            result = subprocess.run(
                [sys.executable, str(runner), "--bench", str(self.args.bench),
                 "--evidence", str(result_path)],
                capture_output=True, text=True, timeout=600)
            if result.returncode:
                raise RuntimeError(f"disposable Frappe runner failed ({result.returncode})")
            value = json.loads(result_path.read_text())
            checks = value.get("person_vertical", {})
            cleanup = value.get("cleanup", {})
            if (len(checks) != 9 or not all(v is True for v in checks.values())
                    or len(cleanup) != 4 or not all(v is True for v in cleanup.values())):
                raise AssertionError("Frappe compatibility or cleanup assertion failed")
            self.evidence.write(step="frappe_compatibility_detail", assertions=checks,
                                cleanup=cleanup, site="marked_disposable")
        self.step("ordinary_home_frappe_compatibility", verify)

    def close(self) -> None:
        self.serving.close()
        self.recovery.close()
        self.evidence.write(step="matrix_summary", steps=self.steps,
                            request_counts=self.ledger.summary())
        marker = self.args.root / MARKER
        if not marker.is_file() or self.args.root.parent != Path("/tmp"):
            raise RuntimeError("refusing unmarked Home cleanup")
        shutil.rmtree(self.args.root)
        self.evidence.write(step="home_cleanup", root_absent=not self.args.root.exists(),
                            request_attempts=self.ledger.count())
        self.evidence.close()


def main() -> None:
    if not __debug__:
        raise SystemExit("optimized Python disables acceptance assertions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--witness-host", required=True)
    parser.add_argument("--port", type=int, default=19442)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--serving-cert", type=Path, required=True)
    parser.add_argument("--serving-key", type=Path, required=True)
    parser.add_argument("--recovery-cert", type=Path, required=True)
    parser.add_argument("--recovery-key", type=Path, required=True)
    parser.add_argument("--bench", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--reset-local", action="store_true",
                        help="development-only restart of a disposable loopback gateway")
    args = parser.parse_args()
    if args.reset_local and not args.local:
        raise SystemExit("--reset-local is forbidden for the two-host run")
    if not args.local and not args.root.name.endswith("-01"):
        raise SystemExit("remote package requires the reviewed -01 disposable root")
    if not args.local and args.evidence.exists():
        raise SystemExit("remote Home evidence must start empty")
    if not args.local:
        if not args.expected_sha:
            raise SystemExit("reviewed exact SHA is required for remote Home runner")
        preflight = verify_preflight(
            side="home", repo=Path(__file__).resolve().parents[2],
            expected_sha=args.expected_sha, root=args.root,
            cert_dir=args.ca.parent, evidence_dir=args.evidence.parent,
            host=args.witness_host, port=args.port, bench=args.bench)
        preflight_evidence = Evidence(args.evidence)
        try:
            preflight_evidence.write(step="preflight", **preflight)
        finally:
            preflight_evidence.close()
        if not preflight["complete"]:
            raise SystemExit("Home preflight rejected")
    matrix = Matrix(args)
    try:
        if args.local:
            matrix.evidence.write(step="preflight",
                                  status="LOCAL_ONLY_REMOTE_PREFLIGHT_UNEXECUTED")
        if args.reset_local:
            assert matrix.recovery.call("restart_gateway") == {"closed": True}
        matrix.transport_and_principals()
        matrix.basic_and_bypass()
        matrix.authority_source_changes()
        matrix.race("reader-first")
        matrix.race("writer-first")
        matrix.connection_loss()
        matrix.uncertain("prepare")
        matrix.uncertain("commit")
        matrix.gateway_restart()
        matrix.physical_restore()
        matrix.latency_screen()
        if not args.local:
            matrix.frappe_compatibility()
        print(json.dumps({"steps": matrix.steps, "request_attempts": matrix.ledger.count()},
                         sort_keys=True))
    finally:
        matrix.close()


if __name__ == "__main__":
    main()
