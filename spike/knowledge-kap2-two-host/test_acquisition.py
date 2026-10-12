"""Local filesystem fixtures for the acquisition script's package checks.

No package download, extraction, wrapper creation or database startup is run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def prefix(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    for name in ("sbin/mariadbd", "bin/mariadb", "bin/mariadb-admin",
                 "bin/mariadb-install-db"):
        path = root / "usr" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o700)
    (root / "usr/lib/mysql/plugin").mkdir(parents=True)
    return root


def package_checks(prefix: Path) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).with_name("acquire_mariadb.sh").read_text()
    # Execute the actual contiguous check block against a local fixture prefix.
    checks = script.split('test -x "$prefix/usr/sbin/mariadbd"', 1)[1]
    checks = 'test -x "$prefix/usr/sbin/mariadbd"' + checks.split('cat > ', 1)[0]
    return subprocess.run(["sh", "-eu"], input=checks, text=True,
                          capture_output=True, env={**os.environ, "prefix": str(prefix)})


def bootstrap_sql(prefix: Path, relative: str = "mariadb/mariadb_system_tables.sql") -> None:
    path = prefix / "usr/share" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("-- synthetic bootstrap SQL fixture\n")


def test_mariadb_11_8_layout_passes_without_share_mysql(prefix: Path) -> None:
    bootstrap_sql(prefix)
    result = package_checks(prefix)
    assert result.returncode == 0, result.stderr


def test_legacy_mysql_layout_does_not_substitute(prefix: Path) -> None:
    bootstrap_sql(prefix, "mysql/mysql_system_tables.sql")
    assert package_checks(prefix).returncode != 0


def test_missing_bootstrap_sql_fails(prefix: Path) -> None:
    assert package_checks(prefix).returncode != 0


def test_bootstrap_sql_directory_fails(prefix: Path) -> None:
    (prefix / "usr/share/mariadb/mariadb_system_tables.sql").mkdir(parents=True)
    assert package_checks(prefix).returncode != 0


def test_nonexecutable_server_fails(prefix: Path) -> None:
    bootstrap_sql(prefix)
    (prefix / "usr/sbin/mariadbd").chmod(0o600)
    assert package_checks(prefix).returncode != 0


def test_missing_plugin_directory_fails(prefix: Path) -> None:
    bootstrap_sql(prefix)
    (prefix / "usr/lib/mysql/plugin").rmdir()
    assert package_checks(prefix).returncode != 0
