# Runbook: Nutrition release 1 rollout (Ana's agent, Hoy page, BLS)

**Status:** prepared. Part A (code, plans 1 to 3) is on branch `feature/nutrition-r1-ana-rollout` and not merged; nothing in this runbook has run on the node.
**Nodes:** `episteck-node1` (Nuremberg) and `episteck-home` (Ashburn). **Date written:** 2026-11-20.
**Design:** `docs/superpowers/specs/2026-11-18-nutrition-release-1-design.md`, ADR-0017 (per-person runtimes).

One-sentence summary: put the BLS reference file and the diary image on Nutrition, set up Ana's and a tester's Home users, open the per-person gateway, BFF and firewall window, roll out the Hub's Hoy page, prove Ana's Telegram agent with a synthetic person, then switch it to Ana and watch it for a week.

## When to Use

After the owner has merged Part A to `main` and names the rollout. `SHA` is the merge commit. Run the stages in order; a failed check stops the rollout at that stage, and that stage's Rollback is the only thing to run.

## Who runs what

The owner runs every production step. Claude prepares and verifies read-only.

| Label | Meaning |
| --- | --- |
| `[OPERATOR]` | The owner runs a live step. |
| `[OPERATOR INPUT]` | Only the owner has the value: a secret, an email, an ID, an approval. It never goes through the chat, an agent or git. |
| `[PREP]` | Writes on the node but changes nothing live (a staged file, an image build). Claude runs it only after the owner says go for that step. |
| `[CLAUDE VERIFY]` | Read-only. |

All `ssh` calls use `-F C:/Users/D064974/.ssh/config`. From a clean checkout of `SHA`, at the repo root:

```bash
SSH="ssh -F C:/Users/D064974/.ssh/config episteck-node1"
HOME_SSH="ssh -F C:/Users/D064974/.ssh/config episteck-home"
SHA=<40-character lowercase merge commit>
ROLL() { $SSH "sudo -n bash -s -- $*" < deploy/ops/image-rollout.sh; }                  # ROLL <component> <step> [arg]
ANA()  { $SSH "sudo -n bash -s -- $*" < deploy/hermes/install-home-agent-ana.sh; }      # ANA <step> [arg]
ARCHIVE() {                                                                              # ARCHIVE <account> <paths...>
  local acct=$1; shift
  git archive "$SHA" "$@" | $SSH "cd /; sudo -n -u $acct bash -c 'mkdir -p /home/$acct/build/$SHA && tar -x -C /home/$acct/build/$SHA'"
}
```

Part B's operator steps run in one interactive Git Bash window where this helper block is pasted once (paste it again in any new window). Each `!` command in Claude Code starts a fresh shell, so if a step is run as a `!` line, the helper block and the step go in the same `!` command.

`ROLL` and `ANA` pipe the script from the working tree, so the working tree must be at `SHA`. Neither script prints a secret, a token or an `.env` value.

## Owner inputs

| Input | Stage | How it is given |
| --- | --- | --- |
| Ana's login email | B2 | Typed by the owner in the Frappe desk |
| A tester email the owner controls | B2 | Desk |
| Bot token for a new BotFather bot for Ana | B5 | Secret drop, slot `telegram-ana` (Termius) |
| The owner's own Telegram ID (test phase) | B5 | `telegram <id>` argument |
| Ana's Telegram ID | B6 | `telegram <id>` argument |
| The ChatGPT device login | B5 | The owner opens the printed URL, enters the code and approves with the owner's ChatGPT account |
| The check-in time (HH:MM, Berlin) | B6 | `cron <HH:MM>` argument |
| The due date | B6 | Ana tells her bot; the owner checks the heading |

## Prerequisites

- Part A merged to `main`; `SHA` recorded. Home's code deploys on merge through the `episteck-deploy` job (it polls about every 5 minutes) and has no effect until the site config in B2 is set.
- **The gateway nginx harness on `ubuntu:26.04` has NOT been run yet, and it is mandatory before window step 3.3 (B3).** The only run so far was WSL Ubuntu 24.04 with nginx 1.24.0; the node runs nginx 1.28.3 on Ubuntu 26.04. The command is under "Isolated integration harness", "Run record", in `deploy/gateway/README.md`. It tests the repository file, so run it on the commit you stage from (`SHA`). Do not start B3 until it passes.
- SSH to `episteck-node1` (user `episteck`, passwordless `sudo -n`) and to `episteck-home` (Ashburn).
- The BLS source `.data/bls-4.0/BLS_4_0_2025_DE/BLS_4_0_Daten_2025_DE.xlsx` locally; the `nutrition-r1` venv (`PY` below is `C:\AIProjects\episteck-delivery-workspace\.venvs\nutrition-r1\Scripts\python.exe`).
- Termius with the `secret-drop-phone` key on the owner's phone.
- The owner's ChatGPT account, and a Telegram account for BotFather.
- At least 900 MB of `MemAvailable` on the node (the node has 3.8 GB in total; `preflight` checks it).

