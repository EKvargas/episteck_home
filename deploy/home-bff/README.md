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

### Transition flag

`RUNTIME_LEGACY_BINDING` is set to `on` in both Quadlet units (public app and mint
must carry the same value). While `on`, a browser login still claims the runtime and
the mint falls back to that binding. After the live verification, change both units to
`off` (grant only) and restart `home-bff-mint` first, then `home-bff`.

### Rollback

Install the previous image tag in both Quadlets, `daemon-reload`, restart
(`home-bff-mint` first), and restore the previous `nginx-home-bff.conf`. The browser
binding works again; grants that exist in Home are ignored without effect. The extra
`runtime_grant` table is harmless to an older image.
