"""Observe authority write paths on an explicitly marked disposable Frappe site.

Run only with: bench --site kap2-probe-... execute episteck_home.probes.kap2_frappe.run
The site must contain sites/<site>/KAP2_DISPOSABLE_SITE. No production site qualifies.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path


def _install_candidate_guard(frappe, token: str) -> tuple[str, str]:
    """Disposable MariaDB guard; DDL persists until the entire site is dropped."""
    import pymysql

    database = frappe.conf.db_name
    socket = os.environ.get("KAP2_DB_SOCKET", "")
    password = os.environ.get("KAP2_DB_ROOT_PASSWORD", "")
    if not re.fullmatch(r"_[0-9a-f]{16}", database) or not socket.startswith("/tmp/kap2-mariadb-") or not password:
        raise RuntimeError("guard setup requires the private probe database and root secret")
    schema = f"kap2_auth_{token}"
    mutator = f"kap2_mutator_{token}"
    reader = f"kap2_reader_{token}"
    qdb, qschema = f"`{database}`", f"`{schema}`"
    root = pymysql.connect(unix_socket=socket, user="root", password=password, autocommit=True)
    try:
        with root.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {qschema}")
            cursor.execute(f"CREATE TABLE {qschema}.authority (id INT PRIMARY KEY, state VARCHAR(16), seq INT, outcome VARCHAR(16))")
            cursor.execute(f"INSERT INTO {qschema}.authority VALUES (1,'ACTIVE',0,'COMMIT')")
            cursor.execute(f"INSERT INTO {qschema}.authority VALUES (2,'ACTIVE',0,'COMMIT')")
            cursor.execute(f"CREATE USER '{mutator}'@'localhost' IDENTIFIED BY 'KAP2_LOCAL_SYNTHETIC_ONLY'")
            cursor.execute(f"CREATE USER '{reader}'@'localhost' IDENTIFIED BY 'KAP2_LOCAL_SYNTHETIC_ONLY'")
            cursor.execute(f"GRANT SELECT ON {qschema}.authority TO '{reader}'@'localhost'")

            protected_updates = {
                "User": ("enabled", "user_type"),
                "Person": ("linked_user",),
                "Home Delegated Session": ("user", "status", "expires_at", "revoked_at"),
                "Consent Grant": ("actor_person", "subject_person", "domain", "actions", "state", "valid_from", "valid_until", "granted_by"),
                "Circle": ("circle_type",),
                "Circle Membership": ("circle", "person", "role_in_circle"),
            }
            for index, (doctype, fields) in enumerate(protected_updates.items()):
                table = f"{qdb}.`tab{doctype}`"
                changed = " OR ".join(f"NOT (OLD.`{field}` <=> NEW.`{field}`)" for field in fields)
                gate = f"USER() <> '{mutator}@localhost'"
                cursor.execute(
                    f"CREATE TRIGGER {qdb}.kap2_guard_{index}_u BEFORE UPDATE ON {table} FOR EACH ROW "
                    f"BEGIN IF {gate} AND ({changed}) THEN SIGNAL SQLSTATE '45000' "
                    "SET MESSAGE_TEXT='KAP2_GUARD_DENY'; END IF; END"
                )
                cursor.execute(
                    f"CREATE TRIGGER {qdb}.kap2_guard_{index}_d BEFORE DELETE ON {table} FOR EACH ROW "
                    f"BEGIN IF {gate} THEN SIGNAL SQLSTATE '45000' "
                    "SET MESSAGE_TEXT='KAP2_GUARD_DENY'; END IF; END"
                )
                cursor.execute(
                    f"CREATE TRIGGER {qdb}.kap2_guard_{index}_i BEFORE INSERT ON {table} FOR EACH ROW "
                    f"BEGIN IF {gate} THEN SIGNAL SQLSTATE '45000' "
                    "SET MESSAGE_TEXT='KAP2_GUARD_DENY'; END IF; END"
                )

            cursor.execute(
                f"CREATE PROCEDURE {qschema}.revoke_synthetic(IN p_authority_id INT, IN p_user VARCHAR(140), IN p_person VARCHAR(140), "
                "IN p_session VARCHAR(140), IN p_grant VARCHAR(140), IN p_membership VARCHAR(140), IN p_hold DOUBLE) "
                "SQL SECURITY DEFINER BEGIN START TRANSACTION; "
                f"UPDATE {qschema}.authority SET seq=seq WHERE id=p_authority_id; "
                f"DO GET_LOCK('kap2_writer_{token}', 0); DO SLEEP(p_hold); "
                f"UPDATE {qdb}.`tabUser` SET enabled=0 WHERE name=p_user; "
                f"UPDATE {qdb}.`tabPerson` SET linked_user=NULL WHERE name=p_person; "
                f"UPDATE {qdb}.`tabHome Delegated Session` SET status='Revoked' WHERE name=p_session; "
                f"UPDATE {qdb}.`tabConsent Grant` SET state='REVOKED' WHERE name=p_grant; "
                f"DELETE FROM {qdb}.`tabCircle Membership` WHERE name=p_membership; "
                f"UPDATE {qschema}.authority SET state='REVOKED', seq=seq+1, outcome='PENDING' WHERE id=p_authority_id; "
                f"COMMIT; DO RELEASE_LOCK('kap2_writer_{token}'); END"
            )
            cursor.execute(f"GRANT EXECUTE ON PROCEDURE {qschema}.revoke_synthetic TO '{mutator}'@'localhost'")
            cursor.execute(f"REVOKE ALL PRIVILEGES ON {qdb}.* FROM '{database}'@'localhost'")
            cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {qdb}.* TO '{database}'@'localhost'")
            cursor.execute(f"SHOW GRANTS FOR '{database}'@'localhost'")
            grants = " ".join(row[0] for row in cursor.fetchall())
            if any(word in grants for word in ("ALL PRIVILEGES", "TRIGGER", "ALTER", "DROP", "CREATE")):
                raise AssertionError("site runtime still holds DDL privilege")
    finally:
        root.close()
    return schema, mutator


def run_guarded() -> dict:
    return _run("guarded")


def run_baseline() -> dict:
    return _run("baseline")


def run() -> dict:
    return run_baseline()


def _candidate_decision(state: str, sequence: int, witness: dict[int, tuple[str, str]],
                        policy_allows: bool) -> bool:
    """Disposable reader rule. The caller must supply an independent trusted witness."""
    return (state == "ACTIVE" and type(sequence) is int and policy_allows
            and witness.get(sequence) == ("COMMIT", "ACTIVE")
            and sequence == max(witness, default=-1))


def _run(mode: str) -> dict:
    import frappe

    site = frappe.local.site
    marker = Path(frappe.get_site_path("KAP2_DISPOSABLE_SITE"))
    if not site.startswith("kap2-probe-") or not marker.is_file():
        raise RuntimeError("KAP-2 probe requires a marked disposable site")
    if not frappe.db.exists("DocType", "Consent Grant"):
        raise RuntimeError("episteck_home DocTypes are not installed on disposable site")
    if mode not in {"baseline", "guarded"}:
        raise ValueError("unknown probe mode")

    token = uuid.uuid4().hex[:12]
    result: dict[str, object] = {"probe": "frappe_authority_paths", "mode": mode, "site": "marked_disposable", "observations": {}}
    observations: dict[str, object] = result["observations"]  # type: ignore[assignment]
    savepoint = f"kap2_{token}"
    original_user = frappe.session.user
    frappe.db.savepoint(savepoint)

    def observe(name: str, action, read) -> None:
        before = read()
        action_savepoint = f"kap2_action_{len(observations)}"
        frappe.db.savepoint(action_savepoint)
        try:
            action()
            after = read()
            observations[name] = {"permitted": True, "changed": before != after}
        except Exception as exc:
            observations[name] = {"permitted": False, "error_type": type(exc).__name__}
            frappe.db.rollback(save_point=action_savepoint)

    def save_field(doctype: str, name: str, field: str, value, *, ignore_permissions: bool = True) -> None:
        row = frappe.get_doc(doctype, name)
        setattr(row, field, value)
        row.save(ignore_permissions=ignore_permissions)

    try:
        user = frappe.get_doc({
            "doctype": "User", "email": f"kap2-{token}@example.invalid",
            "first_name": "KAP2", "send_welcome_email": 0, "enabled": 1,
        }).insert(ignore_permissions=True)
        other = frappe.get_doc({
            "doctype": "User", "email": f"kap2-other-{token}@example.invalid",
            "first_name": "KAP2", "send_welcome_email": 0, "enabled": 1,
        }).insert(ignore_permissions=True)
        person = frappe.get_doc({"doctype": "Person", "full_name": f"Synthetic {token}", "linked_user": user.name}).insert(ignore_permissions=True)
        subject = frappe.get_doc({"doctype": "Person", "full_name": f"Subject {token}"}).insert(ignore_permissions=True)
        circle = frappe.get_doc({"doctype": "Circle", "title": f"Synthetic {token}", "circle_type": "FAMILY"}).insert(ignore_permissions=True)
        membership = frappe.get_doc({"doctype": "Circle Membership", "circle": circle.name, "person": person.name}).insert(ignore_permissions=True)
        grant = frappe.get_doc({
            "doctype": "Consent Grant", "actor_person": person.name,
            "subject_person": subject.name, "domain": "KNOWLEDGE",
            "actions": "VIEW", "state": "ACTIVE", "granted_by": subject.name,
        }).insert(ignore_permissions=True)
        session = frappe.get_doc({
            "doctype": "Home Delegated Session", "user": user.name,
            "status": "Active", "expires_at": "2099-01-01 00:00:00",
        }).insert(ignore_permissions=True)

        fresh = None
        if mode == "guarded":
            fresh_user = frappe.get_doc({
                "doctype": "User", "email": f"kap2-fresh-{token}@example.invalid",
                "first_name": "KAP2", "send_welcome_email": 0, "enabled": 1,
            }).insert(ignore_permissions=True)
            fresh_person = frappe.get_doc({"doctype": "Person", "full_name": f"Fresh {token}",
                                          "linked_user": fresh_user.name}).insert(ignore_permissions=True)
            fresh_subject = frappe.get_doc({"doctype": "Person", "full_name": f"Fresh Subject {token}"}).insert(ignore_permissions=True)
            fresh_circle = frappe.get_doc({"doctype": "Circle", "title": f"Fresh {token}",
                                          "circle_type": "FAMILY"}).insert(ignore_permissions=True)
            fresh_membership = frappe.get_doc({"doctype": "Circle Membership", "circle": fresh_circle.name,
                                              "person": fresh_person.name}).insert(ignore_permissions=True)
            fresh_grant = frappe.get_doc({
                "doctype": "Consent Grant", "actor_person": fresh_person.name,
                "subject_person": fresh_subject.name, "domain": "KNOWLEDGE",
                "actions": "VIEW", "state": "ACTIVE", "granted_by": fresh_subject.name,
            }).insert(ignore_permissions=True)
            fresh_session = frappe.get_doc({
                "doctype": "Home Delegated Session", "user": fresh_user.name,
                "status": "Active", "expires_at": "2099-01-01 00:00:00",
            }).insert(ignore_permissions=True)
            fresh = (fresh_user, fresh_person, fresh_subject, fresh_membership, fresh_grant, fresh_session)

        get = frappe.db.get_value
        from episteck_home.policy.wrappers import check_access
        def legacy_allows() -> bool:
            return check_access(person.name, subject.name, "KNOWLEDGE", "VIEW")["allow"]

        if mode == "guarded":
            # DDL and the separate mutation connection require committed fixtures.
            # The entire marked site is discarded after this run.
            frappe.db.commit()
            result["observations"] = _guarded_checks(
                frappe, token, user, other, person, subject, circle,
                membership, grant, session, fresh, legacy_allows, save_field,
            )
            result["disposable_protected_paths_verified"] = True
            return result

        observations["legacy_wrapper_initial_allow"] = legacy_allows()
        observe("user_disable_save", lambda: save_field("User", user.name, "enabled", 0),
                lambda: get("User", user.name, "enabled"))
        observe("user_reenable_set_value", lambda: frappe.db.set_value("User", user.name, "enabled", 1),
                lambda: get("User", user.name, "enabled"))
        observe("user_disable_raw_sql", lambda: frappe.db.sql("UPDATE `tabUser` SET enabled=0 WHERE name=%s", user.name),
                lambda: get("User", user.name, "enabled"))
        frappe.set_user("Administrator")
        observe("admin_user_reenable_save", lambda: save_field("User", user.name, "enabled", 1, ignore_permissions=False),
                lambda: get("User", user.name, "enabled"))

        observe("person_relink_save", lambda: save_field("Person", person.name, "linked_user", other.name),
                lambda: get("Person", person.name, "linked_user"))
        observe("person_relink_set_value", lambda: frappe.db.set_value("Person", person.name, "linked_user", user.name),
                lambda: get("Person", person.name, "linked_user"))
        observe("person_unlink_raw_sql", lambda: frappe.db.sql("UPDATE `tabPerson` SET linked_user=NULL WHERE name=%s", person.name),
                lambda: get("Person", person.name, "linked_user"))

        observe("session_revoke_controller", lambda: frappe.get_doc("Home Delegated Session", session.name).revoke(),
                lambda: get("Home Delegated Session", session.name, "status"))
        observe("session_reenable_raw_sql", lambda: frappe.db.sql("UPDATE `tabHome Delegated Session` SET status='Active' WHERE name=%s", session.name),
                lambda: get("Home Delegated Session", session.name, "status"))
        observe("session_revoke_set_value", lambda: frappe.db.set_value("Home Delegated Session", session.name, "status", "Revoked"),
                lambda: get("Home Delegated Session", session.name, "status"))
        observe("grant_revoke_save", lambda: save_field("Consent Grant", grant.name, "state", "REVOKED"),
                lambda: get("Consent Grant", grant.name, "state"))
        observations["legacy_wrapper_after_revocation"] = legacy_allows()
        observe("grant_reenable_set_value", lambda: frappe.db.set_value("Consent Grant", grant.name, "state", "ACTIVE"),
                lambda: get("Consent Grant", grant.name, "state"))
        observations["legacy_wrapper_after_set_value"] = legacy_allows()
        observe("grant_revoke_raw_sql", lambda: frappe.db.sql("UPDATE `tabConsent Grant` SET state='REVOKED' WHERE name=%s", grant.name),
                lambda: get("Consent Grant", grant.name, "state"))
        observations["legacy_wrapper_after_raw_sql"] = legacy_allows()
        observe("admin_grant_reenable_save", lambda: save_field("Consent Grant", grant.name, "state", "ACTIVE", ignore_permissions=False),
                lambda: get("Consent Grant", grant.name, "state"))

        observe("ordinary_person_note_save", lambda: save_field("Person", person.name, "notes", "synthetic note"),
                lambda: get("Person", person.name, "notes"))
        observe("ordinary_user_name_save", lambda: save_field("User", user.name, "first_name", "Probe"),
                lambda: get("User", user.name, "first_name"))
        observe("ordinary_circle_note_save", lambda: save_field("Circle", circle.name, "notes", "synthetic note"),
                lambda: get("Circle", circle.name, "notes"))
        observe("circle_exit_membership_delete", lambda: membership.delete(ignore_permissions=True),
                lambda: frappe.db.exists("Circle Membership", membership.name))
        observations["legacy_grant_after_circle_exit"] = get("Consent Grant", grant.name, "state")
        observe("circle_target_delete", lambda: circle.delete(ignore_permissions=True),
                lambda: frappe.db.exists("Circle", circle.name))
        observe("grant_delete", lambda: frappe.get_doc("Consent Grant", grant.name).delete(ignore_permissions=True),
                lambda: frappe.db.exists("Consent Grant", grant.name))
        observe("ordinary_user_read", lambda: frappe.get_doc("User", user.name),
                lambda: frappe.db.exists("User", user.name))
        observe("ordinary_person_read", lambda: frappe.get_doc("Person", person.name),
                lambda: frappe.db.exists("Person", person.name))
        result["canonical_guard_verified"] = False  # No KAP-2 protected schema exists yet.
        return result
    finally:
        frappe.set_user(original_user)
        if mode == "baseline":
            frappe.db.rollback(save_point=savepoint)
        print(json.dumps(result, sort_keys=True, default=str))


def _guarded_checks(frappe, token, user, other, person, subject, circle,
                    membership, grant, session, fresh, legacy_allows, save_field) -> dict:
    import pymysql
    from episteck_home.policy.wrappers import check_access

    schema, mutator = _install_candidate_guard(frappe, token)
    database = frappe.conf.db_name
    socket = os.environ["KAP2_DB_SOCKET"]
    password = "KAP2_LOCAL_SYNTHETIC_ONLY"
    results: dict[str, str] = {}

    # REVOKE does not remove a database-level grant from an already connected
    # MariaDB session. The disposable cutover kills *all* site-principal
    # sessions before any candidate authority read is admitted.
    stale_connection = frappe.db._conn
    stale_id = frappe.db.sql("SELECT CONNECTION_ID()")[0][0]
    root = pymysql.connect(unix_socket=socket, user="root", password=os.environ["KAP2_DB_ROOT_PASSWORD"], autocommit=True)
    try:
        with root.cursor() as cursor:
            cursor.execute("SELECT ID FROM information_schema.PROCESSLIST WHERE USER=%s", (database,))
            sessions = [row[0] for row in cursor.fetchall()]
            if stale_id not in sessions:
                raise AssertionError("site connection absent from cutover inventory")
            for session_id in sessions:
                cursor.execute(f"KILL CONNECTION {int(session_id)}")
            cursor.execute("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE USER=%s", (database,))
            if cursor.fetchone()[0] != 0:
                raise AssertionError("privileged site connection survived cutover")
    finally:
        root.close()
    try:
        stale_connection.cursor().execute("SELECT 1")
    except pymysql.MySQLError:
        pass
    else:
        raise AssertionError("old privileged connection remained usable")
    frappe.db.close()
    frappe.db.connect()
    if frappe.db.sql("SELECT CONNECTION_ID()")[0][0] == stale_id:
        raise AssertionError("site did not reconnect after cutover")
    results["cutover_privileged_sessions_drained"] = "old_connection_killed"

    def expect_denied(name, action, read):
        before = read()
        try:
            action()
        except Exception as exc:
            if "KAP2_GUARD_DENY" not in str(exc):
                raise AssertionError(f"{name}: unexpected {type(exc).__name__}") from exc
            frappe.db.rollback()
            if read() != before:
                raise AssertionError(f"{name}: denied mutation changed state")
            results[name] = "guard_denied"
            return
        raise AssertionError(f"{name}: mutation bypassed guard")

    def expect_allowed(name, action, read):
        before = read()
        action()
        if read() == before:
            raise AssertionError(f"{name}: operation did not change state")
        frappe.db.commit()
        results[name] = "allowed_and_changed"

    def authority(authority_id=1):
        conn = pymysql.connect(unix_socket=socket, user=f"kap2_reader_{token}", password=password)
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT state, seq, outcome FROM `{schema}`.authority WHERE id=%s", (authority_id,))
                return cursor.fetchone()
        finally:
            conn.close()

    witness: dict[int, tuple[str, str]] = {0: ("COMMIT", "ACTIVE")}

    def candidate_read(*, authority_id=1, witness_map=None, locked=None, release=None, policy=None) -> bool:
        # Read the local fence under a shared lock. The separate synthetic
        # witness is supplied by the harness, never inferred from the DB's
        # restored `outcome` column. Production must use verified GCS history.
        conn = pymysql.connect(unix_socket=socket, user=f"kap2_reader_{token}", password=password, autocommit=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT state, seq FROM `{schema}`.authority WHERE id=%s LOCK IN SHARE MODE", (authority_id,))
                state, sequence = cursor.fetchone()
                if locked:
                    locked.set()
                if release and not release.wait(5):
                    raise TimeoutError("reader lock release timed out")
                allowed = _candidate_decision(state, sequence, witness if witness_map is None else witness_map,
                                              (policy or legacy_allows)())
            conn.commit()
            return allowed
        finally:
            conn.close()

    get = frappe.db.get_value
    if not legacy_allows() or authority() != ("ACTIVE", 0, "COMMIT"):
        raise AssertionError("initial synthetic authority invalid")
    results["initial_authority"] = "active_committed"
    witness[0] = ("PENDING", "ACTIVE")
    if candidate_read():
        raise AssertionError("ACTIVE/PENDING disclosed despite permissive grant")
    results["active_pending_reader"] = "denied"
    witness[0] = ("COMMIT", "ACTIVE")
    if not candidate_read():
        raise AssertionError("matching ACTIVE/COMMIT failed to authorize")
    results["active_matching_commit_reader"] = "allowed"

    expect_allowed("ordinary_user_name_save", lambda: save_field("User", other.name, "first_name", "Ordinary"),
                   lambda: get("User", other.name, "first_name"))
    expect_allowed("ordinary_person_note_save", lambda: save_field("Person", person.name, "notes", "ordinary"),
                   lambda: get("Person", person.name, "notes"))
    expect_allowed("ordinary_circle_note_save", lambda: save_field("Circle", circle.name, "notes", "ordinary"),
                   lambda: get("Circle", circle.name, "notes"))
    if not frappe.get_doc("User", user.name) or not frappe.get_doc("Person", person.name):
        raise AssertionError("ordinary reads failed")
    results["ordinary_reads"] = "allowed"

    expect_denied("user_disable_save", lambda: save_field("User", user.name, "enabled", 0),
                  lambda: get("User", user.name, "enabled"))
    expect_denied("person_relink_save", lambda: save_field("Person", person.name, "linked_user", other.name),
                  lambda: get("Person", person.name, "linked_user"))
    expect_denied("session_revoke_controller", lambda: frappe.get_doc("Home Delegated Session", session.name).revoke(),
                  lambda: get("Home Delegated Session", session.name, "status"))
    expect_denied("grant_revoke_save", lambda: save_field("Consent Grant", grant.name, "state", "REVOKED"),
                  lambda: get("Consent Grant", grant.name, "state"))
    expect_denied("circle_exit_delete", lambda: frappe.get_doc("Circle Membership", membership.name).delete(ignore_permissions=True),
                  lambda: frappe.db.exists("Circle Membership", membership.name))

    # Route the actual Frappe DocType controller dispatch through a disposable
    # mutation adapter. The production revoke() was already shown guard-denied
    # above; this monkeypatch is never installed outside this marked site run.
    from concurrent.futures import ThreadPoolExecutor
    from episteck_home.episteck_home.doctype.home_delegated_session.home_delegated_session import HomeDelegatedSession

    original_revoke = HomeDelegatedSession.revoke
    hold_seconds = 0.0
    site_name = frappe.local.site
    fresh_user, fresh_person, fresh_subject, fresh_membership, fresh_grant, fresh_session = fresh

    def fresh_legacy_allows() -> bool:
        return check_access(fresh_person.name, fresh_subject.name, "KNOWLEDGE", "VIEW")["allow"]

    def candidate_revoke(self):
        targets = {
            session.name: (1, user, person, session, grant, membership),
            fresh_session.name: (2, fresh_user, fresh_person, fresh_session, fresh_grant, fresh_membership),
        }
        if self.name not in targets:
            raise AssertionError("unexpected controller target")
        authority_id, target_user, target_person, target_session, target_grant, target_membership = targets[self.name]
        conn = pymysql.connect(unix_socket=socket, user=mutator, password=password, autocommit=True)
        try:
            with conn.cursor() as cursor:
                cursor.callproc(f"{schema}.revoke_synthetic",
                                (authority_id, target_user.name, target_person.name, target_session.name,
                                 target_grant.name, target_membership.name, hold_seconds))
        finally:
            conn.close()

    def thread_call(action):
        import frappe as thread_frappe
        thread_frappe.init(site=site_name)
        thread_frappe.connect()
        try:
            return action(thread_frappe)
        finally:
            thread_frappe.destroy()

    def writer_lock_held() -> bool:
        root = pymysql.connect(unix_socket=socket, user="root", password=os.environ["KAP2_DB_ROOT_PASSWORD"])
        try:
            with root.cursor() as cursor:
                cursor.execute("SELECT IS_USED_LOCK(%s)", (f"kap2_writer_{token}",))
                return cursor.fetchone()[0] is not None
        finally:
            root.close()

    HomeDelegatedSession.revoke = candidate_revoke
    try:
        read_locked, release_read = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_read = pool.submit(thread_call, lambda _f: candidate_read(locked=read_locked, release=release_read))
            if not read_locked.wait(5):
                raise AssertionError("reader-first did not acquire fence lock")
            first_revoke = pool.submit(thread_call, lambda f: f.get_doc("Home Delegated Session", session.name).revoke())
            time.sleep(0.25)
            if first_revoke.done() or writer_lock_held():
                raise AssertionError("reader-first revocation bypassed fence lock")
            release_read.set()
            if first_read.result(timeout=5) is not True:
                raise AssertionError("reader-first did not see the prior committed grant")
            first_revoke.result(timeout=5)
        witness[1] = ("PENDING", "REVOKED")
        frappe.db.commit()
        if authority() != ("REVOKED", 1, "PENDING") or candidate_read():
            raise AssertionError("reader-first revocation did not block subsequent disclosure")
        results["frappe_controller_reader_first"] = "reader_before_revocation_then_denied"

        fresh_witness = {0: ("COMMIT", "ACTIVE")}
        if not fresh_legacy_allows() or authority(2) != ("ACTIVE", 0, "COMMIT"):
            raise AssertionError("writer-first fixture is not fresh permissive authority")
        if not candidate_read(authority_id=2, witness_map=fresh_witness, policy=fresh_legacy_allows):
            raise AssertionError("writer-first fixture did not initially authorize")
        results["writer_first_initial_authorization"] = "allowed"
        hold_seconds = 1.0
        with ThreadPoolExecutor(max_workers=1) as pool:
            second_revoke = pool.submit(thread_call, lambda f: f.get_doc("Home Delegated Session", fresh_session.name).revoke())
            deadline = time.monotonic() + 5
            while not writer_lock_held() and time.monotonic() < deadline:
                if second_revoke.done():
                    second_revoke.result()
                    raise AssertionError("writer-first lock was never held")
                time.sleep(0.02)
            if not writer_lock_held():
                raise AssertionError("writer-first lock acquisition timed out")
            started = time.monotonic()
            if candidate_read(authority_id=2, witness_map=fresh_witness, policy=fresh_legacy_allows):
                raise AssertionError("writer-first disclosed revoked authority")
            waited = time.monotonic() - started
            second_revoke.result(timeout=5)
            if waited < 0.5:
                raise AssertionError("writer-first reader did not wait for revocation")
        fresh_witness[1] = ("PENDING", "REVOKED")
        frappe.db.commit()
        if authority(2) != ("REVOKED", 1, "PENDING") or candidate_read(
                authority_id=2, witness_map=fresh_witness, policy=fresh_legacy_allows):
            raise AssertionError("writer-first revocation did not advance fence")
        results["frappe_controller_writer_first"] = "fresh_active_writer_lock_reader_waited_denied"
        results["revoked_pending_reader"] = "denied"
    finally:
        HomeDelegatedSession.revoke = original_revoke

    frappe.db.commit()
    if legacy_allows():
        raise AssertionError("legacy wrapper still allows after revocation")
    results["protected_revocation"] = "legacy_wrapper_denies"

    expect_denied("user_reenable_set_value", lambda: frappe.db.set_value("User", user.name, "enabled", 1),
                  lambda: get("User", user.name, "enabled"))
    expect_denied("user_reenable_raw_sql", lambda: frappe.db.sql("UPDATE `tabUser` SET enabled=1 WHERE name=%s", user.name),
                  lambda: get("User", user.name, "enabled"))
    frappe.set_user("Administrator")
    expect_denied("admin_user_reenable_save", lambda: save_field("User", user.name, "enabled", 1, ignore_permissions=False),
                  lambda: get("User", user.name, "enabled"))
    expect_denied("person_relink_set_value", lambda: frappe.db.set_value("Person", person.name, "linked_user", other.name),
                  lambda: get("Person", person.name, "linked_user"))
    expect_denied("session_reenable_set_value", lambda: frappe.db.set_value("Home Delegated Session", session.name, "status", "Active"),
                  lambda: get("Home Delegated Session", session.name, "status"))
    expect_denied("session_reenable_raw_sql", lambda: frappe.db.sql("UPDATE `tabHome Delegated Session` SET status='Active' WHERE name=%s", session.name),
                  lambda: get("Home Delegated Session", session.name, "status"))
    expect_denied("grant_reenable_set_value", lambda: frappe.db.set_value("Consent Grant", grant.name, "state", "ACTIVE"),
                  lambda: get("Consent Grant", grant.name, "state"))
    expect_denied("grant_reenable_raw_sql", lambda: frappe.db.sql("UPDATE `tabConsent Grant` SET state='ACTIVE' WHERE name=%s", grant.name),
                  lambda: get("Consent Grant", grant.name, "state"))
    expect_denied("admin_grant_reenable_save", lambda: save_field("Consent Grant", grant.name, "state", "ACTIVE", ignore_permissions=False),
                  lambda: get("Consent Grant", grant.name, "state"))
    expect_denied("membership_insert", lambda: frappe.get_doc({"doctype": "Circle Membership", "circle": circle.name,
                  "person": person.name}).insert(ignore_permissions=True),
                  lambda: frappe.db.exists("Circle Membership", {"circle": circle.name, "person": person.name}))

    # Read-only site principal cannot disable the SQL trigger; root is held only
    # by the disposable harness for setup and synthetic outcome publication.
    try:
        frappe.db.sql("DROP TRIGGER kap2_guard_0_u")
    except Exception as exc:
        if "1142" not in str(exc) and "command denied" not in str(exc).lower():
            raise AssertionError("DDL bypass failed for an unexpected reason") from exc
        frappe.db.rollback()
        results["runtime_trigger_drop"] = "privilege_denied"
    else:
        raise AssertionError("runtime principal dropped guard trigger")

    root = pymysql.connect(unix_socket=socket, user="root", password=os.environ["KAP2_DB_ROOT_PASSWORD"], autocommit=True)
    try:
        with root.cursor() as cursor:
            cursor.execute(f"UPDATE `{schema}`.authority SET outcome='COMMIT' WHERE id=1")
    finally:
        root.close()
    witness[1] = ("COMMIT", "REVOKED")
    if authority() != ("REVOKED", 1, "COMMIT") or legacy_allows() or candidate_read():
        raise AssertionError("published revocation changed access")
    results["revoked_matching_commit_reader"] = "denied"
    if any(value not in {"guard_denied", "allowed_and_changed", "allowed", "active_committed", "denied",
                          "old_connection_killed", "reader_before_revocation_then_denied",
                          "fresh_active_writer_lock_reader_waited_denied",
                          "legacy_wrapper_denies", "privilege_denied"}
           for value in results.values()):
        raise AssertionError("unknown guarded outcome")
    return results
