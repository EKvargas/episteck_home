# G1.6 C — Delegation Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Status:** PLAN ONLY — not implemented, not deployed; revised for PR #14 architecture re-review

**Goal:** Route every Home Agent MCP HTTP request through a dedicated local gateway
that obtains a fresh, single-use Home Control Plane delegation from the BFF without
exposing identity or credential material to Hermes, the model, or shared public nginx.

**Architecture:** Hermes uid 1003 can reach one loopback-only gateway listener. A
dedicated nginx instance running as `svc-home-gateway` is the only group principal
allowed to connect to a BFF Unix mint socket. The mint endpoint is a separate ASGI app
served only on that socket and is structurally absent from the public BFF TCP app.
Public BFF and internal mint processes share SQLite through process-safe transactions.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, SQLite, rootless Podman + Quadlet,
nginx `auth_request`, nftables, FastMCP server `4.0.3`

**Spec:** `docs/architecture/adr/0009-trusted-actor-binding.md`,
`docs/architecture/proposals/G1_6_TRUSTED_IDENTITY.md`,
`docs/architecture/G1_6_VALIDATION.md`, and the blocking architecture review on PR #14

## Global Constraints

- Plan baseline: `main` at `329e48e`; implementation starts only after PR #14 is
  approved and merged.
- Fixed runtime id: `home-agent-primary`; no request may choose a runtime id.
- Exactly one live BFF session may own the runtime binding.
- The BFF is the sole delegation mint authority.
- The internal mint route must not be registered on the public/TCP ASGI app.
- Both Home MCP and Nutrition receive delegations with `aud=home-control-plane`.
  The gateway never mints `svc-nutrition`.
- Hermes/model receives no actor, Person identity, BFF cookie, BFF session id,
  delegation, `jti`, mint credential, or audience selector.
- One fresh delegation is minted for every gateway HTTP request. Protocol chatter may
  mint an unused delegation. Minting does not claim the replay id; the Control Plane
  claims it only when the delegation is presented there.
- The gateway does not parse JSON-RPC bodies. FastMCP rejects JSON-RPC batch arrays;
  one `tools/call` is one HTTP POST.
- The gateway overwrites inbound `X-Episteck-Delegation`, strips inbound
  `Authorization` and `Cookie`, preserves `Mcp-Session-Id`, disables proxy retries,
  and remains streaming/SSE safe.
- Direct Home MCP/Nutrition ports remain fail closed before nftables hardening because
  both services require a transport delegation.
- Existing cookie-authenticated public-app `POST /delegation` cleanup is out of scope.
- Server dependency: Home MCP and Nutrition pin **`fastmcp==4.0.3`**.
- Observed Hermes client environment: **`mcp 2.0.0` / `mcp-types 2.0.0`**. These are
  client dependencies and are separate from the FastMCP server dependency.
- Never install into or modify the user's shared/local FastMCP environment. All tests
  run in an isolated Python 3.11+ virtual environment or container built from repo
  dependencies.
- No live deployment occurs while implementing C. Deployment begins only after C is
  merged and all three images are built from the same final `main` SHA.
- If implementation or live staging evidence contradicts any boundary in this plan,
  stop before cutover and return to architecture review. Do not improvise a weaker
  design.

---

## 1. Required trust boundaries

```text
Hermes uid 1003
    -> nft OUTPUT rule: gateway listener allowed
    -> 127.0.0.1:9934 (dedicated nginx instance)
    -> nginx worker/master identity svc-home-gateway
    -> group-gated Unix socket
    -> BFF internal mint ASGI app

svc-home-gateway
    -> 127.0.0.1:9931 (Nutrition MCP)
    -> 127.0.0.1:9932 (Home MCP)

public nginx worker www-data uid 33
    -> 127.0.0.1:9933 (public BFF app only)
    X no membership in episteck-gw
    X no permission to connect to the mint socket

home-agent uid 1003
    X no mint-socket access
    X no direct MCP-port access after bypass closure
```

`svc-home-gateway` is a dedicated non-login service user. It runs a separate nginx
master/config/systemd service. The distribution nginx service and every public vhost
continue to run as `www-data`; their configuration is not included by the dedicated
gateway instance.

The `episteck-gw` group has exactly one supplementary member:
`svc-home-gateway`. `svc-home-bff` can manage the socket because it owns the socket and
directory, not because it is a group member. `www-data`, `home-agent`,
`svc-home-mcp`, and `svc-nutrition` are not members.

