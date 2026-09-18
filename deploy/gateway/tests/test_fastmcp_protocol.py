from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from importlib.metadata import version

from fastmcp import FastMCP


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_pinned_fastmcp_rejects_json_rpc_batch_arrays():
    assert version("fastmcp") == "4.0.3"
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
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    for _ in range(80):
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp",
                data=json.dumps(batch).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            urllib.request.urlopen(request, timeout=1)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            assert error.code == 400
            response = json.loads(body)
            assert response["jsonrpc"] == "2.0"
            assert response["id"] is None
            assert response["error"]["code"] == -32602
            message = response["error"]["message"]
            assert message.startswith("Validation error:")
            assert (
                "union[JSONRPCRequest,JSONRPCNotification,JSONRPCResponse,JSONRPCError]"
                in message
            )
            assert "input_type=list" in message
            return
        except Exception:
            time.sleep(0.1)
        else:
            raise AssertionError("FastMCP accepted a JSON-RPC batch array")
    raise AssertionError("FastMCP server did not become ready")
