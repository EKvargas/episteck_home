"""Run the PERSON vertical on a marked Frappe site and two private MariaDBs."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

GATEWAY_DIR = Path(__file__).parents[1] / "knowledge-kap2-transactional-witness"
sys.path.insert(0, str(GATEWAY_DIR))
from test_gateway import PrivateDB  # noqa: E402
from test_integrated import install_guards, install_procedures  # noqa: E402


def run_command(args: list[str], *, cwd: Path, env: dict[str, str],
                input_text: str | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                            input=input_text, timeout=600)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): "
                           f"{(result.stderr or result.stdout)[-6000:]}")
    return result.stdout.strip()


def bench_result(output: str) -> dict:
    for line in output.splitlines():
        if line.startswith("{"):
            value = json.loads(line)
            if isinstance(value, dict):
                return value
    raise RuntimeError("bench probe did not return a JSON object")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    bench = args.bench.resolve()
    if not (bench / "apps" / "frappe").is_dir() or not (bench / "sites").is_dir():
        raise SystemExit("existing disposable Frappe bench required")
    site = f"kap2-probe-person-{secrets.token_hex(4)}"
    site_path = (bench / "sites" / site).resolve()
    if site_path.parent != (bench / "sites").resolve() or site_path.exists():
        raise SystemExit("unsafe or existing disposable site target")
    app = Path(__file__).resolve().parents[2] / "apps" / "episteck_home"
    env = os.environ.copy()
    gateway_dir = Path(__file__).parents[1] / "knowledge-kap2-transactional-witness"
    env["PYTHONPATH"] = os.pathsep.join((str(app), str(gateway_dir),
                                           env.get("PYTHONPATH", "")))
    result: dict[str, object] = {"site": "marked_disposable", "cleanup": {}}
    with tempfile.TemporaryDirectory(prefix="kap2-mariadb-person-") as directory:
        with tempfile.TemporaryDirectory(prefix="kap2-witness-person-") as witness_dir:
            db = PrivateDB(Path(directory))
            witness_db = PrivateDB(Path(witness_dir))
            _run_site(bench, site, site_path, app, env, result, db, witness_db)
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        target = args.evidence.resolve()
        if not target.parent.is_dir():
            raise RuntimeError("evidence parent must already exist")
        target.write_text(output)
    print(output)


def _run_site(bench, site, site_path, app, env, result, db, witness_db):
        redis_processes: list[subprocess.Popen] = []
        root_password = "synthetic-person-root"
        site_created = False
        try:
            for port in (11002, 13002):
                with socket.socket() as check:
                    if check.connect_ex(("127.0.0.1", port)) == 0:
                        raise RuntimeError(f"Redis port {port} is already in use; refusing shared service")
                process = subprocess.Popen([
                    "redis-server", "--bind", "127.0.0.1", "--port", str(port),
                    "--save", "", "--appendonly", "no",
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                redis_processes.append(process)
                for _ in range(50):
                    ping = subprocess.run(["redis-cli", "-p", str(port), "ping"],
                                          capture_output=True, text=True)
                    if ping.stdout.strip() == "PONG":
                        break
                    import time
                    time.sleep(0.1)
                else:
                    raise RuntimeError("private Redis did not start")
            db.sql("ALTER USER 'root'@'localhost' IDENTIFIED BY 'synthetic-person-root'")
            env["KAP2_DB_SOCKET"] = str(db.socket)
            env["KAP2_WITNESS_SOCKET"] = str(witness_db.socket)
            database = "_" + secrets.token_hex(8)
            run_command([
                "bench", "new-site", site, "--db-name", database,
                "--db-socket", str(db.socket), "--db-root-password", root_password,
                "--db-password", "synthetic-person-site",
                "--admin-password", "synthetic-person-admin",
                "--install-app", "episteck_home",
            ], cwd=bench, env=env)
            site_created = True
            marker = site_path / "KAP2_DISPOSABLE_SITE"
            marker.write_text("PERSON vertical synthetic probe only\n")
            assert marker.is_file()
            fixture = bench_result(run_command([
                "bench", "--site", site, "execute",
                "episteck_home.knowledge_authority.integrated_frappe_probe.setup",
            ], cwd=bench, env=env))
            env.update({
                "KAP2_OWNER_USER": fixture["owner_user"],
                "KAP2_ACTOR_USER": fixture["actor_user"],
                "KAP2_OWNER_PERSON": fixture["owner_person"],
                "KAP2_ACTOR_PERSON": fixture["actor_person"],
                "KAP2_GRANT": fixture["grant"],
            })
            run_command(["mariadb", "--no-defaults", f"--socket={db.socket}",
                         "-uroot", f"-p{root_password}", "-e", "CREATE DATABASE home_auth"],
                        cwd=bench, env=env)
            schema = (Path(__file__).with_name("integrated_schema.sql")).read_text()
            run_command(["mariadb", "--no-defaults", f"--socket={db.socket}",
                         "-uroot", f"-p{root_password}"], cwd=bench, env=env,
                        input_text=schema)
            install_procedures(db, database, root_password)
            run_command(["mariadb", "--no-defaults", f"--socket={db.socket}",
                         "-uroot", f"-p{root_password}", "-e",
                         "CREATE USER 'ha_mutator'@'localhost' IDENTIFIED BY 'synthetic-mutator';"
                         "CREATE USER 'ha_reader'@'localhost' IDENTIFIED BY 'synthetic-reader';"
                         "CREATE USER 'ha_recovery'@'localhost' IDENTIFIED BY 'synthetic-home-recover';"
                         "GRANT SELECT ON home_auth.* TO 'ha_mutator'@'localhost';"
                         "GRANT SELECT ON home_auth.* TO 'ha_reader'@'localhost';"
                         f"GRANT SELECT ON `{database}`.`tabUser` TO 'ha_mutator'@'localhost';"
                         f"GRANT SELECT ON `{database}`.`tabPerson` TO 'ha_mutator'@'localhost';"
                         f"GRANT SELECT ON `{database}`.`tabConsent Grant` TO 'ha_mutator'@'localhost';"
                         f"GRANT SELECT ON `{database}`.`tabUser` TO 'ha_reader'@'localhost';"
                         f"GRANT SELECT ON `{database}`.`tabPerson` TO 'ha_reader'@'localhost';"
                         f"GRANT SELECT ON `{database}`.`tabConsent Grant` TO 'ha_reader'@'localhost';"
                         "GRANT EXECUTE ON PROCEDURE home_auth.stage_person_mutation TO 'ha_mutator'@'localhost';"
                         "GRANT EXECUTE ON PROCEDURE home_auth.record_person_event TO 'ha_mutator'@'localhost';"
                         "GRANT SELECT ON home_auth.binding TO 'ha_recovery'@'localhost';"
                         "GRANT SELECT ON home_auth.head TO 'ha_recovery'@'localhost';"
                         "GRANT EXECUTE ON PROCEDURE home_auth.reset_person_incarnation TO 'ha_recovery'@'localhost';"
                         f"INSERT INTO home_auth.binding VALUES ('{site}','home-probe','p1','{database}',1);"
                         "INSERT INTO home_auth.head VALUES ('p1','old-incarnation',0,'OLD_ALLOW');"
                         f"INSERT INTO home_auth.dependency VALUES ('p1','{fixture['grant']}',1)"],
                        cwd=bench, env=env)
            install_guards(db, database, root_password)
            result["person_vertical"] = bench_result(run_command([
                "bench", "--site", site, "execute",
                "episteck_home.knowledge_authority.integrated_frappe_probe.run",
            ], cwd=bench, env=env))
        finally:
            if site_created and site_path.is_dir() and site_path.parent == (bench / "sites").resolve():
                run_command([
                    "bench", "drop-site", site, "--no-backup", "--force",
                    "--db-root-password", root_password,
                ], cwd=bench, env=env)
                result["cleanup"] = {"site_removed": not site_path.exists()}
            if db.process is not None and db.process.poll() is None:
                subprocess.run([
                    "mariadb-admin", "--no-defaults", f"--socket={db.socket}",
                    "-uroot", f"-p{root_password}", "shutdown",
                ], capture_output=True, timeout=20, check=True)
                db.process.wait(timeout=10)
            result["cleanup"]["private_db_stopped"] = db.process is None or db.process.poll() is not None
            witness_db.stop()
            result["cleanup"]["private_witness_stopped"] = (
                witness_db.process is None or witness_db.process.poll() is not None)
            for process in redis_processes:
                process.terminate()
                process.wait(timeout=10)
            result["cleanup"]["private_redis_stopped"] = all(
                process.poll() is not None for process in redis_processes)


if __name__ == "__main__":
    main()