---

## 2. Evidence and corrections to the first plan

### 2.1 Confirmed current code

- `home_bff.app.create_app()` is currently the single public app and registers the
  existing browser-cookie `/delegation` route.
- `home_bff.__main__` currently serves that app only on TCP port 9933.
- `SessionStore` currently holds one long-lived SQLite connection and explicitly
  describes itself as suitable for one uvicorn process.
- Home MCP and Nutrition both pin `fastmcp==4.0.3`, read the delegation from the real
  FastMCP HTTP request context, and fail closed when it is absent.
- Nutrition uses each single-use delegation in exactly one Control Plane request per
  business operation.

Therefore the internal mint endpoint cannot be added to `app.py`, and adding a second
listener for the same app is forbidden. The store must also change before separate
public and mint processes may share the database.

### 2.2 Previous socket probe: useful but not sufficient

The read-only investigation proved that container root in the deployed rootless
Podman mapping creates a host socket owned by `svc-home-bff`, not a subuid. It did
**not** prove that supplementary groups propagate into the container, nor that the
final directory and socket retain the intended group/mode across restart.

The final design does not depend on group propagation into the container:

```text
/run/episteck/home-bff-mint/
    owner svc-home-bff
    group episteck-gw
    mode  2770 (setgid)

/run/episteck/home-bff-mint/mint.sock
    owner svc-home-bff
    group episteck-gw (inherited from the setgid directory)
    mode  0660
```

The internal BFF entry point creates and binds the Unix socket itself before handing
the open socket to uvicorn. It temporarily uses umask `0117` for `bind()`, restores the
process umask immediately, applies `chmod(0660)`, and verifies the exact file type,
namespace owner, and mode before uvicorn begins serving. It does **not** assume the
host `episteck-gw` gid is represented inside the rootless user namespace; the host-side
proof gate verifies the inherited host gid. It also does **not** use uvicorn's plain
`uds=` creation path, which applies its own socket permissions. No privileged
post-restart `chown` is required.

This mechanism is still a deployment gate, not an assumption: the exact final image
and Quadlet must prove the observed host uid/gid/mode and connectivity before Hermes
is switched.

### 2.3 Deployed images are behind the plan baseline

The investigation recorded these pre-C deployed tags:

| Service | Observed tag | Contains PRs #10–#13? |
| --- | --- | --- |
| Nutrition API/MCP | `episteck-nutrition:7af4cd8` | No |
| Home MCP | `episteck-home-mcp:243bede` | No |
| Home BFF | `episteck-home-bff:3079cd1` | No |

These are observations, not rollback values to hard-code. The cutover must capture
the actual then-current tags, digests, Quadlet contents, and Hermes URLs again.

### 2.4 Audience and protocol facts

Home MCP and Nutrition forward the delegation to the same Home Control Plane
`auth_hook`, which requires `aud=home-control-plane`. The gateway therefore uses that
fixed audience for both upstream paths.

FastMCP server behavior and Hermes client behavior are tested separately. The plan
must not describe `fastmcp==4.0.3` as a Hermes client dependency.

---

## 3. File and interface map

