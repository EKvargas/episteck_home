# Runbook: Nutrition profile and onboarding rollout (backend, Ultron, Ana)

**Status:** prepared. Plan 1 (backend) is merged on `main`; plan 2 (agents, this runbook) is on branch `feature/nutrition-profile-agents`. Nothing here has run on the node.
**Node:** `episteck-node1` (Nuremberg). **Date written:** 2026-11-23.
**Design:** `docs/superpowers/specs/2026-11-23-nutrition-profile-onboarding-design.md`, sections 6.8, 6.9 and 7.

One-sentence summary: roll out the Nutrition backend with profile versions and onboarding tools, install the shared `olin-nutrition` skill on Ultron (with an evening check-in) and on Ana's agent, then accept it live with Erick and Ana and watch it for a week.

## When to Use

After the owner has merged plan 2 to `main` and names the rollout. `SHA` is the merge commit; it contains plan 1. Run the stages in order. A failed check stops the rollout at that stage, and that stage's Rollback is the only thing to run.

## Who runs what

The owner runs every production step. Claude prepares and verifies read-only.

| Label | Meaning |
| --- | --- |
| `[OPERATOR]` | The owner runs a live step. |
| `[OPERATOR INPUT]` | Only the owner has the value (an ID, a time, an approval). It never goes through git. |
| `[PREP]` | Writes on the node but changes nothing live (a staged file, an image build). Claude runs it only after the owner says go. |
| `[CLAUDE VERIFY]` | Read-only. |

## Preparation of the shell

The scripts are piped from the local checkout, so run everything from a local checkout of `SHA` (`git checkout $SHA`, or a worktree at `SHA`), at the repo root. Confirm it before the first command:

```bash
git rev-parse HEAD     # must print exactly $SHA
git status --short     # must print nothing
```

Then paste this helper block once into one interactive Git Bash window (again in any new window; each `!` command in Claude Code starts a fresh shell, so the block and the step go in the same `!` command):

```bash
SSH="ssh -F C:/Users/D064974/.ssh/config episteck-node1"
SHA=<40-character lowercase merge commit>
ROLL() { $SSH "sudo -n bash -s -- $*" < deploy/ops/image-rollout.sh; }                  # ROLL <component> <step> [arg]
ANA()  { $SSH "sudo -n bash -s -- $*" < deploy/hermes/install-home-agent-ana.sh; }      # ANA <step> [arg]
NUT() { $SSH "sudo -n bash -s -- $*" < deploy/hermes/install-olin-nutrition.sh; }
ARCHIVE() {                                                                              # ARCHIVE <account> <paths...>
  local acct=$1; shift
  git archive "$SHA" "$@" | $SSH "cd /; sudo -n -u $acct bash -c 'mkdir -p /home/$acct/build/$SHA && tar -x -C /home/$acct/build/$SHA'"
}
```

No script prints a secret, a token or an `.env` value.

## Owner inputs

| Input | Stage | How it is given |
| --- | --- | --- |
| Ultron's check-in time (HH:MM, Berlin; default `21:45`) | C2 | `cron <HH:MM>` argument |
| Ana's Telegram ID | C4 | `telegram <id>` argument |
| Ana's check-in time (HH:MM, Berlin) | C4 | `cron <HH:MM>` argument |
| Ana's due date | C4 | Ana tells her bot |

## Prerequisites

- Plan 2 merged to `main`; `SHA` recorded; local checkout at `SHA` (see above).
- Release 1 is live: Ana's agent (`home-agent-ana`) exists, is configured and has its gateway, grants and Telegram bot (release 1 runbook, `docs/runbooks/nutrition-r1-rollout.md`, B5 done; B6 is repeated in C4 only if Ana is not yet on her bot).
- SSH to `episteck-node1` (user `episteck`, passwordless `sudo -n`).

## C0. Baseline

`[CLAUDE VERIFY]` Record the starting state (read-only):

