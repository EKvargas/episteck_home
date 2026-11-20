# Runbook: Finance I2 (family exchanges) on Nuremberg

**Status:** prepared, not run. **Node:** `episteck-node1` (Nuremberg). **Date written:** 2026-11-19.
**Prerequisite:** I1 is live (every step of [finance-i1-nuremberg-bringup.md](finance-i1-nuremberg-bringup.md) done, including step 11). `SHA` is a `main` commit that contains all I2 PRs, the Olin skill and cron included.

One-sentence summary: build the I2 image by commit, restart the API and MCP on it, turn on description rules, register your own IBANs, install the new Olin skill and its scheduled delivery job, then do the first load in Telegram and watch the accounts last.

## Who runs what

Same markers as the I1 runbook: `[! OK]` (safe through the chat), `[OWN TERMINAL]` (a secret or personal identifier is typed: **never through the chat**), `[CLAUDE]` (read-only, afterwards). `[TELEGRAM]` means your own chat with Olin, never through Claude. Use the I1 helpers from the repo root, with the same ssh config:

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
# Read-only schema check: table names and counts only. It runs on the host as svc-finance
# with the system python3 (the node may lack the sqlite3 CLI), like spike S2 did on this WAL
# database: no container, no bind mount, and a mode=ro SQLite URI, so it cannot write. It
# never imports the app, so it never creates a table.
SCHEMA_CHECK() { $SSH "cd /; sudo -n -u svc-finance python3 -I - /srv/episteck/services/finance/data/finance.sqlite" <<'PY'
import sqlite3, sys
I2 = ("counterparty", "counterparty_alias", "exchange", "exchange_line", "funding",
      "funding_movement", "funding_exchange", "funding_share", "ledger_entry", "receipt",
      "allocation", "held_cash_statement", "payer_rule", "movement_role", "revocation",
      "intervention_log", "partner_identifier", "own_identifier", "account_watch",
      "pending_item", "ref_counter", "matcher_cursor")
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
missing = [t for t in I2 if t not in names]
print(f"I2 tables present: {len(I2) - len(missing)}/{len(I2)}; missing: {', '.join(missing) or 'none'}")
print("PRAGMA integrity_check:", db.execute("PRAGMA integrity_check").fetchone()[0])
if "matcher_cursor" in names:
    has = "start_rowid" in {r[1] for r in db.execute("PRAGMA table_info(matcher_cursor)")}
    rows = db.execute("SELECT COUNT(*) FROM matcher_cursor").fetchone()[0]
    unset = (db.execute("SELECT COUNT(*) FROM matcher_cursor WHERE start_rowid IS NULL")
             .fetchone()[0] if has else "n/a")
    print(f"matcher_cursor.start_rowid column: {has}; cursor rows: {rows}; "
          f"rows without a go-live mark: {unset}")
if "partner_identifier" in names:
    taught = "funding_id" in {r[1] for r in db.execute("PRAGMA table_info(partner_identifier)")}
    print(f"partner_identifier.funding_id column: {taught}")
PY
}
# Go-live checks (h) and (i) below: counts only, read-only, same pattern as SCHEMA_CHECK.
# KEY_CHECK copies description_key (it never imports the app): description keys that kept no
# sender word, and keys whose bank receipts name several payers.
KEY_CHECK() { $SSH "cd /; sudo -n -u svc-finance python3 -I - /srv/episteck/services/finance/data/finance.sqlite" <<'PY'
import sqlite3, sys
from collections import defaultdict
RAILS = {"ZELLE", "FROM", "PAYMENT", "TRANSFER", "ONLINE", "BANKING", "CONF#", "REF", "ID", "TO"}
def key(text):  # app.receivables.text.description_key
    kept, skip = [], False
    for tok in (text or "").upper().split():
        if skip:
            skip = False
            continue
        if tok.endswith("#"):
            skip = True
        if not any(c.isdigit() for c in tok):
            kept.append(tok)
    return " ".join(kept)
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
texts = [r[0] for r in db.execute(
    "SELECT m.remittance FROM movement m JOIN account a ON a.id=m.account_id "
    "WHERE a.currency='USD' AND m.amount_minor>0 AND m.status='BOOKED'")]
keys = {key(t) for t in texts} - {""}
bare = [k for k in keys if not set(k.split()) - RAILS]
print(f"USD credits: {len(texts)}; description keys: {len(keys)}; keys with no sender word left: {len(bare)}")
if "receipt" in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
    payers = defaultdict(set)
    for payer, text in db.execute(
            "SELECT r.payer_id, m.remittance FROM receipt r JOIN movement m ON m.id=r.movement_id "
            "WHERE r.kind='BANK' AND NOT EXISTS (SELECT 1 FROM revocation v "
            "WHERE v.table_name='receipt' AND v.target_id=r.id)"):
        payers[key(text)].add(payer)
    print(f"keys shared by several senders (bank receipts of several payers): "
          f"{sum(len(p) > 1 for p in payers.values())}")
PY
}
# PENDING_CHECK: PENDING outgoing payments older than about 5 days that still carry a live funding.
PENDING_CHECK() { $SSH "cd /; sudo -n -u svc-finance python3 -I - /srv/episteck/services/finance/data/finance.sqlite" <<'PY'
import sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
n = db.execute(
    "SELECT COUNT(*) FROM movement m WHERE m.status='PENDING' AND m.amount_minor<0 "
    "AND NOT EXISTS (SELECT 1 FROM movement s WHERE s.supersedes_id=m.id) "
    "AND COALESCE(m.booking_date, m.value_date) < date('now', '-5 days') "
    "AND EXISTS (SELECT 1 FROM funding_movement fm WHERE fm.movement_id=m.id "
    "AND NOT EXISTS (SELECT 1 FROM revocation v WHERE v.table_name='funding' "
    "AND v.target_id=fm.funding_id))").fetchone()[0]
print(f"PENDING outgoing payments older than 5 days with a live funding: {n}")
PY
}
# STALE_PENDING_CHECK, go-live check (j): PENDING rows never posted (no BOOKED row links to them)
# and older than about 5 days, counted per account and direction. Movement table only (I1).
STALE_PENDING_CHECK() { $SSH "cd /; sudo -n -u svc-finance python3 -I - /srv/episteck/services/finance/data/finance.sqlite" <<'PY'
import sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = db.execute(
    "SELECT m.account_id, a.currency, CASE WHEN m.amount_minor>0 THEN 'in' ELSE 'out' END AS d, "
    "COUNT(*) FROM movement m JOIN account a ON a.id=m.account_id WHERE m.status='PENDING' "
    "AND NOT EXISTS (SELECT 1 FROM movement s WHERE s.supersedes_id=m.id) "
    "AND COALESCE(m.booking_date, m.value_date) < date('now', '-5 days') "
    "GROUP BY m.account_id, a.currency, d ORDER BY m.account_id, d").fetchall()
for account, currency, direction, n in rows:
    print(f"account {account} ({currency}) {direction}: {n}")
print(f"open PENDING rows older than 5 days: {sum(r[3] for r in rows)}")
PY
}
```

What I2 changes: new tables in `finance.sqlite` (created when the new image opens the file, `CREATE TABLE IF NOT EXISTS`; I1 tables are never altered), the receivables tools on the MCP, the receivables routes on the API (loopback, only `www-data` reaches `:9935`), the matcher at the end of each sync, the Olin skill, and one Hermes cron job. **Never `VACUUM` `finance.sqlite`:** the matcher's cursor uses SQLite's implicit `rowid`, which `VACUUM` may renumber.

## Pre-deploy S1 and go-live checklist

Each item once; record the results on the I2 board (`docs/architecture/FINANCE_I2_PROGRESS.md` §5), facts only.

- **(a) Before step 6, the owner's S1 test `[! OK]`.** Two one-off jobs as `home-agent`, no figures in their prompts or replies. (Verified read-only on the node 2026-11-19: the operator may run `sudo -n -u home-agent`.)
  ```bash
  HAGENT="sudo -n -u home-agent -H env XDG_RUNTIME_DIR=/run/user/\$(id -u home-agent) /home/home-agent/.hermes/hermes-agent/venv/bin/hermes"
  $SSH "cd /; $HAGENT cron create --name i2-s1-a --deliver telegram 'in 2m' 'Prueba técnica S1a de Episteck. Llama una vez a mcp__finance__finance_overview sin argumentos. No escribas ninguna cifra, importe, saldo, banco ni nombre de cuenta. Escribe en español: Prueba S1a, el cron llamó a Finanzas: sí o no, y el código de error si lo hubo. Si puedes, ofrece dos botones A y B; si no, termina con: Responde P1 A o P1 B.'"
  $SSH "cd /; $HAGENT cron create --name i2-s1-b --deliver telegram 'in 4m' 'Prueba técnica S1b de Episteck. Llama una vez a mcp__finance__finance_overview sin argumentos. Si el resultado trae ok false, responde solo: Prueba S1b, error y el código. En cualquier otro caso tu respuesta final es exactamente [SILENT] y nada más.'"
  $SSH "cd /; $HAGENT cron list"
  ```
  Job A must arrive in your private chat. Note whether it shows buttons; tap one (or reply "P1 A") and check that your next chat with Olin receives it. Job B must send nothing (`[SILENT]`). Then remove both with `hermes cron remove` as `home-agent`: `$SSH "cd /; $HAGENT cron remove i2-s1-a; $HAGENT cron remove i2-s1-b; $HAGENT cron list"`. Verdict: `BUTTONS` changes only the skill's "Scheduled delivery (cron)" section and the job prompt, in a PR, before step 6; `CODE_REPLY` changes nothing.
- **(b) After the first real 06:35 or 18:35 UTC run `[CLAUDE]`: the job called Finance.** The gateway access log records the path only (no query, no body). (Verified read-only on the node 2026-11-19: readable with `sudo -n`, it already holds `/gateway/finance/` paths, eight space-separated fields per line: address, time, zone, method, path, protocol, status, bytes.)
  ```bash
  $SSH "sudo -n grep -E ':(06|18):3[5-9]:[0-9]{2} .*/gateway/finance/' /var/lib/episteck-mcp-gateway/access.log | tail -n 10"
  ```
  Expect `POST /gateway/finance/` lines with `200` a few seconds after :35. None means the job never reached Finance: check `HSTEP verify` (the job's last status).
- **(c) The first run is not `session_invalid`.** The cron session must carry a delegation: the delivered message (if anything was pending) is not the "No tengo una sesión válida…" line, and the lines in (b) show `200`, not `401` or `403`.
- **(d) What a clarify tap returns `[TELEGRAM]`.** The first time Olin shows buttons in the chat (an echo, or a `LINK_FUNDING` question), tap one and check that Olin answers that code with the tapped option: its reply names the result (for example "Enlazado (F<n>)"), and "¿qué tengo pendiente?" no longer lists the code. If a tap comes back as a label Olin cannot match, answer that kind by text ("P<n> <número>") until the skill is fixed.
- **(e) Cron output retention (owner decision).** Hermes keeps every cron run's output under `/home/home-agent/.hermes/cron/output`, figures and names included, even for `[SILENT]` runs. `HSTEP memory-scan` prints how many files there are. Keeping them is your decision; if you choose to prune, a suggested command (deletes files older than 14 days, prints nothing): `$SSH "sudo -n find /home/home-agent/.hermes/cron/output -type f -mtime +14 -delete"`.
- **(f) Before `HSTEP cron`: `--deliver telegram` targets your private chat.** It goes to `home-agent`'s Telegram home channel (set in B7). The S1 job A arriving in your private chat with the bot proves it; the skill allows figures only in a private chat with the owner.
- **(g) At step 6 and the first fire: the `cron list` format and `--skill`.** `HSTEP cron` must print the job's lines (its id, name and schedule) and a count of at least 1. If `hermes cron list` does not show the job name, the step stops after creating the job ("a job may exist"): remove it by id before re-running. At the first fire, the message follows the skill's format (codes, options numbered as Finance returned them), which shows that `--skill olin-finance` resolved from `/etc/episteck/hermes/skills`.
- **(h) No description key is shared by several senders `[CLAUDE]`.** Before step 3 (description rules on), then once a week during the first month. A payer rule keyed by a description that lost its sender's name would send one person's payment to another payer. `KEY_CHECK` (helpers above) prints counts only:
  ```bash
  KEY_CHECK
  ```
  Expect `keys with no sender word left: 0` and, once I2 runs, `keys shared by several senders (bank receipts of several payers): 0`. Anything else: turn description rules off (step 3 rollback) and stop until the developer has looked at the counts.
- **(i) No PENDING outgoing payment stays linked for long `[CLAUDE]`.** Once a week during the first month. A partner payment links while PENDING; a PENDING row older than about 5 days that still carries a funding may have been cancelled, or posted under another id. `PENDING_CHECK` (helpers above) prints one count:
  ```bash
  PENDING_CHECK
  ```
  Expect `0`. Anything else: ask Olin "¿qué cambios están pagados?" and compare with the bank; if the bank shows no such payment, undo that funding in the chat (`finance_reverse` of its `F<n>`): Olin then asks about the payment again.
- **(j) Before step 4 (go-live): old PENDING rows that never posted `[CLAUDE]`.** Run it in step 1, and again just before step 4 if days passed. I1 links a posted (BOOKED) row to the only open PENDING row of the same amount on its account, however old, so a PENDING row from before go-live that never posted (a cancelled pending, a card hold, a payment posted under another id) can take the place of the next movement of exactly that amount. I2 treats that movement as new (a question or a link, never silent history) unless it carries the PENDING row's id or was booked within 7 days of it (R65). `STALE_PENDING_CHECK` (helpers above) prints counts per account and direction only:
  ```bash
  STALE_PENDING_CHECK
  ```
  Expect `open PENDING rows older than 5 days: 0`. Anything else: nothing to undo; write the counts on the board. During the first weeks, Olin may ask about a credit or a partner payment of the same amount on that account: answer it as usual. If it is money you already counted in a starting balance (a pending that posted late under another id), answer "no es de intercambios" and say not to remember the sender. A movement booked within 7 days of such a row is read as its posting and is not asked about: during go-live week, compare the bank with Olin's balances for those accounts, and tell the developer if a family payment or a partner payment is missing (Olin cannot record a bank payment by hand).

## 1. Pre-check `[! OK]`

```bash
STEP verify
$SSH "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman ps --format '{{.Names}} {{.Image}}'"
```

Write down the image tag the units run now as `PREV_SHA`: it is the rollback target. Checklist item (a) decides how the scheduled message asks, before step 6.

**Rollback:** nothing changed.

## 2. Snapshot, ship and build by SHA `[! OK]`

A restic snapshot first, so the database before I2 can be restored:

```bash
$SSH "sudo -n systemctl start episteck-backup.service"
git archive "$SHA" services/finance deploy/finance \
  | $SSH "cd /; sudo -n -u svc-finance bash -c 'mkdir -p /srv/episteck/services/finance/build/$SHA && tar -x -C /srv/episteck/services/finance/build/$SHA'"
