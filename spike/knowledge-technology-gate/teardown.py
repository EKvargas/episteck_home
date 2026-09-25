"""Removes every artifact this spike creates. Disposable by construction (Phase-1 SS16.2).

Does NOT touch anything outside spike/knowledge-technology-gate/ -- no production state,
no host configuration, nothing installed by this spike (it never installed anything).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parent


def teardown() -> list[str]:
    removed: list[str] = []

    # Any SQLite files created by ad-hoc runs (bench/report_data/*.db, pytest tmp dirs are
    # cleaned by pytest itself and are outside this tree).
    for pattern in ("**/*.db", "**/*.db-wal", "**/*.db-shm", "**/*.sqlite", "**/*.sqlite3"):
        for f in SPIKE_ROOT.glob(pattern):
            f.unlink()
            removed.append(str(f))

    # __pycache__ directories.
    for pycache in SPIKE_ROOT.glob("**/__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
        removed.append(str(pycache))

    # If a PostgreSQL scratch schema was used, drop it too (best-effort; only if a
    # detected instance is reachable -- never provisions or touches anything else).
    try:
        sys.path.insert(0, str(SPIKE_ROOT))
        from backends.postgres_env import detect_postgres

        availability = detect_postgres()
        if availability.available:
            import psycopg

            with psycopg.connect(availability.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("DROP SCHEMA IF EXISTS spike_kn CASCADE")
                conn.commit()
            removed.append("postgres schema spike_kn (dropped)")
    except Exception as e:  # noqa: BLE001 -- teardown must not crash the report step
        print(f"Postgres teardown skipped/best-effort: {e}")

    return removed


if __name__ == "__main__":
    removed = teardown()
    print(f"Teardown complete. Removed {len(removed)} artifacts:")
    for r in removed:
        print(f"  - {r}")
