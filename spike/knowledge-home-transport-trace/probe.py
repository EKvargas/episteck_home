"""Disposable mTLS HTTP/1.1 transport probe; all request content is synthetic."""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import random
import socket
import ssl
import statistics
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "100.71.79.33"
PORT = 18463
DNS_NAME = "home-bench.invalid"
CASES = (
    ("small_split_off", 832, 112, "split", "split", "length", 0, 0, False),
    ("medium_split_off", 1297, 204, "split", "split", "length", 0, 0, False),
    ("large_split_off", 2222, 5036, "split", "split", "length", 0, 0, False),
    ("large_request_off", 2222, 112, "split", "split", "length", 0, 0, False),
    ("large_response_off", 832, 5036, "split", "split", "length", 0, 0, False),
    ("small_client_nodelay", 832, 112, "split", "split", "length", 1, 0, False),
    ("small_server_nodelay", 832, 112, "split", "split", "length", 0, 1, False),
    ("small_both_nodelay", 832, 112, "split", "split", "length", 1, 1, False),
    ("small_request_combined", 832, 112, "combined", "split", "length", 0, 0, False),
    ("small_response_combined", 832, 112, "split", "combined", "length", 0, 0, False),
    ("small_chunked", 832, 112, "split", "split", "chunked", 0, 0, False),
    ("small_fresh_tls", 832, 112, "split", "split", "length", 0, 0, True),
    ("large_fresh_tls", 2222, 5036, "split", "split", "length", 0, 0, True),
)


def certificates(root: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    root.mkdir(mode=0o700)
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic transport probe CA")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(hours=8))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                       key_encipherment=False, data_encipherment=False,
                                       key_agreement=False, key_cert_sign=True, crl_sign=True,
                                       encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    (root / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for label, san, eku in (
        ("server", x509.DNSName(DNS_NAME), ExtendedKeyUsageOID.SERVER_AUTH),
        ("client", x509.UniformResourceIdentifier("urn:episteck:synthetic:transport-probe"),
         ExtendedKeyUsageOID.CLIENT_AUTH),
    ):
        key = ec.generate_private_key(ec.SECP256R1())
        leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])
        cert = (x509.CertificateBuilder().subject_name(leaf_name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(hours=8))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                             key_encipherment=False, data_encipherment=False,
                                             key_agreement=False, key_cert_sign=False, crl_sign=False,
                                             encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.SubjectAlternativeName([san]), critical=False)
                .add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                               critical=False).sign(ca_key, hashes.SHA256()))
        (root / f"{label}.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file = root / f"{label}.key"
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                              serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        key_file.chmod(0o600)
    print(json.dumps({"created": True, "directory": str(root), "expires_utc":
                      (now + dt.timedelta(hours=8)).isoformat()}))


class Server(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:
        return

    def do_POST(self) -> None:
        started = time.time_ns()
        length = int(self.headers.get("Content-Length", "-1"))
        exact = self.path in ("/exact", "/mimic")
        mimic = self.path == "/mimic"
        if self.path not in ("/probe", "/exact", "/mimic") or not 0 <= length <= 8192:
            self.send_error(400)
            return
        request_id = self.headers.get("X-Probe-Id")
        if mimic:
            response_size = 82 if length == 250 else 0
        elif exact:
            response_size = {250: 82, 832: 112, 1297: 204, 2222: 387}.get(length, 0)
        else:
            response_size = int(self.headers["X-Response-Size"])
        response_write = self.headers["X-Response-Write"] if not exact else "legacy"
        framing = self.headers["X-Response-Framing"] if not exact else "length"
        if not exact:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY,
                                       int(self.headers["X-Server-Nodelay"]))
        body = self.rfile.read(length)
        body_read = time.time_ns()
        if exact:
            request_id = body[:12].decode("ascii")
        if len(body) != length or response_size not in (82, 112, 204, 387, 5036):
            self.send_error(400)
            return
        payload = (b'{"decisions":[{"allowed":true,"operation_id":"BENCH-BASELINE-OP-K"}],"revision":1}'
                   if mimic else b"S" * response_size)
        headers = (b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                   + (f"Content-Length: {response_size}\r\n".encode() if framing == "length"
                      else b"Transfer-Encoding: chunked\r\n")
                   + b"Connection: keep-alive\r\n\r\n")
        wire_body = (payload if framing == "length" else
                     f"{response_size:x}\r\n".encode() + payload + b"\r\n0\r\n\r\n")
        before_write = time.time_ns()
        if response_write == "legacy":
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if mimic else "application/octet-stream")
            self.send_header("Content-Length", str(response_size))
            self.end_headers()
            after_headers = time.time_ns()
            self.wfile.write(payload)
        elif response_write == "combined":
            self.connection.sendall(headers + wire_body)
            after_headers = before_write
        else:
            self.connection.sendall(headers)
            after_headers = time.time_ns()
            self.connection.sendall(wire_body)
        after_body = time.time_ns()
        self.server.log.write(json.dumps({"id": request_id, "started_ns": started,
            "body_read_ns": body_read, "before_write_ns": before_write,
            "after_headers_ns": after_headers, "after_body_ns": after_body,
            "request_bytes": length, "response_bytes": response_size,
            "server_nodelay": self.headers.get("X-Server-Nodelay", "default"),
            "response_write": response_write, "framing": framing}) + "\n")
        self.server.log.flush()


