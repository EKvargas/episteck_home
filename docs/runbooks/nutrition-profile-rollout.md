# Runbook: Nutrition profile and onboarding rollout (backend, Ultron, Ana)

**Status:** prepared. Plan 1 (backend) and plan 2 (agents, this runbook) are merged on `main`; `SHA` is the merge commit of the backup-as-agent fix (`fix/nutrition-backup-as-agent`) or a later one. Nothing here has run on the node.
**Node:** `episteck-node1` (Nuremberg). **Date written:** 2026-11-23.
**Design:** `docs/superpowers/specs/2026-11-23-nutrition-profile-onboarding-design.md`, sections 6.8, 6.9 and 7.

One-sentence summary: roll out the Nutrition backend with profile versions and onboarding tools, install the shared `olin-nutrition` skill on Ultron (with an evening check-in) and on Ana's agent, then accept it live with Erick and Ana and watch it for a week.

## When to Use

After the owner has merged the backup-as-agent fix (`fix/nutrition-backup-as-agent`) to `main` and names the rollout. `SHA` is the merge commit of that fix (or a later one); it contains plans 1 and 2. Run the stages in order. A failed check stops the rollout at that stage, and that stage's Rollback is the only thing to run.

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
SSH="ssh -F $HOME/.ssh/config episteck-node1"   # $HOME expands here; Git Bash's has no spaces
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
| Mirror the check-in into Ultron's chat (on or off) | C2 | `mirror on`, or nothing |
| Ana's Telegram ID | C4 | `telegram <id>` argument |
| Ana's check-in time (HH:MM, Berlin) | C4 | `cron <HH:MM>` argument |
| Ana's due date | C4 | Ana tells her bot |

## Prerequisites

- Plan 2 merged to `main`; `SHA` recorded; local checkout at `SHA` (see above).
- Release 1 is live: Ana's agent (`home-agent-ana`) exists, is configured and has its gateway, grants and Telegram bot (release 1 runbook, `docs/runbooks/nutrition-r1-rollout.md`, B5 done; B6 is repeated in C4 only if Ana is not yet on her bot).
- SSH to `episteck-node1` (user `episteck`, passwordless `sudo -n`).

## C0. Baseline

1. `[PREP]` Put a fresh copy of `deploy/hermes` at `SHA` in `/var/lib/episteck/hermes-nutrition`. `NUT preflight` exits 2 without it, and staging it changes nothing live. The old directory moves aside to `.prev` first so no stale file remains (on a first install there is nothing to move). The command refuses when `.prev` already exists, because that is the copy C2's rollback puts back:

   ```bash
   $SSH 'if [ -e /var/lib/episteck/hermes-nutrition.prev ]; then echo "refusing: /var/lib/episteck/hermes-nutrition.prev exists; keep it, it is the copy C2 rollback puts back" >&2; exit 1; fi; if [ -d /var/lib/episteck/hermes-nutrition ]; then sudo -n mv /var/lib/episteck/hermes-nutrition /var/lib/episteck/hermes-nutrition.prev; fi' \
     && git archive $SHA deploy/hermes | $SSH 'sudo -n install -d -m 755 /var/lib/episteck/hermes-nutrition && sudo -n tar -x -C /var/lib/episteck/hermes-nutrition'
   ```

   If it refuses (an earlier staging run already moved a copy to `.prev`), keep `.prev` and replace only this plan's copy: `$SSH 'sudo -n rm -rf /var/lib/episteck/hermes-nutrition'`, then the `git archive` line on its own.

2. `[CLAUDE VERIFY]` Record the starting state (read-only):

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

   Expected: the baseline shows the running image, `ActiveState=active` and `NRestarts` (note it); `NUT preflight` and `ANA preflight` each end `preflight: all checks passed` (a failed check is listed and the script exits 1: fix it before C1; on a first install `NUT preflight` also says `/etc/episteck/hermes/skills/olin-nutrition absent (first install)`). One exception: `ANA preflight`'s memory (`MemAvailable` 900 MB) and disk (5 GB free) floors are install-time thresholds for creating Ana's agent; while her gateway is running, a failure of only those is recorded here, not a stop. `NUT preflight` also prints `cron.mirror_delivery: unset` (record it; C2 decides it) and `plan 1 backend: not live yet` (expected before C1; `install` refuses until it is live). The owner's and Ana's `NRestarts` are noted; the counts of `profile`, `intake` and `diary_entry` rows per person are written down (counts only). If a table name differs, the query fails: stop and look at the schema names before going on.

