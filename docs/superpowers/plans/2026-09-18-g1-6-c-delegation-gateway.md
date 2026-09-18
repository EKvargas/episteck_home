# G1.6 C — Nginx Delegation Gateway + BFF Runtime Binding

**Status:** PLAN — not implemented, not deployed
**Date:** 2026-09-18
**Repo state:** `main` @ `329e48e`, clean, in sync with origin
**Scope:** G1.6 **C** only. No G2, no new domains, no identity-architecture changes.

---

## 0. What this delivers

Hermes (uid 1003) stops holding any delegation concern. Every MCP request it makes is
minted a fresh, single-use, audience-bound delegation by the BFF, injected by nginx,
and proven server-side by the Home Control Plane.

```
Hermes uid 1003
  -> loopback nginx MCP gateway            (ingress: skuid 1003 only)
  -> auth_request  -> BFF internal mint    (unix socket, 0660 root:episteck-gw)
  -> BFF resolves FIXED runtime binding    (home-agent-primary -> live session)
  -> fresh delegation, new jti per request
  -> nginx OVERWRITES X-Episteck-Delegation
  -> Home MCP (9932) | Nutrition MCP (9931)
```

No model, prompt, or caller selects runtime id, Person, session, audience, delegation,
or actor. Hermes receives **no static credential**.

---

## 1. Evidence gathered before planning (read-only, on the real box)

All verified on Nuremberg `91.98.132.9`, 2026-09-18. Probe artifacts were removed and
the box was restored (`episteck-gw` group deleted, `www-data` membership reverted).

### 1.1 The mint boundary is achievable — PROVEN, not assumed

Your brief required proving how only nginx can reach a cookie-less mint endpoint
**before** exposing it. Preference 1 (OS/network UID) is **weaker than it appears here**:

> nginx workers run as **`www-data`, uid 33, no supplementary groups**
> (`/etc/nginx/nginx.conf:1` = `user www-data;`).

`www-data` is a shared, general-purpose web account. An `nft meta skuid 33` rule would
authorize *every* nginx vhost on this node, now and in future. So preference 2 (Unix
socket permissions) is the correct boundary here, and it was tested live:

```
SOCKET 0o660 uid 0 gid 1008(episteck-gw)
AS www-data:   CONNECT_OK            <- nginx, member of episteck-gw
AS home-agent: CONNECT_DENIED PermissionError   <- uid 1003, Hermes
```

This is a **permission boundary, not a filter rule**: the mint endpoint leaves the TCP
namespace entirely, so `home-agent` cannot reach it at all rather than being filtered.

### 1.2 Rootless podman does NOT break the socket (the thing that could have killed this)

Concern: a socket created inside a rootless container could surface on the host owned by
a subuid (`svc-home-bff` maps to `558752:65536`), which would be ungroupable by
`www-data`. Tested with the real deployed image:

```
container: bound inside container OK
host:      srw-rw---- 1 1007 1007 t.sock
```

Container-root maps to the **owning user (1007 = svc-home-bff)**, not a subuid. The
socket is therefore chown/chmod-able to `root:episteck-gw` from the host side.

### 1.3 Blocking deployment finding — the box is far behind `main`

| service | deployed image | contains G1.6 PRs #10–#13? |
| --- | --- | --- |
| nutrition, nutrition-mcp (:9930/:9931) | `episteck-nutrition:7af4cd8` | **NO** |
| home-mcp (:9932) | `episteck-home-mcp:243bede` | **NO** |
| home-bff (:9933) | `episteck-home-bff:3079cd1` | **NO** |
| `main` | `329e48e` | — |

`243bede` is the PR-#2 merge; `3079cd1` is PR #4. **The transport binding from #10/#11
is not running.** A gateway cutover onto these images would inject a header that no
running service reads — every person-scoped tool would fail closed. Rebuilding all three
is a **gated pre-step** (decision recorded 2026-09-18), in the same window, before cutover.

### 1.4 Other confirmed facts