STEP build "$SHA"
# Smoke check inside the new image (no network, no data): the MCP tools must register on the
# image's Python before step 4 restarts anything. The first I2 deploy failed exactly here.
$SSH "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman run --rm --network none localhost/episteck-finance:$SHA python -c 'from fastmcp import FastMCP; from app.mcp.receivables_tools import register_receivables_tools; register_receivables_tools(FastMCP(\"smoke\"), None); print(\"MCP tools register OK\")'"
```

**Verify:** the backup journal says `Finance DB staged`; the last build line lists `localhost/episteck-finance:<SHA>`; the smoke check prints `MCP tools register OK`. Anything else: stop here, nothing has restarted.
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
SCHEMA_CHECK          # before: "I2 tables present: 0/22" and "PRAGMA integrity_check: ok"
STEP install "$SHA"
STEP verify
SCHEMA_CHECK          # after: "22/22; missing: none", "ok", "start_rowid column: True; cursor rows: 0",
                      #        "partner_identifier.funding_id column: True"
```

`install` rewrites the three units for `SHA` and restarts `finance-api` and `finance-mcp`; opening the file creates the I2 tables. `finance-sync.timer` is unchanged (about 06:20 and 18:20 UTC); its next run uses the new image, runs the matcher after the providers, and its first matcher run sets the go-live mark.

