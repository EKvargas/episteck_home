"""Fail-closed preflight for the reviewed disposable two-host checkout."""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def verify(*, side: str, repo: Path, expected_sha: str, root: Path,
           cert_dir: Path, evidence_dir: Path, host: str, port: int,
           bench: Path | None = None) -> dict:
    if side not in {"home", "witness"}:
        raise ValueError("invalid side")
    if not (len(expected_sha) == 40 and all(c in "0123456789abcdef" for c in expected_sha)):
        raise ValueError("exact 40-character reviewed SHA required")
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ required")
    checks: dict[str, bool] = {}
    current = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
    checks["reviewed_sha"] = current == expected_sha
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout.strip()
    checks["checkout_clean"] = not status
    checks["source_isolated"] = repo.resolve() == Path("/tmp/kap2-pr71-src-01")
    checks["fixed_probe_port"] = port == 19442
    try:
        checks["private_witness_address"] = (
            ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10"))
    except ValueError:
        checks["private_witness_address"] = False
    checks["new_marked_root"] = (root.parent == Path("/tmp")
                                  and root.name == "kap2-pr71-twohost-01"
                                  and not root.exists())
    checks["evidence_outside_root"] = (
        evidence_dir.resolve() == Path("/tmp/kap2-pr71-twohost-evidence")
        and evidence_dir.is_dir()
        and (os.stat(evidence_dir).st_mode & 0o077) == 0
        and not evidence_dir.resolve().is_relative_to(root.resolve()))
    required = ("mariadbd", "mariadb", "mariadb-admin", "mariadb-install-db")
    checks["private_db_binaries"] = all(shutil.which(name) for name in required)
    names = ("server",) if side == "witness" else ("serving", "recovery")
    expected_certs = Path("/tmp/kap2-pr71-witness-certs-01" if side == "witness"
                          else "/tmp/kap2-pr71-home-certs-01")
    checks["isolated_cert_dir"] = cert_dir.resolve() == expected_certs
    required_files = [cert_dir / "ca.crt"]
    for name in names:
        required_files += [cert_dir / f"{name}.crt", cert_dir / f"{name}.key"]
    checks["certificate_inventory"] = (all(path.is_file() for path in required_files)
                                        and not (cert_dir / "ca.key").exists())
    checks["private_key_modes"] = all(
        (os.stat(cert_dir / f"{name}.key").st_mode & 0o077) == 0
        and os.stat(cert_dir / f"{name}.key").st_uid == os.getuid()
        for name in names if (cert_dir / f"{name}.key").exists())
    if side == "witness":
        tailnet = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                                 text=True) if shutil.which("tailscale") else None
        checks["verified_tailnet_bind"] = bool(
            tailnet is not None and tailnet.returncode == 0
            and host in tailnet.stdout.splitlines())
        try:
            with socket.socket() as check:
                check.bind((host, port))
            checks["tailnet_port_free"] = True
        except OSError:
            checks["tailnet_port_free"] = False
    else:
        checks["disposable_bench"] = bool(
            bench is not None and bench.resolve() == Path("/tmp/kap2-pr71-frappe-bench-01")
            and (bench / "apps" / "frappe").is_dir()
            and (bench / "env" / "bin" / "python").is_file()
            and (bench / "apps" / "episteck_home").resolve() ==
            repo.resolve() / "apps" / "episteck_home")
        version = subprocess.run(
            [str(bench / "env" / "bin" / "python"), "-c",
             "import frappe; print(frappe.__version__)"],
            capture_output=True, text=True) if checks["disposable_bench"] else None
        checks["frappe_15_99_0"] = bool(
            version is not None and version.returncode == 0
            and version.stdout.strip() == "15.99.0")
    return {"side": side, "checks": checks, "complete": all(checks.values()),
            "expected_sha": expected_sha}


def require(**kwargs) -> dict:
    result = verify(**kwargs)
    if not result["complete"]:
        failed = [name for name, passed in result["checks"].items() if not passed]
        raise RuntimeError("preflight failed: " + ",".join(failed))
    return result


if __name__ == "__main__":
    raise SystemExit("preflight is invoked by the two runners")
