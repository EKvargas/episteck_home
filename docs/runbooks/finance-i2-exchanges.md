# Runbook: Finance I2 (family exchanges) on Nuremberg

**Status:** prepared, not run. **Node:** `episteck-node1` (Nuremberg). **Date written:** 2026-11-19.
**Prerequisite:** I1 is live (every step of [finance-i1-nuremberg-bringup.md](finance-i1-nuremberg-bringup.md) done, including step 11). `SHA` is a `main` commit that contains all I2 PRs, the Olin skill and cron included.

One-sentence summary: build the I2 image by commit, restart the API and MCP on it, turn on description rules, mark the watched accounts and your own IBANs, then install the new Olin skill and the scheduled job that delivers Finance's questions.

## Who runs what

Same markers as the I1 runbook: `[! OK]` (safe through the chat), `[OWN TERMINAL]` (a secret or personal identifier is typed: **never through the chat**), `[CLAUDE]` (read-only, afterwards). Use the I1 helpers from the repo root, with the same ssh config:

```bash
SSH="ssh -F <ssh config> episteck-node1"
STEP()  { $SSH "sudo -n bash -s -- $*" < deploy/finance/bringup.sh; }
HSTEP() { $SSH "sudo -n bash -s -- $*" < deploy/hermes/install-olin-finance.sh; }
SHA=<merged-commit>
PREV_SHA=<the image the units run now, from step 1>
# Same podman run as I1 step 7 (admin commands), with the image under test:
ADMIN="cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman run --rm \
  -v /srv/episteck/services/finance/data:/data:z -v /srv/episteck/services/finance/secrets:/secrets:ro,z \
  --env-file /srv/episteck/services/finance/config/finance.env \
  -e FINANCE_DB=/data/finance.sqlite -e FINANCE_SECRETS_DIR=/secrets -e FINANCE_PEPPER_FILE=/secrets/pepper \
  localhost/episteck-finance:$SHA python -m app.admin"
```

What I2 changes: new tables in `finance.sqlite` (created on first open, `CREATE TABLE IF NOT EXISTS`; I1 tables are never altered), the receivables tools on the MCP, the receivables routes on the API (loopback, only `www-data` reaches `:9935`), the matcher at the end of each sync, the Olin skill, and one Hermes cron job. **Never `VACUUM` `finance.sqlite`:** the matcher's cursor uses SQLite's implicit `rowid`, which `VACUUM` may renumber.

## 1. Pre-check `[! OK]`

```bash
STEP verify
$SSH "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman ps --format '{{.Names}} {{.Image}}'"
```

Write down the image tag the units run now as `PREV_SHA`: it is the rollback target.

Before this runbook, the owner's live S1 test (Task 13) decides how the scheduled message asks. If the cron message can carry buttons, only the skill's "Scheduled delivery (cron)" section changes, in a PR, before step 6.

**Rollback:** nothing changed.

## 2. Snapshot, ship and build by SHA `[! OK]`

A restic snapshot first, so the database before I2 can be restored:

```bash
$SSH "sudo -n systemctl start episteck-backup.service"
git archive "$SHA" services/finance deploy/finance \
  | $SSH "cd /; sudo -n -u svc-finance bash -c 'mkdir -p /srv/episteck/services/finance/build/$SHA && tar -x -C /srv/episteck/services/finance/build/$SHA'"
STEP build "$SHA"
```

**Verify:** the backup journal says `Finance DB staged`; the last build line lists `localhost/episteck-finance:<SHA>`.
**Rollback:** as I1 step 3 (remove the build directory and the image); nothing runs on it yet.

## 3. Description rules `[! OK]`

Spike S2 found the USD account's credit descriptions STABLE, so a payer rule may be keyed by the normalised description. Add the flag once (the file holds no secret):

```bash
$SSH "sudo -n -u svc-finance bash -c 'f=/srv/episteck/services/finance/config/finance.env; grep -q ^FINANCE_DESCRIPTION_RULES= \$f || echo FINANCE_DESCRIPTION_RULES=on >> \$f; grep -c ^FINANCE_DESCRIPTION_RULES=on \$f'"
```

**Verify:** the command prints `1`. The units read it at the restart in step 4; the sync at its next run.
**Rollback:** `$SSH "sudo -n -u svc-finance sed -i '/^FINANCE_DESCRIPTION_RULES=/d' /srv/episteck/services/finance/config/finance.env"`, then `STEP install` again on the running SHA.

## 4. Restart the API and MCP on the new image `[! OK]`

```bash
STEP install "$SHA"
STEP verify
```

`install` rewrites the three units for `SHA` and restarts `finance-api` and `finance-mcp`. `finance-sync.timer` is unchanged (about 06:20 and 18:20 UTC); its next run uses the new image and runs the matcher after the providers.

**Verify:** the I1 checks of step 6 (listeners, `/health`, `401` without a session, both containers running on `SHA`).
**Rollback:** `STEP install "$PREV_SHA"`. The I2 tables stay, inert: the I1 code never reads them.