**Verify:** the I1 checks of step 6 (listeners, `/health`, `401` without a session, both containers running on `SHA`), the second `SCHEMA_CHECK` as above, and after the next sync `SCHEMA_CHECK` again: `cursor rows: 1; rows without a go-live mark: 0`. Right after `install`, `/health` may answer `Connection reset` while uvicorn starts: run `STEP verify` again after about 10 seconds. If `127.0.0.1:9936` is still not listed, the MCP is not running: roll back now.
**Rollback:** before step 6, `STEP install "$PREV_SHA"`; the I2 tables stay, inert (the I1 code never reads them). Once step 6 has installed the new skill, never roll back the image alone: the skill's `requires_tools` lists the receivables tools, and Hermes hides a skill when any of them is missing, so Olin would lose the balances too. Use "Rollback (everything)" below, Hermes first.

## 5. Your own IBANs `[OWN TERMINAL]`

List the account ids first `[! OK]`:

```bash
$SSH "$ADMIN list"
```

Once per account of yours that can send money to the accounts you will watch, so a transfer between your own accounts is never asked about. Finance keeps only the peppered hash. You type the IBAN at a hidden prompt, so the command **must** run with `ssh -t` and `podman run --rm -it`: without a terminal it reads standard input instead, and your terminal echoes the IBAN.

