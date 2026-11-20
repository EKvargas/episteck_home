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

A second listener, `127.0.0.1:9937`, serves Ana's agent (ADR-0017): only `/gateway/home/` and
`/gateway/nutrition/`, no Finance route. Its mint stamps `X-Runtime-ID home-agent-ana`; port
9934 stamps `home-agent-primary`. In nftables only the `home-agent-ana` uid reaches 9937 and uid
`1003` stays on 9934 only; `render-nft.sh` resolves `id -u home-agent-ana` and fails if that
user does not exist. The rollout order is in `deploy/home-bff/README.md`.

## Installation staging (no runtime switch)

The service loads only the live path `/etc/episteck/mcp-gateway/nginx-mcp-gateway.conf`,
so any reload, restart or reboot serves whatever is there. Stage a new config next to it
and test the staging copy; never put an untested or not-yet-due config at the live path:

```bash
sudo install -D -m 0644 deploy/gateway/nginx-mcp-gateway.conf \
  /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new
sudo -u svc-home-gateway nginx -e /dev/stderr -t \
  -c /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new -p /etc/episteck/mcp-gateway/
```

First install only, the unit too:
`sudo install -D -m 0644 deploy/gateway/episteck-mcp-gateway.service /etc/systemd/system/episteck-mcp-gateway.service`.

Switch at the planned moment only (for the per-person rollout that is step 3.3 in
`deploy/home-bff/README.md`). Keep the previous file for rollback when one exists:

```bash
sudo cp -p /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf \
  /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.old
sudo install -m 0644 /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new \
  /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf
sudo -u svc-home-gateway nginx -e /dev/stderr -t \
  -c /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf -p /etc/episteck/mcp-gateway/
sudo systemctl reload episteck-mcp-gateway.service
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

### Run record (first run, 2026-11-20)

Result: **9 passed** (8 integration tests, including the 9937 forged-header and no-Finance
tests, plus the lifecycle test). The suite must run as an unprivileged user: as root the same
run gives 9 failures (500s from the workers, and the lifecycle test refuses root).

The node runs `nginx/1.28.3 (Ubuntu)` on Ubuntu 26.04. The dev machine's Docker daemon
(Rancher Desktop) was stopped, so the controller-approved fallback ran: WSL Ubuntu 24.04.3,
apt `nginx/1.24.0 (Ubuntu)`, pytest 7.4.4, repo read from `/mnt/c`, user `t`:

```bash
useradd -m t && su t -c 'python3 -m pytest -q -p no:cacheprovider \
  deploy/gateway/tests/test_gateway_integration.py deploy/gateway/tests/test_gateway_lifecycle.py'
```

The `ubuntu:26.04` container run is **still to do before step 3.3** of the per-person rollout.
The WSL run above does not satisfy that precondition. Command (same tests, the node's OS, run
as `t`):

```bash
docker run --rm -v "$(pwd -W):/src:ro" -w /src ubuntu:26.04 bash -c \
  "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx python3 python3-pytest >/dev/null \
   && useradd -m t && su t -c 'python3 -m pytest -q -p no:cacheprovider \
   deploy/gateway/tests/test_gateway_integration.py deploy/gateway/tests/test_gateway_lifecycle.py'"
```

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
There is no admin, health, root, shared-group, or `www-data` exception there.

The Finance API `127.0.0.1:9935` (B11 finding F1, 2026-11-15) is reachable only by
the rendered numeric `www-data` UID, because nginx serves the public PSD2 callback
(`/finance/connect/callback`). Every other local user is dropped, Hermes included.
Operator health checks therefore run as `www-data` (`bringup.sh verify` does).

After the coordinated runtime cutover, load only this table, and only through the
boot file and its unit (next section). Never run `nft -f` on the rendered file by hand:
that load does not survive a reboot, and on an existing table it appends duplicate
rules. Then run the real connection matrix as the actual Unix users:

```bash
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9934/gateway/home/
sudo -u svc-home-mcp curl --max-time 3 http://127.0.0.1:9934/gateway/home/
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9932/mcp
sudo -u svc-home-bff curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u svc-home-bff curl --max-time 3 http://127.0.0.1:9932/mcp
sudo -u svc-home-gateway curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u svc-home-gateway curl --max-time 3 http://127.0.0.1:9932/mcp
sudo -u www-data curl --max-time 3 http://127.0.0.1:9935/health
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9935/health
sudo -u home-agent-ana curl --max-time 3 http://127.0.0.1:9937/gateway/home/
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9937/gateway/home/
sudo -u home-agent-ana curl --max-time 3 http://127.0.0.1:9934/gateway/home/
```

Expected for `9935`: `www-data` gets the health JSON; `home-agent` times out (dropped).
Expected for `9937`: `home-agent-ana` gets an HTTP answer (401 until Ana grants); `home-agent`
times out (dropped), and so does `home-agent-ana` on `9934`.

### Persist at boot (2026-11-15)

Without this, a reboot drops the whole table (nothing else loads it, and the stock
`nftables.service` stays disabled because its `nftables.conf` flushes the ruleset,
which would wipe ufw). `episteck-gateway-nft.service` loads ONLY this table, before
`episteck-mcp-gateway.service`:

```bash
{ echo "table inet episteck_gateway"; echo "delete table inet episteck_gateway"; \
  cat /tmp/episteck-gateway-rendered.nft; } > /tmp/episteck-gateway-boot.nft
sudo install -d -m 0755 /etc/episteck/nft
sudo install -m 0644 /tmp/episteck-gateway-boot.nft /etc/episteck/nft/episteck-gateway.nft
sudo nft --check -f /etc/episteck/nft/episteck-gateway.nft
sudo install -m 0644 deploy/gateway/episteck-gateway-nft.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now episteck-gateway-nft.service
```

The `table …; delete table …` prefix makes every load an atomic replacement, so a
restart never duplicates rules. After any policy change: re-render, rebuild the boot
file with that prefix and `nft --check` it, replace `/etc/episteck/nft/episteck-gateway.nft`,
then `sudo systemctl restart episteck-gateway-nft.service` and check the result with
`sudo nft list table inet episteck_gateway`. For a coordinated change, stage the boot file
first as `/etc/episteck/nft/episteck-gateway.nft.new`, which the unit never loads, and
install it at the boot path in the window (the per-person rollout in
`deploy/home-bff/README.md` does this in step 3.1).

Expected: Hermes reaches `9934`; the ordinary alternate user is denied there;
Hermes and `svc-home-bff` are denied direct `9931/9932`; the gateway user reaches
both direct MCP ports (an MCP HTTP error is acceptable, connection refusal is
not). On rollback, restore the previous boot file and restart episteck-gateway-nft.service. Never delete the table at runtime (that drops every rule until the next boot) and never flush the global ruleset. The coordinated rollout in `deploy/home-bff/README.md` keeps the previous boot file as `/etc/episteck/nft/episteck-gateway.nft.old` before installing the new one; after restoring it, compare its sha256 with the recorded one.

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

Verification: the gateway's own access log (`/var/lib/episteck-mcp-gateway/access.log`) shows
`gateway/home/` requests changing from 401 to 200 (counts only), or, for Ana's agent, `ANA verify`
reports "the Home gateway answers HTTP <code>" other than 401. Hermes does not log its HTTP requests.