def serve(args: argparse.Namespace) -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(args.certs / "server.pem", args.certs / "server.key")
    context.load_verify_locations(args.certs / "ca.pem")
    context.verify_mode = ssl.CERT_REQUIRED
    server = Server((HOST, PORT), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    with args.log.open("a", encoding="utf-8", buffering=1) as server.log:
        print(json.dumps({"ready": True, "bind": HOST, "port": PORT}), flush=True)
        server.serve_forever()


def connection(context: ssl.SSLContext, nodelay: int) -> tuple[ssl.SSLSocket, float, float]:
    start = time.perf_counter_ns()
    tcp = socket.create_connection((HOST, PORT), timeout=5)
    tcp_ms = (time.perf_counter_ns() - start) / 1e6
    tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, nodelay)
    try:
        tls = context.wrap_socket(tcp, server_hostname=DNS_NAME)
    except BaseException:
        tcp.close()
        raise
    tls.settimeout(5)
    return tls, tcp_ms, (time.perf_counter_ns() - start) / 1e6


def exchange(sock: ssl.SSLSocket, case: tuple, round_number: int) -> dict:
    name, request_size, response_size, request_write, response_write, framing, \
        client_nodelay, server_nodelay, fresh = case
    request_id = uuid.uuid4().hex[:12]
    body = b"R" * request_size
    headers = (f"POST /probe HTTP/1.1\r\nHost: {DNS_NAME}\r\n"
               f"Content-Length: {request_size}\r\nX-Probe-Id: {request_id}\r\n"
               f"X-Response-Size: {response_size}\r\nX-Response-Write: {response_write}\r\n"
               f"X-Response-Framing: {framing}\r\nX-Server-Nodelay: {server_nodelay}\r\n"
               "Connection: keep-alive\r\n\r\n").encode()
    start = time.perf_counter_ns()
    if request_write == "combined":
        sock.sendall(headers + body)
        headers_sent = start
    else:
        sock.sendall(headers)
        headers_sent = time.perf_counter_ns()
        sock.sendall(body)
    sent = time.perf_counter_ns()
    data = b""
    first_read = None
    header_end = None
    response_header = b""
    while True:
        chunk = sock.recv(16384)
        if not chunk:
            raise ConnectionError("server closed before complete response")
        if first_read is None:
            first_read = time.perf_counter_ns()
        data += chunk
        if header_end is None and b"\r\n\r\n" in data:
            response_header, data = data.split(b"\r\n\r\n", 1)
            header_end = time.perf_counter_ns()
            if not response_header.startswith(b"HTTP/1.1 200 "):
                raise ValueError(response_header[:100])
        if header_end is not None:
            if framing == "length" and len(data) >= response_size:
                if data != b"S" * response_size:
                    raise ValueError("incorrect length-framed response")
                break
            if framing == "chunked" and data.endswith(b"\r\n0\r\n\r\n"):
                if data != f"{response_size:x}\r\n".encode() + b"S" * response_size + b"\r\n0\r\n\r\n":
                    raise ValueError("incorrect chunk-framed response")
                break
    end = time.perf_counter_ns()
    return {"case": name, "round": round_number, "id": request_id,
            "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "request_bytes": request_size, "response_bytes": response_size,
            "request_write": request_write, "response_write": response_write,
            "framing": framing, "client_nodelay": client_nodelay,
            "server_nodelay": server_nodelay, "fresh_tls": fresh,
            "request_ms": (end - start) / 1e6,
            "send_ms": (sent - start) / 1e6,
            "header_send_ms": (headers_sent - start) / 1e6,
            "wait_first_read_ms": (first_read - sent) / 1e6,
            "header_read_ms": (header_end - first_read) / 1e6,
            "body_read_ms": (end - header_end) / 1e6}