**Verification:** every command ran and the numbers are recorded.
**Rollback:** nothing live changed. To undo the staging: `$SSH 'sudo -n rm -rf /var/lib/episteck/hermes-nutrition && if [ -d /var/lib/episteck/hermes-nutrition.prev ]; then sudo -n mv /var/lib/episteck/hermes-nutrition.prev /var/lib/episteck/hermes-nutrition; fi'`.

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

   Expected: `verify: PASS`; the `curl` prints `401` (no delegation). Then count again, read-only. `profile_version` is created at startup, so it exists only from here on:

   ```bash
   $SSH 'cd /; sudo -n -u svc-nutrition env XDG_RUNTIME_DIR=/run/user/$(id -u svc-nutrition) podman exec -i nutrition python -' <<'PY'
   import sqlite3
   c = sqlite3.connect("file:/data/nutrition.sqlite?mode=ro", uri=True)
   print("profile_version", c.execute("select origin, count(*), count(distinct person_id) from profile_version group by origin").fetchall())
   print("intake", c.execute("select person_id, count(*) from intake group by person_id").fetchall())
   PY
   ```

   Expected: `profile_version` shows only the origin `MIGRATED`: one version-1 row per person who had a `profile` row in C0, so the two counts are equal and match C0's `profile` persons. That includes Ana's real release 1 row (her mode from B6, when she has one), not only legacy synthetic persons. No rows at all only when C0 counted no `profile` rows. Any other origin is a finding: stop. The `intake` counts equal C0's.

**Verification:** `verify: PASS`, the `401`, the MIGRATED-only `profile_version`, the unchanged `intake` count, `NRestarts` `0`.
**Rollback:** `ROLL nutrition rollback <BACKUP_DIR>` (the directory `apply` printed). It restores both Quadlets byte for byte and restarts them. Rolling back loses mode changes made on the new image. Do not run Ana's B6 (or C4) inside a rollback window.

## C2. Ultron

The fresh copy of `deploy/hermes` is already on the node from C0.

