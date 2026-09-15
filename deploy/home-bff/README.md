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
```

## 5. Reverse proxy

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
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