| File | Responsibility |
| --- | --- |
| `services/home-bff/home_bff/runtime.py` | Fixed runtime id and typed binding outcomes; no HTTP concerns |
| `services/home-bff/home_bff/store.py` | Per-operation SQLite connections, schema, `BEGIN IMMEDIATE` binding/resolve/clear operations |
| `services/home-bff/home_bff/app.py` | Public TCP app only; login/callback/logout/session/whoami/existing browser `/delegation`; callback claims binding |
| `services/home-bff/home_bff/internal_app.py` | Internal mint app only; fixed-runtime mint route and minimal health if operationally necessary |
| `services/home-bff/home_bff/__main__.py` | Public app entry point; TCP 9933 only |
| `services/home-bff/home_bff/internal_main.py` | Internal app entry point; safely creates a pre-bound 0660 Unix socket and passes it to uvicorn |
| `services/home-bff/home_bff/config.py` | Explicit public/store/socket settings; no insecure defaults |
| `services/home-bff/tests/test_runtime_binding.py` | Real-file, cross-process binding atomicity tests |
| `services/home-bff/tests/test_internal_mint.py` | Internal-only route, fixed audience, fresh `jti`, no body/secrets |
| `services/home-bff/tests/test_app.py` | Public app route inventory and callback/logout binding behavior |
| `services/home-bff/tests/test_store.py` | Existing store behavior moved from `:memory:` to isolated real SQLite files |
| `services/home-bff/tests/test_security_audit.py` | Existing public boundary audit retained against the split apps |
| `deploy/home-bff/home-bff.container` | Public BFF process, TCP 9933, shared SQLite mount |
| `deploy/home-bff/home-bff-mint.container` | Same final BFF image, separate internal process, shared SQLite + socket mounts |
| `deploy/gateway/nginx-mcp-gateway.conf` | Standalone nginx config, loopback 9934, UDS mint subrequest, MCP proxying |
| `deploy/gateway/episteck-mcp-gateway.service` | Dedicated system service running nginx as `svc-home-gateway` |
| `deploy/gateway/home-bff-mint.tmpfiles.conf` | Boot-safe setgid socket directory creation |
| `deploy/gateway/episteck-gateway.nft` | Dedicated `inet` table with local OUTPUT uid rules |
| `deploy/gateway/README.md` | Provision, stage, cutover, live proof, rollback, and evidence runbook |
| `docs/architecture/G1_6_VALIDATION.md` | C evidence section added only with implementation evidence |

`policy/access.py`, the Frappe `auth_hook`, delegation verification/replay code, MCP
tool schemas, and Nutrition business authorization semantics remain unchanged.

---

## 4. Runtime binding and process-safe SQLite

### 4.1 Schema and interface

```sql
CREATE TABLE IF NOT EXISTS runtime_binding (
    runtime_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    bound_at   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES bff_session(session_id) ON DELETE CASCADE
);
```

`runtime.py` defines only the constant and result vocabulary:

```python
RUNTIME_ID = "home-agent-primary"

class BindResult(StrEnum):
    BOUND = "bound"
    ALREADY_BOUND = "already_bound"
    REPLACED_STALE = "replaced_stale"
    SAME_SESSION = "same_session"
```

The store exposes fixed-runtime-capable primitives without accepting an HTTP request:

```python
def claim_runtime(self, runtime_id: str, session_id: str) -> BindResult: ...
def resolve_runtime(self, runtime_id: str) -> Session | None: ...
def clear_runtime_for_session(self, session_id: str) -> bool: ...
```

The public and internal processes open independent SQLite connections to the same
real file. Each operation obtains and closes its own connection, configures a bounded
`busy_timeout`, enables foreign keys, and uses WAL where supported. Runtime mutation
uses explicit `BEGIN IMMEDIATE`, then reads liveness and writes/clears before commit.
An `OperationalError` rolls back and becomes a controlled unavailable/deny result;
it can never be interpreted as a successful claim.

Existing BFF tests that construct `SessionStore(":memory:")` move to per-test files
under `tmp_path`; an in-memory database cannot prove or accurately exercise the
multi-connection/multi-process production design.

### 4.2 Atomic rules

| Situation inside one `BEGIN IMMEDIATE` transaction | Result |
| --- | --- |
| No binding and candidate session is live | insert; `BOUND` |
| Same live session already bound | no change; `SAME_SESSION` |
| Different live session already bound | no change; `ALREADY_BOUND` |
| Binding points to expired/deleted session | replace atomically; `REPLACED_STALE` |
| Candidate session is absent/expired | deny; no binding change |
| Logout of bound session | clear binding and session in the same transaction |

`resolve_runtime()` also removes an expired/deleted binding within its transaction
before returning `None`, so repeated mint attempts cannot retain stale binding state.

The callback may create a valid browser session even when another live session owns
the runtime; its response states `already_bound`, and it does not replace the live
binding. Runtime identity never comes from a request value.

### 4.3 Required concurrency proof

The concurrency test uses `tmp_path / "bff.sqlite"`, not `:memory:`. Two genuinely
concurrent child processes each create their own `SessionStore` and race from a
barrier against the same SQLite file.

It must prove:

- exactly one different live-session candidate wins an empty binding;
- the loser returns `ALREADY_BOUND`;
- there is one row and one winning session, never two winners;
- no `database is locked` exception is reported as success;
- two contenders replacing one stale binding still produce exactly one winner;
- a mint-process reader observes only a committed live binding.

