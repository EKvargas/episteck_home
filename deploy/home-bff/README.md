# Home BFF deployment (Nuremberg EU node)

Runbook for deploying the Episteck Home BFF. Follow it in order; every step is
idempotent except the OAuth client creation, which happens exactly once.

## When to use

After PR #4 merges to `main`, as part of the G1.6 live cutover.

## Prerequisites

- `bff.home.episteck.com` A record → `91.98.132.9` (**manual, operator action**)
- SSH to `episteck@91.98.132.9`
- `main` merged and `bench --site home.episteck.com migrate` already run

## 1. Service account and directories

```bash
sudo useradd -m -u 1007 -s /bin/bash svc-home-bff
sudo loginctl enable-linger svc-home-bff          # user units survive logout

sudo mkdir -p /srv/episteck/services/home-bff/{data,secrets}
sudo chown -R svc-home-bff:svc-home-bff /srv/episteck/services/home-bff
sudo chmod 700 /srv/episteck/services/home-bff/data
sudo chmod 700 /srv/episteck/services/home-bff/secrets
```

`svc-home-bff` gets no sudo and no SSH key, matching `svc-nutrition` and
`svc-home-mcp`.

Create the dedicated gateway identity and socket directory before starting either
user unit:

```bash
sudo groupadd --system episteck-gw
sudo useradd --system --no-create-home --shell /usr/sbin/nologin svc-home-gateway
sudo usermod --append --groups episteck-gw svc-home-gateway
sudo install -D -m 0644 deploy/gateway/home-bff-mint.tmpfiles.conf \
  /etc/tmpfiles.d/episteck-home-bff-mint.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/episteck-home-bff-mint.conf
stat -c '%U:%G %a %A' /run/episteck/home-bff-mint
```

The expected directory proof is `svc-home-bff:episteck-gw 2770` with setgid.
Only `svc-home-gateway` belongs to `episteck-gw`; public nginx `www-data` and
`home-agent` must not be added. `GroupAdd=keep-groups` on the mint unit is
intentional: rootless Podman must retain the host service account's supplementary
groups rather than assuming a container group mapping. Validate that mapping before
cutover:

```bash
sudo -u svc-home-bff podman run --rm --userns=keep-id --group-add=keep-groups \
  -v /run/episteck/home-bff-mint:/run/episteck/home-bff-mint:rw \
  localhost/episteck-home-bff:FINAL_SHA id
sudo -u svc-home-bff podman run --rm --userns=keep-id --group-add=keep-groups \
  -v /run/episteck/home-bff-mint:/run/episteck/home-bff-mint:rw \
  localhost/episteck-home-bff:FINAL_SHA sh -c \
  'python -c "import os; print(os.getuid(), os.getgroups())"'
```

The exact isolated container proof must start the mint image with the real SQLite
and socket-directory mounts, assert socket owner `svc-home-bff`, group
`episteck-gw`, mode `0660`, and repeat after stopping and starting the mint unit.
Failure to create/recreate this socket with the host group mapping is a deployment
blocker; do not compensate with privileged chown.

## 2. Build the image

```bash
cd /srv/episteck/build/episteck_home        # a checkout of the repo at the SHA
sudo -u svc-home-bff podman build \
  -f services/home-bff/Dockerfile \
  -t localhost/episteck-home-bff:$(git rev-parse --short HEAD) .
```

Record the SHA — it goes in the Quadlet `Image=` line.

## 3. Secrets

Written directly on the box, never through a shell argument and never echoed:

```bash
sudo -u svc-home-bff install -m 600 /dev/null \
  /srv/episteck/services/home-bff/secrets/oauth.env
sudo -u svc-home-bff nano /srv/episteck/services/home-bff/secrets/oauth.env
```

Contents (values filled in on the box):

```
HOME_BASE_URL=https://home.episteck.com
BFF_CLIENT_ID=...
BFF_CLIENT_SECRET=...
BFF_REDIRECT_URI=https://bff.home.episteck.com/callback
HOME_DELEGATION_SECRET=...
HOME_DELEGATION_ISSUER=episteck-home-bff
BFF_SCOPE=all openid
```