- nftables has only `ip/ip6 filter|nat|mangle` (iptables-nft/ufw). A new `table inet`
  will not collide. `meta skuid` validated previously (`nft --check` exit 0).
- All app ports are `127.0.0.1`-only, but loopback is reachable by **every** local user —
  `home-agent` can hit `:9932`/`:9931`/`:9933` directly today. That is the bypass to close.
- `episteck` has `NOPASSWD: ALL` on this node.
- Only enabled nginx site is `home-bff.conf`; only `conf.d` entry is the log format.

### 1.5 Audience: ONE audience, not two

Both `home-mcp/client.py` and `nutrition/app/home_control/client.py` forward the **same**
delegation token straight to the Home Control Plane, whose `auth_hook` requires
`aud == "home-control-plane"` (`CONTROL_PLANE_AUDIENCE`). Nutrition's own API reads the
header only to pass it on; it never verifies it locally.

**Therefore the gateway mints `home-control-plane` for BOTH paths.** `AUDIENCE_NUTRITION`
stays defined but the gateway never mints it. Minting `svc-nutrition` for the nutrition
path would be rejected by the auth hook — this is the single most likely design mistake
and it is now closed by test.

---

## 2. What changes

```
services/home-bff/home_bff/runtime.py       NEW — runtime binding (atomic, 7 rules)
services/home-bff/home_bff/store.py         + runtime_binding table + atomic ops
services/home-bff/home_bff/app.py           + internal mint route; bind on callback
services/home-bff/home_bff/config.py        + mint socket path
services/home-bff/home_bff/__main__.py      + second uvicorn listener (uds)
deploy/home-bff/home-bff.container          + socket volume
deploy/gateway/nginx-mcp-gateway.conf       NEW
deploy/gateway/episteck-gateway.nft         NEW
deploy/gateway/README.md                    NEW — runbook incl. rebuild pre-step
services/home-bff/tests/test_runtime_binding.py   NEW
services/home-bff/tests/test_internal_mint.py     NEW
docs/architecture/G1_6_VALIDATION.md        + C section
```

`policy/access.py`, the Frappe `auth_hook`, `delegation.py`, `replay.py`, and every MCP
tool schema are **untouched**.

---

## 3. BFF runtime binding

`runtime_binding(runtime_id PK, session_id, bound_at)`. `RUNTIME_ID = "home-agent-primary"`
is a **module constant**; it is never accepted as request input anywhere.

All seven rules enforced atomically in **one** SQLite `IMMEDIATE` transaction, so two
concurrent logins cannot both win:

| # | Situation | Result |
| --- | --- | --- |
| 1 | no binding | authenticated session binds |
| 2 | same session rebinds | idempotent, success |
| 3 | bound to stale/expired/deleted session | may replace |
| 4 | bound to a **different LIVE** session | **MUST NOT replace** — auth succeeds, binding unchanged, response says already bound |
| 5 | logout of bound session | clears binding |
| 6 | session expiry | invalidates/clears binding |
| 7 | simultaneous bind attempts | exactly one winner |

Liveness is judged by joining `bff_session` (which already self-expires in
`get_session`), so rule 6 needs no separate sweep.

---

## 4. Internal mint endpoint

Served **only** on the Unix socket, never on `:9933`. Accepts **no** caller-selected
session, runtime, Person, actor, or audience — it takes no parameters at all.

```
POST (auth_request)  ->  resolve home-agent-primary
                     ->  resolve its live BFF session
                     ->  mint fresh delegation (aud=home-control-plane, new jti)
                     ->  204 No Content
                         X-Episteck-Delegation: <token>
                         Cache-Control: no-store
```

- Token returned **only** as a response header — never in a JSON body.
- Binding absent / stale / session revoked / expired → **401, fail closed**.
- The existing cookie-authenticated `POST /delegation` (which lets the caller choose an
  audience) is **left on `:9933` but stays `deny all` in the public vhost**, exactly as
  today. The gateway never uses it. *(Removing it is a separate change; noted, not done.)*

