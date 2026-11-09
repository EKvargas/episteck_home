"""B11 Home-down probe (stdlib only). Runs INSIDE a throwaway Finance container started from
the live image with --network none, an empty temp DB, a throwaway pepper and
HOME_CONTROL_PLANE_URL=http://127.0.0.1:9999. The API (9935) and MCP (9936) run in the same
container. This script plays a broken Home on 9999 and checks that Finance never answers
with data: 503 / service_unavailable for an outage, 401 / session_invalid for a Home 401.

Output: status codes, fixed refusal codes, booleans and seconds. Nothing else.
"""
import http.client
import http.server
import json
import socket
import threading
import time

API, MCP, HOME = 9935, 9936, 9999
DLG = {"X-Episteck-Delegation": "b11-homedown-probe"}


def wait_port(port, seconds=40):
    end = time.time() + seconds
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        except OSError:
            time.sleep(0.5)
    return False


def api(path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", API, timeout=20)
    t = time.time()
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    body = r.read().decode("utf-8", "replace")
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    out = {"http": r.status, "s": round(time.time() - t, 1)}
    if isinstance(data, dict):
        out["detail"] = data.get("detail")
        out["has_accounts"] = "accounts" in data
    return out


def _sse_json(text):
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:") and line[5:].strip().startswith("{"):
            return json.loads(line[5:].strip())
    return None


def mcp_call(headers):
    session, n = None, 0

    def post(method, params=None, notify=False):
        nonlocal session, n
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            n += 1
            msg["id"] = n
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        h.update(headers)
        if session:
            h["mcp-session-id"] = session
        c = http.client.HTTPConnection("127.0.0.1", MCP, timeout=20)
        c.request("POST", "/mcp", body=json.dumps(msg), headers=h)
        r = c.getresponse()
        text = r.read().decode("utf-8", "replace")
        session = r.getheader("mcp-session-id") or session
        return r.status, (_sse_json(text) if text else None)

    st, _ = post("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "b11-homedown", "version": "1"}})
    if st != 200:
        return {"init_http": st}
    post("notifications/initialized", notify=True)
    t = time.time()
    st, body = post("tools/call", {"name": "finance_overview", "arguments": {}})
    out = {"http": st, "s": round(time.time() - t, 1)}
    res = (body or {}).get("result", {})
    data = res.get("structuredContent")
    if data is None:
        for part in res.get("content", []):
            if part.get("type") == "text":
                try:
                    data = json.loads(part["text"])
                except ValueError:
                    data = None
                break
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if isinstance(data, dict):
        out["error"] = data.get("error")
        out["ok"] = data.get("ok")
        out["has_accounts"] = "accounts" in data
    if "error" in (body or {}):
        out["jsonrpc_error"] = True
    return out


def p(label, value):
    print(f"{label}: {json.dumps(value, sort_keys=True)}", flush=True)


def check(label):
    p(f"{label} | API  /overview", api("/overview", DLG))
    p(f"{label} | API  /overview?valuation_currency=EUR", api("/overview?valuation_currency=EUR", DLG))
    p(f"{label} | MCP  finance_overview", mcp_call(DLG))


def fake_home(status, body):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            raw = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", HOME), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    p("H0 API and MCP up", {"api": wait_port(API), "mcp": wait_port(MCP)})
    p("H0 API /health", api("/health"))
    p("H1 no delegation | API  /overview", api("/overview"))
    p("H1 no delegation | MCP  finance_overview", mcp_call({}))

    check("H2 Home refused (nothing on 9999)")

    hang = socket.socket()
    hang.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    hang.bind(("127.0.0.1", HOME))
    hang.listen(16)  # accepts the TCP connection, never answers
    check("H3 Home hangs (no reply, 3 s timeout)")
    hang.close()

    for label, status, body in (
        ("H4 Home HTTP 500", 500, '{"exc": "boom"}'),
        ("H5 Home 200 malformed", 200, '{"message": {"unexpected": true}}'),
        ("H6 Home 401 (control: session invalid)", 401, '{"exc_type": "AuthenticationError"}'),
    ):
        srv = fake_home(status, body)
        check(label)
        srv.shutdown()
        srv.server_close()


main()