`HOME_DELEGATION_SECRET` must be **byte-identical** to `home_delegation_secret` in
the Ashburn `site_config.json`, or every delegation fails closed.

## 4. Quadlet unit

```bash
sudo -u svc-home-bff mkdir -p /home/svc-home-bff/.config/containers/systemd
# copy home-bff.container, replacing REPLACE_WITH_COMMIT_SHA
sudo -u XDG_RUNTIME_DIR=/run/user/1007 systemctl --user daemon-reload
sudo -u XDG_RUNTIME_DIR=/run/user/1007 systemctl --user start home-bff
sudo -u XDG_RUNTIME_DIR=/run/user/1007 systemctl --user start home-bff-mint
```

Start the mint unit only after the tmpfiles directory exists. The public unit
publishes only loopback `9933`; `home-bff-mint.container` publishes no TCP port.
Both units use the same shared-label `/data/bff.sqlite` mount. Only the mint unit
mounts the socket directory and retains supplementary groups; the public BFF has no
socket-directory mount and its ASGI process has no internal mint route.

## 5. Reverse proxy

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp episteck-log-format.conf /etc/nginx/conf.d/episteck-log-format.conf
sudo cp episteck-rate-limit.conf /etc/nginx/conf.d/episteck-rate-limit.conf
sudo cp nginx-home-bff.conf /etc/nginx/sites-available/home-bff.conf
sudo ln -sf /etc/nginx/sites-available/home-bff.conf /etc/nginx/sites-enabled/
sudo ufw allow 80/tcp comment 'HTTP (ACME + redirect)'
sudo ufw allow 443/tcp comment 'HTTPS (Home BFF)'
sudo certbot --nginx -d bff.home.episteck.com
sudo nginx -t && sudo systemctl reload nginx
```

This opens the **first** public ports on this node. Only 80/443 are opened; 9933
stays on loopback.

## 6. Verify

```bash
curl -fsS https://bff.home.episteck.com/health          # {"status":"ok",...}
# No query string may ever appear in the access log:
curl -s -o /dev/null 'https://bff.home.episteck.com/health?probe=LEAKCHECK'
sudo grep -c LEAKCHECK /var/log/nginx/home-bff-access.log   # must be 0
curl -fsS -o /dev/null -w '%{http_code}\n' \
     https://bff.home.episteck.com/delegation           # 404 — not public
ss -tlnp | grep 9933                                    # 127.0.0.1 only
```

## Rollback

```bash
systemctl --user stop home-bff          # as svc-home-bff
sudo rm /etc/nginx/sites-enabled/home-bff.conf && sudo systemctl reload nginx
```

The BFF is additive: nothing else depends on it, so stopping it restores the
pre-G1.6 state. Revoking the OAuth Client record on Frappe invalidates its
credentials independently.

## Session state

| Property | Value |
| --- | --- |
| Location | `/srv/episteck/services/home-bff/data/bff.sqlite` (volume `/data`) |
| Owner / mode | `svc-home-bff`, directory `700`, file `600` |
| Contents | OAuth access/refresh tokens, PKCE verifiers, opaque session ids |
| Expiry | transactions 10 min; sessions 12 h |
| Cleanup | `purge_expired()` on each `/login` |
| Restart | survives (sessions persist across deploys) |
| Logout | row deleted locally; Home session revoked; upstream token revoked |
| Backup | **excluded** — holds only re-obtainable credentials, never domain data |


## Agent runtime grant (H5)

Lets the owner grant `home-agent-primary` up to 90 days of delegated access without a
daily login. Design: ADR-0010. Page: `https://bff.home.episteck.com/runtime`.

| Item | Detail |
| --- | --- |
| Routes (exact nginx locations) | `GET /runtime`, `POST /runtime/grant`, `POST /runtime/revoke`, `POST /logout/all` |
| Grant needs | session cookie + CSRF (Origin or `Sec-Fetch-Site`, plus form token) + login at most 10 min old |
| State | table `runtime_grant` in `bff.sqlite`: pointer only, **no OAuth tokens** |
| Mint | resolves the grant first; falls back to the browser binding while `RUNTIME_LEGACY_BINDING=on` |
| Rate limit | 600 mints/min, then 429 and the log line `mint rate limit exceeded` |
| `BFF_RUNTIME_GRANT_DAYS` | optional, 1..90, default 90 (Home enforces its own maximum) |

