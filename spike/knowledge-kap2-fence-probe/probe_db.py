"""Private socket-only MariaDB guard probe. Uses synthetic data and cleans up its own datadir."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result


def main() -> None:
    results: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="kap2-mariadb-") as directory:
        root = Path(directory)
        data, socket = root / "data", root / "db.sock"
        data.mkdir()
        run("mariadb-install-db", "--no-defaults", f"--datadir={data}",
            "--auth-root-authentication-method=normal", "--skip-test-db")
        server = subprocess.Popen(
            ["mariadbd", "--no-defaults", f"--datadir={data}",
             f"--socket={socket}", f"--pid-file={root / 'db.pid'}",
             f"--log-error={root / 'db.log'}", "--skip-networking"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                if socket.exists() and run("mariadb-admin", "--no-defaults", f"--socket={socket}",
                                           "-uroot", "ping", check=False).returncode == 0:
                    break
                if server.poll() is not None:
                    raise RuntimeError((root / "db.log").read_text()[-2000:])
                time.sleep(0.1)
            else:
                raise TimeoutError("private MariaDB did not start")

            def sql(query: str, user: str = "root", check: bool = True) -> subprocess.CompletedProcess[str]:
                return run("mariadb", "--no-defaults", f"--socket={socket}",
                           f"-u{user}", "-N", "-B", "-e", query, check=check)

            sql("CREATE DATABASE site_probe; CREATE DATABASE auth_probe;"
                "CREATE TABLE auth_probe.grants (id INT PRIMARY KEY, state VARCHAR(16));"
                "CREATE TABLE auth_probe.fence (id INT PRIMARY KEY, seq INT);"
                "INSERT INTO auth_probe.grants VALUES (1,'ACTIVE');"
                "INSERT INTO auth_probe.fence VALUES (1,0);"
                "CREATE USER 'site_runtime'@'localhost';"
                "CREATE USER 'auth_mutator'@'localhost';"
                "GRANT ALL ON site_probe.* TO 'site_runtime'@'localhost';")
            # No direct table DML privilege for either runtime principal.
            run("mariadb", "--no-defaults", f"--socket={socket}", "-uroot",
                "--delimiter=//", "-e",
                "CREATE PROCEDURE auth_probe.revoke_synthetic() SQL SECURITY DEFINER "
                "BEGIN START TRANSACTION; "
                "UPDATE auth_probe.fence SET seq=seq WHERE id=1; DO SLEEP(2); "
                "UPDATE auth_probe.grants SET state='REVOKED' WHERE id=1; "
                "UPDATE auth_probe.fence SET seq=seq+1 WHERE id=1; COMMIT; END//")
            sql("GRANT EXECUTE ON PROCEDURE auth_probe.revoke_synthetic TO 'auth_mutator'@'localhost'")

            attempts = {
                "generic_save_insert": "INSERT INTO auth_probe.grants VALUES (2,'ACTIVE')",
                "generic_save_update": "UPDATE auth_probe.grants SET state='ACTIVE' WHERE id=1",
                "generic_delete": "DELETE FROM auth_probe.grants WHERE id=1",
                "db_set_value": "UPDATE auth_probe.grants SET state='ACTIVE' WHERE id=1",
                "raw_sql": "UPDATE auth_probe.fence SET seq=99 WHERE id=1",
            }
            for name, query in attempts.items():
                assert sql(query, "site_runtime", check=False).returncode != 0, name
                results[name] = "DENIED"
            assert sql("UPDATE auth_probe.grants SET state='ACTIVE' WHERE id=1",
                       "auth_mutator", check=False).returncode != 0
            results["mutator_direct_dml"] = "DENIED"
            writer = subprocess.Popen(
                ["mariadb", "--no-defaults", f"--socket={socket}",
                 "-uauth_mutator", "-e", "CALL auth_probe.revoke_synthetic()"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            time.sleep(0.3)
            started = time.monotonic()
            current = sql("START TRANSACTION; SELECT seq FROM auth_probe.fence WHERE id=1 FOR UPDATE; "
                          "SELECT state FROM auth_probe.grants WHERE id=1; COMMIT;")
            waited = time.monotonic() - started
            assert writer.wait(timeout=5) == 0
            assert waited >= 1.0, waited
            assert "REVOKED" in current.stdout and "1" in current.stdout
            assert sql("SELECT g.state, f.seq FROM auth_probe.grants g JOIN auth_probe.fence f ON f.id=g.id").stdout.strip() == "REVOKED\t1"
            results["definer_procedure_atomic_change"] = "PASS"
            results["current_reader_waits_for_revocation"] = "PASS"

            # Concurrent direct bypass is still denied while a legal transaction holds row locks.
            lock = subprocess.Popen(
                ["mariadb", "--no-defaults", f"--socket={socket}", "-uroot", "-e",
                 "START TRANSACTION; SELECT * FROM auth_probe.fence WHERE id=1 FOR UPDATE; DO SLEEP(2); COMMIT;"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(0.3)
            assert sql("UPDATE auth_probe.fence SET seq=100 WHERE id=1",
                       "site_runtime", check=False).returncode != 0
            lock.wait(timeout=5)
            assert sql("SELECT seq FROM auth_probe.fence WHERE id=1").stdout.strip() == "1"
            results["concurrent_bypass"] = "DENIED"

            # Reverse order: a current reader holding the fence locks before revoke.
            sql("UPDATE auth_probe.grants SET state='ACTIVE' WHERE id=1; "
                "UPDATE auth_probe.fence SET seq=0 WHERE id=1")
            reader = subprocess.Popen(
                ["mariadb", "--no-defaults", f"--socket={socket}", "-uroot", "-e",
                 "START TRANSACTION; SELECT seq FROM auth_probe.fence WHERE id=1 FOR UPDATE; "
                 "DO SLEEP(2); SELECT state FROM auth_probe.grants WHERE id=1; COMMIT;"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            time.sleep(0.3)
            started = time.monotonic()
            sql("CALL auth_probe.revoke_synthetic()", "auth_mutator")
            waited = time.monotonic() - started
            reader_output, _ = reader.communicate(timeout=5)
            assert reader.returncode == 0 and "ACTIVE" in reader_output
            assert waited >= 3.0, waited
            assert sql("SELECT g.state, f.seq FROM auth_probe.grants g JOIN auth_probe.fence f ON f.id=g.id").stdout.strip() == "REVOKED\t1"
            results["reader_before_revocation"] = "PASS"

            # The external journal is deliberately a separate in-memory witness here.
            # MariaDB committed a permissive change, but publication is still pending.
            external = {1: ("COMMIT", "REVOKED"), 2: ("PREPARE", "ACTIVE")}
            sql("START TRANSACTION; UPDATE auth_probe.grants SET state='ACTIVE' WHERE id=1; "
                "UPDATE auth_probe.fence SET seq=2 WHERE id=1; COMMIT")

            def authorized() -> bool:
                state, revision = sql(
                    "SELECT g.state, f.seq FROM auth_probe.grants g JOIN auth_probe.fence f ON f.id=g.id"
                ).stdout.strip().split("\t")
                latest = max(external)
                return int(revision) == latest and external[latest] == ("COMMIT", state) and state == "ACTIVE"

            assert not authorized()
            results["external_commit_gap"] = "DENIED"
            external[2] = ("COMMIT", "ACTIVE")
            assert authorized()
            # Simulate restoring a local snapshot behind the independent witness.
            sql("UPDATE auth_probe.grants SET state='REVOKED' WHERE id=1; "
                "UPDATE auth_probe.fence SET seq=1 WHERE id=1")
            assert not authorized()
            results["restore_behind_witness"] = "DENIED"
        finally:
            if server.poll() is None:
                run("mariadb-admin", "--no-defaults", f"--socket={socket}",
                    "-uroot", "shutdown", check=False)
                server.wait(timeout=10)
    print(json.dumps({"probe": "private_mariadb_guard", "results": results}, sort_keys=True))


if __name__ == "__main__":
    main()