```bash
ssh -t -F <ssh config> episteck-node1 "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman run --rm -it \
  -v /srv/episteck/services/finance/data:/data:z -v /srv/episteck/services/finance/secrets:/secrets:ro,z \
  --env-file /srv/episteck/services/finance/config/finance.env \
  -e FINANCE_DB=/data/finance.sqlite -e FINANCE_SECRETS_DIR=/secrets -e FINANCE_PEPPER_FILE=/secrets/pepper \
  localhost/episteck-finance:$SHA python -m app.admin own-iban <account-id>"
```

`$SHA` expands in your own shell: set it there first, as in the helpers above. The prompt shows `IBAN:` and nothing you type. No account is watched yet: that is the last step of the first load (step 7).

**Rollback:** an own-IBAN hash only stops questions about transfers from that IBAN; I2 has no command to remove it.

## 6. Olin skill and scheduled delivery on `home-agent` `[! OK]`

Checklist items (a) and (f) first.

```bash
git archive "$SHA" deploy/hermes \
  | $SSH "cd /; sudo -n install -d -m 700 /var/lib/episteck/hermes-b9 && sudo -n tar -x -C /var/lib/episteck/hermes-b9"
HSTEP preflight   # Hermes version, finance route, finance keys, time zone (+0000) and config.yaml timezone (empty), job count
HSTEP install     # backs up config.yaml, installs the new skill, restarts the gateway
HSTEP cron        # creates the olin-finance-pending job, replacing one of the same name
HSTEP verify
```