---

## 5. Public app / internal mint app separation

### 5.1 Public TCP app

`create_app()` remains the browser-facing app on TCP `:9933` and contains:

```text
/health
/login
/callback
/logout
/session
/whoami
/delegation    existing cookie-authenticated route; cleanup remains out of scope
```

It does **not** import/include the internal router and does not register the internal
mint path. A test sends the internal path directly to the public ASGI app and asserts
404, and inspects public OpenAPI/routes to prove structural absence. Public nginx
deny rules, path secrecy, localhost, and headers are not used as the security boundary.

### 5.2 Internal UDS app

`create_internal_app()` is a separate FastAPI object. It contains only:

```text
POST /internal/mint
GET  /health        only if required for readiness; no configuration/session data
```

The mint request has no body, query parameters, cookies, actor, session id, runtime id,
audience, or credential input. It always resolves `home-agent-primary`, requires its
bound BFF session to be live, and mints `aud=home-control-plane`.

Success:

```text
204 No Content
X-Episteck-Delegation: <fresh token>
Cache-Control: no-store
```

The body is empty. Missing/stale/revoked/expired binding returns 401. Database
unavailability returns a fail-closed non-2xx response without leaking SQLite text.
Every successful request receives a new `jti`.

### 5.3 Separate processes/listeners

The final BFF image is used by two Quadlets:

- `home-bff.container` runs `python -m home_bff` and publishes only
  `127.0.0.1:9933:9933`.
- `home-bff-mint.container` runs `python -m home_bff.internal_main`, publishes no TCP
  port, mounts the same SQLite directory with shared-label semantics, and mounts the
  setgid socket directory.

The internal entry point serves only the UDS. Its startup sequence is explicit:

```python
sock = create_mint_socket(
    socket_path,
    expected_uid=os.getuid(),
)
uvicorn.Server(config).run(sockets=[sock])
```

`create_mint_socket(path: Path, *, expected_uid: int) -> socket.socket` performs the
bind under umask `0117` (`0777 & ~0117 == 0660`), restores the prior umask in
`finally`, applies `chmod(0660)`, checks the path with `lstat`, and returns only after
socket type, namespace uid, and mode match exactly. The host-side §7 proof verifies
the required inherited `episteck-gw` gid without assuming supplementary-group or gid
mapping into the container.

It safely removes only its known stale socket after verifying the path is a socket
owned by `svc-home-bff`; it never removes a directory, symlink, or arbitrary path.
The socket is not handed to uvicorn until the `0660` assertion passes. Neither entry
point serves both apps.

---

## 6. Dedicated gateway instance

### 6.1 Service identity and isolation

The provisioning runbook creates:

```text
svc-home-gateway   dedicated non-login Unix account
episteck-gw        socket-connect group; member list = svc-home-gateway only
```

`episteck-mcp-gateway.service` runs `/usr/sbin/nginx` in the foreground with an
explicit standalone config prefix as `User=svc-home-gateway` and
`Group=svc-home-gateway`. It uses its own pid, temp, log, and config paths and does
not load `/etc/nginx/sites-enabled` or the public nginx config. The gateway listens
only on `127.0.0.1:9934`.

Public nginx remains unchanged as `www-data` uid 33 and is never added to
`episteck-gw`.

### 6.2 Per-request mint and upstream proxy

```text
/gateway/home/       -> http://127.0.0.1:9932/mcp
/gateway/nutrition/  -> http://127.0.0.1:9931/mcp
```

For every incoming gateway HTTP request:

1. `auth_request /__mint` runs before proxying.
2. The internal location uses `proxy_method POST`, disables request headers and the
   request body, clears `Content-Length`, sets only a constant `Host`, and proxies
   through the Unix socket to `/internal/mint`. No inbound Cookie, Authorization,
   delegation, or identity-like header reaches the mint app.
3. `auth_request_set` captures only the mint response's
   `X-Episteck-Delegation` header.
4. The upstream request overwrites `X-Episteck-Delegation` with that value.
5. Inbound `Authorization` and `Cookie` are set to empty and therefore omitted.
6. `Mcp-Session-Id` is explicitly forwarded.
7. `proxy_next_upstream off` forbids transparent replay of a single-use delegation.
8. HTTP/1.1, disabled response buffering, and a 300-second read timeout preserve
   Streamable HTTP/SSE behavior.
