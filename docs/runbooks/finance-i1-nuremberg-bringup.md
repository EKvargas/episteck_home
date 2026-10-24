# Runbook: bring up svc-finance (I1) on Nuremberg

**Status:** prepared. Phase A and the Phase B code (H1 to H4) are merged in `main`; the BFF mint, gateway route and nft rule are already live on Nuremberg (2026-10-12). Finance itself is not installed yet.
**Node:** `episteck-node1` (Nuremberg). **Date written:** 2026-10-12.
**Prerequisite:** `SHA` is a `main` commit that contains `services/finance/app/home_control/` (PR #97 or later).

One-sentence summary: create the `svc-finance` user and directories, build one image from the merged commit, start the API and MCP on loopback, place secrets yourself, then enable the sync timer and add the backup block.

## Who runs what

| Marker | Meaning |
| --- | --- |
| `[! OK]` | Safe to run with `!` in the Claude session. The command text and output contain no secret. |
| `[OWN TERMINAL]` | Run in your own terminal, **never through the chat** or an agent. The command or its prompt handles a secret, and anything typed in a Claude session lands in the transcript. |
| `[CLAUDE]` | Claude does it afterwards, read-only. |

Every command below goes through `deploy/finance/bringup.sh`, which runs as root on the node and prints no secret content. All `ssh` calls use `-F C:/Users/D064974/.ssh/config`.

```bash
SSH="ssh -F C:/Users/D064974/.ssh/config episteck-node1"
STEP() { $SSH "sudo -n bash -s -- $*" < deploy/finance/bringup.sh; }   # from the repo root
SHA=<merged-commit>      # e.g. git rev-parse origin/main after the PRs merge
```

## 1. Pre-check `[! OK]`

```bash
STEP preflight
```

Expected: ports 9935 and 9936 print `free`, `svc-finance` does not exist, `podman`, `sqlite3`, `loginctl`, `runuser` present, enough disk and memory (the service needs about 150 MB).

**Rollback:** nothing changed.

## 2. User and directories `[! OK]`

```bash
STEP create-user
STEP create-dirs
```

Creates `svc-finance` (home `700`, linger on, subuid/subgid verified) and `/srv/episteck/services/finance/{data,secrets,config,build}` (mode `700`, owned by `svc-finance`; the parent is `root:root 755`, same shape as the other services).

**Verify:** the last command lists the four directories with `drwx------ svc-finance`.
**Rollback:** `STEP rollback-units` (no units yet, so a no-op) and, if the user must go, see Purge below.

## 3. Ship the code and build the image `[! OK]`

The commit is shipped from your checkout, so the node needs no GitHub access.

```bash
git archive "$SHA" services/finance deploy/finance \
  | $SSH "cd /; sudo -n -u svc-finance bash -c 'mkdir -p /srv/episteck/services/finance/build/$SHA && tar -x -C /srv/episteck/services/finance/build/$SHA'"
STEP build "$SHA"
```

**Verify:** the last line lists `localhost/episteck-finance:<SHA>`.
**Rollback:** `$SSH "sudo -n -u svc-finance rm -rf /srv/episteck/services/finance/build/$SHA"` and remove the image with `podman rmi` as `svc-finance`.

## 4. Non-secret config `[! OK]`

The workspace id is an opaque label, not a secret.

Optional: add `FINANCE_EB_ACCESS_CAP=<1-12>` to the same file to change the per-account unattended data requests allowed per rolling 24 h (default 4, counting every call). Lower it if a bank refuses earlier; raise it only with evidence from the live measurement.

```bash
$SSH "sudo -n -u svc-finance bash -c 'umask 077; echo FINANCE_WORKSPACE_ID=ws-home-erick > /srv/episteck/services/finance/config/finance.env'"
```

## 4b. Home machine credential `[OWN TERMINAL]`

Finance calls Home with its own Frappe API user. This script creates `finance-service@episteck.invalid` on Home (idempotent), generates its key and secret on the Home host, streams them into `secrets/home-auth.env` (mode `600`) on the node without printing them, and sets site config `home_finance_machine_user`. Run it from the repo root:

```bash
bash deploy/finance/provision-home-credentials.sh
```

It refuses to overwrite an existing `home-auth.env` (a new key rotates the secret); use `--rotate` on purpose. The API and MCP units require this file (`EnvironmentFile` has no optional form in Quadlet), so run this step **before** step 6 or the units fail to start.

**Verify:** the script prints `600 svc-finance .../home-auth.env`. Step 6 then starts the units with the credential loaded.
**Rollback:** `ssh ... "sudo -n rm -f /srv/episteck/services/finance/secrets/home-auth.env"` (the units will then fail to start until it is recreated), then on Home `bench --site home.episteck.com set-config home_finance_machine_user ""` and disable the user.

## 5. The pepper `[OWN TERMINAL]`

The pepper keys the IBAN hashes. It is generated **on the node** and never leaves it.

```bash
ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
  "sudo -n -u svc-finance bash -c 'umask 077; head -c 32 /dev/urandom | base64 > /srv/episteck/services/finance/secrets/pepper'"
```

> **Back this up yourself.** `secrets/` is excluded from the restic job (re-obtainable from providers), but the pepper is *not* re-obtainable: without it, hashes of counterparty IBANs cannot be recomputed after a restore. Copy it into your password manager from your own terminal (`ssh ... 'sudo cat .../secrets/pepper'`), never into the chat.

**Rollback:** `ssh ... "sudo -n rm -f /srv/episteck/services/finance/secrets/pepper"`.

## 6. Install and start the API and MCP `[! OK]`

```bash
STEP install "$SHA"
STEP verify
```

`install` refuses to run unless the pepper exists with mode `600` and `finance.env` has `FINANCE_WORKSPACE_ID`.

**Expected `verify` output:**

| Check | Expected |
| --- | --- |
| Listeners | `127.0.0.1:9935` and `127.0.0.1:9936` only |
| `/health` | `{"status":"ok"}` |
| `/overview` without a session | `401` |
| `/overview` with any session | `401` for an invalid session (Home rejects it). `503` means Home is unreachable or the credential is wrong |
| Containers | `finance-api` and `finance-mcp` running |

A `503` for an authenticated request is **correct** at this stage. It proves the service refuses everything until Home can answer.

**Rollback:** `STEP rollback-units` stops and removes the units; data and secrets stay.

## 7. Bootstrap the workspace `[! OK]`

No secret is involved. Use `podman run` with the same image (replace `<ERICK_PSN>` with your Person id from Home; you type it, I do not read it from Home):

```bash
$SSH "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman run --rm \
  -v /srv/episteck/services/finance/data:/data:z -v /srv/episteck/services/finance/secrets:/secrets:ro,z \
  --env-file /srv/episteck/services/finance/config/finance.env \
  -e FINANCE_DB=/data/finance.sqlite -e FINANCE_SECRETS_DIR=/secrets -e FINANCE_PEPPER_FILE=/secrets/pepper \
  localhost/episteck-finance:$SHA python -m app.admin init-workspace --name Home --owner <ERICK_PSN>"
```

Run `... python -m app.admin list` the same way to confirm. Commands are idempotent.

**Rollback:** `STEP purge --i-understand-this-deletes-financial-data` removes the database (nothing real is in it yet).

## 8. Provider connections `[OWN TERMINAL]`

Only after steps 1–7 pass. These steps read or write credentials. Do them from your own terminal.

**Account safety:** read-only credentials only. Enable Banking in restricted mode covers your own accounts. Nothing here can move money.

### 8a. SimpleFIN (Bank of America)

1. In SimpleFIN Bridge, create a setup token (you do this in the browser).
2. Put it on the node with a hidden prompt:
   ```bash
   ssh -t -F C:/Users/D064974/.ssh/config episteck-node1 \
     "sudo -u svc-finance bash -c 'umask 077; read -rsp \"setup token: \" t; echo; printf %s \"\$t\" > /srv/episteck/services/finance/secrets/simplefin-setup-token'"
   ```
3. Claim it. The Access URL is written to a `600` file and never printed; the setup token is burned by the claim:
   `... python -m app.admin claim-simplefin --setup-token-file /secrets/simplefin-setup-token --out /secrets/bofa.simplefin` (same `podman run` as step 7 but with `/secrets` mounted `rw`).
4. `shred -u` the setup token file on the node.
5. `add-connection --id bofa --provider simplefin --owner <ERICK_PSN>`.
6. `provider-accounts --connection bofa` prints one line per account the bridge offers: `reference | name | currency | institution`. It never prints a balance or the Access URL, but account names can carry the last digits of the account number, so run it in your own terminal. It uses one of SimpleFIN's daily requests.
7. `link-account` once per account you want (checking, savings), with `--provider-ref` set to the first column, for example:
   `link-account --id bofa-checking --connection bofa --provider-ref <reference> --institution "Bank of America" --type CURRENT --liquidity AVAILABLE --currency USD --owner <ERICK_PSN>` (use `--type SAVINGS` for savings). An account you do not link is never read.

**Rollback:** `rm` the `bofa.simplefin` file and the connection stays `PAUSED`/unused; revoke the token in SimpleFIN Bridge.

### 8b. Enable Banking (Sparkasse, Trade Republic cash)

Needs the PSD2 callback (B5, ADR-0013) live first: section 8c.

1. In the Enable Banking Control Panel (restricted mode) register the application with the redirect URL **exactly** `https://bff.home.episteck.com/finance/connect/callback`.
2. Copy the application's private key to the node and wrap it with the application id:
   ```bash
   scp -F C:/Users/D064974/.ssh/config <local-key.pem> episteck-node1:/home/episteck/eb.pem
   ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
     "sudo -n bash -c 'umask 077; python3 -c \"import json,sys; print(json.dumps({\\\"application_id\\\": sys.argv[1], \\\"private_key_pem\\\": open(sys.argv[2]).read()}))\" <APPLICATION_ID> /home/episteck/eb.pem > /srv/episteck/services/finance/secrets/sparkasse.enable_banking && chown svc-finance:svc-finance /srv/episteck/services/finance/secrets/sparkasse.enable_banking && shred -u /home/episteck/eb.pem'"
   ```
3. `add-connection --id sparkasse --provider enable_banking --owner <ERICK_PSN>` (it validates the file).
4. Find the bank's exact name (one call to `/aspsps`, no account data): `... python -m app.connect banks --connection sparkasse --country DE --match sparkasse` (same `podman run` as step 7).
5. Give consent. Use `ssh -t` so the command can wait while you approve:
   ```bash
   ssh -t -F C:/Users/D064974/.ssh/config episteck-node1 "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman run --rm \
     -v /srv/episteck/services/finance/data:/data:z -v /srv/episteck/services/finance/secrets:/secrets:ro,z \
     --env-file /srv/episteck/services/finance/config/finance.env \
     -e FINANCE_DB=/data/finance.sqlite -e FINANCE_SECRETS_DIR=/secrets -e FINANCE_PEPPER_FILE=/secrets/pepper \
     localhost/episteck-finance:$SHA python -m app.connect authorize --connection sparkasse --aspsp '<name from step 4>' --country DE"
   ```
   It prints the bank's consent link. Open it, approve with S-pushTAN, and the browser lands on `.../finance/connect/callback` ("return to the terminal"). Within seconds the terminal prints `authorized sparkasse until <date>` and one line per account: `reference | product | currency | linked/not linked`. The link and the wait last 15 minutes; on a timeout or a refusal nothing changes.
6. `link-account` each account you want, with `--provider-ref` set to its reference (the stable **`identification_hash`**), `--type CURRENT`, `--liquidity AVAILABLE`, `--currency EUR`. No second consent is needed: the session already maps every returned account, but only linked accounts are ever read.
7. **Trade Republic cash:** copy the same application JSON to `secrets/traderepublic.enable_banking` (mode 600, owner `svc-finance`) and repeat steps 3–6 with `--id traderepublic` and its bank name.

**Rollback:** `rm` the `.enable_banking` file; revoke the application's key in the Control Panel if it was exposed. Revoking the consent at the bank stops all reads; the connection then shows `REAUTH_REQUIRED`.

### 8c. Ship the PSD2 callback (B5) `[! OK]`

Once, after the B5 PR merges. Nothing here touches a secret.

1. New image and units: steps 3 and 6 with the new `SHA` (`STEP build "$SHA"`, then `STEP install "$SHA"`, which now restarts the API and MCP on the new image). The API unit now runs without uvicorn's access log, because the callback query carries the code and state.
2. nginx on the BFF vhost (the live file equals `deploy/home-bff/nginx-home-bff.conf` before B5):
   ```bash
   $SSH "sudo -n cp -a /etc/nginx/sites-available/home-bff.conf /etc/nginx/sites-available/home-bff.conf.pre-b5"
   scp -F C:/Users/D064974/.ssh/config deploy/home-bff/nginx-home-bff.conf episteck-node1:/home/episteck/home-bff.conf.b5
   $SSH "sudo -n install -m 644 -o root -g root /home/episteck/home-bff.conf.b5 /etc/nginx/sites-available/home-bff.conf && rm /home/episteck/home-bff.conf.b5 && sudo -n diff /etc/nginx/sites-available/home-bff.conf.pre-b5 /etc/nginx/sites-available/home-bff.conf; sudo -n nginx -t && sudo -n systemctl reload nginx"
   ```
   The diff must show only the new `location = /finance/connect/callback` block.

**Verify (`[CLAUDE]`):** `GET https://bff.home.episteck.com/finance/connect/callback?state=x` returns `400` (Finance answered), a `POST` returns `403`, `/finance/overview` returns `404`, and `journalctl --user -u finance-api` shows no request lines.
**Rollback:** `$SSH "sudo -n cp -a /etc/nginx/sites-available/home-bff.conf.pre-b5 /etc/nginx/sites-available/home-bff.conf && sudo -n nginx -t && sudo -n systemctl reload nginx"`, then `STEP install <previous SHA>`.

## 9. Backup block `[! OK]`

The existing job is `/etc/episteck/backup/episteck-backup.sh`, run as root. The change adds a consistent `.backup` of `finance.sqlite` plus `PRAGMA integrity_check`, and the `finance` tag. The existing `--exclude "/srv/episteck/services/*/secrets"` already keeps secrets out.

```bash
STEP apply-backup      # prints the diff; keeps a .bak-finance copy; checks bash -n
```

**Verify:** `$SSH "sudo -n systemctl start episteck-backup.service"` then check the journal for `Finance DB staged` (after step 8 there is data to stage; before it the log says `finance.sqlite not present yet`, which is fine).
**Rollback:** `STEP rollback-backup` restores the original script.

## 10. Enable the timer `[! OK]`

Only after at least one connection exists.

```bash
STEP enable-timer
```

Runs `finance-sync` at about 06:20 and 18:20 (±5 min). Two syncs use the whole conservative PSD2 budget of four data requests per account per day, so do not add times without measuring how the bank counts.

**Verify (`[CLAUDE]`):** `list-timers`, the first run's `journalctl` (statuses only, no amounts), and `python -m app.admin list`.
**Rollback:** `STEP rollback-units`.

## Purge (destructive) `[OWN TERMINAL]`

Deletes `svc-finance`, its database and its secrets. restic snapshots are untouched.

```bash
STEP purge --i-understand-this-deletes-financial-data
```

## Residual risks

- The pepper is the one secret that must be backed up out of band (step 5).
- PSD2 consent lasts at most the bank's `maximum_consent_validity` (about 180 days); the overview shows `REAUTH_DUE` seven days before.
- SimpleFIN and Enable Banking rate behaviour is unmeasured until the live gate; the budget cap is configuration.
- The units use `ReadOnly=true`, `NoNewPrivileges` and `DropCapability=ALL`. If a container refuses to start for a write error, check the journal before loosening any of them.

## Phase B (blocked until H5 merges)

H1 audience, H2 `authorize_batch` plus the real `HomeAuthorizer`, H3 Feature Activation (manual `bench migrate` on home), H4 `/gateway/finance/` route and nft rule, the PSD2 callback route on the BFF vhost, Telegram on `home-agent`, the `openai-codex` login (yours), the Olin Finance skill, and the live check Telegram → Hermes → gateway → Finance → Home.
