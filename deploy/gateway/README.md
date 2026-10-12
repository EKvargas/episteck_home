# Dedicated MCP delegation gateway

This is a standalone nginx instance for the Home Agent only. It is not included
by public nginx and does not load `/etc/nginx/sites-enabled`. The system service
runs the master and workers as `svc-home-gateway` with supplementary group
`episteck-gw`; public nginx remains `www-data` and is not a member of that group.

The listener is loopback-only on `127.0.0.1:9934`. Home MCP is reached at
`/gateway/home/`, Nutrition at `/gateway/nutrition/` and Finance at `/gateway/finance/`
(`127.0.0.1:9936`); every upstream receives `/mcp`. Every request performs an `auth_request` mint through the BFF Unix socket.
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
allows only the rendered numeric `svc-home-gateway` UID to direct ports `9931`,
`9932` and `9936`. All other local sender UIDs are dropped for those destinations.
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

## Hermes shows "Home MCP not connected" (2026-10-10)

The gateway mints only while the BFF holds a live session bound to `home-agent-primary`.
Without one, every gateway request returns 401 and Hermes reports that no Home MCP server
is connected. The binding is claimed by an operator login at the **BFF**:
`https://bff.home.episteck.com/login`. Logging in at `home.episteck.com` does not create
a BFF session and does not help.

1. Open `https://bff.home.episteck.com/login` and sign in as the operator's Frappe user.
   The browser ends on JSON with `"status":"authenticated"` and a `runtime_binding` value.
2. Keep that session. Logging out releases the binding.
3. Re-run Hermes. A new login cannot replace another live owner (`already_bound`).

Verification: `gateway/home/` requests in the Home Agent's `agent.log` change from
`401 Unauthorized` to `200 OK`.

## B4: svc-finance route (Olin Finance I1)

**Nothing here is deployed by the B4 PR.** Merging only changes the repo. The OWNER
runs the steps below, in this order: BFF image first, then gateway conf + nft.
`/gateway/finance/` returns **502** until the Finance service (B6) listens on
`127.0.0.1:9936`; 502 (not 401) after the steps proves the mint worked.

What changes: `/internal/mint` accepts an optional `?audience=` limited to the fixed
list (`home-control-plane`, `svc-nutrition`, `svc-finance`), which must also be in the
runtime grant's `allowed_audiences`. The default (no parameter) is unchanged. The
gateway gets an internal `/__mint_finance` seam that always requests
`audience=svc-finance`, used only by `/gateway/finance/`. The client can never choose
the audience. Home and Nutrition still use `/__mint` (default audience).

Replace `<SHA>` with the merged `main` commit. All commands run from the owner shell.

### 1. BFF mint image (only `home-bff-mint` needs it)

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && sudo -n -u svc-home-bff env XDG_RUNTIME_DIR=/run/user/$(id -u svc-home-bff) podman build -f services/home-bff/Dockerfile -t localhost/episteck-home-bff:<SHA> /srv/episteck/build/episteck_home'
```

Prepare `/srv/episteck/build/episteck_home` at `<SHA>` first (clean `git archive`, see
`deploy/home-bff/README.md` section 2). Then back up and switch the mint Quadlet:

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && Q=/home/svc-home-bff/.config/containers/systemd/home-bff-mint.container && sudo -n cp -p $Q $Q.pre-b4 && sudo -n sed -i "s#^Image=.*#Image=localhost/episteck-home-bff:<SHA>#" $Q && sudo -n diff $Q.pre-b4 $Q; sudo -n -u svc-home-bff env XDG_RUNTIME_DIR=/run/user/$(id -u svc-home-bff) systemctl --user daemon-reload && sudo -n -u svc-home-bff env XDG_RUNTIME_DIR=/run/user/$(id -u svc-home-bff) systemctl --user restart home-bff-mint'
```

