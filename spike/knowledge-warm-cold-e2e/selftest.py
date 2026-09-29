"""Local functional smoke test; never acceptance latency evidence."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from argparse import Namespace
from pathlib import Path

from provision import create
from runner import SCENARIOS, prepare_database, run_one


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="knowledge-e2e-selftest-") as temporary:
        base = Path(temporary)
        root = base / "identity"
        create(root)
        db = base / "knowledge.sqlite"
        prepare_database(db)
        processes = []
        try:
            for mode, port in (("home", 18543), ("domain", 18544)):
                command = [sys.executable, str(Path(__file__).with_name("responders.py")), mode,
                           "--root", str(root), "--bind", "127.0.0.1", "--port", str(port)]
                if mode == "domain":
                    command += ["--db", str(base / "domain.sqlite")]
                processes.append(subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.PIPE))
            time.sleep(1)
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(process.stderr.read().decode())
            checks = {}
            for scenario in SCENARIOS:
                args = Namespace(root=str(root), db=str(db), home_host="127.0.0.1",
                                 home_port=18543, domain_port=18544, git_sha="selftest",
                                 scenario=scenario, classification="warm", iteration=0,
                                 home_count_start=0)
                row = run_one(args)
                if not row["success"]:
                    raise AssertionError((scenario, row))
                if row["counters"]["home_auth_round_trip_count"] != 2:
                    raise AssertionError((scenario, row["counters"]))
                if row["counters"]["domain_call_count"] != len(SCENARIOS[scenario]):
                    raise AssertionError((scenario, row["counters"]))
                checks[scenario] = row["counters"]
            print(json.dumps({"local_smoke_passed": True, "counters": checks}, sort_keys=True))
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                process.wait(timeout=5)
                process.stderr.close()
            # Windows can retain the SQLite file handle briefly after a child exits.
            time.sleep(0.5)


if __name__ == "__main__":
    main()
