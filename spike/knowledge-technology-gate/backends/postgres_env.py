"""Detect (never provision) an already-available disposable PostgreSQL (correction 5).

This module does not install, start, configure, or modify any database, container
runtime, or host setting. It only checks what is ALREADY present and reachable.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresAvailability:
    available: bool
    reason: str
    dsn: str | None = None
    version: str | None = None


DEFAULT_DSN_ENV = "SPIKE_POSTGRES_DSN"


def detect_postgres() -> PostgresAvailability:
    """Detection order, per correction 5:
      1. Explicit DSN the operator already set (SPIKE_POSTGRES_DSN env var) pointing at
         an already-running disposable instance.
      2. A container runtime that is ALREADY up (docker/podman daemon reachable) AND
         already has a usable Postgres container running (we do not start one).
      3. Otherwise: NOT EXECUTED - ENVIRONMENT BLOCKED.
    """
    dsn = os.environ.get(DEFAULT_DSN_ENV)
    if dsn:
        ok, version_or_error = _try_connect(dsn)
        if ok:
            return PostgresAvailability(True, f"connected via ${DEFAULT_DSN_ENV}", dsn, version_or_error)
        return PostgresAvailability(
            False, f"${DEFAULT_DSN_ENV} set but connection failed: {version_or_error}"
        )

    daemon_up = _docker_daemon_reachable()
    if not daemon_up:
        return PostgresAvailability(
            False,
            "no SPIKE_POSTGRES_DSN set; no reachable container daemon "
            "(docker/podman info failed) -- spike does not start one",
        )

    running_pg = _find_running_postgres_container()
    if running_pg is None:
        return PostgresAvailability(
            False,
            "container daemon reachable but no already-running disposable PostgreSQL "
            "container found -- spike does not start one",
        )

    dsn = running_pg
    ok, version_or_error = _try_connect(dsn)
    if ok:
        return PostgresAvailability(True, "connected via already-running container", dsn, version_or_error)
    return PostgresAvailability(False, f"found container but connection failed: {version_or_error}")


def _docker_daemon_reachable() -> bool:
    for binary in ("docker", "podman"):
        try:
            result = subprocess.run(
                [binary, "info"], capture_output=True, timeout=5, text=True
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


def _find_running_postgres_container() -> str | None:
    for binary in ("docker", "podman"):
        try:
            result = subprocess.run(
                [binary, "ps", "--filter", "ancestor=postgres", "--format", "{{.Ports}}"],
                capture_output=True, timeout=5, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return None  # found evidence of a container, but we do NOT auto-derive
                # connection details or credentials from it -- an operator must set
                # SPIKE_POSTGRES_DSN explicitly. Detection here is informational only.
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _try_connect(dsn: str) -> tuple[bool, str]:
    try:
        import psycopg
    except ImportError as e:
        return False, f"psycopg not installed: {e}"
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                (version,) = cur.fetchone()
                return True, version
    except Exception as e:  # noqa: BLE001 -- detection path, report and move on
        return False, str(e)


if __name__ == "__main__":
    result = detect_postgres()
    print(result)
