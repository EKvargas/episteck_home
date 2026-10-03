"""Disposable synthetic WSGI endpoint for the private Home transport seam."""

from __future__ import annotations

import hashlib
import time
from functools import lru_cache
from typing import Callable, Iterable


@lru_cache(maxsize=8)
def _body(size: int) -> bytes:
    prefix, suffix = b'{"ok":true,"pad":"', b'"}'
    remaining = size - len(prefix) - len(suffix)
    if remaining < 0 or size > 16_384:
        raise ValueError("invalid synthetic response size")
    blocks = []
    index = 0
    while sum(map(len, blocks)) < remaining:
        blocks.append(hashlib.sha256(f"transport-{index}".encode()).hexdigest().encode())
        index += 1
    return prefix + b"".join(blocks)[:remaining] + suffix


def application(environ: dict, start_response: Callable) -> Iterable[bytes]:
    arrived = time.perf_counter_ns()
    if environ.get("PATH_INFO") != "/probe" or environ.get("REQUEST_METHOD") != "POST":
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]
    length = int(environ.get("CONTENT_LENGTH") or "0")
    if not 0 < length <= 16_384:
        start_response("400 Bad Request", [("Content-Length", "0")])
        return [b""]
    request_body = environ["wsgi.input"].read(length)
    received = time.perf_counter_ns()
    if len(request_body) != length or not request_body.startswith(b'{"pad":"'):
        start_response("400 Bad Request", [("Content-Length", "0")])
        return [b""]
    size = int(environ.get("HTTP_X_RESPONSE_BYTES") or "0")
    try:
        response_body = _body(size)
    except ValueError:
        start_response("400 Bad Request", [("Content-Length", "0")])
        return [b""]
    app_end = time.perf_counter_ns()
    start_response(
        "200 OK",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(response_body))),
            ("X-Probe-Server-Receive-Ns", str(received - arrived)),
            ("X-Probe-App-Ns", str(app_end - received)),
        ],
    )
    return [response_body]
