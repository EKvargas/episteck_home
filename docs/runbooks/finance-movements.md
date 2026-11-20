# Runbook: Finance movements and summary on Nuremberg

**Status:** prepared, not run. **Node:** `episteck-node1` (Nuremberg). **Date written:** 2026-11-20.
**Prerequisite:** I2 is live ([finance-i2-exchanges.md](finance-i2-exchanges.md), every step). `SHA` is a `main` commit that contains the movements PRs and Olin skill 2.1.0.

One-sentence summary: build the image by commit, restart the API and MCP on it, reinstall the Olin skill (2.1.0), time the two new tools on a copy of the database, then check them in Telegram.

What changes: two read-only MCP tools (`finance_movements`, `finance_summary`), one new answer `PARTNER` ("Es del socio (un favor)") in the `EXPLAIN_INCOMING` question, and the skill. No schema change, no new unit, no data written by the tools.

## Who runs what

Same markers and helpers as the I2 runbook: `[! OK]` (safe through the chat), `[CLAUDE]` (read-only, afterwards), `[TELEGRAM]` (your own chat with Olin, never through Claude). Define `SSH`, `STEP`, `HSTEP`, `SHA` and `PREV_SHA` exactly as in the "Who runs what" block of [finance-i2-exchanges.md](finance-i2-exchanges.md), with the same ssh config. `PYRO` is that runbook's read-only host-side pattern (`SCHEMA_CHECK` and its siblings): Python on the host as `svc-finance`, a `mode=ro` SQLite URI, counts only:

```bash
PYRO() { $SSH "cd /; sudo -n -u svc-finance python3 -I - /srv/episteck/services/finance/data/finance.sqlite"; }
```

`PREV_SHA` is the image the units run now (I2 step 1).

## 1. Build by SHA, then smoke test `[! OK]`

```bash
$SSH "sudo -n systemctl start episteck-backup.service"
git archive "$SHA" services/finance deploy/finance \
  | $SSH "cd /; sudo -n -u svc-finance bash -c 'mkdir -p /srv/episteck/services/finance/build/$SHA && tar -x -C /srv/episteck/services/finance/build/$SHA'"
STEP build "$SHA"
$SSH "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U podman run --rm --network none localhost/episteck-finance:$SHA python -c 'from fastmcp import FastMCP; from app.mcp.movements_tools import register_movements_tools; register_movements_tools(FastMCP(\"smoke\"), None); print(\"MOVEMENTS TOOLS OK\")'"
```

**Verify:** the last build line lists `localhost/episteck-finance:<SHA>`; the smoke check prints `MOVEMENTS TOOLS OK`. Anything else: stop, nothing has restarted.
**Rollback:** remove the build directory and the image; nothing runs on it yet.

## 2. Install and verify `[! OK]`

```bash
STEP install "$SHA"
STEP verify
sleep 10; STEP verify     # /health may answer "Connection reset" while uvicorn starts
```

**Verify:** both containers run on `SHA`, `/health` answers, `127.0.0.1:9936` is listed. Otherwise `STEP install "$PREV_SHA"` now (the skill is not installed yet, so the image alone may be rolled back).

## 3. Skill reinstall `[! OK]`

The same `HSTEP` step as I2 step 6, with its backup:

```bash
git archive "$SHA" deploy/hermes \
  | $SSH "cd /; sudo -n install -d -m 700 /var/lib/episteck/hermes-b9 && sudo -n tar -x -C /var/lib/episteck/hermes-b9"
HSTEP preflight
HSTEP install     # prints "backup OK: /var/backups/episteck/hermes-b9-<UTC>": note it, it is the rollback target
HSTEP verify
```