`install` should report no key changes (the finance keys are already set). Note the `backup OK: /var/backups/episteck/hermes-b9-<UTC>` line it prints: that directory is the rollback target for this I2 install. The `cron` step refuses to run unless the installed skill is this commit's (with its "Scheduled delivery" section), the node is on UTC and `config.yaml` sets no other `timezone`. It runs, as `home-agent`:

```bash
hermes cron remove olin-finance-pending            # only when a job of that name is listed
hermes cron create --name olin-finance-pending --deliver telegram --skill olin-finance \
  "35 6,18 * * *" "<the delivery prompt in the script>"
hermes cron list                                     # the job's own lines are printed
```

**Verify (`[CLAUDE]`):** `HSTEP verify` shows the skill `644 root` and matching the commit, `home-agent cannot write the skill (expected)`, `finance tools listed: 15 (expect 15)` from `hermes mcp test finance`, and one `olin-finance-pending` job at `35 6,18 * * *` delivering to telegram with the skill `olin-finance`. After the next 06:35 or 18:35 UTC run, checklist items (b), (c) and (g). When nothing is pending, no message arrives.

**Rollback:** `HSTEP rollback-cron` removes the job only. For the skill, use "Rollback (everything)": an I1 skill would not work with the job, and no skill at all would hide the balances too.

