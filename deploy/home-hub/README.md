# Home Hub F2b deployment and runbook

The `svc-home-hub.container` Quadlet is designed for the dedicated rootless
`svc-home-hub` account. The coordinated persistent rollout was completed on
2026-09-27; see [Live rollout record](#live-rollout-record-2026-09-27). The
original implementation PR prepared the image and Quadlet without activating
them. Build the image from the repository root with:

```bash
podman build -f apps/home-hub/Dockerfile \
  -t localhost/episteck-home-hub:COMMIT_SHA apps/home-hub
```

Replace `COMMIT_SHA` in the image tag and Quadlet with the reviewed commit SHA.
The Hub publishes host port 9940 only on `127.0.0.1`; the container reaches the
host BFF through the approved `pasta:-T,9933` forward. Do not change this network
topology in response to a failed proof; stop and return the evidence for review.

## Pre-rollout VERIFY LIVE gate (historical procedure)

These commands were not run as part of F2b implementation. They were subsequently
run during the coordinated rollout recorded below. Retain the stop condition: if
pasta/Podman versions, BFF reachability, or isolation differ from the reviewed
design, stop and return the evidence without trying another network topology.

```bash
# Record installed versions and rootless network backend.
sudo -u svc-home-hub podman --version
sudo -u svc-home-hub podman info --format '{{.Host.NetworkBackend}}'
pasta --version

# The BFF health endpoint must be reachable from the isolated Hub container.
sudo -u svc-home-hub podman run --rm --network pasta:-T,9933 \
  --entrypoint node localhost/episteck-home-hub:COMMIT_SHA \
  -e 'fetch("http://127.0.0.1:9933/health").then(r => { console.log(r.status); process.exit(r.status === 200 ? 0 : 1) }).catch(() => process.exit(1))'

# No other tested host-loopback service may be reachable through this network.
sudo -u svc-home-hub podman run --rm --network pasta:-T,9933 \
  --entrypoint node localhost/episteck-home-hub:COMMIT_SHA \
  -e 'const net=require("node:net"); const ports=[9930,9931,9932,9934]; let failed=false; Promise.all(ports.map(port => new Promise(resolve => { const socket=net.createConnection({host:"127.0.0.1",port,timeout:1500}); socket.once("connect",()=>{console.error(`UNEXPECTED reachable port ${port}`); failed=true; socket.destroy(); resolve()}); socket.once("error",resolve); socket.once("timeout",()=>{socket.destroy();resolve()}) }))).then(()=>process.exit(failed?1:0))'

# On the host, verify the Hub bind is loopback-only and nginx proxies /app to it.
sudo ss -ltnp | grep ':9940'
sudo nginx -T 2>/dev/null | grep -A8 -E 'location = /app|location \^~ /app/'

# From a separate external machine, direct access to the host port must fail.
curl --connect-timeout 3 -v http://HOST_PUBLIC_IP:9940/app
```

Expected at review time: BFF health returns 200; the other listed ports refuse or
time out; `ss` shows only `127.0.0.1:9940`; nginx's exact `/app` and `/app/`
locations proxy to that loopback listener; the external direct-port probe cannot
connect. The coordinated rollout outcomes are recorded below.

## Live rollout record (2026-09-27)

Target: `ubuntu-4gb-nbg1-1` in Nuremberg. The deployed repository baseline was
`484d129174bc9e81872ae67ac7fa5581a8a43f2d`, the PR #41 merge. `origin/main` was
that exact SHA at rollout time; it contains F2a Control Plane, F2a BFF, the PR #42
duplicate-Circle fix, and F2b Hub.

**Coordinated rollout: PASS. Rollback was not used.**

### BFF

- Previous image: `localhost/episteck-home-bff:ddebab6439c9d68487d180dec6995fc546d3cf68`
  (image ID `88a5734e3d27b91ea8d19a645c8131d67e57fb9821371f28a70bb686208efb58`).
- Deployed image: `localhost/episteck-home-bff:484d129174bc9e81872ae67ac7fa5581a8a43f2d`
  (image ID `2343b29b548ed5889b96af9da45799a2486d231c38b44604f72be788035106c2`).
- Existing `svc-home-bff` Quadlet, service identity, environment file, loopback
  bind, and SQLite session store were preserved. `/health` returned 200;
  cookie-free `/bootstrap` returned 401 `SESSION_REQUIRED` with
  `Cache-Control: no-store`. BFF remains on `127.0.0.1:9933`.

### Hub and network

- Image: `localhost/episteck-home-hub:484d129174bc9e81872ae67ac7fa5581a8a43f2d`
  (image ID `4c08dfe625b39cf65f8d380d9bf0cd1f64e3b88fa7cf92cf3fe148b6b0b89d4c`,
  305 MB). Image user is `node` (UID 1000); `prelisten.mjs` and `server.js` are
  present; the command starts `prelisten.mjs`.
- The generated `svc-home-hub.service` is active; Quadlet generated its
  `default.target.wants` link from `[Install]`, and `svc-home-hub` lingering is
  enabled. This host rejects `systemctl enable` for generated units, so the unit
  was activated with `systemctl --user start` after daemon reload.
- The reviewed Quadlet is installed at
  `/home/svc-home-hub/.config/containers/systemd/svc-home-hub.container` with
  `Network=pasta:-T,9933`, `PublishPort=127.0.0.1:9940:3000`, `LIVE` mode, the
  existing BFF/public-origin URLs, 512 MiB memory and swap limits, and
  `NoNewPrivileges=true` (effective systemd property `yes`).
- Hub-to-BFF `/health` returned 200. Ports 9930, 9931, 9932, and 9934 were
  inaccessible from the Hub. Host `ss` showed only `127.0.0.1:9940`; the Hub
  container runs as UID 1000, with zero restarts at verification.
- Cookie-free internal `/app` returned 307 to
  `https://bff.home.episteck.com/login`.

### nginx and public checks

- The reviewed `deploy/home-bff/nginx-home-bff.conf` was installed. `nginx -t`
  succeeded before reload; nginx remained active. The explicit identity-route
  allowlist remains in place; `/bootstrap` is caught by the 404 fallback.
- From an external client, public `/app` returned 307 to trusted `/login`, public
  `/login` returned 302 to the Control Plane OAuth authorize endpoint, and public
  `/bootstrap` returned 404. Direct `http://91.98.132.9:9940/app` timed out.
- `/application` is not routed to the Hub by the reviewed exact `/app` and
  `/app/` locations.

### Persistence, rollback, and follow-up

- BFF is active and generated-enabled with `svc-home-bff` lingering enabled. Hub is
  active and generated-enabled with `svc-home-hub` lingering enabled. nginx is
  active and enabled. No reboot was performed.
- Exact pre-rollout BFF Quadlet and nginx config, prior image identity, and rollback
  commands are stored on the host in
  `/var/backups/episteck/home-f2-rollout-484d129/`. The session database was left
  untouched. The earlier PR-head Hub proof image was retained.
- Post-rollout BFF and Hub logs contained no access/refresh token, cookie, client or
  delegation secret, PKCE verifier, bearer credential, or JWT-shaped value. Hub
  emitted a non-fatal Node module-type warning at startup.
- Authenticated OAuth verification: **PASS** (2026-09-27). A human login in a
  fresh incognito browser completed OAuth and returned to the authenticated Hub
  UI at `/app`. The authenticated Frappe User was
  `vargas3rick@gmail.com`, mapped to `PSN-00013` / Erick Vargas. The live BFF
  had one current unexpired session for this actor; the matching Home Delegated
  Session was active and unexpired.
- A read-only server-side check of the live BFF session at `/bootstrap` returned
  HTTP 200 with a valid bootstrap from the Control Plane's
  `get_home_bootstrap(...)`: viewer `PSN-00013` / Erick Vargas, one person context
  (the viewer), zero Circle contexts, and zero care relationships. No synthetic
  Person or Circle was returned. No authorization error or malformed bootstrap
  was observed. No Circle data was created.
- One earlier normal-browser callback returned the safe
  “invalid or already-used authorization state” response; the fresh incognito
  flow then succeeded. The implementation atomically consumes OAuth
  transactions and returns that response for absent, expired, or already-used
  state. Logs show one callback 400 followed by a successful callback 303, so
  the observation is consistent with an old/stale or already-consumed browser
  transaction. The exact cause cannot be distinguished from safe logs, and no
  persistent failure was observed.
- Recent BFF and Hub logs had no matches for OAuth code/state, PKCE verifier,
  cookie, bearer credential, access/refresh token, or JWT patterns. The nginx
  access log recorded no request query strings. No F3 or domain authorization
  work was included in this rollout or verification.

## F3a live rollout attempt and rollback (2026-09-27)

**Result: live verification remains open.** The merged F3a Hub image was deployed
briefly, then rolled back when the production nginx access-log format failed the
query-metadata hygiene gate. No F3b work or production topology/data mutation was
performed.

- A fresh `git fetch origin` resolved `origin/main` to
  `7739dab807873270163f62b8b9d3511c9f46b585` (PR #50 and subsequent PR #49).
  The new local worktree was
  `C:\AIProjects\episteck-delivery-workspace\.worktrees\home-f3a-live-verification`
  on `ops/home-f3a-live-verification`, clean at that SHA. A separate clean host
  checkout at `/tmp/episteck-home-f3a-build-7739dab` had the same HEAD.
- Pre-rollout Hub: `localhost/episteck-home-hub:484d129174bc9e81872ae67ac7fa5581a8a43f2d`,
  image ID `4c08dfe625b39cf65f8d380d9bf0cd1f64e3b88fa7cf92cf3fe148b6b0b89d4c`,
  digest `sha256:97f944ad15d9affc12cb1a23031ba7c3e1295de5258279e9c96235008a9d7ae7`.
  BFF was left on `localhost/episteck-home-bff:484d129174bc9e81872ae67ac7fa5581a8a43f2d`,
  image ID `2343b29b548ed5889b96af9da45799a2486d231c38b44604f72be788035106c2`.
- Build command, run rootlessly as `svc-home-hub` from `/tmp`:
  `podman build -f /tmp/episteck-home-f3a-build-7739dab/apps/home-hub/Dockerfile -t localhost/episteck-home-hub:7739dab807873270163f62b8b9d3511c9f46b585 /tmp/episteck-home-f3a-build-7739dab/apps/home-hub`.
  Build and Next.js TypeScript compilation succeeded. New image ID:
  `9b0f64701e86dfa7b8ff3ffb1a4a01e0d9d7e284490b26b5247f3ad7c72f5714`;
  digest `sha256:229a5f7900a30c9bfd04d81c669ef3b00f79388c0b65e8c3c3b5902c71d2304e`.
- The installed Quadlet changed only its `Image=` line. After user-unit reload and
  restart, at `2026-09-27T21:59:53Z` the service was active with zero restarts,
  the expected new image, container user `node`, 512 MiB memory and swap limits,
  `NoNewPrivileges=yes`, and `127.0.0.1:9940:3000` only. The Quadlet retained
  `Network=pasta:-T,9933` and the existing BFF and public-origin settings.
- Before and after the restart, TCP `9933` was reachable from the Hub container;
  `9930`, `9931`, `9932`, and `9934` were blocked. Anonymous `/app` redirected
  to `/login`; public `/bootstrap` and `/delegation` returned 404. Direct public
  access to `9940` and `9930` timed out. No network or firewall rule changed.
- **Blocking log finding:** the production
  `/etc/nginx/conf.d/episteck-log-format.conf` defines `episteck_noqs` with
  `$uri` for the request path **but also** `$http_referer` and `$http_user_agent`.
  The checked-in `deploy/home-bff/episteck-log-format.conf` omits both headers.
  A harmless `/health` request with a `Referer` containing
  `?probe=F3A_REF_PROBE_20260928` returned 200 and the marker appeared once in
  `/var/log/nginx/home-bff-access.log`. No `?person=` or Person ID was found in
  that log during this attempt. The Hub/public responses carried
  `Referrer-Policy: no-referrer`, but the live log format still accepts and
  records query-bearing request headers. No nginx configuration was changed.
- No connected browser was available to this session and the BFF store had zero
  unexpired sessions. Authenticated Erick login, live self context, URL/history/
  focus/two-tab behavior, and authenticated context API results were **not**
  verified. Cross-Person live tab proof also remains deferred until approved
  real topology exists; synthetic F3a tests cover P1/P2 separation.
- The saved pre-rollout Quadlet is
  `/var/backups/episteck/home-f3a-rollout-7739dab/svc-home-hub.container`;
  the prior Hub image above was retained. The Quadlet was restored byte for byte
  and the Hub restarted. At `2026-09-27T22:03:42Z`, service and container were
  active again on image ID `4c08dfe625b39cf65f8d380d9bf0cd1f64e3b88fa7cf92cf3fe148b6b0b89d4c`,
  zero restarts, loopback `9940`, `9933` reachable, and the four excluded ports
  blocked. Anonymous `/app` redirected to login; public internal routes stayed 404.

Restore the reviewed path-only nginx log format under a separately reviewed
operational change, verify that a query-bearing `Referer` is not recorded, then
repeat the F3a rollout and authenticated browser/API matrix. Until those checks
pass, **F3a implementation is merged but live verification remains open**;
F3b, F3c, and F3d remain open.

## Production nginx log-hygiene correction (2026-09-28)

**Disposition: nginx log-hygiene blocker CLOSED; F3a live verification still
OPEN.** This was a logging-only correction on the Nuremberg host. No Hub image,
route, proxy, TLS, OAuth, firewall, upstream, BFF session, or delegation setting
was changed, and the F3a Hub was not deployed. The evidence branch is
`ops/home-nginx-log-hygiene`, created as a clean worktree from `origin/main`
`91c8a680c931188ff3b5a097d57cbab6e8f7dfc2`.

### Exact drift and custody

The reviewed source is `deploy/home-bff/episteck-log-format.conf` (SHA-256
`3a8d7c0d95f0bd592817adefd8f87447770fa5f9c2cf714cff915eb227919e68`).
The previous live file was `/etc/nginx/conf.d/episteck-log-format.conf` (SHA-256
`d34314e42d32436417bdd5b01160cce74d27e79678695773d0b1ee42c269f7bd`).
The complete sanitized file diff, before correction, was:

```diff
--- repository/deploy/home-bff/episteck-log-format.conf
+++ production/etc/nginx/conf.d/episteck-log-format.conf
@@ -1,10 +1,4 @@
-# Install to: /etc/nginx/conf.d/episteck-log-format.conf
-#
-# Must be in the http{} context, which is why it is a conf.d file and not part of the
-# vhost: a log_format inside a server block is a configuration error.
-#
-# Logs the path and low-risk request metadata only. Callback queries carry the
-# OAuth code/state; Referer and User-Agent are untrusted and may carry them too.
-log_format episteck_noqs '$remote_addr [$time_local] '
+# Path only: OAuth authorization codes and state must never reach disk.
+log_format episteck_noqs '$remote_addr - $remote_user [$time_local] '
                          '"$request_method $uri $server_protocol" '
-                         '$status $body_bytes_sent';
+                         '$status $body_bytes_sent "$http_referer" "$http_user_agent"';
```

Thus the live format added `$remote_user`, `$http_referer`, and
`$http_user_agent` to the reviewed path-safe format. The Home vhost's two
server-level `access_log` directives, two `error_log /dev/null` directives,
and lack of location-level logging overrides matched the reviewed
`deploy/home-bff/nginx-home-bff.conf`; no other Home logging drift was found.
nginx's global default access log exists, but both Home server blocks override
it with `episteck_noqs`.

Before replacement, the exact old file was copied with metadata to the
root-controlled directory
`/var/backups/episteck/home-nginx-log-hygiene-20260928-91c8a68/` as
`episteck-log-format.conf.before`; its SHA-256 equals the old live hash above.
The directory is `root:root 0700`. Sanitized `nginx -T` logging excerpts were
saved there as `nginx-logging-effective.before.txt` (SHA-256
`25e0b400477f9f0c293b99893512deaa1376f13cdff465a613a1ef4453bd6897`)
and `nginx-logging-effective.after.txt` (SHA-256
`7bd169034b476d04573c7cca87749eb9fda50d13d568073312470697290a82e7`).
The byte-identical reviewed staging file is
`episteck-log-format.conf.reviewed` (SHA-256 equals the reviewed source above).
Before change, nginx was active/running, master PID `995442`, with zero restarts.

### Apply and live proof

The reviewed staging file alone was installed at
`/etc/nginx/conf.d/episteck-log-format.conf` as `root:root 0644`. `nginx -t`
passed (`syntax is ok`; `test is successful`), then `systemctl reload nginx`
passed. nginx remained active/running with master PID `995442` and zero
restarts. The test emitted only the existing `listen ... http2` deprecation
warning for the unchanged Home vhost.

Post-reload `nginx -T` succeeded and showed exactly one `episteck_noqs`
definition, textually equal to the reviewed active statement:

```nginx
log_format episteck_noqs '$remote_addr [$time_local] '
                         '"$request_method $uri $server_protocol" '
                         '$status $body_bytes_sent';
```

The effective Home vhost retained its two server-level
`access_log /var/log/nginx/home-bff-access.log episteck_noqs;` directives and
`error_log /dev/null;` directives. The selected format has no `$request`,
`$args`, `$query_string`, `$request_uri`, `$http_referer`, `$http_user_agent`,
Cookie, Authorization, or delegation-bearing field. It records the method and
`$uri` path, status, bytes, timestamp, protocol, and previously reviewed remote
address. Successful reload plus the fresh log probes below confirms this format
was used by the running server, beyond the on-disk file comparison.

Three external `/health` requests each returned 200. Each was checked against
only its own new byte window in `/var/log/nginx/home-bff-access.log` (inode
`826553`), and each window contained exactly one `"GET /health HTTP/..." 200`
entry and none of the synthetic markers:

| Probe | Harmless input | New-log byte window | Result |
| --- | --- | --- | --- |
| URL query | `probe=F3A_QUERY_8CDA9A2684C1`, plus synthetic `code=F3A_CODE_8CDA9A2684C1`, `state=F3A_STATE_8CDA9A2684C1`, `person=F3A_PERSON_8CDA9A2684C1` | `[40770, 40843)` | 200; path/status present; all markers absent |
| Referer | `https://example.invalid/path?probe=F3A_REF_8CDA9A2684C1` | `[40843, 40916)` | 200; path/status present; marker absent |
| User-Agent | `F3A_UA_8CDA9A2684C1` | `[40916, 40989)` | 200; path/status present; marker absent |

These are synthetic strings, not OAuth credentials or real Person IDs. Because
the effective format contains neither a query-bearing request field nor
Referer, it cannot record OAuth `code`/`state` or Person query parameters from
those surfaces. No historical log was rewritten; older production entries may
still contain Referer or User-Agent values from before this correction. This
gate applies to entries created after the reload.

Post-reload public GET results matched the pre-reload baseline: `/health` 200,
anonymous `/app` 307, `/bootstrap` 404, and `/delegation` 404. External direct
connections to `91.98.132.9:9940` (Hub) and `91.98.132.9:9930` (Nutrition)
timed out before and after reload. Host `ss` showed `127.0.0.1:9940`,
`127.0.0.1:9930`, and `127.0.0.1:9933` only for those selected listeners.

The ready, syntax-checked one-command rollback artifact is
`/var/backups/episteck/home-nginx-log-hygiene-20260928-91c8a68/rollback.sh`
(SHA-256 `4eb326b585e179ae3c937552e09a086191be9c64c5aa9c6e62e5e49cb5f43e29`):

```bash
ssh episteck-node1 'sudo -n /var/backups/episteck/home-nginx-log-hygiene-20260928-91c8a68/rollback.sh'
```

It restores the exact old file, tests nginx, and reloads it. Running it would
restore the old unsafe logging format and reopen this blocker; use only for an
emergency rollback. The next separate task must repeat the F3a Hub rollout and
authenticated matrix. No F3b work is authorized by this log correction.

## F3a live rollout and verification (2026-10-05)

**Disposition: F3a live verification PASS. Rollback was not used.** No BFF,
nginx, network, firewall, OAuth, session-store, or Control Plane change was made.
No production Person, Circle, grant, or Nutrition record was created. F3b, F3c,
and F3d remain open.

### Provenance and build

- Fresh `git fetch origin` resolved `origin/main` to
  `b1a3d5f7cc58b58968a3250b752a1dab37d0fa8b` (PR #55). Evidence branch
  `ops/home-f3a-live-verification-retry`, worktree
  `.worktrees/home-f3a-live-retry`, clean at that SHA.
- `apps/home-hub`, the BFF, and `deploy/home-bff` are unchanged between `7739dab`
  and `b1a3d5f` (only this README changed under the Hub/BFF paths).
- Clean host checkout `/tmp/episteck-home-f3a-build-b1a3d5f` (detached, no local
  changes). Rootless build as `svc-home-hub` tagged
  `localhost/episteck-home-hub:b1a3d5f7cc58b58968a3250b752a1dab37d0fa8b`
  produced image ID
  `9b0f64701e86dfa7b8ff3ffb1a4a01e0d9d7e284490b26b5247f3ad7c72f5714`, digest
  `sha256:229a5f7900a30c9bfd04d81c669ef3b00f79388c0b65e8c3c3b5902c71d2304e` —
  identical to the 2026-09-27 `7739dab` build, confirming reproducibility.
- Pre-rollout baseline: Hub on `484d129…` (image ID `4c08dfe6…`); nginx
  `episteck-log-format.conf` SHA-256 equal to the reviewed
  `3a8d7c0d…919e68`; BFF `/health` 200; listeners `127.0.0.1` 9930/9933/9940.

### Apply

- Pre-rollout Quadlet saved to the root-only directory
  `/var/backups/episteck/home-f3a-rollout-b1a3d5f/svc-home-hub.container.before`
  (SHA-256 `3039a74b3b2d13ca7e9a482bd8a7efd8e9c0a1a335174a33c36dbf2282d72d46`,
  equal to the live file).
- Before restart, the new image under `pasta:-T,9933` reached BFF `/health`
  (200) and could not reach 9930/9931/9932/9934.
- The Quadlet diff against the backup was exactly one line (`Image=` 484d129 →
  b1a3d5f). The change, user-unit reload and restart were run by the operator.
  At `2026-10-05T15:21:06Z` the service was `active/running`, `NRestarts=0`,
  image ID `9b0f6470…`, user `node`, 512 MiB memory and swap, `NoNewPrivileges=yes`,
  published only `127.0.0.1:9940:3000`; Quadlet retained `Network=pasta:-T,9933`,
  `LIVE` mode, and the existing BFF and public-origin settings.

### Anonymous and network checks

- From the running Hub container: BFF `/health` 200; 9930/9931/9932/9934 blocked.
  Host `ss`: `127.0.0.1` 9930/9933/9940 only. Internal `/app` 307 to login.
- External: `/health` 200; `/app` 307 to `/login`; `/login` 302 to the Control
  Plane authorize endpoint with S256 PKCE; `/bootstrap` and `/delegation` 404.
  `/app` carries `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
  Direct `91.98.132.9:9940`, `:9930`, `:9933` timed out.
- Log-hygiene probe: synthetic markers in the URL query (`person`, `code`,
  `state`), `Referer`, and `User-Agent`. In the new byte window of
  `home-bff-access.log` (9 lines): 0 marker hits, 0 query strings.

### Authenticated matrix

A human login in a fresh isolated browser context (password entered by the
operator only) completed OAuth and landed on `/app`. Browser checks were driven
via Chrome DevTools in that context.

| Check | Result |
| --- | --- |
| Self default | Viewer and only context `PSN-00013` / Erick Vargas; nav links carry `?person=PSN-00013` |
| Context request | Body `{"person":[]}` only (no actor); response `CURRENT`, bootstrap with one person context, zero Circles, zero care relationships, `LIVE`; `no-store`, `no-referrer` |
| Unknown Person in URL | `/app/nutrition?person=PSN-99999` canonicalized to `?person=PSN-00013`, "Context changed" notice |
| Resolver matrix | Unknown, malformed, Circle-shaped, and duplicate values → `STALE_CONTEXT` → self (requested ID never echoed); self → `CURRENT`; body with `actor`/`viewer` → 400 `INVALID_CONTEXT_REQUEST`; non-array shape → 400; all `no-store` |
| Refresh | Route and self context preserved; no stale notice |
| Two tabs | Tab 2 opened with a stale Person canonicalized independently; tab 1 route and context unchanged, no notice |
| Focus revalidation | A focus/visibility event issued exactly one new `POST /app/api/context` |
| History | Link → back → forward restored each route with the self context |

Cross-Person live tab proof remains deferred until approved real topology
exists; synthetic F3a tests cover P1/P2 separation.

### Logs

Since `2026-10-05T15:20Z`: 207 `home-bff-access.log` lines, 9 Hub and 25 BFF
container log lines. Zero matches for Person IDs, probe markers, OAuth
`code`/`state` parameters, session cookie, bearer credential, access/refresh
token, PKCE verifier, or JWT shape; zero nginx lines with a query string. Status
codes were 200/302/303/307/400/404 as exercised, plus two client-cancelled
prefetches (499). The Hub still emits the known non-fatal Node module-type
warning at startup.

### Rollback

```bash
ssh episteck-node1 'cd /; sudo cp -p /var/backups/episteck/home-f3a-rollout-b1a3d5f/svc-home-hub.container.before /home/svc-home-hub/.config/containers/systemd/svc-home-hub.container; H=$(id -u svc-home-hub); S="sudo -u svc-home-hub XDG_RUNTIME_DIR=/run/user/$H DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$H/bus"; $S systemctl --user daemon-reload; $S systemctl --user restart svc-home-hub.service'
```

The prior `484d129` image is retained. F3b is the next Home MVP step and still
requires its own reviewed Hub-server → Nutrition transport change and live
isolation proof.