## B0. Preparation. Nothing goes live.

1. `[PREP]` Build `bls-4.0.sqlite` locally from the merged importer, record its hash and stage it. Run from the repo root in PowerShell:

   ```powershell
   PY services/nutrition/scripts/import_bls.py .data/bls-4.0/BLS_4_0_2025_DE/BLS_4_0_Daten_2025_DE.xlsx .data/bls-4.0/bls-4.0.sqlite
   (Get-FileHash .data/bls-4.0/bls-4.0.sqlite -Algorithm SHA256).Hash.ToLower()
   ssh -F C:/Users/D064974/.ssh/config episteck-node1 'mkdir -p /home/episteck/stage'
   scp -F C:/Users/D064974/.ssh/config .data/bls-4.0/bls-4.0.sqlite episteck-node1:/home/episteck/stage/bls-4.0.sqlite
   ```

   Expected: `wrote 7140 foods to ...`. Write down the hash. `Get-FileHash` prints uppercase hex and `sha256sum` lowercase, so `.ToLower()` makes the comparison in B1 exact. The file is never committed.
2. `[PREP]` Extract the archives and build the three images (the images are not used until each stage's `apply`):

   ```bash
   ARCHIVE svc-nutrition services/nutrition packages/nutrition-domain deploy/nutrition
   ARCHIVE svc-home-bff  services/home-bff deploy/home-bff
   ARCHIVE svc-home-hub  apps/home-hub deploy/home-hub
   git archive $SHA deploy/hermes | $SSH 'sudo -n install -d -m 755 /var/lib/episteck/hermes-ana && sudo -n tar -x -C /var/lib/episteck/hermes-ana'
   ROLL nutrition build $SHA
   ROLL home-bff build $SHA
   ROLL home-hub build $SHA
   ```

   Each `build` prints the image ID. The Hub image builds with `HOME_HUB_DATA_MODE=LIVE` set in its Dockerfile.
3. `[CLAUDE VERIFY]` Record the starting state (read-only):

   ```bash
   ROLL nutrition baseline
   ROLL home-bff baseline
   ROLL home-hub baseline
   ANA preflight
   $SSH 'free -m'
   $SSH 'sudo -n sha256sum /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf /etc/episteck/nft/episteck-gateway.nft'
   $SSH 'sudo -n runuser -u home-agent -- env HOME=/home/home-agent /home/home-agent/.hermes/hermes-agent/venv/bin/hermes cron list --all'
   $SSH 'sudo -n runuser -u home-agent -- env XDG_RUNTIME_DIR=/run/user/1003 systemctl --user show hermes-gateway.service -p NRestarts -p LoadState'
   curl -s -o /dev/null -w '%{http_code}\n' https://home.episteck.com/api/method/episteck_home.identity.session.get_grantable_runtimes
   ```

   Expected: each baseline shows the running image, `ActiveState=active` and the `NRestarts` to compare against later (note them); `preflight` ends `preflight: all checks passed` and says `home-agent-ana does not exist yet`; `free -m` is noted; the owner's `home-agent` `NRestarts` is printed (record it: B5.8 and B7 compare against it); the Finance job is in the owner's cron list; the last `curl` prints `403` (Home's new code is deployed and refuses an anonymous caller; a `404` means the deploy job has not run yet, so wait). The two `sha256` lines are the rollback reference for the gateway config and the nft boot file.
   - Also confirm: the `ubuntu:26.04` gateway harness has passed (see Prerequisites). It has not yet.

**Verification:** every command above ran, nothing live changed (the baselines match the live Quadlets).
**Rollback:** nothing live changed. Remove the staged file with `$SSH 'rm -f /home/episteck/stage/bls-4.0.sqlite'`, the build directories with `sudo -n -u <account> rm -rf /home/<account>/build/$SHA` and `/var/lib/episteck/hermes-ana`, and the images with `podman rmi` as each account.

## B1. Nutrition (plan 1 live, BLS in both containers)

1. `[OPERATOR]` Install the reference file (0750 directory and 0440 file, owned by `svc-nutrition`), then check the hash:

   ```bash
   $SSH 'sudo -n install -d -m 0750 -o svc-nutrition -g svc-nutrition /srv/episteck/services/nutrition/reference'
   $SSH 'sudo -n install -m 0440 -o svc-nutrition -g svc-nutrition /home/episteck/stage/bls-4.0.sqlite /srv/episteck/services/nutrition/reference/bls-4.0.sqlite'
   $SSH 'sudo -n sha256sum /srv/episteck/services/nutrition/reference/bls-4.0.sqlite'
   ```

   The `sha256sum` must equal B0.1's value, compared case-insensitively. The running containers do not mount it yet, so nothing changes.
2. `[CLAUDE VERIFY]` Preview the change (read-only, writes and restarts nothing):

   ```bash
   ROLL nutrition preview $SHA
   ```

   The `diff -u live rendered` per unit must be exactly: the `Image=` line, `Volume=/srv/episteck/services/nutrition/reference:/reference:ro`, `Environment=BLS_DB=/reference/bls-4.0.sqlite` and `Environment=DIARY_TZ=Europe/Berlin`. Anything else (a node-only line `apply` would drop) stops the rollout.
3. `[OPERATOR]` Apply:

   ```bash
   ROLL nutrition apply $SHA
   ```

   It backs up both Quadlets under `/var/backups/episteck/nutrition-<sha7>-<UTC stamp>/`, installs the rendered ones, prints the diff, restarts `nutrition` then `nutrition-mcp`, and prints the rollback command. Keep that backup directory name.
4. `[CLAUDE VERIFY]`

   ```bash
   ROLL nutrition verify
   ```

   Expected: `verify: PASS`, with `9930 /health 200`, the MCP answering, the person probe without delegation `401`, and in both `nutrition` and `nutrition-mcp` a first `Apfel` hit whose food id starts with `bls:`. Then, read-only:
   - The diary tables exist (names only):

     ```bash
     $SSH 'cd /; sudo -n -u svc-nutrition env XDG_RUNTIME_DIR=/run/user/$(id -u svc-nutrition) podman exec -i nutrition python -' <<'PY'
     import sqlite3
     c = sqlite3.connect("file:/data/nutrition.sqlite?mode=ro", uri=True)
     print(sorted(r[0] for r in c.execute("select name from sqlite_master where type='table'")))
     PY
     ```

     Expected to include `diary_day`, `diary_draft`, `diary_entry`, `diary_revision`. Their absence is a finding: stop.
   - Logs carry no food text. The image runs uvicorn with `--no-access-log` and `podman logs` writes the container's stderr to its own stderr, so the `2>&1` is inside the remote command. Both containers print `0`:

     ```bash
     for c in nutrition nutrition-mcp; do
       $SSH "cd /; sudo -n -u svc-nutrition env XDG_RUNTIME_DIR=/run/user/\$(id -u svc-nutrition) podman logs --tail 300 $c 2>&1" | grep -ci apfel
     done
     ```
   - `NRestarts` is `0` for both units (`ROLL nutrition baseline`).
   - The live Hub still answers: `$SSH 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9940/app/nutrition'` prints `307` (anonymous, to the login).

**Verification:** `verify: PASS` plus the four checks above.
**Rollback:** `ROLL nutrition rollback <BACKUP_DIR>` (the directory `apply` printed). It restores both Quadlets byte for byte and restarts them. The reference file may stay: the old image ignores it, and it ignores the diary tables too. To remove it: `$SSH 'sudo -n rm /srv/episteck/services/nutrition/reference/bls-4.0.sqlite'`.

## B2. Home (site config and desk only)

Nothing on the node changes in this stage.

1. `[OPERATOR]` In the desk at `home.episteck.com`, open OAuth Client "Episteck Home BFF" and tick **Skip Authorization**. This fixes the phone login that fires twice.
2. `[OPERATOR INPUT]` Create two Users, each with **Send Welcome Email** on, no roles (a Website User), and exactly one Person with **Linked User** set:
   - Ana's User, with `<Ana email>`. If a Person for Ana already exists, link that one instead of creating a new one.
   - The tester's User, with `<tester email>`, and Person `Prueba Nutrición (sintética)`.
3. `[OPERATOR]` Set the site config on Ashburn. The Ana runtime is mapped to the **tester** first. `-p` is required: without it `set-config` stores a plain string and the lists are ignored:

   ```bash
   $HOME_SSH
   cd ~/frappe-bench
   bench --site home.episteck.com set-config -p home_runtime_ids '["home-agent-primary","home-agent-ana"]'
   bench --site home.episteck.com set-config -p home_runtime_grantees_by_runtime \
     '{"home-agent-primary":["<owner user, as in home_runtime_grantees>"],"home-agent-ana":["<tester email>"]}'
   grep -E 'home_runtime' sites/home.episteck.com/site_config.json
   ```

   The lists must look like `["..."]` and the map like `{"...":["..."]}` (no surrounding quotes). Exactly one user per runtime: the BFF keeps one grant per runtime.
4. `[CLAUDE VERIFY]` Read-only SQL and config checks, counts and flags only (no names, no emails):
   - The OAuth client has `skip_authorization=1`.
   - Both users are enabled Website Users and each has exactly one Person (count of Person rows per `linked_user` is 1).
   - Each runtime has 1 grantee (read from the `home_runtime_grantees_by_runtime` key only).
   - An anonymous call still returns 403: `curl -s -o /dev/null -w '%{http_code}\n' https://home.episteck.com/api/method/episteck_home.identity.session.get_grantable_runtimes`.

**Verification:** the four checks above.
**Rollback:**
- Untick Skip Authorization.
- `bench --site home.episteck.com execute frappe.installer.update_site_config --args '["home_runtime_grantees_by_runtime","None"]'`.
- Set `home_runtime_ids` back: `bench --site home.episteck.com set-config -p home_runtime_ids '["home-agent-primary"]'`.
- Disable the two new Users in the desk (they are harmless while disabled).

## B3. BFF, gateway and firewall window

Follows `deploy/home-bff/README.md`, "Per-person runtimes rollout (ADR-0017)", and `deploy/gateway/README.md`. The order matters and every moment must fail closed: the old gateway stamps no `X-Runtime-ID`, so the new BFF refuses its mints; the old BFF ignores it and always mints `home-agent-primary`. **Never serve 9937 in front of a BFF older than this change.** Hence: nft, then BFF, then gateway.

**Prerequisites (all done before the window):**
- B0 to B2 done.
- **The `ubuntu:26.04` gateway integration run has passed.** It is not done yet; the WSL 24.04 / nginx 1.24.0 run does not satisfy this. Command in `deploy/gateway/README.md`, run on the `SHA` checkout. Expected: 9 passed.
- `id home-agent-ana` and `id home-agent` show no `episteck-gw` (checked in step 1).
- The new gateway config and the nft boot file are staged as `.new` files and tested (step 2); they are not at the live paths.

1. `[OPERATOR]` Create Ana's Linux user, then `[CLAUDE VERIFY]` it:

   ```bash
   ANA user
   $SSH 'id home-agent-ana; id home-agent'
   ```

   Expected: `user: all checks passed`; neither `id` lists `episteck-gw`; the uid of `home-agent-ana` is not 0, 1003, `svc-home-gateway`'s or `www-data`'s.
2. Stage the gateway and nft files. `[PREP]` writes only `.new` files that nothing loads:

   ```bash
   git archive $SHA deploy/gateway | $SSH 'sudo -n install -d -m 755 /var/lib/episteck/gateway-src && sudo -n tar -x -C /var/lib/episteck/gateway-src'
   ```

   Then, `[OPERATOR]`, on the node (`$SSH`, then `cd /var/lib/episteck/gateway-src`), the commands from `deploy/home-bff/README.md`:

   ```bash
   # Gateway config: a staging copy, tested at the staging path, as svc-home-gateway.
   sudo install -m 0644 deploy/gateway/nginx-mcp-gateway.conf \
     /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new
   sudo -u svc-home-gateway nginx -e /dev/stderr -t \
     -c /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new -p /etc/episteck/mcp-gateway/
   cmp deploy/gateway/nginx-mcp-gateway.conf \
     /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new   # silent = identical

   # nft: the boot file with the delete-table prefix, checked but not loaded.
   ./deploy/gateway/render-nft.sh deploy/gateway/episteck-gateway.nft \
     /tmp/episteck-gateway-rendered.nft
   { echo "table inet episteck_gateway"; echo "delete table inet episteck_gateway"; \
     cat /tmp/episteck-gateway-rendered.nft; } > /tmp/episteck-gateway-boot.nft
   sudo install -m 0644 /tmp/episteck-gateway-boot.nft /etc/episteck/nft/episteck-gateway.nft.new
   sudo nft --check -f /etc/episteck/nft/episteck-gateway.nft.new
   ```

   Expected: `nginx -t` says `syntax is ok` and `test is successful`; `cmp` prints nothing; `nft --check` prints nothing. The renderer needs `home-agent-ana` to exist and refuses a uid that collides with root, 1003, the gateway or `www-data`.
   `[CLAUDE VERIFY]` The live files are untouched: `$SSH 'sudo -n sha256sum /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf /etc/episteck/nft/episteck-gateway.nft'` equals B0.3's two lines.
3. `[CLAUDE VERIFY]` Preview the BFF change (read-only):

   ```bash
   ROLL home-bff preview $SHA
   ```

   Per unit (`home-bff-mint`, `home-bff`) the diff is `Image=` plus `RUNTIME_IDS=home-agent-primary,home-agent-ana`. `RUNTIME_LEGACY_BINDING` stays `off` (`on` with more than one runtime is a startup error). Anything else stops the window.
4. Window, in exactly this order. Keep it short.
   1. `[OPERATOR]` 3.1 On the node (`$SSH`): load nft. Port 9937 is then locked to Ana's uid and has no listener yet; the owner's bot keeps working. Never run `nft -f` by hand alone (it does not survive a reboot and appends duplicate rules):

      ```bash
      sudo cp -p /etc/episteck/nft/episteck-gateway.nft /etc/episteck/nft/episteck-gateway.nft.old
      sudo install -m 0644 /etc/episteck/nft/episteck-gateway.nft.new /etc/episteck/nft/episteck-gateway.nft
      sudo systemctl restart episteck-gateway-nft.service
      sudo nft list table inet episteck_gateway
      ```

      Expected: one `tcp dport 9937` accept rule for Ana's uid followed by `tcp dport 9937 drop`; the 9934, `{ 9931, 9932, 9936 }` and 9935 rules as before, each listed once. If the listing is not as expected, install `.old` back, restart the unit and compare its sha256 with B0.3's record (`sudo install -m 0644 /etc/episteck/nft/episteck-gateway.nft.old /etc/episteck/nft/episteck-gateway.nft`, `sudo systemctl restart episteck-gateway-nft.service`, `sudo sha256sum /etc/episteck/nft/episteck-gateway.nft`), then stop the window.
   2. `[OPERATOR]` 3.2 Roll out the BFF image:

      ```bash
      ROLL home-bff apply $SHA
      ```

      Keep the backup directory it prints. From here the owner's bot gets 401. That is fail closed.
   3. `[OPERATOR]` 3.3 On the node (`$SSH`): only now, with the `ubuntu:26.04` run passed, install the staged gateway config at the live path, test it as the gateway user and reload (the old one is kept for rollback):

      ```bash
      sudo cp -p /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf \
        /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.old
      sudo install -m 0644 /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new \
        /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf
      sudo -u svc-home-gateway nginx -e /dev/stderr -t \
        -c /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf -p /etc/episteck/mcp-gateway/
      sudo systemctl reload episteck-mcp-gateway.service
      ```

      9934 now stamps `home-agent-primary`, so the owner's bot works again. 9937 goes live for Ana's uid only and returns 401 until she grants.
5. `[OPERATOR]` **Immediately, and mandatory:** log in again at `bff.home.episteck.com/runtime` and re-grant `home-agent-primary`. A browser session from before the deploy has no person reference, so `/runtime` first sends it to log in again. Until the re-grant the owner's page says "no tiene permiso".
6. `[CLAUDE VERIFY]` README step 5, each with its expected outcome. `ROLL home-bff verify` runs from the repo root; the other commands run in an `$SSH` session on the node:

   ```bash
   ROLL home-bff verify
   # on the node:
   sudo -u svc-home-gateway curl -s -o /dev/null -w '%{http_code}\n' \
     --unix-socket /run/episteck/home-bff-mint/mint.sock -X POST http://x/internal/mint
   sudo -u home-agent curl --max-time 3 http://127.0.0.1:9937/gateway/home/
   sudo -u home-agent-ana curl --max-time 3 http://127.0.0.1:9934/gateway/home/
   sudo -u home-agent-ana curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 http://127.0.0.1:9937/gateway/finance/
   sudo -u home-agent-ana curl --unix-socket /run/episteck/home-bff-mint/mint.sock -X POST \
     -H 'X-Runtime-ID: home-agent-primary' http://x/internal/mint
   sudo -u home-agent curl --unix-socket /run/episteck/home-bff-mint/mint.sock -X POST \
     -H 'X-Runtime-ID: home-agent-primary' http://x/internal/mint
   ```

   Expected: `verify: PASS` (`/health` 200, the mint answers 401 without `X-Runtime-ID`); the mint call prints `401`; the two cross-port calls time out (curl exit 28, no HTTP status, dropped by nft); Ana's port has no Finance route (`404`); both socket calls fail with permission denied (curl exit 7). Ana's own grant is checked in B5.
   - The owner sends the owner's own bot one Home question and one Finance question. Both answer.

**Verification:** step 6 passes, and the owner's bot answers Home and Finance.
**Rollback:** README step 6, in reverse order. Never serve 9937 in front of the old BFF.
1. Restore the gateway config. Before 3.3 the live config was never replaced and there is no `.old`: remove only the staged copy, nothing is reloaded:

   ```bash
   sudo rm /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new
   ```

   After 3.3 restore `.old`, reload, then remove `.conf.new`. This removes 9937; the owner's bot gets 401 until the next step:

   ```bash
   sudo install -m 0644 /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.old \
     /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf
   sudo systemctl reload episteck-mcp-gateway.service
   sudo rm /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new
   ```

2. Restore the old BFF image and Quadlets (`home-bff-mint` first): `ROLL home-bff rollback <BACKUP_DIR>` (the directory `apply` printed).
3. The new nft table stays, boot file included. It is the old table plus one rule pair that only restricts 9937, which has no listener after step 1. Restoring the old boot file would only reopen 9937 to every local uid. Restore `episteck-gateway.nft.old` only if 3.1's listing was wrong (see 3.1).

## B4. Hub ("Hoy")

1. `[CLAUDE VERIFY]` Preview (read-only): `ROLL home-hub preview $SHA`. The diff is the `Image=` line only.
2. `[OPERATOR]` Apply: `ROLL home-hub apply $SHA`. Keep the backup directory it prints.
3. `[CLAUDE VERIFY]` `ROLL home-hub verify`. Expected: `verify: PASS`, the Hub reaches 9933 and 9930, 9931/9932/9934 are refused, and an anonymous `/app/nutrition/hoy` returns 307 to the login: `$SSH 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9940/app/nutrition/hoy'`.
4. `[OPERATOR]` On the phone, open `/app/nutrition/hoy`. Expected: `Sin registros hoy`, no `0 g`, no demo banner.

**Verification:** steps 3 and 4.
**Rollback:** `ROLL home-hub rollback <BACKUP_DIR>`.

## B5. Ana's agent, proven with the synthetic person

Her bot talks to the owner (allowlisted) and acts as the tester, so no real data is involved.

1. `[OPERATOR]` Install Hermes and her config, then her `.env` base (the Kimi fallback lines are copied root-to-root from the owner's `.env` and never shown):

   ```bash
   ANA install
   ANA configure
   ANA env
   ```

   `install` checks the installer's pinned sha256 and Hermes v0.21.2 at the pinned commit. `configure` backs up `config.yaml` (it prints `rollback-config <dir>`), installs the persona and the root-owned `olin-nutrition` skill under `/etc/episteck/hermes-ana/skills`, sets the config (model `openai-codex` / `gpt-5.6-sol`, fallback `kimi-coding` / `kimi-k2.6`, memory off, timezone `Europe/Berlin`) and leaves only the `skills` and `clarify` toolsets on Telegram and cron. Each ends `all checks passed`.
2. `[OPERATOR]` Install the updated `secret-drop` (it gains the `telegram-ana` slot; `deploy/secret-drop/README.md`), keeping the old copy:

   ```bash
   scp -F C:/Users/D064974/.ssh/config deploy/secret-drop/secret-drop episteck-node1:/home/episteck/stage/secret-drop
   $SSH 'sudo -n cp -p /usr/local/sbin/secret-drop /var/backups/episteck/secret-drop.before-ana && sudo -n install -m 0755 -o root -g root /home/episteck/stage/secret-drop /usr/local/sbin/secret-drop && sudo -n bash -n /usr/local/sbin/secret-drop'
   $SSH 'printf "9\n" | sudo -n /usr/local/sbin/secret-drop'
   ```

   The last command, a wrong slot number, must store nothing.
   - `[OPERATOR INPUT]` Create Ana's bot in @BotFather. In Termius (host `episteck-node1 (secret drop)`), pick slot `telegram-ana` and paste the token at the hidden prompt.
   - `[CLAUDE VERIFY]` The journal line `stored slot=telegram-ana` and the file mode:

     ```bash
     $SSH 'sudo -n journalctl -t secret-drop --since "15 min ago" --no-pager | grep -c "stored slot=telegram-ana"'
     $SSH 'sudo -n stat -c "%a %U %n" /home/home-agent-ana/.hermes/.env'
     ```

     Expected: the count is at least `1` (the line names the slot, never a value); `600 home-agent-ana`.
3. `[OPERATOR INPUT]` Allow the owner's own Telegram account (test phase) and make it the home channel: `ANA telegram <owner Telegram ID>`. It backs up `.env` and `config.yaml` first.
4. `[OPERATOR INPUT]` `ANA login`. It prints a URL and a device code; the owner opens the URL, signs in with the owner's ChatGPT account and enters the code (credential label `ana-codex`).
5. `[CLAUDE VERIFY]` `ANA login-check`. Expected: `ana-codex credential` listed, and both `openai-codex / gpt-5.6-sol answered ok` and `kimi-coding / kimi-k2.6 answered ok`.
6. `[OPERATOR]` Grant before her gateway starts (a gateway that starts with no grant retries the MCP connect on a backoff of up to 600 s). In a private browser window, log in as the tester at `bff.home.episteck.com/runtime`. Only `home-agent-ana` is listed; grant it. Then open `/app/nutrition/hoy` as the tester.
7. `[OPERATOR]` Start her gateway, then the media purge, then the check-in a few minutes ahead (Berlin time):

   ```bash
   ANA gateway
   ANA purge
   ANA cron <HH:MM, 5 minutes from now, Europe/Berlin>
   ```

   `gateway` installs with `--no-start-now`, adds the `MemoryMax=900M` drop-in, and only then starts it. Expected: `cgroup memory.max ... (900M)` and `home-agent gateway NRestarts unchanged`. `purge` installs the timer that deletes voice notes and images older than 10 minutes, checking every 10 minutes. `cron` creates `olin-nutrition-checkin`.
8. `[CLAUDE VERIFY]` `ANA verify`, then `$SSH 'free -m'`. Expected: `verify: all checks passed`; the owner's `home-agent` NRestarts equals B0.3's; `free -m` noted (compare with B0.3); the 9934 port times out for her user (curl exit 28).
   Before the first message, check that her gateway reaches 9937 (count only, never print log lines; they can contain her text). Expected: at least `1`. If it is `0`, wait and count again: Hermes retries the MCP connect with a growing backoff.

   ```bash
   $SSH 'sudo -n grep -cE "gateway/home/.*200" /home/home-agent-ana/.hermes/logs/agent.log'
   ```

   Then `[OPERATOR]` the owner sends Ana's bot one message ("hola"). A Telegram bot cannot message someone who never wrote to it, so this must happen before the first check-in time.

9. End to end, on the owner's phone with Ana's bot (spec 7, step A):
   1. A voice note, for example "un vaso de zumo de naranja y dos rebanadas de pan", gives a draft with `~` and `¿Lo guardo? (sí / corrige)`.
   2. `sí` gives `Guardado.` and the free-sugar figure. The tester's Hoy page shows the entry.
   3. A voice correction, "era un vaso grande", calls `correct_intake`, and Hoy shows the new figure.
   4. "una arepa" is saved as `sin dato`. Hoy shows `1 alimento sin contar`, never `0 g`.
   5. The check-in arrives, ending `¿Eso fue todo hoy?`. `sí` gives `Día cerrado.`, and Hoy shows `Día cerrado`.
   6. A photo gets `Todavía no leo fotos; dime qué es.`
   7. "¿qué tiempo hace?" gets `Solo te ayudo con tu diario de comidas.`
   8. `[CLAUDE VERIFY]` Positive control, right after the voice note: count the files in her audio cache (count only, as the agent user). Expected: at least `1`, so the next check proves deletion and not a wrong path:

      ```bash
      $SSH 'sudo -n -u home-agent-ana find /home/home-agent-ana/.hermes/cache/audio -type f 2>/dev/null | wc -l'
      ```

      Then 21 minutes or more after the voice notes, no audio file older than 21 minutes is left (file count only). A file is deleted once it is older than 10 minutes, by a timer that runs every 10 minutes, so it can live about 21 minutes:

      ```bash
      $SSH 'sudo -n find /home/home-agent-ana/.hermes/cache/audio /home/home-agent-ana/.hermes/audio_cache -type f -mmin +21 2>/dev/null | wc -l'
      ```

      Expected: `0`.
   9. `[CLAUDE VERIFY]` Neither Nutrition container logs food text. Ana's food goes through `/gateway/nutrition/` to `nutrition-mcp`, so check both (`2>&1` inside the remote command). Expected `0` each:

      ```bash
      for c in nutrition nutrition-mcp; do
        $SSH "cd /; sudo -n -u svc-nutrition env XDG_RUNTIME_DIR=/run/user/\$(id -u svc-nutrition) podman logs --tail 300 $c 2>&1" | grep -ciwE 'zumo|naranja|pan|arepa'
      done
      ```
   10. The owner's own bot still answers Home and Finance.

   Before 9.5, re-run `ANA cron <HH:MM, a few minutes ahead, Europe/Berlin>`: the 5-minute check-in from step 7 fires during steps 8 to 9.4, before the test entries exist, so it cannot show the `¿Eso fue todo hoy?` flow then.

**Verification:** steps 5, 8 and 9, every sub-step.
**Rollback:** `ANA stop` removes the check-in job and stops the gateway and the purge timer; config, `.env`, sessions and the login stay. To restore the config alone: `ANA rollback-config <dir>` (the directory `configure` or `telegram` printed). To undo the secret drop: `$SSH 'sudo -n install -m 0755 -o root -g root /var/backups/episteck/secret-drop.before-ana /usr/local/sbin/secret-drop'`. **Destructive, only if the owner wants it:** `ANA remove yes-delete-home-agent-ana` deletes the user and its home (it saves `.hermes` state, without the Hermes checkout, to a backup first). The Home mapping and grants stay harmless without the agent.

## B6. Switch to Ana

1. `[OPERATOR]` As the tester, revoke the grant at `/runtime`. Then disable the tester User in the desk. Ana's agent keeps its gateway running; it has no grant until step 4.
2. `[OPERATOR]` Map `home-agent-ana` to Ana's user (on Ashburn, as in B2.3):

   ```bash
   bench --site home.episteck.com set-config -p home_runtime_grantees_by_runtime \
     '{"home-agent-primary":["<owner user>"],"home-agent-ana":["<Ana email>"]}'
   ```

3. With Ana, on her phone (her grant comes first, so the restart in step 4 finds it):
   - She sets her password from the welcome email.
   - She logs in at `bff.home.episteck.com`.
   - She grants at `/runtime`; only `home-agent-ana` is shown.
   - She bookmarks `/app/nutrition/hoy`.
4. `[OPERATOR INPUT]` Only after Ana has granted: point her bot at Ana and set her check-in time (`telegram` restarts her gateway; re-running `cron` replaces the job, so there is never a second one):

   ```bash
   ANA telegram <Ana Telegram ID>
   ANA cron <Ana's check-in time, HH:MM Berlin>
   ```

   Before her first message, `[CLAUDE VERIFY]` that the restarted gateway reaches 9937 (count only, never print log lines; expected at least `1`, otherwise wait and count again: Hermes retries the MCP connect with a growing backoff):

   ```bash
   $SSH 'sudo -n grep -cE "gateway/home/.*200" /home/home-agent-ana/.hermes/logs/agent.log'
   ```

   Then Ana sends the bot one message ("hola") before her first check-in time: a Telegram bot cannot message someone who never wrote to it.

5. Ana writes to her bot: `Estoy embarazada; la fecha probable de parto es el <fecha>`. She confirms. The Hoy heading reads `Hoy · Embarazo, 2.º trimestre`.
6. `[CLAUDE VERIFY]` Checks:
   - `ANA verify` passes.
   - The BFF holds two live grants with distinct grantor references (counts only):

     ```bash
     $SSH 'cd /; sudo -n -u svc-home-bff python3 -I -' <<'PY'
     import sqlite3
     c = sqlite3.connect("file:/srv/episteck/services/home-bff/data/bff.sqlite?mode=ro", uri=True)
     print(c.execute("SELECT COUNT(*), COUNT(DISTINCT grantor_ref) FROM runtime_grant WHERE expires_at > strftime('%s','now')").fetchone())
     PY
     ```

     Expected: `(2, 2)` (counts only; never print a reference).
   - The 9937 gateway log shows 200s (`/var/lib/episteck-mcp-gateway`, status counts only).
   - The owner's bot is unaffected (Home and Finance still answer).
7. Claude updates the "Olin Household Guide" artifact and writes the rollout evidence to the deploy READMEs and `STATUS.md` in a docs PR.

**Verification:** steps 5 and 6.
**Rollback:** Ana revokes her grant at `/runtime` (until she does, or the grant expires, her agent keeps acting as her). Then set `home_runtime_grantees_by_runtime` back to the tester mapping, re-enable the tester User, and run `ANA telegram <owner Telegram ID>`. Or stop her agent: `ANA stop`. Ana keeps her Home user.

## B7. One week with Ana (spec 7)

Each day Claude checks read-only:
- The check-in was delivered (`ANA verify`, and the journal for `olin-nutrition-checkin`).
- Ana's agent and `home-agent` show no restarts (`NRestarts` against the value recorded in B0.3).
- Nutrition logs no errors (`podman logs ... 2>&1` for both containers, error lines only).
- Memory headroom (`free -m`, and the gateway's RSS in `ANA verify` against the 900 MB cap).

If her Spanish voice notes come out poorly, compare the `small` Whisper model with `base` on three of her recordings, and measure RAM before switching `stt.local.model` (spec 6.2).

Collect what annoyed Ana before extending the scope (plan 4).

**Rollback:** B5's, or B6's.

## Acceptance checklist

- [ ] B0: `wrote 7140 foods`; baselines recorded; `preflight` passes; the `ubuntu:26.04` gateway harness passed (9 passed).
- [ ] B1: `bls-4.0.sqlite` is 0440 with the recorded hash; `ROLL nutrition verify` is `PASS`; both containers return `bls:` for `Apfel`; the diary tables exist; NRestarts 0.
- [ ] B2: Skip Authorization on; Ana and the tester are enabled Website Users with one Person each; each runtime has one grantee; the anonymous call is 403.
- [ ] B3: nft table has the 9937 pair; `ROLL home-bff verify` `PASS`; 9934 and 9937 never cross; no Finance route on 9937; neither agent reaches the mint socket; the owner re-granted and the owner's bot answers Home and Finance.
- [ ] B4: `ROLL home-hub verify` `PASS`; anonymous `/app/nutrition/hoy` is 307; the phone shows `Sin registros hoy`.
- [ ] B5: `ANA verify` passes; `login-check` answers `ok` for both providers; memory and the owner's NRestarts unchanged; all ten end-to-end checks pass; no audio file older than 21 minutes remains; neither Nutrition container logs food text.
- [ ] B6: the tester's grant is revoked and the User disabled; Ana grants and sees only `home-agent-ana`; the heading reads `Hoy · Embarazo, 2.º trimestre`; two live grants with distinct grantor references; the owner's bot is unaffected.
- [ ] B7: seven days with a delivered check-in, no restarts, no Nutrition errors and memory headroom; what annoyed Ana is collected.
- [ ] Rollout evidence written to the deploy READMEs and `STATUS.md` in a docs PR.

## Parked for plan 4 (not in this rollout)

- **Nutrition data and display:**
  - USDA branded and FNDDS category fields for the free-sugar class.
  - The day shows the profile's current mode, not the stamped mode. This matters once past days are shown (Week view).
  - The protein, energy and DHA pregnancy references are unverified; nothing shows them yet.
  - `get_food_detail` has no error mapping.
- **Hub:**
  - Meal names and ml labels for drinks.
  - A "Hoy" entry in the main navigation (exact-match active state).
- **BFF (plan 2's "can wait" minors):**
  - Distinct log line for a Finance refusal of a known runtime.
  - Store-down 503 page may become 500.
  - Home asked twice when it is unreachable during a grant.
- **Home and gateway:**
  - The tester User can be deleted once the week with Ana has passed.
  - The gateway README's generic "Switch" block on a true first install.
