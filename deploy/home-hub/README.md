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
- Authenticated OAuth verification remains **PENDING USER LOGIN**. Open
  `https://bff.home.episteck.com/app` manually to verify callback, opaque session
  cookie, server-side bootstrap, and real viewer/person/circle/care contexts. No
  F3 or domain authorization work was included in this rollout.