9. Query strings and delegation headers are absent from the gateway access log.

No directive inspects or parses the JSON-RPC body. An unused delegation minted for
initialize/discovery/other protocol traffic is acceptable.

---

## 7. Unix socket proof gate

After staging the final BFF image but before switching Hermes, run the exact final
Quadlet and verify the host object:

```bash
stat -c '{"path":"%n","mode":"%a","uid":%u,"gid":%g}' \
  /run/episteck/home-bff-mint/mint.sock
getent group episteck-gw
id svc-home-gateway
id www-data
id home-agent
```

Expected JSON values: mode `660`, uid equal to `id -u svc-home-bff`, gid equal to
`getent group episteck-gw`; the group member list contains only
`svc-home-gateway`.

Connection tests use the real Unix users:

```bash
sudo -u svc-home-gateway curl --unix-socket \
  /run/episteck/home-bff-mint/mint.sock -X POST -i http://localhost/internal/mint
sudo -u www-data curl --unix-socket \
  /run/episteck/home-bff-mint/mint.sock -X POST -i http://localhost/internal/mint
sudo -u home-agent curl --unix-socket \
  /run/episteck/home-bff-mint/mint.sock -X POST -i http://localhost/internal/mint
```

`svc-home-gateway` must connect (401 is acceptable before a runtime is bound; it proves
socket reachability). `www-data` and `home-agent` must fail at Unix permission checking.

Restart `home-bff-mint`, repeat `stat` and all three connection tests, and confirm no
privileged chown/chmod hook ran. If ownership, mode, or access differs, stop: do not
add `www-data` to the group and do not continue to cutover.

---

## 8. nftables OUTPUT enforcement

The dedicated `table inet episteck_gateway` uses an `output` base chain because locally
generated loopback packets are classified by sender uid in the OUTPUT path.

Required policy:

```text
127.0.0.1:9934 gateway listener
    meta skuid 1003                       accept
    all other local sender uids           reject/drop

127.0.0.1:{9931,9932} direct MCP ports
    meta skuid <numeric svc-home-gateway> accept
    all other local sender uids           reject/drop
```

The rendered file records the numeric gateway uid resolved during provisioning. It
does not rely on `nft --check` as proof. `nft --check` remains only a syntax precheck.
No additional admin or health uid is planned: diagnostics use the gateway listener or
run explicitly as `svc-home-gateway`. If staging discovers a real existing health
consumer of 9931/9932, its exact uid and necessity must be recorded and narrowly
allowlisted before cutover; a shared group, `www-data`, and a blanket root/local-user
exception are forbidden.

After the coordinated runtime is working, apply the table and run real connections:

```bash
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9934/gateway/home/
sudo -u svc-home-mcp curl --max-time 3 http://127.0.0.1:9934/gateway/home/
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u home-agent curl --max-time 3 http://127.0.0.1:9932/mcp
sudo -u svc-home-bff curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u svc-home-bff curl --max-time 3 http://127.0.0.1:9932/mcp
sudo -u svc-home-gateway curl --max-time 3 http://127.0.0.1:9931/mcp
sudo -u svc-home-gateway curl --max-time 3 http://127.0.0.1:9932/mcp
```

Expected network results:

- uid 1003 reaches 9934;
- the other ordinary uid cannot reach 9934;
- uid 1003 cannot reach 9931 or 9932;
- unrelated ordinary service uid `svc-home-bff` cannot reach 9931 or 9932;
- `svc-home-gateway` reaches 9931 and 9932 (an MCP HTTP error is acceptable as proof
  of transport reachability; connection refusal/timeout is not).

Then repeat an actual initialized MCP call through the gateway. Removing only the
`episteck_gateway` table in a test rollback must restore the pre-rule network state;
never flush the global nftables ruleset.

---

## 9. Test and implementation tasks

### Task 1: Make runtime binding atomic across processes

**Files:**

- Create: `services/home-bff/home_bff/runtime.py`
- Modify: `services/home-bff/home_bff/store.py`
- Create: `services/home-bff/tests/test_runtime_binding.py`

**Interfaces:** Produces `RUNTIME_ID`, `BindResult`, `claim_runtime`,
`resolve_runtime`, and `clear_runtime_for_session` for Tasks 2 and 3.