## 5. Watched accounts and your own IBANs

List the account ids first `[! OK]`:

```bash
$SSH "$ADMIN list"
```

**Watched accounts `[! OK]`.** Credits on a watched account are matched to a payer or asked about (`EXPLAIN_INCOMING`). Watch the USD account and the EUR account that receive family payments:

```bash
$SSH "$ADMIN watch-account <account-id> on"
```

**Your own IBANs `[OWN TERMINAL]`.** Once per account of yours that can send money to a watched account, so a transfer between your own accounts is never asked about. Finance keeps only the peppered hash. You type the IBAN at a hidden prompt, so the command **must** run with `ssh -t` and `podman run --rm -it`: without a terminal it reads standard input instead, and your terminal echoes the IBAN.

```bash
ssh -t -F <ssh config> episteck-node1 "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman run --rm -it \
  -v /srv/episteck/services/finance/data:/data:z -v /srv/episteck/services/finance/secrets:/secrets:ro,z \
  --env-file /srv/episteck/services/finance/config/finance.env \
  -e FINANCE_DB=/data/finance.sqlite -e FINANCE_SECRETS_DIR=/secrets -e FINANCE_PEPPER_FILE=/secrets/pepper \
  localhost/episteck-finance:$SHA python -m app.admin own-iban <account-id>"
```

`$SHA` expands in your own shell: set it there first, as in the helpers above. The prompt shows `IBAN:` and nothing you type.

**Rollback:** `$SSH "$ADMIN watch-account <account-id> off"`. An own-IBAN hash only stops questions about transfers from that IBAN; I2 has no command to remove it.

## 6. Olin skill and scheduled delivery on `home-agent` `[! OK]`

Before the `cron` step, check that `home-agent`'s Telegram home channel is your private chat with the bot (set in B7): `--deliver telegram` sends there, and the skill allows figures only in a private chat with the owner.

```bash
git archive "$SHA" deploy/hermes \
  | $SSH "cd /; sudo -n install -d -m 700 /var/lib/episteck/hermes-b9 && sudo -n tar -x -C /var/lib/episteck/hermes-b9"
HSTEP preflight   # Hermes version, finance route, finance keys, node time zone (+0000), job count
HSTEP install     # backs up config.yaml, installs the new skill, restarts the gateway
HSTEP cron        # creates the olin-finance-pending job, replacing one of the same name
HSTEP verify
```

`install` should report no key changes (the finance keys are already set). The `cron` step refuses to run before the skill is installed or when the node is not on UTC. It runs, as `home-agent`:

```bash
hermes cron remove olin-finance-pending            # only when a job of that name is listed
hermes cron create --name olin-finance-pending --deliver telegram --skill olin-finance \
  "35 6,18 * * *" "<the delivery prompt in the script>"
hermes cron list                                     # the job's own lines are printed
```

**Verify (`[CLAUDE]`):** `HSTEP verify` shows the skill `644 root` and matching the commit, `home-agent cannot write the skill (expected)`, `hermes mcp test finance` listing `finance_overview` and the fourteen receivables tools, and one `olin-finance-pending` job at `35 6,18 * * *` delivering to telegram with the skill `olin-finance`. After the next 06:35 or 18:35 UTC run, `HSTEP verify` shows the job's last status; when nothing is pending, no message arrives. Then, in the chat, ask "¿cuánto me debe <alias>?" and check that the answer names its date and shows subtotals per currency.

**Rollback:** `HSTEP rollback-cron` removes the job only. To go back to the I1 skill, extract `PREV_SHA`'s `deploy/hermes` the same way and run `HSTEP install` again. `HSTEP rollback /var/backups/episteck/hermes-b9-<UTC>` removes the job, the skill and the scanner, and restores `config.yaml` byte for byte.

## 7. Daily check `[CLAUDE]`

A matcher failure never stops the sync's provider results, but the sync exits non-zero and logs `matcher failed: <type>` (no figures). After each sync, and in the daily check:

```bash
$SSH "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U journalctl --user -u finance-sync --since -1d --no-pager -o cat | grep -c 'matcher failed' || true"
```

**Verify:** `0`. Any other count: read the matching journal lines (exception types only) and fix it before the next sync. Until then new movements get no links, receipts or questions.

## Rollback (everything)

1. `HSTEP rollback /var/backups/episteck/hermes-b9-<UTC>` (job, skill, config), then re-install the I1 skill from `PREV_SHA` as in step 6.
2. `STEP install "$PREV_SHA"`: the units run the previous image. The I2 tables stay in `finance.sqlite`, inert.
3. Remove `FINANCE_DESCRIPTION_RULES` (step 3) and set the watched accounts `off` (step 5), or leave them: the I1 image ignores both.
4. Only if the database itself is wrong: restore `finance.sqlite` from the restic snapshot taken in step 2, with the units stopped.