```bash
ROLL nutrition baseline
NUT preflight
ANA preflight
$SSH 'sudo -n runuser -u home-agent -- env XDG_RUNTIME_DIR=/run/user/1003 systemctl --user show hermes-gateway.service -p NRestarts -p LoadState'
$SSH 'sudo -n runuser -u home-agent-ana -- env XDG_RUNTIME_DIR=/run/user/$(id -u home-agent-ana) systemctl --user show hermes-gateway.service -p NRestarts -p LoadState'
$SSH 'cd /; sudo -n -u svc-nutrition env XDG_RUNTIME_DIR=/run/user/$(id -u svc-nutrition) podman exec -i nutrition python -' <<'PY'
import sqlite3
c = sqlite3.connect("file:/data/nutrition.sqlite?mode=ro", uri=True)
for t in ("profile", "intake", "diary_entry"):
    print(t, c.execute(f"select person_id, count(*) from {t} group by person_id").fetchall())
PY
```

Expected: the baseline shows the running image, `ActiveState=active` and `NRestarts` (note it); both preflights end `preflight: all checks passed`; the owner's and Ana's `NRestarts` are noted; the counts of `profile`, `intake` and `diary_entry` rows per person are written down (counts only). If a table name differs, the query fails: stop and look at the schema names before going on.

**Verification:** every command ran and the numbers are recorded.
**Rollback:** nothing changed.

## C1. Nutrition backend

1. `[PREP]` Extract the sources and build the image (not used until `apply`):

   ```bash
   ARCHIVE svc-nutrition services/nutrition packages/nutrition-domain deploy/nutrition
   ROLL nutrition build $SHA
   ```

2. `[CLAUDE VERIFY]` Preview (read-only): `ROLL nutrition preview $SHA`. The diff per unit is the `Image=` line only. Anything else stops the rollout.
3. `[OPERATOR]` Apply: `ROLL nutrition apply $SHA`. It backs up both Quadlets and prints the rollback command. Keep the backup directory name.
4. `[CLAUDE VERIFY]` `ROLL nutrition verify`, then:

   ```bash
   $SSH 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9930/profile/PSN-00013'
   ```

   Expected: `verify: PASS`; the `curl` prints `401` (no delegation). Then rerun the count query from C0. `profile_version` holds only MIGRATED rows, for the legacy synthetic persons, and the `intake` row count equals C0's.

**Verification:** `verify: PASS`, the `401`, the MIGRATED-only `profile_version`, the unchanged `intake` count, `NRestarts` `0`.
**Rollback:** `ROLL nutrition rollback <BACKUP_DIR>` (the directory `apply` printed). It restores both Quadlets byte for byte and restarts them. Rolling back loses mode changes made on the new image. Do not run Ana's B6 (or C4) inside a rollback window.

## C2. Ultron

1. `[PREP]` Put a fresh copy of `deploy/hermes` at `SHA` on the node. Move the old directory aside first so no stale file remains (on a first install there is nothing to move):

   ```bash
   $SSH 'if [ -d /var/lib/episteck/hermes-nutrition ]; then sudo -n rm -rf /var/lib/episteck/hermes-nutrition.prev && sudo -n mv /var/lib/episteck/hermes-nutrition /var/lib/episteck/hermes-nutrition.prev; fi'
   git archive $SHA deploy/hermes | $SSH 'sudo -n install -d -m 755 /var/lib/episteck/hermes-nutrition && sudo -n tar -x -C /var/lib/episteck/hermes-nutrition'
   ```