### Home site config (operator, no migrate)

Set on `home.episteck.com` before the first grant:

```bash
bench --site home.episteck.com set-config -p home_runtime_ids '["home-agent-primary"]'
bench --site home.episteck.com set-config -p home_runtime_grant_max_days 90
bench --site home.episteck.com set-config -p home_runtime_grantees '["<owner user>"]'
```

`-p` is required: without it `set-config` stores a plain string and the lists are
ignored (every grant is denied). Check the stored types before the first grant
(read-only; the file also holds secrets, so grep only these keys):

```bash
grep -E 'home_runtime' sites/home.episteck.com/site_config.json
# lists must look like ["..."], max days like 90 (no quotes)
```

An absent or empty `home_runtime_grantees` denies every grant. Use exactly one
grantee: the BFF keeps one grant per runtime.

### Per-person runtimes rollout (ADR-0017, plan 3 executes)

Adds `home-agent-ana`, which acts only as Ana and never reaches Finance. Follow in order.

**Preconditions (all done before the window):**

- `home-agent-ana` and the owner's Hermes user (uid 1003) have **no access** to the mint socket
  `/run/episteck/home-bff-mint/mint.sock`. Check `id home-agent-ana` and `id home-agent`:
  neither output may list the group `episteck-gw` (no `episteck-gw`). The `X-Runtime-ID` trust model needs `svc-home-gateway`
  to be the only client of that socket; otherwise an agent could call `/internal/mint` directly
  with a header of its choosing.
- The Linux user `home-agent-ana` exists (plan 3; Hermes and the Telegram bot are also plan 3).
- The new gateway config is staged at `/etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new`
  and passes the gateway-user config test below at that staging path. It is **not** at the live path.