---

## 5. Nginx gateway

Loopback-only listener, ingress restricted to uid 1003 by nftables.

```
location /gateway/home/       -> 127.0.0.1:9932   (Home MCP)
location /gateway/nutrition/  -> 127.0.0.1:9931   (Nutrition MCP)
```

Per request, **no body parsing**:

1. `auth_request /__mint;` → `unix:/run/episteck/home-bff/mint.sock`
2. `auth_request_set $deleg $upstream_http_x_episteck_delegation;`
3. `proxy_set_header X-Episteck-Delegation $deleg;` — **overwrites** any inbound value
4. `proxy_set_header Authorization "";` — stripped
5. `proxy_set_header Cookie "";` — stripped
6. `Mcp-Session-Id` preserved (default header pass-through; explicitly asserted by test)
7. `proxy_next_upstream off;` — **no transparent replay** of a single-use delegation
8. `proxy_buffering off; proxy_http_version 1.1; proxy_read_timeout 300s;` for SSE
9. Delegation headers never logged (reuse `episteck_noqs` log format)

Mint-per-request is accepted: `tools/list` / `server/discover` receive a delegation that
is never presented to the Control Plane and expires unused. **Mint ≠ replay claim** —
the `jti` is only burned when `auth_hook` claims it.

---

## 6. Direct-bypass hardening

`table inet episteck_gateway`:

- gateway ingress port: `meta skuid 1003 accept`, else `drop`
- `127.0.0.1:9931`, `:9932`: allow the gateway's own uid + svc uids; `drop` uid 1003

Services stay fail-closed regardless; this makes the gateway the *intended single
transport path*. Applied **after** cutover is proven, as its own step.

---

## 7. Tests

**BFF (new, ~26):** all seven binding rules incl. a real threaded concurrency test
asserting exactly one winner; mint with no binding denies; mint produces a distinct `jti`
each call; no caller-selectable runtime/session/audience/actor (assert the route takes no
parameters); token absent from body and from `caplog`; **mint audience is
`home-control-plane`** (guards the §1.5 trap).

**Gateway (live, post-deploy):** only uid 1003 reaches ingress; forged inbound
`X-Episteck-Delegation` overwritten; `Authorization` stripped; `Cookie` stripped;
`Mcp-Session-Id` preserved; fresh token per request; `tools/list` works; `tools/call`
works; sequential calls → distinct tokens; concurrent calls → distinct tokens; upstream
failure does not replay; absent binding → denied; logout → next request denied.

**End-to-end:** browser login → binding → Hermes MCP call → gateway → fresh delegation →
MCP service → Control Plane → correct `machine_caller` + `human_actor` → business result.
Then logout → next operation **DENIED**.

Every security assertion is **mutation-tested**: revert the control, confirm the suite
goes red. (Per `g1-6-delegation-hardening`: a loop over a discovered collection must
assert a non-zero count, or it silently tests nothing.)

---

## 8. Deployment — STOP BEFORE CUTOVER

No incremental deploy into a mixed-trust state. One window:

```
STEP 0  rebuild + redeploy home-mcp, nutrition, home-bff @ <gateway SHA>   [GATED]
STEP 1  verify each container reports the new image
STEP 2  create episteck-gw, add www-data, socket dir via tmpfiles.d
STEP 3  install gateway vhost; nginx -t; reload
STEP 4  prove mint boundary live (www-data OK / home-agent DENIED)
STEP 5  cut Hermes MCP URLs over to the gateway
STEP 6  nftables ingress + bypass rules
```

Evidence to record: repo `main` SHA → built image tag → Quadlet `Image=` → running
container image → FastMCP server version → Hermes MCP client version → live MCP tool
schema.

**Rollback:** point Hermes back at `:9931`/`:9932`, disable the vhost, flush the nft
table. The BFF changes are additive and inert without the gateway.

**This plan stops here for architecture review. No production cutover.**