1. `[CLAUDE VERIFY]` `NUT preflight` again (C1 changed the backend). Expected: `preflight: all checks passed`, including the notes helper's dry run, and now `plan 1 backend: live`.
2. `[OPERATOR]` Install, then schedule the evening check-in (Berlin time, converted to UTC for Ultron's Hermes), then verify:

   ```bash
   NUT install
   NUT cron 21:45
   NUT verify
   ```

   `install` refuses, changing nothing, until the live Nutrition server lists `propose_profile` and `get_period_summary` (C1 done). It prints `backup OK: <dir>  (rollback: rollback <dir>)`. **Record that directory.** A re-run backs up notes that are already rewritten (`install` then warns `this backup holds already-rewritten notes; roll back with the first install's backup`), so rollback must use the FIRST install's directory.
3. `[OPERATOR INPUT]` **Owner decision: mirror the check-in into Ultron's chat.** Hermes stores a cron delivery in the chat session only with `cron.mirror_delivery: true`; Ultron has it unset (off). `NUT verify` prints the value.
   - `NUT mirror on`: the owner's "yes" after the check-in closes the day, because Ultron sees its own question. Finance's cron deliveries are then also mirrored into the chat session. `NUT mirror off` turns it off again. Each run backs up `config.yaml` (it prints the directory), changes only `cron.mirror_delivery` through Hermes' own config load/save, checks that no other key changed, then restarts the gateway.
   - Leave it off: a bare "yes" is not understood, because the chat has no check-in to answer. Say "cierra el día" or "close today" instead.
   - Known Hermes v0.21.2 quirk with mirroring on: the mirrored delivery is stored as a user turn (upstream issue #118863), so Ultron may read the check-in as if Erick wrote it. Watch for it in C3 step 7 and in C4 (Ana's agent mirrors since release 1).
4. Re-run `NUT cron 21:45` after each daylight-saving change, on the last Sunday of March and of October: next on **2027-03-28** and **2027-10-31**. Hermes v0.21.2 has no per-job timezone, and Ultron's Hermes reads cron times in UTC (Finance's job needs it), so the cron step fixes today's Berlin offset into the UTC time.

**Verification:** `NUT verify` ends `verify: all checks passed` (the 20 Nutrition tools listed, the job scheduled, `cron.mirror_delivery` as decided). Finance's cron job is still listed, next to the check-in:

```bash
$SSH 'sudo -n runuser -u home-agent -- env HOME=/home/home-agent /home/home-agent/.hermes/hermes-agent/venv/bin/hermes cron list --all'
```

Expected: `olin-finance-pending` and `olin-nutrition-checkin` both listed.
**Rollback:**
- `NUT rollback <dir>` with the first install's backup directory. It removes the check-in job, restores Ultron's notes byte for byte as home-agent (any edits Ultron made to them after the install are lost), and puts back the `olin-nutrition` skill an earlier install left, or removes the skill. It never touches `config.yaml`: install does not change it, so when it differs from the install-time backup (Finance, a model change, `NUT mirror`) rollback says `config.yaml differs from the install-time backup in <dir>; not touched`. Rollback exits 1 after the gateway restart when anything warned: read the warnings.
- If `NUT mirror on` was run: `NUT mirror off` (rollback leaves `config.yaml` alone).
- To remove only the check-in: `NUT rollback-cron`.
- The staged copy stays harmless. To put the previous one back, only when there is one: `$SSH 'if [ -d /var/lib/episteck/hermes-nutrition.prev ]; then sudo -n rm -rf /var/lib/episteck/hermes-nutrition && sudo -n mv /var/lib/episteck/hermes-nutrition.prev /var/lib/episteck/hermes-nutrition; fi'`.

## C3. Erick (acceptance, spec section 7, steps 2 to 4, 6 and 7)

Spec step 1 (Erick is the first live user, the tester is not used) is the setup here. `[OPERATOR]` On the owner's phone with Ultron, claim by claim:

1. Spec step 2: onboarding takes about ten messages and the summary shows targets with sources. After "sí", the profile is saved. The Hub's Perfil page arrives with plan 3 (deferred); until then check that `get_nutrition_profile` returns the same profile and targets.
2. Spec step 3: ask for a recommendation from "my last two days and today's match". Ultron answers against his targets using `get_period_summary`. Check its figures against that tool's result. The Hub's Días page arrives with plan 3 (deferred); the tool result stands in for it.
3. Spec step 4: change your weight. Today's targets change (`get_day_summary` for today shows the new targets) and yesterday does not (`get_day_summary` for yesterday is unchanged; the Días row check is deferred to plan 3).
4. Spec step 6: without a consent grant, Ultron does not read Ana's profile: ask Ultron for it, and it declines. This exercises the refusal through the skill, which acts only for the person `whoami` returns and never passes another id. The backend's fail-closed path (Home refuses a read without a grant) is covered by plan 1's tests, not here. The reverse needs her agent: `[OPERATOR]` ask Ana's bot for Erick's profile; it is refused. The app side of this check (Perfil) is deferred to plan 3.
5. Spec step 7, on a day Erick has not finished: the 21:45 check-in arrives and ends with `Was that everything today?`.
6. Spec step 7, on a day he has finished: the same job stays silent (no message).
7. Spec step 7: on an unfinished day, his answer to the check-in finishes the day (`get_day_summary` says `COMPLETE`): a bare "yes" with `NUT mirror on`, "close today" with it off (C2 step 3). With it on, check that Ultron treats the mirrored check-in as its own question, not as Erick's message (the v0.21.2 quirk, issue #118863). The averages in Días then include the day: deferred to plan 3; `get_period_summary` stands in.

`[CLAUDE VERIFY]` `NUT verify`, and the owner's `NRestarts` equals C0's.

**Verification:** all seven checks pass.
**Rollback:** C2's, then C1's. Do not roll back C1 or C2 while Ana's B6 mode changes are live: C1's rollback puts back the image that predates them and loses the mode changes made on the new image, and C2's comes before it. The owner decides first.

## C4. Ana

1. `[PREP]` Put a fresh copy of `deploy/hermes` at `SHA` in `/var/lib/episteck/hermes-ana`. Ana's installer now reads the shared skill at `skills/olin-nutrition/SKILL.md`, which the release 1 copy lacks. The release 1 copy moves aside to `.prev`, then a new one is extracted. The command refuses when `.prev` already exists: after a first run, `.prev` holds the release 1 copy that this stage's rollback needs, and moving the current copy over it would destroy it:

   ```bash
   $SSH 'if [ -e /var/lib/episteck/hermes-ana.prev ]; then echo "refusing: /var/lib/episteck/hermes-ana.prev exists; keep it, it holds the release 1 copy the C4 rollback needs" >&2; exit 1; fi; if [ -d /var/lib/episteck/hermes-ana ]; then sudo -n mv /var/lib/episteck/hermes-ana /var/lib/episteck/hermes-ana.prev; fi' \
     && git archive $SHA deploy/hermes | $SSH 'sudo -n install -d -m 755 /var/lib/episteck/hermes-ana && sudo -n tar -x -C /var/lib/episteck/hermes-ana'
   ```

   If it refuses on a second staging run, keep `.prev` (the release 1 copy) and replace only this plan's copy: `$SSH 'sudo -n rm -rf /var/lib/episteck/hermes-ana'`, then the `git archive` line on its own.

2. `[OPERATOR]` `ANA configure` installs the shared skill (it prints `rollback-config <dir>`; keep it). Then `[CLAUDE VERIFY]` `ANA verify`.
3. `[OPERATOR INPUT]` Rollout stage B6 of the release 1 runbook, with her phone. Skip the B6 parts already done, except `ANA cron <HH:MM>` (Berlin time): always re-run it, because a job keeps the prompt it was created with, and this commit's prompt adds her targets.
4. She sends her due date and confirms, then onboards: due date, weight before the pregnancy, the rest. Her agent mirrors cron deliveries since release 1 (`cron.mirror_delivery: true`): when she answers her first check-in, check that the agent treats it as its own question (the v0.21.2 quirk, issue #118863, C2 step 3).
5. Check: the energy target shows the second-trimester supplement.

**Verification:** `ANA verify` passes; step 5.
**Rollback:** the `ANA` helper pipes the SHA script, which needs the shared skill path the release 1 copy lacks, so run the release 1 installer that sits in the restored copy on the node instead.
1. Put the release 1 copy back (the fresh copy goes aside):

   ```bash
   $SSH 'sudo -n rm -rf /var/lib/episteck/hermes-ana.fresh && sudo -n mv /var/lib/episteck/hermes-ana /var/lib/episteck/hermes-ana.fresh && sudo -n mv /var/lib/episteck/hermes-ana.prev /var/lib/episteck/hermes-ana'
   ```

2. Run its installer from that copy, as a file (not through `ANA`). This brings back the release 1 SOUL, skill and check-in prompt:

   ```bash
   $SSH "sudo -n bash /var/lib/episteck/hermes-ana/deploy/hermes/install-home-agent-ana.sh configure"
   $SSH "sudo -n bash /var/lib/episteck/hermes-ana/deploy/hermes/install-home-agent-ana.sh cron <HH:MM>"   # always: C4 re-created the check-in with this commit's prompt
   $SSH "sudo -n bash /var/lib/episteck/hermes-ana/deploy/hermes/install-home-agent-ana.sh verify"
   ```

3. Use `ANA rollback-config <dir>` (the directory `configure` printed) only when `config.yaml` itself must be restored byte for byte.
4. Use `ANA stop` only to abandon Ana's agent entirely: it removes her check-in and stops her gateway and purge timer (config, `.env`, sessions and the login stay), and `ANA verify` fails afterwards.

## C5. Watch

For one week, each day, read-only:
- The check-ins arrived (`NUT verify`, `ANA verify`).
- Restart counts of both gateways against C0.
- Memory scan: `$SSH 'free -m'` and the gateways' RSS in `ANA verify`.
- Nutrition logs no errors (error lines only, both containers).

Later, once: when Ana reaches pregnancy week 28, her energy target steps up to the third-trimester supplement. Check it in a day review from her bot on the first day of week 28 (or the next).

**Rollback:** C4's, C2's, C1's, in that order. Do not roll back C1 or C2 while Ana's B6 mode changes are live: C1's rollback puts back the image that predates them and loses the mode changes made on the new image. The owner decides first.

## C6. Hub (plan 3)

Plan 3 adds three read-only Hub pages: Perfil (`/app/nutrition`), Hoy (`/app/nutrition/hoy`) and Días (`/app/nutrition/dias`, live in LIVE mode). `SHA` here is plan 3's merge commit. The Hub running today is `1ff95d8`; no Hub change has landed on `main` since. Nutrition and the agents are untouched by this stage.

1. `[PREP]` Record the running Hub image (read-only baseline; on 2026-11-24 it is `1ff95d8`):

   ```bash
   ROLL home-hub baseline
   ```

2. `[OPERATOR]` Build the Hub image from `SHA` (not used until `apply`):

   ```bash
   ROLL home-hub build $SHA
   ```

3. `[CLAUDE VERIFY]` Preview (read-only): `ROLL home-hub preview $SHA`. The `Image=` line is the only difference. Anything else stops the rollout.

4. `[OPERATOR]` Apply: `ROLL home-hub apply $SHA`. It backs up the Quadlet and prints the rollback command. Keep the printed backup directory.

5. `[CLAUDE VERIFY]` `ROLL home-hub verify` is `PASS`, and anonymous `/app/nutrition/dias` returns 307:

   ```bash
   $SSH 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9940/app/nutrition/dias'
   ```

6. `[OPERATOR INPUT]` Phone checks (spec 7, acceptance 2 to 6):
   - Ana's Perfil shows `Embarazo · 2.º trimestre`, `≈ 2.250 kcal` with its source line, and `24 nov: perfil creado por chat`.
   - Ana's Hoy shows `Energía: … de 2.250 kcal`.
   - Ana's Días (7 days) matches what her bot says for the same days.
   - Erick's Perfil shows the onboarding offer until he onboards (C3), then his targets.
   - Erick, without a consent grant, gets `Acceso restringido` on Ana's Perfil and Días, and the reverse.

7. `[CLAUDE VERIFY]` The Hub logs carry only `nutrition.<view> outcome=<KIND>` lines for these pages. Count the outcomes (counts only; no IDs, names or numbers):

   ```bash
   $SSH 'cd /; sudo -n -u svc-home-hub env XDG_RUNTIME_DIR=/run/user/$(id -u svc-home-hub) podman logs svc-home-hub 2>&1 | grep -o "nutrition\.[a-z]* outcome=[A-Z_]*" | sort | uniq -c'
   ```

**Verification:** `ROLL home-hub verify` is `PASS`, the anonymous `/app/nutrition/dias` check returns 307, the phone checks pass, and the logs show only outcome lines.
**Rollback:** `ROLL home-hub rollback <backup dir>` (the directory `apply` printed). Nutrition and the agents are untouched by this stage.

## Acceptance checklist

- [ ] C0: baselines and counts recorded; both preflights pass.
- [ ] C1: `ROLL nutrition verify` is `PASS`; `401` without delegation; `intake` count unchanged.
- [ ] C2: `NUT verify` passes; first install's backup directory recorded; the owner's mirror decision recorded (`NUT mirror on`, or off); Finance's job still listed.
- [ ] C3: all seven checks pass.
- [ ] C4: `ANA verify` passes; `ANA cron` re-run; second-trimester supplement shown.
- [ ] C5: seven days, no restarts, no errors; the third-trimester supplement checked at week 28.
- [ ] C6: ROLL home-hub verify PASS; anonymous /app/nutrition/dias 307; Ana's Perfil, Hoy and Días checked on her phone; access refused across people without consent.