**Verify (`[CLAUDE]`):** the skill is `644 root` and matches the commit, and the job `olin-finance-pending` is still listed. `finance tools listed: 17 (expect 17)`.
**Rollback:** step 7 (extract `PREV_SHA`'s `deploy/hermes`, `HSTEP install`, `HSTEP verify`). Never `HSTEP rollback` alone: it removes the job and the skill.

## 4. Timing check `[CLAUDE]`

Budget: each call under 1 second. The live database is never opened read-write, and never from a container: `finance.sqlite` is in WAL mode, and a `mode=ro` open on a read-only bind mount cannot create the `-wal`/`-shm` files it needs once the database is idle. So the copy is made on the host, as `svc-finance`, the way `SCHEMA_CHECK` and `PYRO` read it: host `python3 -I`, a `mode=ro` URI and SQLite's backup API, into a private temporary directory (mode 0700, owned by `svc-finance`). The container mounts only that copy and runs the service on it with an allow-all authorizer stub (no Home call, no session). The directory holds real data, so the same step deletes it, whatever the outcome. The output is `elapsed=<s> ok=<bool>` lines only: no figures, no names.

```bash
$SSH "cd /; sudo -n -u svc-finance env SHA=$SHA bash -s" <<'SH'
set -u
U=$(id -u svc-finance)
WORK=$(mktemp -d /tmp/finance-timing.XXXXXX)    # mktemp: mode 0700, owned by svc-finance
trap 'rm -rf "$WORK"' EXIT                       # the copy holds real data: always removed
python3 -I - /srv/episteck/services/finance/data/finance.sqlite "$WORK/timing.sqlite" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
PY
cat > "$WORK/timing.py" <<'PY'
import sys, time
from datetime import date

sys.path.insert(0, "/srv/services/finance")  # python -I drops the working directory from the path
from app.authz import ANSWERED, BatchDecision, Decision
from app.config import Settings
from app.movements.service import MovementsService
from app.store.repo import FinanceRepository


class AllowAll:
    def __init__(self, actor):
        self.actor = actor

    def authorize(self, delegation, requirements):
        return BatchDecision(ANSWERED, self.actor, tuple(
            Decision(r.subject, r.domain, r.action, True, "stub") for r in requirements))


settings = Settings.from_env()
repo = FinanceRepository(settings.db_path, pepper=settings.pepper)
with repo.connection() as conn:
    row = conn.execute("SELECT person_id FROM workspace_member WHERE workspace_id=? AND role='OWNER'",
                       (settings.workspace_id,)).fetchone()
service = MovementsService(repo, AllowAll(row["person_id"]), settings.workspace_id,
                           description_rules=settings.description_rules)
for name, call in (("summary", lambda: service.summary("stub", str(date.today().year))),
                   ("movements", lambda: service.movements("stub"))):
    start = time.perf_counter()
    result = call()
    print(f"{name} elapsed={time.perf_counter() - start:.3f} ok={result.get('ok') is True}")
PY
env XDG_RUNTIME_DIR=/run/user/$U podman run --rm --network none \
  -v "$WORK":/work:z -v /srv/episteck/services/finance/secrets:/secrets:ro,z \
  --env-file /srv/episteck/services/finance/config/finance.env \
  -e FINANCE_DB=/work/timing.sqlite -e FINANCE_SECRETS_DIR=/secrets -e FINANCE_PEPPER_FILE=/secrets/pepper \
  "localhost/episteck-finance:$SHA" python -I /work/timing.py
SH
```

**Verify:** two lines, `ok=True`, `elapsed=` under 1. Slower, or `ok=False`: do not go on to step 5; send the developer the two lines. "cannot open the database" or "unable to open database file": the host copy failed (check the `svc-finance` read access and that `/tmp` has space), not the tools. An import or path error: only the `sys.path` line or the import names need adjusting (`Settings` is the class `app.deps` uses; the image holds `app` in `/srv/services/finance`).
**Rollback:** nothing to undo: the temporary directory is removed when the step ends. If the connection dropped mid-step, remove any `/tmp/finance-timing.*` directory as `svc-finance`.

## 5. Telegram smoke `[TELEGRAM]`

In your private chat with Olin, once each:

1. A month question: "¿cuánto gasté este mes?". Olin gives income, spending and net per currency, the family help person by person, what was set aside, and that the month is not over.
2. A family-help question: "¿cuánto ayudé a <alias> este año?". The amount matches what Olin showed for that person in the summary.
3. A search by amount: "busca el pago de <importe>". Olin names the kind of each hit; for an account that sends no text, he says it can only be found by amount and date.

**Verify:** each answer has figures from this turn only, never a sum across currencies. An `EXPLAIN_INCOMING` question now offers "Es del socio (un favor)" when exactly one partner is active.

## 6. Census `[CLAUDE]`

After two syncs (about 06:20 and 18:20 UTC), count what the bank sends. `finance-sync` runs as a user unit of `svc-finance`; it logs counts only:

```bash
$SSH "cd /; U=\$(id -u svc-finance); sudo -n -u svc-finance env XDG_RUNTIME_DIR=/run/user/\$U journalctl --user -u finance-sync --since -2d --no-pager -o cat | grep 'descriptor census'"
```

Record the lines (`rows` and `remittance_information` counts) on the board. An account with `remittance_information=0` is the one whose movements are only found by amount and date.

## 7. Rollback `[! OK]`

First, a read-only count of live `PARTNER_SIDE` roles (the `PARTNER` answer). The previous image does not know that role:

```bash
PYRO <<'PY'
import sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
print("live PARTNER_SIDE roles:", db.execute(
    "SELECT COUNT(*) FROM movement_role r WHERE r.role='PARTNER_SIDE' AND NOT EXISTS "
    "(SELECT 1 FROM revocation v WHERE v.table_name='movement_role' AND v.target_id=r.id)").fetchone()[0])
PY
```

It must print `0`. Otherwise reopen those answers with the new image first (`finance_reverse` of each `P<n>` in the chat), then run the count again.

Then, Hermes first (the skill lists the new tools, so rolling back the image alone would hide Olin's skill):

1. Extract `PREV_SHA`'s `deploy/hermes` as in step 3 (with `PREV_SHA` in place of `SHA`), then `HSTEP install` and `HSTEP verify`: the previous skill version (2.0.0) is back and `olin-finance-pending` is still listed. Do not use `HSTEP rollback` here: it removes the skill, the scanner and the job, and restores `config.yaml`. If it was used anyway, run `HSTEP install` from `PREV_SHA` and then `HSTEP cron`.
2. `STEP install "$PREV_SHA"`, then `STEP verify`. No schema change was made, so no data is restored.
