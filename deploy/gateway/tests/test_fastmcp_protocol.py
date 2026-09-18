from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

from fastmcp import FastMCP


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_pinned_fastmcp_rejects_json_rpc_batch_arrays():
    mcp = FastMCP("gateway-protocol-proof")

    @mcp.tool
    def probe() -> str:
        return "ok"

    port = _free_port()
    thread = threading.Thread(
        target=lambda: mcp.run(transport="http", host="127.0.0.1", port=port),
        daemon=True,
    )
    thread.start()
    for _ in range(80):
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp",
                data=json.dumps([]).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            urllib.request.urlopen(request, timeout=1)
        except urllib.error.HTTPError as error:
            assert error.code in {400, 406, 404, 405, 422}
            return
        except Exception:
            time.sleep(0.1)
        else:
            raise AssertionError("FastMCP accepted a JSON-RPC batch array")
    raise AssertionError("FastMCP server did not become ready")