- [ ] Write failing real-file tests for all binding rules and a two-process barrier
  race against one SQLite file.
- [ ] Run only the new tests and confirm they fail because the interfaces/schema do
  not exist.
- [ ] Implement per-operation connections, bounded busy handling, and explicit
  `BEGIN IMMEDIATE` transactions.
- [ ] Re-run the new tests and confirm the exact single-winner/stale-replacement
  assertions pass repeatedly.
- [ ] Run all BFF tests in the isolated environment.

Verify:

```bash
python -m pytest services/home-bff/tests/test_runtime_binding.py -q
python -m pytest services/home-bff/tests -q
```

### Task 2: Split public and internal ASGI applications

**Files:**

- Modify: `services/home-bff/home_bff/app.py`
- Modify: `services/home-bff/home_bff/config.py`
- Modify: `services/home-bff/home_bff/__main__.py`
- Create: `services/home-bff/home_bff/internal_app.py`
- Create: `services/home-bff/home_bff/internal_main.py`
- Modify/Create tests listed in §3

**Interfaces:** Consumes Task 1 store methods. Produces one public TCP app and one
internal UDS app with no shared router registration, plus
`create_mint_socket(path: Path, *, expected_uid: int) -> socket.socket` for the UDS
entry point.

- [ ] Write failing tests proving the public app returns 404 for the internal path,
  internal OpenAPI contains no browser routes, the internal route takes no identity or
  audience input, and every success returns 204 plus a fresh header.
- [ ] Write failing callback/logout tests for binding claim/refusal/clear behavior.
- [ ] Write failing socket tests for exact `0660` creation and refusal to unlink a
  stale path that is a symlink, directory, non-socket file, or wrong-owner socket.
- [ ] Implement the minimum separate app and entry point without changing the existing
  cookie-authenticated `/delegation` route.
- [ ] Run route inventory, mint, callback, logout, and full BFF tests.

Verify:

```bash
python -m pytest services/home-bff/tests/test_internal_mint.py \
  services/home-bff/tests/test_app.py -q
python -m pytest services/home-bff/tests -q
```

### Task 3: Add the second BFF process and stable socket directory

**Files:**

- Modify: `deploy/home-bff/home-bff.container`
- Create: `deploy/home-bff/home-bff-mint.container`
- Create: `deploy/gateway/home-bff-mint.tmpfiles.conf`

- [ ] Add shared SQLite mount semantics and the socket-directory mount without
  publishing a mint TCP port.
- [ ] Add static tests that assert the public Quadlet publishes only 9933 and the mint
  Quadlet publishes no TCP port.
- [ ] Build/run the exact image in an isolated container test and assert public-route
  absence plus socket uid/gid/mode.
- [ ] Stop/start the mint container and repeat the socket assertions.

Verify:

```bash
rg -n 'PublishPort|internal_main|home-bff-mint|BFF_STORE_PATH' deploy/home-bff deploy/gateway
python -m pytest services/home-bff/tests -q
```

### Task 4: Add the dedicated nginx gateway

**Files:**

- Create: `deploy/gateway/nginx-mcp-gateway.conf`
- Create: `deploy/gateway/episteck-mcp-gateway.service`
- Create: `deploy/gateway/README.md`
- Create gateway integration tests under `deploy/gateway/tests/`

- [ ] Write config tests for the dedicated user/service/config namespace and for
  forged-header overwrite, Cookie/Authorization stripping, `Mcp-Session-Id`
  preservation, retry-off, and streaming directives.
- [ ] Add an integration harness with a fake UDS mint app and instrumented upstreams;
  assert one mint subrequest and one upstream request for each client HTTP request.
- [ ] Prove a JSON-RPC batch array is rejected by real FastMCP 4.0.3 and that the
  gateway never parses/splits it.
- [ ] Prove sequential and concurrent requests receive different delegation tokens.
- [ ] Prove an upstream failure is not retried with the minted token.

Verify:

```bash
nginx -t -c "$PWD/deploy/gateway/nginx-mcp-gateway.conf" -p "$PWD/deploy/gateway/test-root/"
python -m pytest deploy/gateway/tests -q
```

### Task 5: Add nftables rules and live-user validation

**Files:**

- Create: `deploy/gateway/episteck-gateway.nft`
- Modify: `deploy/gateway/README.md`