def run(args: argparse.Namespace) -> None:
    context = ssl.create_default_context(cafile=str(args.certs / "ca.pem"))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(args.certs / "client.pem", args.certs / "client.key")
    rng = random.Random(42)
    persistent: dict[str, ssl.SSLSocket] = {}
    for case in CASES:
        if not case[-1]:
            sock, _, _ = connection(context, case[6])
            persistent[case[0]] = sock
            exchange(sock, case, -1)  # warmup excluded
    try:
        with args.output.open("w", encoding="utf-8") as output:
            for round_number in range(args.rounds):
                cases = list(CASES)
                rng.shuffle(cases)
                for case in cases:
                    fresh = case[-1]
                    if fresh:
                        sock, tcp_ms, tls_ms = connection(context, case[6])
                    else:
                        sock = persistent[case[0]]
                        tcp_ms = tls_ms = None
                    try:
                        row = exchange(sock, case, round_number)
                        row["tcp_connect_ms"] = tcp_ms
                        row["tls_connect_ms"] = tls_ms
                        output.write(json.dumps(row) + "\n")
                        output.flush()
                    finally:
                        if fresh:
                            sock.close()
    finally:
        for sock in persistent.values():
            sock.close()
    print(json.dumps({"rows": args.rounds * len(CASES), "output": str(args.output)}))


def legacy_run(args: argparse.Namespace) -> None:
    """Match the earlier benchmark's http.client connection/request/read path."""
    context = ssl.create_default_context(cafile=str(args.certs / "ca.pem"))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(args.certs / "client.pem", args.certs / "client.key")
    exact = args.mode == "exact"
    sizes = ((("exact_baseline", 250, 82), ("exact_p1", 832, 112),
              ("exact_p2", 1297, 204), ("exact_p3", 2222, 387)) if exact else
             (("legacy_small", 832, 112), ("legacy_medium", 1297, 204),
              ("legacy_large", 2222, 5036), ("legacy_large_request", 2222, 112),
              ("legacy_large_response", 832, 5036)))
    connections = {}
    for name, _, _ in sizes:
        conn = http.client.HTTPSConnection(DNS_NAME, PORT, context=context, timeout=5)
        conn._create_connection = lambda address, timeout=5, source_address=None: socket.create_connection(
            (HOST, PORT), timeout=timeout, source_address=source_address)
        connections[name] = conn
    rng = random.Random(42)
    try:
        with args.output.open("w", encoding="utf-8") as output:
            for round_number in range(-1, args.rounds):
                ordered = list(sizes)
                rng.shuffle(ordered)
                for name, request_size, response_size in ordered:
                    conn = connections[name]
                    request_id = uuid.uuid4().hex[:12]
                    headers = {"Content-Type": "application/json"}
                    if not exact:
                        headers.update({"X-Probe-Id": request_id,
                                        "X-Response-Size": str(response_size),
                                        "X-Response-Write": "legacy", "X-Response-Framing": "length",
                                        "X-Server-Nodelay": "0"})
                    body_request = request_id.encode() + b"R" * (request_size - len(request_id))
                    start = time.perf_counter_ns()
                    conn.request("POST", "/exact" if exact else "/probe",
                                 body=body_request, headers=headers)
                    sent = time.perf_counter_ns()
                    response = conn.getresponse()
                    headers_read = time.perf_counter_ns()
                    body = response.read()
                    end = time.perf_counter_ns()
                    if response.status != 200 or body != b"S" * response_size:
                        raise ValueError(f"unexpected response: {response.status}, {len(body)} bytes")
                    if round_number >= 0:
                        output.write(json.dumps({"case": name, "round": round_number,
                            "id": request_id, "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                            "request_bytes": request_size, "response_bytes": response_size,
                            "request_ms": (end - start) / 1e6,
                            "send_ms": (sent - start) / 1e6,
                            "headers_read_ms": (headers_read - sent) / 1e6,
                            "body_read_ms": (end - headers_read) / 1e6}) + "\n")
                        output.flush()
    finally:
        for conn in connections.values():
            conn.close()
    print(json.dumps({"rows": args.rounds * len(sizes), "output": str(args.output)}))


def summarize(args: argparse.Namespace) -> None:
    rows = [json.loads(line) for line in args.output.read_text().splitlines()]
    result = {}
    for case in CASES:
        name = case[0]
        group = [row for row in rows if row["case"] == name]
        if len(group) != args.rounds:
            raise ValueError(f"{name}: expected {args.rounds}, found {len(group)}")
        result[name] = {key: {"median": round(statistics.median(values), 3),
                              "min": round(min(values), 3), "max": round(max(values), 3)}
                        for key in ("request_ms", "send_ms", "wait_first_read_ms",
                                    "header_read_ms", "body_read_ms", "tls_connect_ms")
                        if (values := [row[key] for row in group if row[key] is not None])}
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("certs", "server", "run", "legacy", "exact", "summary"))
    parser.add_argument("--certs", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=30)
    args = parser.parse_args()
    if args.mode == "certs":
        certificates(args.certs)
    elif args.mode == "server":
        serve(args)
    elif args.mode == "run":
        run(args)
    elif args.mode in ("legacy", "exact"):
        legacy_run(args)
    else:
        summarize(args)


if __name__ == "__main__":
    main()