- The nginx integration tests for 9937 (`deploy/gateway/tests/test_gateway_integration.py`) pass
  before step 3.3. The only run so far (WSL Ubuntu 24.04, nginx 1.24.0) does NOT satisfy this
  precondition. The throwaway `ubuntu:26.04` container run (the node's OS, nginx 1.28.3) must
  pass before step 3.3. Its exact command is under "Isolated integration harness", "Run
  record", in `deploy/gateway/README.md`. They test the repository file, so run them on the commit you staged from, and
  `cmp` must find the staged copy identical.
- The new nft table is rendered into a boot file staged at
  `/etc/episteck/nft/episteck-gateway.nft.new` and passes `nft --check`. It is not loaded. The
  renderer needs `home-agent-ana` to exist and refuses a uid that collides with root, 1003, the
  gateway or `www-data`.

**Staging commands.** Each writes only a `.new` file that nothing loads:

```bash
# Gateway config: a staging copy, tested at the staging path.
sudo install -m 0644 deploy/gateway/nginx-mcp-gateway.conf \
  /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new
sudo -u svc-home-gateway nginx -e /dev/stderr -t \
  -c /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new -p /etc/episteck/mcp-gateway/
cmp deploy/gateway/nginx-mcp-gateway.conf \
  /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new   # silent = identical

# nft: the boot file, with the delete-table prefix, checked but not loaded.
./deploy/gateway/render-nft.sh deploy/gateway/episteck-gateway.nft \
  /tmp/episteck-gateway-rendered.nft
{ echo "table inet episteck_gateway"; echo "delete table inet episteck_gateway"; \
  cat /tmp/episteck-gateway-rendered.nft; } > /tmp/episteck-gateway-boot.nft
sudo install -m 0644 /tmp/episteck-gateway-boot.nft /etc/episteck/nft/episteck-gateway.nft.new
sudo nft --check -f /etc/episteck/nft/episteck-gateway.nft.new
```

**Never put the new config at the live path before step 3.3.** The gateway service loads only
`/etc/episteck/mcp-gateway/nginx-mcp-gateway.conf`, so any reload, restart or reboot would serve
9937 in front of the old BFF, which mints `home-agent-primary` for anyone. Before step 3.1 no nft
rule guards 9937 either, so any local uid could reach it.

**Order matters, and every moment must fail closed.** The old gateway stamps no
`X-Runtime-ID`, so the new BFF refuses its mints (401, never a fallback to the primary). The
old BFF ignores `X-Runtime-ID` and always mints for `home-agent-primary`, so **never serve 9937
in front of a BFF older than this change**: Ana's uid would get the owner's identity. Hence the
BFF goes first, the gateway reload last, and the owner's bot is briefly refused in between.

**Steps:**

1. Merge. Home's code deploys on merge and has no effect until the site config below is set.
2. Set the Home site config (no migrate; `-p` is required):

   ```bash
   bench --site home.episteck.com set-config -p home_runtime_ids '["home-agent-primary","home-agent-ana"]'
   bench --site home.episteck.com set-config -p home_runtime_grantees_by_runtime \
     '{"home-agent-primary":["<owner user>"],"home-agent-ana":["<ana user>"]}'
   ```

   Put exactly one user per runtime in `home_runtime_grantees_by_runtime`. The BFF keeps one
   grant per runtime and refuses (409) to replace another person's live grant.

3. Maintenance window, in exactly this order. Keep it short.
   1. Install the staged nft boot file and load it through its unit. Port 9937 is then locked
      to Ana's uid and has no listener yet; the other rules are unchanged, so the owner's bot
      keeps working. Never run `nft -f` by hand alone: it does not survive a reboot, and without
      the delete-table prefix it appends duplicate rules.

      ```bash
      sudo install -m 0644 /etc/episteck/nft/episteck-gateway.nft.new \
        /etc/episteck/nft/episteck-gateway.nft
      sudo systemctl restart episteck-gateway-nft.service
      sudo nft list table inet episteck_gateway
      ```

      Expected: one `tcp dport 9937` accept rule for Ana's uid, followed by `tcp dport 9937 drop`.
      The 9934, `{ 9931, 9932, 9936 }` and 9935 rules are as before, each listed once.
   2. The BFF image is built from the merge SHA **before the window**, after extracting the
      archive on the node (`deploy/ops/README.md`):
      `deploy/ops/image-rollout.sh home-bff build <SHA>`. This step only runs preview, then
      apply. Roll out the BFF image with `deploy/ops/image-rollout.sh`, which updates both Quadlet
      units (`home-bff` and `home-bff-mint`) with `RUNTIME_IDS=home-agent-primary,home-agent-ana`
      and restarts `home-bff-mint` first. Keep `RUNTIME_LEGACY_BINDING=off` (`on` with more than
      one runtime is a startup error). First run the read-only preview and read the diff: the
      `Image=` and `RUNTIME_IDS` lines of each unit. Then apply:

      ```bash
      ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
        'sudo -n bash -s -- home-bff preview <SHA>' < deploy/ops/image-rollout.sh
      ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
        'sudo -n bash -s -- home-bff apply <SHA>' < deploy/ops/image-rollout.sh
      ```

      That is `deploy/ops/image-rollout.sh home-bff preview <SHA>`, then
      `deploy/ops/image-rollout.sh home-bff apply <SHA>`. From here the owner's bot gets 401.
      That is fail closed.
   3. Only now, install the staged gateway config at the live path and reload. Keep the old one
      for rollback:

      ```bash
      sudo cp -p /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf \
        /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.old
      sudo install -m 0644 /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new \
        /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf
      sudo -u svc-home-gateway nginx -e /dev/stderr -t \
        -c /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf -p /etc/episteck/mcp-gateway/
      sudo systemctl reload episteck-mcp-gateway.service
      ```

      9934 now stamps `home-agent-primary`, so the owner's bot works again. 9937 goes live for
      Ana's uid only and returns 401 until she grants.
4. **Immediately, and mandatory:** the owner logs in and re-grants `home-agent-primary` at
   `/runtime`. A browser session from before the deploy has no person reference, so `/runtime`
   first sends it to log in again. Grant rows from before this change have an empty
   `grantor_ref`: the mint still honours them, but until the re-grant the owner's page says "no
   tiene permiso" and "Cerrar sesión y revocar permiso" does not revoke that row.
5. Verify on the node. Each command's expected outcome follows it.
   - The owner's bot still answers, including on Finance.
   - Ana grants at `/runtime`; her page lists only `home-agent-ana`.
   - The mint refuses a request without `X-Runtime-ID` (the gateway user may use the socket):

     ```bash
     sudo -u svc-home-gateway curl -s -o /dev/null -w '%{http_code}\n' \
       --unix-socket /run/episteck/home-bff-mint/mint.sock -X POST http://x/internal/mint
     ```

     Expected: `401`.
   - The ports never cross. Each command is dropped by nft: no HTTP status, curl times out
     (exit 28) after 3 s.

     ```bash
     sudo -u home-agent curl --max-time 3 http://127.0.0.1:9937/gateway/home/
     sudo -u home-agent-ana curl --max-time 3 http://127.0.0.1:9934/gateway/home/
     ```

   - Ana's port has no Finance route:

     ```bash
     sudo -u home-agent-ana curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 \
       http://127.0.0.1:9937/gateway/finance/
     ```

     Expected: `404`.
   - Neither agent can reach the mint socket, so neither can choose its own `X-Runtime-ID`:

     ```bash
     sudo -u home-agent-ana curl --unix-socket /run/episteck/home-bff-mint/mint.sock -X POST \
       -H 'X-Runtime-ID: home-agent-primary' http://x/internal/mint
     sudo -u home-agent curl --unix-socket /run/episteck/home-bff-mint/mint.sock -X POST \
       -H 'X-Runtime-ID: home-agent-primary' http://x/internal/mint
     ```

     Expected for both: permission denied. curl cannot connect (exit 7) and gets no HTTP status.
6. Rollback, in reverse order:
   1. Restore the gateway config. Pick the case by how far the rollout got.

      **Before 3.3** the live config was never replaced and there is no `.old`. Remove only the
      staged copy. Nothing is reloaded:

      ```bash
      sudo rm /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new
      ```

      **After 3.3** restore `.old`, reload, then remove `.conf.new`. This removes 9937; the
      owner's bot gets 401 until the next step:

      ```bash
      sudo install -m 0644 /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.old \
        /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf
      sudo systemctl reload episteck-mcp-gateway.service
      sudo rm /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new
      ```

   2. Restore the old BFF image and Quadlets (`home-bff-mint` first):
      run the `rollback <BACKUP_DIR>` command that `apply` printed (`deploy/ops/image-rollout.sh`).
   3. The new nft table stays, boot file included. It is the old table plus one rule pair that
      only restricts 9937, which has no listener after step 6.1; every other rule is unchanged.
      Restoring the old boot file would only reopen 9937 to every local uid.
   Never serve 9937 in front of a BFF older than this change.

Person references are keyed on `HOME_DELEGATION_SECRET`: after rotating it, every person must
re-grant.

### Transition flag

`RUNTIME_LEGACY_BINDING` is `off` in both Quadlet units (public app and mint must
carry the same value). Only an explicit runtime grant lets the agent act; a browser
login no longer claims the runtime. Live since 2026-10-13 (see the verification
record below). To return to the transition behavior, set both units to `on` and
restart `home-bff-mint` first, then `home-bff`. Turning it back on is not a valid rollback
once a second person can log in: any login could claim the primary binding. With more than one
runtime in `RUNTIME_IDS`, `on` is also a startup error.

### Live verification (2026-10-13)

H5 live test **PASS**. Hermes answered "who am I" with no browser session
(`bff_session` = 0) and `last_mint_at` moved. After **Revoke** on `/runtime` the next
Hermes call had no identity. Both units were then set to
`RUNTIME_LEGACY_BINDING=off` (backup `/var/backups/episteck/h5-legacy-off-20261013T162114Z`,
diff exactly one line per unit, `NRestarts=0`, `/health` 200, flag `off` inside both
running containers). After a new **Conceder**, Hermes identified the user again and
`last_mint_at` moved after `granted_at`, so the grant alone carries the agent.
Not checked: that Home closed the revoked grant (only the BFF side was observed).

### Rollback

Install the previous image tag in both Quadlets, `daemon-reload`, restart
(`home-bff-mint` first), and restore the previous `nginx-home-bff.conf`. The browser
binding works again; grants that exist in Home are ignored without effect. The extra
`runtime_grant` table is harmless to an older image.
