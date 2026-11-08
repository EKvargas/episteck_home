"""B11 live probes for Olin Finance (stdlib only, run ON episteck-node1).

Modes (argv[1]):
  agent   run as home-agent: through the real gateway (allow, forged header, schema), and the
          direct 9936 bypass attempt (must be blocked by nftables).
  gateway run as svc-home-gateway: direct to finance-mcp 9936 with no delegation, and with one
          minted delegation used twice (replay must fail).
  expired run as svc-home-gateway: mint, wait past the 120 s TTL, then use it (must fail).

Output never contains an amount, a delegation, a token or a bank identifier: only status codes,
error codes, field names, account statuses, dates and booleans.
"""
import http.client
import json
import re
import socket
import sys
import time

GATEWAY = ("127.0.0.1", 9934, "/gateway/finance/")
DIRECT = ("127.0.0.1", 9936, "/mcp")
MINT_SOCK = "/run/episteck/home-bff-mint/mint.sock"
CODE = re.compile(r"\b[A-Z][A-Z_]{3,}\b")


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("home-bff-mint", timeout=10)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self._path)


def mint():
    c = UnixHTTPConnection(MINT_SOCK)
    c.request("POST", "/internal/mint_finance", headers={"Content-Length": "0"})
    r = c.getresponse()
    r.read()
    return r.status, r.getheader("X-Episteck-Delegation")


def _body(resp_text):
    """JSON-RPC message from a JSON or SSE response."""
    text = resp_text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data.startswith("{"):
                return json.loads(data)
    return None


class Mcp:
    def __init__(self, target, delegation=None):
        self.host, self.port, self.path = target
        self.delegation = delegation
        self.session = None
        self.n = 0

    def post(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session:
            h["mcp-session-id"] = self.session
        if self.delegation is not None:
            h["X-Episteck-Delegation"] = self.delegation
        c = http.client.HTTPConnection(self.host, self.port, timeout=30)
        c.request("POST", self.path, body=json.dumps(msg), headers=h)
        r = c.getresponse()
        text = r.read().decode("utf-8", "replace")
        self.session = r.getheader("mcp-session-id") or self.session
        return r.status, (_body(text) if text else None)

    def init(self):
        st, body = self.post("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "b11-probe", "version": "1"}})
        if st == 200:
            self.post("notifications/initialized", notify=True)
        return st, body


def summarize_tool(st, body):
    """Status-only summary of a tools/call result. Never prints a number other than dates."""
    if st != 200 or body is None:
        return {"http": st}
    if "error" in body:
        return {"http": st, "jsonrpc_error": CODE.findall(str(body["error"].get("message", "")))[:3]}
    res = body.get("result", {})
    data = res.get("structuredContent")
    if data is None:
        for part in res.get("content", []):
            if part.get("type") == "text":
                try:
                    data = json.loads(part["text"])
                except ValueError:
                    data = {"_text_codes": CODE.findall(part["text"])[:5]}
                break
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    out = {"http": st, "isError": bool(res.get("isError"))}
    if not isinstance(data, dict):
        return out
    out["keys"] = sorted(data)
    for k in ("error", "code", "status", "reason"):
        if isinstance(data.get(k), str):
            out[k] = data[k]
    accts = data.get("accounts")
    if isinstance(accts, list):
        rows = []
        for a in accts:
            if isinstance(a, dict):
                rows.append({
                    "account": a.get("account_id") or a.get("id"),
                    "currency": a.get("currency"),
                    "status": a.get("status"),
                    "has_figure": a.get("amount_minor") is not None,
                    "as_of": (a.get("as_of") or "")[:16] or None,
                })
        out["accounts"] = rows
    val = data.get("valuation")
    if isinstance(val, dict):
        out["valuation"] = {k: val.get(k) for k in ("currency", "rate_date", "stale_rates")
                            if k in val}
        out["valuation"]["has_total"] = any(
            val.get(k) is not None for k in ("total_minor", "total", "total_amount"))
    return out


def call_overview(target, delegation=None):
    m = Mcp(target, delegation)
    st, _ = m.init()
    if st != 200:
        return {"init_http": st}
    return summarize_tool(*m.post("tools/call", {"name": "finance_overview", "arguments": {}}))


def p(label, value):
    print(f"{label}: {json.dumps(value, sort_keys=True)}", flush=True)


def mode_agent():
    m = Mcp(GATEWAY)
    st, _ = m.init()
    p("G0 gateway initialize", {"http": st})
    st, body = m.post("tools/list", {})
    tools = (body or {}).get("result", {}).get("tools", [])
    p("G1 tools/list", [{"name": t.get("name"),
                         "args": sorted((t.get("inputSchema") or {}).get("properties", {}))}
                        for t in tools])
    p("G2 allow via gateway", summarize_tool(*m.post(
        "tools/call", {"name": "finance_overview", "arguments": {}})))
    p("G3 forged delegation header via gateway", call_overview(GATEWAY, "forged.delegation.value"))
    try:
        s = socket.create_connection(DIRECT[:2], timeout=5)
        s.close()
        p("G4 home-agent direct 9936", "CAN CONNECT (unexpected)")
    except OSError as exc:
        p("G4 home-agent direct 9936", f"CANNOT ({type(exc).__name__})")


def mode_gateway():
    p("D1 direct 9936, no delegation", call_overview(DIRECT, None))
    p("D2 direct 9936, garbage delegation", call_overview(DIRECT, "not-a-delegation"))
    st, dlg = mint()
    p("D3 mint", {"http": st, "got_delegation": bool(dlg)})
    if dlg:
        p("D3a first use", call_overview(DIRECT, dlg))
        p("D3b replay of the same delegation", call_overview(DIRECT, dlg))
    del dlg


def mode_expired():
    st, dlg = mint()
    p("E1 mint", {"http": st, "got_delegation": bool(dlg)})
    if dlg:
        time.sleep(130)
        p("E2 use after 130 s (TTL 120 s)", call_overview(DIRECT, dlg))
    del dlg


if __name__ == "__main__":
    {"agent": mode_agent, "gateway": mode_gateway, "expired": mode_expired}[sys.argv[1]]()