Rollback (byte-for-byte restore, then restart):

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && Q=/home/svc-home-bff/.config/containers/systemd/home-bff-mint.container && sudo -n cp -p $Q.pre-b4 $Q && sudo -n -u svc-home-bff env XDG_RUNTIME_DIR=/run/user/$(id -u svc-home-bff) systemctl --user daemon-reload && sudo -n -u svc-home-bff env XDG_RUNTIME_DIR=/run/user/$(id -u svc-home-bff) systemctl --user restart home-bff-mint'
```

Verify (read-only): unit active, socket still `svc-home-bff:episteck-gw 0660`.

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && sudo -n -u svc-home-bff env XDG_RUNTIME_DIR=/run/user/$(id -u svc-home-bff) systemctl --user is-active home-bff-mint; stat -c "%U:%G %a" /run/episteck/home-bff-mint/mint.sock'
```

### 2. Gateway conf (with `nginx -t` before reload)

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && C=/etc/episteck/mcp-gateway/nginx-mcp-gateway.conf && sudo -n cp -p $C $C.pre-b4 && curl -fsS https://raw.githubusercontent.com/EKvargas/episteck-delivery-workspace/<SHA>/deploy/gateway/nginx-mcp-gateway.conf | sudo -n tee $C.new >/dev/null && sudo -n nginx -t -c $C.new -p /etc/episteck/mcp-gateway/ && sudo -n install -m 0644 $C.new $C && sudo -n systemctl reload episteck-mcp-gateway'
```

If the repo is private, copy the file from a clean `git archive` of `<SHA>` instead of
`curl`. If `nginx -t` fails nothing is installed (`&&` chain); the live file is untouched.

Rollback:

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && C=/etc/episteck/mcp-gateway/nginx-mcp-gateway.conf && sudo -n cp -p $C.pre-b4 $C && sudo -n nginx -t -c $C -p /etc/episteck/mcp-gateway/ && sudo -n systemctl reload episteck-mcp-gateway'
```

### 3. nft (dedicated table only; never flush the global ruleset)

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && sudo -n nft list table inet episteck_gateway > /tmp/episteck-gateway.pre-b4.nft && curl -fsS https://raw.githubusercontent.com/EKvargas/episteck-delivery-workspace/<SHA>/deploy/gateway/episteck-gateway.nft -o /tmp/episteck-gateway.tpl && sh -c "sed s/__SVC_HOME_GATEWAY_UID__/$(id -u svc-home-gateway)/ /tmp/episteck-gateway.tpl > /tmp/episteck-gateway.rendered.nft" && sudo -n nft --check -f /tmp/episteck-gateway.rendered.nft && sudo -n nft delete table inet episteck_gateway && sudo -n nft -f /tmp/episteck-gateway.rendered.nft'
```

Rollback: `nft delete table inet episteck_gateway`, then load the previous ruleset
(`/tmp/episteck-gateway.pre-b4.nft` is a `nft list` dump and loads as-is; the previous
`main` template rendered with `render-nft.sh` is equivalent).

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && sudo -n nft delete table inet episteck_gateway && sudo -n nft -f /tmp/episteck-gateway.pre-b4.nft'
```

Verify (read-only): 9936 appears in the table and only the gateway UID is accepted.

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && sudo -n nft list table inet episteck_gateway | grep -E "9931|9936"; id -u svc-home-gateway'
```

### 4. End-to-end (read-only)

The mint seam works if `/gateway/finance/` returns 502 (grant ok, upstream not up yet),
not 401. Run as the Hermes user (`home-agent`, the only uid allowed to reach 9934):

```text
! ssh -F C:/Users/D064974/.ssh/config episteck-node1 'cd / && for p in home nutrition finance; do printf "%s " $p; sudo -n -u home-agent curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:9934/gateway/$p/; echo; done'
```

Expected after B4 and before B6: home/nutrition unchanged from before (MCP error codes,
not 401), finance `502`. A `401` on finance means the runtime grant lacks `svc-finance`
in `allowed_audiences` (re-issue the grant via the Home runtime-grant procedure) or the
BFF image is not the B4 one. A `404` means the new conf is not loaded.