- [ ] Add a render/check step that substitutes and records the numeric
  `svc-home-gateway` uid.
- [ ] Syntax-check only the dedicated table without loading it.
- [ ] Document the eight real-user connection tests in §8 and their expected results.
- [ ] Document deletion/restoration of only `table inet episteck_gateway`.

Verify before deployment (syntax only):

```bash
sudo nft --check -f deploy/gateway/episteck-gateway.nft
```

The implementation is not accepted until the post-cutover real-user tests also pass.

### Task 6: Full isolated verification and documentation

**Files:**

- Modify: `docs/architecture/G1_6_VALIDATION.md`
- Modify: `deploy/gateway/README.md`

- [ ] Create a fresh Python 3.11+ virtual environment dedicated to this repo; do not
  install or upgrade the shared FastMCP installation.
- [ ] Install each repo service and its test dependencies into that environment, or
  run the equivalent tests in disposable containers.
- [ ] Run BFF, Home MCP, and Nutrition suites plus gateway integration tests.
- [ ] Run compilation, whitespace, route-inventory, and dependency-pin checks.
- [ ] Record server and client dependency versions separately.

Verify:

```bash
python3.11 -m venv .venv-g1-6-c
. .venv-g1-6-c/bin/activate
python -m pip install --upgrade pip
python -m pip install -e services/home-bff -e services/home-mcp -e services/nutrition pytest
python -m pytest services/home-bff/tests services/home-mcp/tests services/nutrition/tests deploy/gateway/tests -q
python -m compileall -q services/home-bff services/home-mcp services/nutrition
git diff --check
```

Delete the disposable venv only after verification; never point these commands at the
user's shared interpreter.

---

## 10. Build, stage, and coordinated cutover

### 10.1 Merge first, then build one provenance set

Implementation C follows branch → PR → architecture/code review → merge. After merge:

```bash
git fetch origin
git checkout --detach origin/main
FINAL_MAIN_SHA="$(git rev-parse HEAD)"
test "$FINAL_MAIN_SHA" = "$(git rev-parse origin/main)"
```

Build all three images from that exact checkout and label/tag them with the same full
SHA:

```text
localhost/episteck-home-bff:${FINAL_MAIN_SHA}
localhost/episteck-home-mcp:${FINAL_MAIN_SHA}
localhost/episteck-nutrition:${FINAL_MAIN_SHA}
```

Record image ids/digests and the OCI revision label. A build from pre-C `main`, the C
feature branch, or three different commits is rejected.

### 10.2 Stage without changing the running transport

Before the maintenance window:

- build and inspect all three final images;
- stage new Quadlet files outside their active paths;
- stage the dedicated nginx config/service and tmpfiles definition without enabling
  the listener;
- stage the nftables file without loading it;
- create/verify the dedicated service user, group, directories, and permissions;
- verify with `ss -lnt` that the selected loopback port 9934 is unoccupied;
- leave the running MCP/BFF images, Hermes URLs, public nginx, and nftables unchanged.

### 10.3 Record exact pre-cutover state

Create a root-readable, mode-0700 timestamped rollback directory and record, without
copying secret values into the JSON manifest:

- current Home BFF, Home MCP, and Nutrition container image tags, ids, and digests;
- exact active Quadlet files and each `Image=` value;
- exact Hermes Home/Nutrition MCP URLs, source config path, secure backup, and checksum;
- active/enabled/running state of all affected user/system services;
- existence, checksums, and enabled state of gateway config/service files;
- `nft -j list ruleset` plus whether `table inet episteck_gateway` existed;
- public nginx worker uid/groups and `episteck-gw` membership;
- repo `FINAL_MAIN_SHA` and all three staged image digests.

Validate the JSON manifest and confirm every previous image remains locally available.

### 10.4 Maintenance/cutover sequence

Do not create an intentional half-wired runtime:

1. Enter the maintenance window and stop/pause the Home Agent user service so it
   cannot issue MCP traffic during the transport switch.
2. Activate the final-sha public BFF Quadlet and the final-sha internal mint Quadlet.
3. Prove the public route inventory, shared SQLite access, socket ownership/access,
   and internal fail-closed response.
4. Start the dedicated gateway service on loopback and prove it can reach the socket.
5. Complete/re-establish the authorized browser login that atomically binds
   `home-agent-primary`; prove the gateway mint subrequest now succeeds.
