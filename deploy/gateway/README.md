# Dedicated MCP delegation gateway

This is a standalone nginx instance for the Home Agent only. It is not included
by public nginx and does not load `/etc/nginx/sites-enabled`. The system service
runs the master and workers as `svc-home-gateway` with supplementary group
`episteck-gw`; public nginx remains `www-data` and is not a member of that group.

The listener is loopback-only on `127.0.0.1:9934`. Home MCP is reached at
`/gateway/home/` and Nutrition at `/gateway/nutrition/`; both upstreams receive
`/mcp`. Every request performs an `auth_request` mint through the BFF Unix socket.
The mint subrequest sends no inbound headers or body, and only its fresh
`X-Episteck-Delegation` response header is copied to the upstream request.

The upstream request deliberately overwrites `X-Episteck-Delegation`, strips
`Authorization` and `Cookie`, preserves `Mcp-Session-Id`, disables retries, and
uses HTTP/1.1 with buffering disabled and a 300-second read timeout. Delegation
response headers are hidden from the client on both upstream paths. The config does
not inspect JSON-RPC bodies; a protocol request is one proxied HTTP request. Access
logs use `$uri`, never the query string or delegation header.

The PID and nginx temporary paths live under the unit's
`RuntimeDirectory=/run/episteck-mcp-gateway`; access and error logs live under its
`StateDirectory=/var/lib/episteck-mcp-gateway`. The standalone instance does not need
write access to the public nginx prefix or default cache paths.

## Installation staging (no runtime switch)

```bash
sudo install -D -m 0644 deploy/gateway/nginx-mcp-gateway.conf \
  /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf
sudo install -D -m 0644 deploy/gateway/episteck-mcp-gateway.service \
  /etc/systemd/system/episteck-mcp-gateway.service
sudo nginx -t -c /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf \
  -p /etc/episteck/mcp-gateway/
```

The service is intentionally not started during implementation. At cutover,
verify `id svc-home-gateway`, `getent group episteck-gw`, and `id www-data` before
starting it. Confirm the worker UID, loopback bind, and socket access before
switching Hermes.

## Isolated integration harness

`deploy/gateway/tests/` contains config/mutation tests and a harness that starts a
fake Unix-socket mint plus instrumented upstreams when an isolated nginx binary is
available. It asserts one mint subrequest and one upstream request per client
request, fresh distinct delegation values, forged-header overwrite, credential
stripping, session-header preservation, response-header suppression, opaque body
forwarding, and no retry after upstream failure. A separate lifecycle test proves
start, unprivileged master/worker identity, reload, and graceful stop using the
dedicated PID path.
The real FastMCP 4.0.3 batch-array rejection test runs in the repository venv and
is kept separate from the Hermes client (`mcp 2.0.0` / `mcp-types 2.0.0`) environment.

## nftables OUTPUT policy

The dedicated table uses `meta skuid` in the local `OUTPUT` path. Render the
numeric gateway UID and syntax-check only the dedicated table; do not load it
during implementation:

```bash
./deploy/gateway/render-nft.sh deploy/gateway/episteck-gateway.nft \
  /tmp/episteck-gateway-rendered.nft
sudo nft --check -f /tmp/episteck-gateway-rendered.nft
```

The rendered policy allows uid `1003` (`home-agent`) to `127.0.0.1:9934`, and
allows only the rendered numeric `svc-home-gateway` UID to direct ports `9931`
and `9932`. All other local sender UIDs are dropped for those destinations.
There is no admin, health, root, shared-group, or `www-data` exception.

After the coordinated runtime cutover, apply only this table and run the real
connection matrix as the actual Unix users:

```bash
sudo nft -f /tmp/episteck-gateway-rendered.nft
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9934/gateway/home/
sudo -u svc-home-mcp curl --max-time 3 http://127.0.0.1:9934/gateway/home/
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9932/mcp
sudo -u svc-home-bff curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u svc-home-bff curl --max-time 3 http://127.0.0.1:9932/mcp
sudo -u svc-home-gateway curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u svc-home-gateway curl --max-time 3 http://127.0.0.1:9932/mcp
```

Expected: Hermes reaches `9934`; the ordinary alternate user is denied there;
Hermes and `svc-home-bff` are denied direct `9931/9932`; the gateway user reaches
both direct MCP ports (an MCP HTTP error is acceptable, connection refusal is
not). On test rollback delete only `table inet episteck_gateway`; never flush the
global nftables ruleset.