2. `[CLAUDE VERIFY]` `NUT preflight`. Expected: `preflight: all checks passed`, including the notes helper's dry run.
3. `[OPERATOR]` Install, then schedule the evening check-in (Berlin time, converted to UTC for Ultron's Hermes), then verify:

   ```bash
   NUT install
   NUT cron 21:45
   NUT verify
   ```

   `install` prints `backup OK: <dir>  (rollback: rollback <dir>)`. **Record that directory.** A re-run backs up notes that are already rewritten, so rollback must use the FIRST install's directory.
4. Re-run `NUT cron 21:45` after each daylight-saving change (last Sunday of March and of October).

**Verification:** `NUT verify` ends `all checks passed` (the 20 Nutrition tools listed, the job scheduled); Finance's cron job is still in the owner's list.
**Rollback:**
- `NUT rollback <dir>` with the first install's backup directory. It removes the check-in job and restores Ultron's notes byte for byte, so any edits Ultron made to them after the install are lost.
- To remove only the check-in: `NUT rollback-cron`.
- The fresh copy stays harmless. To put the previous one back: `$SSH 'sudo -n rm -rf /var/lib/episteck/hermes-nutrition && sudo -n mv /var/lib/episteck/hermes-nutrition.prev /var/lib/episteck/hermes-nutrition'`.

## C3. Erick (acceptance, spec 7 steps 2 to 4, 6, 7)

`[OPERATOR]` On the owner's phone with Ultron:

1. Onboarding with Ultron: profile questions, then the confirmation.
2. Ask for "my last two days and today's match". Check the figures against `get_period_summary`. The Hub's DÃ­as page arrives with plan 3.
3. Change your weight on a later day and check that yesterday is unchanged.
4. Ultron cannot see Ana's profile without her grant.
5. Check the 21:45 check-in arrives and ends with `Was that everything today?`.

`[CLAUDE VERIFY]` `NUT verify` and the owner's `NRestarts` equal C0's.

**Verification:** all five steps pass.
**Rollback:** C2's, then C1's.

## C4. Ana

1. `[PREP]` Put a fresh copy of `deploy/hermes` at `SHA` in `/var/lib/episteck/hermes-ana`. Ana's installer now reads the shared skill at `skills/olin-nutrition/SKILL.md`, which the release 1 copy lacks. Move the old directory aside first, then extract into a new one:

   ```bash
   $SSH 'if [ -d /var/lib/episteck/hermes-ana ]; then sudo -n rm -rf /var/lib/episteck/hermes-ana.prev && sudo -n mv /var/lib/episteck/hermes-ana /var/lib/episteck/hermes-ana.prev; fi'
   git archive $SHA deploy/hermes | $SSH 'sudo -n install -d -m 755 /var/lib/episteck/hermes-ana && sudo -n tar -x -C /var/lib/episteck/hermes-ana'
   ```

2. `[OPERATOR]` `ANA configure` installs the shared skill (it prints `rollback-config <dir>`; keep it). Then `[CLAUDE VERIFY]` `ANA verify`.
3. `[OPERATOR INPUT]` Rollout stage B6 of the release 1 runbook, with her phone, including `ANA cron <HH:MM>` (Berlin time). Skip the parts already done.
4. She sends her due date and confirms, then onboards: due date, weight before the pregnancy, the rest.
5. Check: the energy target shows the second-trimester supplement.

**Verification:** `ANA verify` passes; step 5.
**Rollback:** `ANA rollback-config <dir>` (the directory `configure` printed) restores the config; `ANA stop` removes the check-in job and stops her gateway. To put back the release 1 copy: `$SSH 'sudo -n rm -rf /var/lib/episteck/hermes-ana && sudo -n mv /var/lib/episteck/hermes-ana.prev /var/lib/episteck/hermes-ana'`. Then re-run `ANA configure` from that copy so the installed skill is the release 1 one.

## C5. Watch

For one week, each day, read-only:
- The check-ins arrived (`NUT verify`, `ANA verify`).
- Restart counts of both gateways against C0.
- Memory scan: `$SSH 'free -m'` and the gateways' RSS in `ANA verify`.
- Nutrition logs no errors (error lines only, both containers).

**Rollback:** C4's, C2's, C1's, in that order.

## Acceptance checklist

- [ ] C0: baselines and counts recorded; both preflights pass.
- [ ] C1: `ROLL nutrition verify` is `PASS`; `401` without delegation; `intake` count unchanged.
- [ ] C2: `NUT verify` passes; first install's backup directory recorded.
- [ ] C3: five steps pass.
- [ ] C4: `ANA verify` passes; second-trimester supplement shown.
- [ ] C5: seven days, no restarts, no errors.
