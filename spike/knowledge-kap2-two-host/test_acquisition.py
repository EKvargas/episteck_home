"""Local fixtures for the acquisition script's package and help checks.

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


def help_check(tmp_path: Path, output: str, status: int) -> subprocess.CompletedProcess[str]:
    executable = tmp_path / "mariadb-install-db"
    executable.write_text(
        '#!/bin/sh\n[ "$#" -eq 1 ] && [ "$1" = --help ] || exit 99\n'
        'printf "%s\\n" "$HELP_OUTPUT"\nexit "$HELP_STATUS"\n'
    )
    executable.chmod(0o700)
    script = Path(__file__).with_name("acquire_mariadb.sh").read_text()
    # Run the actual final check, without downloading packages or running a DB.
    check = script.split("mariadb-admin --version\n", 1)[1]
    return subprocess.run(
        ["sh", "-eu"], input=check, text=True, capture_output=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
             "HELP_OUTPUT": output, "HELP_STATUS": str(status)},
    )


VALID_HELP = (
    "Usage: /private/usr/bin/mariadb-install-db [OPTIONS]\n"
    "  --auth-root-authentication-method=normal|socket\n"
    "  --datadir=path  The path to the MariaDB data directory."
)


def test_pinned_help_exit_one_with_usage_passes(tmp_path: Path) -> None:
    result = help_check(tmp_path, VALID_HELP, 1)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("status", [0, 2, 126, 127])
def test_unexpected_help_status_fails(tmp_path: Path, status: int) -> None:
    assert help_check(tmp_path, VALID_HELP, status).returncode != 0


@pytest.mark.parametrize("output", ["", "cannot find my_print_defaults",
                                    "Usage: incomplete",
                                    "Usage: /private/usr/bin/mariadb-install-db [OPTIONS]",
                                    "Usage: /private/usr/bin/mariadb-install-db [OPTIONS]\n"
                                    "--auth-root-authentication-method=normal|socket",
                                    "--auth-root-authentication-method=normal|socket\n--datadir"])
def test_exit_one_without_complete_help_fails(tmp_path: Path, output: str) -> None:
    assert help_check(tmp_path, output, 1).returncode != 0
