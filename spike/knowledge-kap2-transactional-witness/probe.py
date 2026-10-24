"""Disposable, socket-only MariaDB witness transaction probe (synthetic data)."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def main() -> None:
    evidence: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="kap2-tx-witness-") as directory:
        root = Path(directory)
        data = root / "data"
        socket = root / "mariadb.sock"
        data.mkdir()
        command("mariadb-install-db", "--no-defaults", f"--datadir={data}",
                "--auth-root-authentication-method=normal", "--skip-test-db")
        server = subprocess.Popen(
            ["mariadbd", "--no-defaults", f"--datadir={data}",
             f"--socket={socket}", f"--pid-file={root / 'pid'}",
             f"--log-error={root / 'log'}", "--skip-networking"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        def sql(statement: str, user: str = "root", check: bool = True) -> subprocess.CompletedProcess[str]:
            return command("mariadb", "--no-defaults", f"--socket={socket}",
                           f"-u{user}", "-N", "-B", "-e", statement, check=check)

        try:
            for _ in range(100):
                if socket.exists() and command("mariadb-admin", "--no-defaults",
                                               f"--socket={socket}", "-uroot", "ping",
                                               check=False).returncode == 0:
                    break
                if server.poll() is not None:
                    raise RuntimeError((root / "log").read_text()[-2000:])
                time.sleep(0.1)
            else:
                raise TimeoutError("private MariaDB did not start")

            sql("CREATE DATABASE witness; CREATE DATABASE home;"
                "CREATE TABLE witness.head (partition_id INT PRIMARY KEY, revision INT NOT NULL,"
                " epoch INT NOT NULL, state VARCHAR(16) NOT NULL, event_id VARCHAR(32),"
                " digest VARCHAR(64) NOT NULL) ENGINE=InnoDB;"
                "INSERT INTO witness.head VALUES (1,0,1,'COMMITTED',NULL,'grant-active');"
                "CREATE TABLE home.authority (partition_id INT PRIMARY KEY, revision INT NOT NULL,"
                " digest VARCHAR(64) NOT NULL) ENGINE=InnoDB;"
                "INSERT INTO home.authority VALUES (1,0,'grant-active');"
                "CREATE USER 'writer_e1'@'localhost'; CREATE USER 'writer_e2'@'localhost';"
                "CREATE USER 'reader'@'localhost';"
                "GRANT SELECT ON witness.head TO 'reader'@'localhost';")
            # Distinct epoch-specific entry points avoid trusting a caller-supplied epoch.
            for epoch in (1, 2):
                for action, update in (
                    ("prepare", "revision=revision+1,state='PENDING',event_id='revoke-1'"),
                    ("commit", "state='COMMITTED',digest='grant-revoked'"),
                ):
                    predicate = (f"epoch={epoch} AND state='COMMITTED' AND revision=0"
                                 if action == "prepare" else
                                 f"epoch={epoch} AND state='PENDING' AND revision=1 "
                                 "AND event_id='revoke-1'")
                    routine = (f"CREATE PROCEDURE witness.{action}_e{epoch}() SQL SECURITY DEFINER "
                               f"BEGIN UPDATE witness.head SET {update} WHERE partition_id=1 "
                               f"AND {predicate}; IF ROW_COUNT() != 1 THEN "
                               "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='obsolete or illegal transition'; "
                               "END IF; END")
                    command("mariadb", "--no-defaults", f"--socket={socket}", "-uroot",
                            "--delimiter=//", "-e", routine + "//")
                    sql(f"GRANT EXECUTE ON PROCEDURE witness.{action}_e{epoch} "
                        f"TO 'writer_e{epoch}'@'localhost'")

            assert sql("UPDATE witness.head SET digest='forged' WHERE partition_id=1",
                       "writer_e1", check=False).returncode != 0
            evidence["direct_writer_dml"] = "denied"
            assert sql("CALL witness.prepare_e2()", "writer_e1", check=False).returncode != 0
            evidence["cross_epoch_execute"] = "denied"

            sql("CALL witness.prepare_e1()", "writer_e1")
            assert sql("SELECT state FROM witness.head").stdout.strip() == "PENDING"
            evidence["commit_gap"] = "PENDING visible; authorization must deny"
            sql("UPDATE home.authority SET revision=1,digest='grant-revoked' WHERE partition_id=1")
            sql("CALL witness.commit_e1()", "writer_e1")
            assert sql("SELECT revision,state,digest FROM witness.head").stdout.strip() == (
                "1\tCOMMITTED\tgrant-revoked")
            assert sql("CALL witness.commit_e1()", "writer_e1", check=False).returncode != 0
            evidence["commit_and_duplicate"] = "committed; duplicate rejected"

            # Simulate a Home backup restore while the witness stays current.
            sql("UPDATE home.authority SET revision=0,digest='grant-active' WHERE partition_id=1")
            home = sql("SELECT revision,digest FROM home.authority").stdout.strip()
            witness = sql("SELECT revision,digest FROM witness.head").stdout.strip()
            assert home != witness
            evidence["home_restore"] = "revision/digest mismatch; authorization must deny"

            # Controlled privileged takeover: old entry points remain callable but fail.
            sql("UPDATE witness.head SET epoch=2 WHERE partition_id=1")
            assert sql("CALL witness.commit_e1()", "writer_e1", check=False).returncode != 0
            evidence["old_principal_after_takeover"] = "illegal transition rejected"

            # Both stores rolled back to matching obsolete rows: row comparison alone fails.
            sql("UPDATE witness.head SET revision=0,epoch=1,state='COMMITTED',"
                "event_id=NULL,digest='grant-active' WHERE partition_id=1")
            assert sql("SELECT revision,digest FROM home.authority").stdout.strip() == (
                sql("SELECT revision,digest FROM witness.head").stdout.strip())
            evidence["combined_restore"] = "obsolete rows match; independent admission proof required"
        finally:
            if server.poll() is None:
                command("mariadb-admin", "--no-defaults", f"--socket={socket}",
                        "-uroot", "shutdown", check=False)
                server.wait(timeout=10)
    print(json.dumps({"probe": "local_mariadb_transaction_witness", "evidence": evidence},
                     sort_keys=True))


if __name__ == "__main__":
    main()