6. Switch Home MCP and both Nutrition containers to their final-sha images in the same
   maintenance sequence; verify their running image ids before resuming traffic.
7. Change both Hermes MCP URLs to the gateway paths and restart/resume Hermes.
8. Run initialized `tools/list` and representative Home/Nutrition `tools/call`
   operations through the gateway, including forged-header and logout denial checks.
9. Only after end-to-end validation, load the nftables OUTPUT rules and run every
   real-user connection test in §8.
10. Repeat the end-to-end tests after bypass closure and record evidence.

Any failure before step 9 leaves nftables untouched and triggers full rollback. Any
failure at/after step 9 first restores the prior dedicated-table state, then triggers
full rollback.

---

## 11. Rollback: restore the complete previous transport stack

Pointing Hermes directly to 9931/9932 while leaving the new MCP images running is
**not rollback**: those images require delegation and correctly deny direct Hermes
traffic.

Rollback uses the captured pre-cutover bundle and proceeds under maintenance:

1. Stop/pause Hermes.
2. Restore the prior `episteck_gateway` table state only; do not flush unrelated
   nftables tables.
3. Restore previous Home MCP, Nutrition, and (if changed) Home BFF Quadlet files,
   including their exact `Image=` values.
4. Reload the appropriate rootless user managers and restart all restored containers;
   verify their image ids/digests match the manifest.
5. Restore the exact previous Hermes MCP URLs from the secure backup and checksum.
6. Stop/disable the dedicated gateway service and restore its prior config/enabled
   state (normally absent).
7. Restore the previous BFF/gateway socket configuration state if the failed cutover
   changed active paths; leaving inert user/group provisioning is acceptable only if
   the manifest and runbook explicitly record it.
8. Restart Hermes and run the previous-stack functional checks, including
   person-scoped operations against the restored old MCP images.
9. Emit a structured rollback result containing expected/observed image ids, URLs,
   service states, nft table state, and validation outcomes.

Do not prune previous images until the cutover has passed its soak/approval gate.

---

## 12. Acceptance matrix

| Requirement | Required proof |
| --- | --- |
| Dedicated identity | Separate nginx service/config; process uid is `svc-home-gateway`; public nginx remains uid 33 |
| Socket isolation | Pre-bound socket startup uses umask 0117 + explicit chmod/assert; final socket `svc-home-bff:episteck-gw` 0660 after initial start and restart; gateway connects; www-data/home-agent denied before HTTP |
| No TCP mint route | Public app route/OpenAPI inventory plus direct `127.0.0.1:9933/internal/mint` 404 |
| Internal app minimal | Only mint + optional health; no request-selectable identity/runtime/audience |
| SQLite atomicity | Cross-process, same-file race: exactly one winner; stale replacement atomic; controlled busy failure |
| Fresh delegation | Sequential/concurrent gateway requests have distinct `jti`; both gateway paths use `home-control-plane` |
| Header controls | Forged delegation overwritten; Authorization/Cookie absent upstream; Mcp-Session-Id preserved |
| Protocol behavior | Real FastMCP 4.0.3 rejects batch arrays; one tools/call POST is proxied once; no body parsing |
| Replay safety | `proxy_next_upstream off`; forced upstream failure causes no second attempt |
| OUTPUT uid controls | Gateway listener allows uid 1003 only; direct 9931/9932 allow the dedicated gateway identity and deny uid 1003 plus an unrelated ordinary uid, with a final catch-all deny |
| Provenance | All three final images carry the same final post-C main SHA and recorded digests |
| Coordinated cutover | Gateway/mint ready before MCP/Hermes switch; no active half-wired period |
| Complete rollback | Previous three image states, Quadlets, Hermes URLs, gateway state, and nft state restored and validated |
| Dependency distinction | Server `fastmcp==4.0.3`; observed Hermes client `mcp 2.0.0` / `mcp-types 2.0.0` |

Every security assertion receives a negative/mutation check: remove or invert the
control and confirm the test fails. Any loop over discovered tools/routes must assert a
non-zero count before claiming coverage.

---

## 13. PR #14 stopping point

This revision changes only this plan. It does not create any file named in §3, change
any service, access the live servers, build an image, or deploy anything.

Stop after pushing the revised PR #14 branch. C implementation begins only after the
architect re-reviews and approves this plan.
