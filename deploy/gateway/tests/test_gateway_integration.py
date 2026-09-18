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
from concurrent.futures import ThreadPoolExecutor
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
        status, response_headers, response_body = self.server.response(
            self.server.requests[-1]
        )
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
            self.lock = threading.Lock()
            self.requests = []
            super().__init__(str(path), _HTTPHandler)

        def response(self, request):
            with self.lock:
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

    def upstream_response(_request):
        return 200, {
            "Content-Type": "application/json",
            "X-Episteck-Delegation": "should-never-reach-client",
        }, b"ok"

    home_upstream = _Server(upstream_response)
    home_thread = threading.Thread(target=home_upstream.serve_forever, daemon=True)
    home_thread.start()
    nutrition_upstream = _Server(upstream_response)
    nutrition_thread = threading.Thread(
        target=nutrition_upstream.serve_forever, daemon=True
    )
    nutrition_thread.start()
    retry_upstream = _Server(upstream_response)
    retry_thread = threading.Thread(target=retry_upstream.serve_forever, daemon=True)
    retry_thread.start()

    listen_port = _free_port()
    prefix = tmp_path / "prefix"
    (prefix / "conf").mkdir(parents=True)
    (prefix / "logs").mkdir()
    runtime = prefix / "runtime"
    runtime.mkdir()
    unavailable_port = _free_port()
    config = CONFIG_SOURCE.read_text(encoding="utf-8")
    config = config.replace(
        "/run/episteck/home-bff-mint/mint.sock", str(mint_path)
    )
    config = config.replace("/run/episteck-mcp-gateway", str(runtime))
    config = config.replace("127.0.0.1:9934", f"127.0.0.1:{listen_port}")
    config = config.replace(
        "127.0.0.1:9931", f"127.0.0.1:{nutrition_upstream.server_address[1]}"
    )
    config = config.replace(
        "127.0.0.1:9932", f"127.0.0.1:{home_upstream.server_address[1]}"
    )
    home_proxy = f"proxy_pass http://127.0.0.1:{home_upstream.server_address[1]}/mcp;"
    config = config.replace(home_proxy, "proxy_pass http://home_test_backend/mcp;")
    home_start = config.index("        location /gateway/home/ {")
    home_end = config.index(
        "\n        }\n\n        location /gateway/nutrition/", home_start
    ) + len("\n        }")
    retry_location = config[home_start:home_end].replace(
        "location /gateway/home/", "location /gateway/retry-proof/", 1
    ).replace("home_test_backend", "retry_test_backend", 1)
    config = config[:home_start] + retry_location + "\n\n" + config[home_start:]
    config = config.replace(
        "http {",
        "http {\n"
        "    upstream home_test_backend {\n"
        f"        server 127.0.0.1:{home_upstream.server_address[1]};\n"
        f"        server 127.0.0.1:{retry_upstream.server_address[1]} backup;\n"
        "    }\n"
        "    upstream retry_test_backend {\n"
        f"        server 127.0.0.1:{unavailable_port};\n"
        f"        server 127.0.0.1:{retry_upstream.server_address[1]} backup;\n"
        "    }",
        1,
    )
    config = config.replace(
        "/var/lib/episteck-mcp-gateway/access.log", str(prefix / "logs/access.log")
    )
    config = config.replace(
        "/var/lib/episteck-mcp-gateway/error.log", str(prefix / "logs/error.log")
    )
    conf = prefix / "conf" / "gateway.conf"
    conf.write_text(config, encoding="utf-8")
    proc = subprocess.Popen(
        [NGINX, "-c", str(conf), "-p", str(prefix), "-g", "daemon off;"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(50):
            if proc.poll() is not None:
                _, stderr = proc.communicate()
                pytest.fail(f"nginx exited during startup: {stderr}")
            try:
                with socket.create_connection(("127.0.0.1", listen_port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("nginx did not open the gateway listener")
        yield listen_port, mint, home_upstream, nutrition_upstream, retry_upstream
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        mint.shutdown()
        mint.server_close()
        home_upstream.shutdown()
        home_upstream.server_close()
        nutrition_upstream.shutdown()
        nutrition_upstream.server_close()
        retry_upstream.shutdown()
        retry_upstream.server_close()


def _request(
    port: int, path: str = "/gateway/home/", body: bytes = b"{}", headers=None
):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("POST", path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, response_headers, payload


def test_one_mint_and_one_upstream_per_request_with_header_controls(gateway):
    port, mint, home, nutrition, retry = gateway
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer forged-machine",
        "Cookie": "forged=browser",
        "X-Episteck-Delegation": "forged-token",
        "Mcp-Session-Id": "session-123",
    }
    first = _request(port, body=b'{"jsonrpc":"2.0"}', headers=headers)
    second = _request(port, body=b'{"jsonrpc":"2.0"}', headers=headers)
    assert first[0] == 200
    assert second[0] == 200
    assert mint.counter == 2
    assert len(home.requests) == 2
    assert len(nutrition.requests) == 0
    assert len(retry.requests) == 0
    assert home.requests[0][2]["x-episteck-delegation"] == "delegation-1"
    assert home.requests[1][2]["x-episteck-delegation"] == "delegation-2"
    assert "authorization" not in home.requests[0][2]
    assert "cookie" not in home.requests[0][2]
    assert home.requests[0][2]["mcp-session-id"] == "session-123"
    assert home.requests[0][3] == b'{"jsonrpc":"2.0"}'
    assert "x-episteck-delegation" not in first[1]
    assert "x-episteck-delegation" not in second[1]


def test_nutrition_path_mints_once_and_hides_delegation_response(gateway):
    port, mint, home, nutrition, retry = gateway
    status, response_headers, _ = _request(port, path="/gateway/nutrition/")
    assert status == 200
    assert mint.counter == 1
    assert len(home.requests) == 0
    assert len(nutrition.requests) == 1
    assert len(retry.requests) == 0
    assert nutrition.requests[0][2]["x-episteck-delegation"] == "delegation-1"
    assert "x-episteck-delegation" not in response_headers


def test_concurrent_requests_receive_distinct_delegations(gateway):
    port, mint, home, nutrition, retry = gateway
    count = 8
    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(lambda _: _request(port), range(count)))
    assert all(status == 200 for status, _, _ in results)
    assert mint.counter == count
    assert len(home.requests) == count
    assert len(nutrition.requests) == 0
    assert len(retry.requests) == 0
    delegations = {
        request[2]["x-episteck-delegation"] for request in home.requests
    }
    assert len(delegations) == count
    assert all("x-episteck-delegation" not in headers for _, headers, _ in results)


def test_batch_body_is_forwarded_unchanged_and_not_parsed(gateway):
    port, mint, home, nutrition, retry = gateway
    batch = b'[{"jsonrpc":"2.0","id":1},{"jsonrpc":"2.0","id":2}]'
    result = _request(port, body=batch, headers={"Content-Type": "application/json"})
    assert result[0] == 200
    assert mint.counter == 1
    assert home.requests[0][3] == batch
    assert len(nutrition.requests) == 0
    assert len(retry.requests) == 0


def test_upstream_failure_is_not_retried(gateway):
    port, mint, home, nutrition, retry = gateway
    status, _, _ = _request(port, path="/gateway/retry-proof/")
    assert status == 502
    assert mint.counter == 1
    assert len(home.requests) == 0
    assert len(nutrition.requests) == 0
    assert len(retry.requests) == 0
