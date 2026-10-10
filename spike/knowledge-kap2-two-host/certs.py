"""Generate one-run mTLS identities for the disposable KAP-2 two-host probe."""

from __future__ import annotations

import argparse
import ipaddress
import os
import subprocess
from pathlib import Path


def _openssl(*args: str) -> None:
    result = subprocess.run(["openssl", *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"openssl failed: {result.stderr[-1000:]}")


def generate(out: Path, server_ip: str, *, local: bool = False) -> None:
    address = ipaddress.ip_address(server_ip)
    if local:
        if address != ipaddress.ip_address("127.0.0.1"):
            raise ValueError("local certificates require loopback")
    elif address not in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("server certificate requires a literal Tailscale IPv4 address")
    if out.exists():
        raise FileExistsError("certificate directory must be new")
    out.mkdir(mode=0o700, parents=False)
    (out / "KAP2_PR71_CERTS").write_text("disposable mTLS identities only\n",
                                         encoding="ascii")
    try:
        _openssl("genpkey", "-algorithm", "ED25519", "-out", str(out / "ca.key"))
        _openssl("req", "-x509", "-new", "-key", str(out / "ca.key"),
                 "-out", str(out / "ca.crt"), "-days", "2",
                 "-subj", "/CN=kap2-pr71-disposable-ca")
        for serial, (name, cn, usage) in enumerate((
            ("server", "kap2-witness-probe", "serverAuth"),
            ("serving", "kap2-home-serving", "clientAuth"),
            ("recovery", "kap2-home-recovery", "clientAuth"),
        ), 1):
            key, csr, cert = out / f"{name}.key", out / f"{name}.csr", out / f"{name}.crt"
            _openssl("genpkey", "-algorithm", "ED25519", "-out", str(key))
            _openssl("req", "-new", "-key", str(key), "-out", str(csr),
                     "-subj", f"/CN={cn}")
            extension = out / f"{name}.ext"
            extension.write_text(f"extendedKeyUsage={usage}\n" +
                                 (f"subjectAltName=IP:{server_ip}\n" if name == "server" else ""),
                                 encoding="ascii")
            _openssl("x509", "-req", "-in", str(csr), "-CA", str(out / "ca.crt"),
                     "-CAkey", str(out / "ca.key"), "-set_serial", str(serial),
                     "-out", str(cert), "-days", "2", "-extfile", str(extension))
            csr.unlink()
            extension.unlink()
        for key in out.glob("*.key"):
            os.chmod(key, 0o600)
        _openssl("verify", "-CAfile", str(out / "ca.crt"),
                 str(out / "server.crt"), str(out / "serving.crt"),
                 str(out / "recovery.crt"))
    except Exception:
        # Leave files for explicit inspected cleanup; never hide partial key creation.
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--server-ip", required=True)
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    generate(args.out, args.server_ip, local=args.local)
    print("disposable mTLS identities created and verified")


if __name__ == "__main__":
    main()
