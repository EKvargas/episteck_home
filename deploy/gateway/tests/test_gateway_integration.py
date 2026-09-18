"""Black-box nginx harness for the gateway when an isolated nginx is installed."""
from __future__ import annotations

import http.client
import os
import shutil
import socket
import socketserver
import subprocess
import threading
import time
from pathlib import Path

import pytest


NGINX = shutil.which("nginx")
pytestmark = pytest.mark.skipif(NGINX is None, reason="isolated nginx binary unavailable")
CONFIG_SOURCE = Path(__file__).resolve().parents[1] / "nginx-mcp-gateway.conf"


class _HTTPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data = b""
        self.request.settimeout(2)
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(65536)
            if not chunk:
                return
            data += chunk
        header_bytes, body = data.split(b"\r\n\r\n", 1)
        lines = header_bytes.decode("iso-8859-1").split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        while len(body) < length:
            body += self.request.recv(length - len(body))
        self.server.requests.append((method, path, headers, body))
        status, response_headers, response_body = self.server.response(self.server.requests[-1])
        payload = f"HTTP/1.1 {status}\r\n".encode()
        for key, value in response_headers.items():
            payload += f"{key}: {value}\r\n".encode()
        payload += f"Content-Length: {len(response_body)}\r\nConnection: close\r\n\r\n".encode()
        self.request.sendall(payload + response_body)


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, response):
        super().__init__(("127.0.0.1", 0), _HTTPHandler)
        self.response = response
        self.requests = []


if hasattr(socketserver, "UnixStreamServer"):

    class _UnixMint(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

        def __init__(self, path):
            self.counter = 0
            self.requests = []
            super().__init__(str(path), _HTTPHandler)

        def response(self, request):
            self.counter += 1
            token = f"delegation-{self.counter}"
            return 204, {"X-Episteck-Delegation": token}, b""

else:  # pragma: no cover - module collection must still work on Windows.

    class _UnixMint:
        def __init__(self, path):
            pytest.skip("Unix socket harness unavailable on this platform")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def gateway(tmp_path):
    mint_path = tmp_path / "mint.sock"
    mint = _UnixMint(mint_path)
    mint_thread = threading.Thread(target=mint.serve_forever, daemon=True)
    mint_thread.start()

    upstream = _Server(lambda request: (200, {"Content-Type": "application/json"}, b"ok"))
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    listen_port = _free_port()
    prefix = tmp_path / "prefix"
    (prefix / "conf").mkdir(parents=True)
    (prefix / "logs").mkdir()
    config = CONFIG_SOURCE.read_text(encoding="utf-8")
    config = config.replace(str(mint_path), str(mint_path))
    config = config.replace("127.0.0.1:9934", f"127.0.0.1:{listen_port}")
    config = config.replace("127.0.0.1:9931", f"127.0.0.1:{upstream.server_address[1]}")
    config = config.replace("127.0.0.1:9932", f"127.0.0.1:{upstream.server_address[1]}")
    config = config.replace("/var/lib/episteck-mcp-gateway/access.log", str(prefix / "logs/access.log"))
    config = config.replace("/var/lib/episteck-mcp-gateway/error.log", str(prefix / "logs/error.log"))
    conf = prefix / "conf" / "gateway.conf"
    conf.write_text(config, encoding="utf-8")
    proc = subprocess.Popen([NGINX, "-c", str(conf), "-p", str(prefix), "-g", "daemon off;"])
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", listen_port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        yield listen_port, mint, upstream
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        mint.shutdown()
        mint.server_close()
        upstream.shutdown()
        upstream.server_close()


def _request(port: int, body: bytes = b"{}", headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("POST", "/gateway/home/", body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


def test_one_mint_and_one_upstream_per_request_with_header_controls(gateway):
    port, mint, upstream = gateway
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer forged-machine",
        "Cookie": "forged=browser",
        "X-Episteck-Delegation": "forged-token",
        "Mcp-Session-Id": "session-123",
    }
    assert _request(port, b'{"jsonrpc":"2.0"}', headers)[0] == 200
    assert _request(port, b'{"jsonrpc":"2.0"}', headers)[0] == 200
    assert mint.counter == 2
    assert len(upstream.requests) == 2
    assert upstream.requests[0][2]["x-episteck-delegation"] == "delegation-1"
    assert upstream.requests[1][2]["x-episteck-delegation"] == "delegation-2"
    assert "authorization" not in upstream.requests[0][2]
    assert "cookie" not in upstream.requests[0][2]
    assert upstream.requests[0][2]["mcp-session-id"] == "session-123"
    assert upstream.requests[0][3] == b'{"jsonrpc":"2.0"}'


def test_batch_body_is_forwarded_unchanged_and_not_parsed(gateway):
    port, mint, upstream = gateway
    batch = b'[{"jsonrpc":"2.0","id":1},{"jsonrpc":"2.0","id":2}]'
    assert _request(port, batch, {"Content-Type": "application/json"})[0] == 200
    assert mint.counter == 1
    assert upstream.requests[0][3] == batch


def test_upstream_failure_is_not_retried(gateway):
    port, mint, upstream = gateway

    def fail(_request):
        upstream.shutdown_request = True
        return 500, {}, b"failure"

    upstream.response = fail
    status, _ = _request(port)
    assert status == 500
    assert mint.counter == 1
    assert len(upstream.requests) == 1