## 7. First load (F8) and go-live `[TELEGRAM]`, then `[! OK]`

**When:** right after a sync (about 06:20 or 18:20 UTC; `STEP verify` shows the recent sync result), once `SCHEMA_CHECK` shows one cursor row, and finish before the next sync.

**Why:** the first matcher run after step 4 set the go-live mark at the newest movement. Movements up to that mark are history and are never asked about. Credits that arrive on an account before you watch it are passed too and are never asked about. So state the starting balances as the bank showed them at the last sync, and switch the watch on before the next sync.

In your chat with Olin, in this order (spec §7 F8). Answer each echo yourself; check each step with "¿quién me debe qué?".

1. **Counterparties.** Each person (alias, how they usually pay, `USD` or `EUR`, and where their payments arrive), each fund, and the exchange partner. Olin proposes each with `finance_setup_counterparty`. A fund starts with its starting balance unknown.
2. **Starting balances.** For each person who owes you or has money in your keeping today, the figure as the bank showed them at the last sync, with `APPROXIMATE` or `CONFIRMED` and where it comes from ("según el dueño, a fecha <fecha>"). Olin proposes each with `finance_record_opening`.
3. **Today's open exchange.** Forward the partner's screenshot; Olin proposes it with `finance_record_exchange`.
4. **The partner's IBAN.** You never type it. Finance learns it when you pick one of the partner's payments in a `PREVIOUS_UNPAID` (or `LINK_FUNDING`) question, which comes after the next exchange is registered and a sync has run. Nothing to do now.
5. **Watched accounts, last `[! OK]`.** Credits on a watched account are matched to a payer or asked about. Watch the USD account and the EUR account that receive family payments (ids from `$SSH "$ADMIN list"`):
   ```bash
   $SSH "$ADMIN watch-account <account-id> on"
   ```

**"No es de intercambios" saves a rule.** Answering an incoming payment with "No es de intercambios" remembers that sender by default: their later credits are not asked about again. Say "no lo recuerdes" for a one-off (Olin sends `remember` false). To undo it, ask Olin "¿qué marqué como no de intercambios?" (`finance_explain` with `ignored`) and undo the payment by its `undo_ref`, or the answer by its `P<n>`, through `finance_reverse`.

**Rollback:** `$SSH "$ADMIN watch-account <account-id> off"`. A wrong counterparty, balance or exchange is undone in the chat with `finance_reverse` of its reference (each through an echo); facts are never edited.

## 8. Daily check `[CLAUDE]`

A matcher failure never stops the sync's provider results, but the sync exits non-zero and logs `matcher failed: <type>` (no figures). After each sync, and in the daily check:

```bash
$SSH "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U journalctl --user -u finance-sync --since -1d --no-pager -o cat | grep -c 'matcher failed' || true"
```

**Verify:** `0`. Any other count: read the matching journal lines (exception types only) and fix it before the next sync. Until then new movements get no links, receipts or questions.

## Rollback (everything)

Hermes first, then the image:

1. `HSTEP rollback <backup-dir>` with the directory printed by step 6's `HSTEP install` (`backup OK: /var/backups/episteck/hermes-b9-<UTC>`), not the I1 one. It removes the job, the skill and the scanner, and restores `config.yaml` byte for byte.
2. Extract `PREV_SHA`'s `deploy/hermes` the same way as step 6 and run `HSTEP install`: the I1 skill is back.
3. `STEP install "$PREV_SHA"`: the units run the previous image. The I2 tables stay in `finance.sqlite`, inert.
4. Remove `FINANCE_DESCRIPTION_RULES` (step 3) and set the watched accounts `off` (step 7), or leave them: the I1 image ignores both.
5. Only if the database itself is wrong: restore `finance.sqlite` from the restic snapshot taken in step 2, with the units stopped.
