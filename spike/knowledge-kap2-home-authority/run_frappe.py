"""Run Task 2 probes on a new marked Frappe site and private MariaDB only."""

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
    site = f"kap2-probe-task2-{secrets.token_hex(4)}"
    site_path = (bench / "sites" / site).resolve()
    if site_path.parent != (bench / "sites").resolve() or site_path.exists():
        raise SystemExit("unsafe or existing disposable site target")
    app = Path(__file__).resolve().parents[2] / "apps" / "episteck_home"
    env = os.environ.copy()
    gateway_dir = Path(__file__).parents[1] / "knowledge-kap2-transactional-witness"
    env["PYTHONPATH"] = os.pathsep.join((str(app), str(gateway_dir),
                                           env.get("PYTHONPATH", "")))
    result: dict[str, object] = {"site": "marked_disposable", "cleanup": {}}
    with tempfile.TemporaryDirectory(prefix="kap2-mariadb-task2-") as directory:
        db = PrivateDB(Path(directory))
        redis_processes: list[subprocess.Popen] = []
        root_password = "synthetic-task2-root"
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
            db.sql("ALTER USER 'root'@'localhost' IDENTIFIED BY 'synthetic-task2-root'")
            env["KAP2_DB_SOCKET"] = str(db.socket)
            env["KAP2_DB_ROOT_PASSWORD"] = root_password
            database = "_" + secrets.token_hex(8)
            run_command([
                "bench", "new-site", site, "--db-name", database,
                "--db-socket", str(db.socket), "--db-root-password", root_password,
                "--db-password", "synthetic-task2-site",
                "--admin-password", "synthetic-task2-admin",
                "--install-app", "episteck_home",
            ], cwd=bench, env=env)
            site_created = True
            marker = site_path / "KAP2_DISPOSABLE_SITE"
            marker.write_text("Task 2 synthetic probe only\n")
            assert marker.is_file()
            run_command(["mariadb", "--no-defaults", f"--socket={db.socket}",
                         "-uroot", f"-p{root_password}", "-e", "CREATE DATABASE home_auth"],
                        cwd=bench, env=env)
            schema = (Path(__file__).with_name("home_schema.sql")).read_text()
            run_command(["mariadb", "--no-defaults", f"--socket={db.socket}",
                         "-uroot", f"-p{root_password}"], cwd=bench, env=env,
                        input_text=schema)
            run_command(["mariadb", "--no-defaults", f"--socket={db.socket}",
                         "-uroot", f"-p{root_password}", "-e",
                         "CREATE USER 'home_auth_writer'@'localhost' IDENTIFIED BY 'synthetic-home-write';"
                         "CREATE USER 'home_auth_reader'@'localhost' IDENTIFIED BY 'synthetic-home-read';"
                         "GRANT EXECUTE ON PROCEDURE home_auth.apply_event TO 'home_auth_writer'@'localhost';"
                         "GRANT EXECUTE ON PROCEDURE home_auth.read_head TO 'home_auth_reader'@'localhost';"
                         "GRANT SELECT ON home_auth.events TO 'home_auth_reader'@'localhost';"
                         "GRANT SELECT ON home_auth.activations TO 'home_auth_reader'@'localhost'"],
                        cwd=bench, env=env)
            result["authority_policy"] = bench_result(run_command([
                "bench", "--site", site, "execute",
                "episteck_home.knowledge_authority.frappe_probe.run",
            ], cwd=bench, env=env))
            result["guarded_frappe"] = bench_result(run_command([
                "bench", "--site", site, "execute",
                "episteck_home.probes.kap2_frappe.run_guarded",
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
            for process in redis_processes:
                process.terminate()
                process.wait(timeout=10)
            result["cleanup"]["private_redis_stopped"] = all(
                process.poll() is not None for process in redis_processes)
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        target = args.evidence.resolve()
        if not target.parent.is_dir():
            raise RuntimeError("evidence parent must already exist")
        target.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
