#!/bin/bash
# Olin Nutrition on the owner's Hermes agent "Ultron" (user home-agent, Hermes v0.21.2), plan 2:
# the shared olin-nutrition skill, Ultron's own nutrition notes turned into pointers to it, and
# the evening check-in. Ultron also runs Finance (install-olin-finance.sh): its skills root, its
# config.yaml and its UTC cron times stay as they are.
# NOT run by CI, NOT run by an agent: the owner runs install, cron and the rollbacks; Claude runs
# only the read-only steps (preflight, verify). Runbook: docs/runbooks/nutrition-profile-rollout.md.
#
# Extract the merged commit on the node first, from the repo root:
#   git archive <SHA> deploy/hermes | ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
#     'sudo -n install -d -m 755 /var/lib/episteck/hermes-nutrition && sudo -n tar -x -C /var/lib/episteck/hermes-nutrition'
# then, one step at a time:
#   ssh -F C:/Users/D064974/.ssh/config episteck-node1 'sudo -n bash -s -- <step> [arg]' < deploy/hermes/install-olin-nutrition.sh
#
# Steps: preflight | install | cron <HH:MM> | verify | rollback-cron | rollback <backup-dir>
# Never reads .env, auth.json, tokens or memory files. Never prints Ultron's notes, nor a
# config.yaml value other than the nutrition server's url and enabled, skills.external_dirs and
# timezone. Root never writes through a symlink under /home/home-agent: install and rollback
# refuse when a path they write, or a directory leading to it, is one (home_links).
set -euo pipefail
cd /

AGENT=home-agent
AGENT_HOME=/home/$AGENT
HHOME=$AGENT_HOME/.hermes
CONFIG=$HHOME/config.yaml
HERMES=$HHOME/hermes-agent/venv/bin/hermes
PY=/usr/bin/python3
SRC=/var/lib/episteck/hermes-nutrition/deploy/hermes
SKILLS_ROOT=/etc/episteck/hermes/skills
SKILL_DIR=$SKILLS_ROOT/olin-nutrition
NOTES=/home/home-agent/.hermes/skills/episteck-home-agent
BACKUPS=/var/backups/episteck

# The Nutrition MCP's 20 tools (plan 1): verify looks for each in `hermes mcp test nutrition`.
NUTRITION_TOOLS=(close_day confirm_intake confirm_profile correct_intake evaluate_meal
  get_day_summary get_diary_entry get_food_detail get_meal_plan get_nutrition_profile
  get_period_summary get_pregnancy_profile plan_menu propose_intake propose_meal_change
  propose_profile search_foods search_recipes set_nutrition_mode void_intake)

# The evening check-in, "M H * * *" in UTC: this Hermes reads cron expressions in the system zone
# (config.yaml has no `timezone`; Finance's job needs UTC), so the cron step converts the Berlin
# time with today's Berlin offset and must be re-run after each daylight-saving change. A failed
# run stays local. The prompt must not contain the job name (the job list is searched for it).
CRON_NAME=olin-nutrition-checkin
CRON_PROMPT='Scheduled evening check-in. Follow the skill section "Evening check-in (cron)".
1. Call mcp__home__whoami once, then mcp__nutrition__get_day_summary once with subject_person_id set to its actor_person_id and no date. Call no other tool and save nothing.
2. If day_status is COMPLETE, or a call returns an error other than an access refusal, your whole final response is exactly [SILENT].
3. If a call returns an access refusal, reply with the permission line from the skill and stop.
4. Otherwise write ONE short message in English as that section says. It names the day it is about as day and month, no weekday (for example 20 November), taken from the date of get_day_summary. It gives the free sugars against the reference and the uncounted items, or says that nothing is logged yet. When profile_version is not null, it also gives energy and protein from nutrients against their targets. The message ends with exactly: Was that everything today?'

as_agent() {  # stdin is /dev/null so no command can swallow the rest of this piped script
  local u; u="$(id -u "$AGENT")"
  runuser -u "$AGENT" -- env "HOME=/home/$AGENT" "XDG_RUNTIME_DIR=/run/user/$u" \
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus" "$@" </dev/null
}
restart_gateway() {
  as_agent systemctl --user restart hermes-gateway.service
  sleep 5
  as_agent systemctl --user show hermes-gateway.service -p ActiveState -p NRestarts
}
need_src() {  # the files of the merged commit, extracted on the node (see the top)
  local f
  for f in skills/olin-nutrition/SKILL.md ultron_nutrition_notes.py \
           home-agent/nutrition-pointer-section.md home-agent/nutrition-diary-pointer.md; do
    if [ ! -f "$SRC/$f" ]; then
      echo "extract deploy/hermes of the merged commit into /var/lib/episteck/hermes-nutrition first ($f is missing)" >&2
      exit 2
    fi
  done
}
need_notes() {
  [ -f "$NOTES/SKILL.md" ] && [ -f "$NOTES/references/nutrition-diary.md" ] \
    || { echo "Ultron's notes are not where this step expects them ($NOTES): nothing was changed" >&2; exit 2; }
}
home_links() {  # the symlinks among the paths install or rollback writes as root or writes into,
  # and the directories leading to them, all in the agent's home; on one line (empty when none)
  local p found=""
  for p in "$AGENT_HOME" "$HHOME" "$CONFIG" "$HHOME/skills" "$NOTES" "$NOTES/SKILL.md" \
           "$NOTES/references" "$NOTES/references/nutrition-diary.md"; do
    if [ -L "$p" ]; then found="$found $p"; fi
  done
  echo "${found# }"
}
refuse_links() {  # root never writes through a symlink into the agent's home: stop before any change
  local links; links="$(home_links)"
  if [ -n "$links" ]; then
    echo "refusing: symlink under $AGENT_HOME ($links); nothing was changed. Look at it by hand." >&2
    exit 1
  fi
}
same() {  # two files with the same sha256
  [ "$(sha256sum < "$1")" = "$(sha256sum < "$2")" ]
}
contains() {  # file $1 holds the text of file $2; prints nothing
  "$PY" -I -c 'import sys
read = lambda p: open(p, encoding="utf-8", newline="").read()
raise SystemExit(0 if read(sys.argv[2]).strip("\n") in read(sys.argv[1]) else 1)' "$1" "$2" </dev/null
}
nutrition_keys() {  # the keys this step relies on; exit 1 when Ultron cannot load the skill or reach the server
  "$PY" -I - "$CONFIG" "$SKILLS_ROOT" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
servers = c.get("mcp_servers") or {}
nut = servers.get("nutrition") if isinstance(servers.get("nutrition"), dict) else {}
dirs = (c.get("skills") or {}).get("external_dirs")
print("mcp_servers:", sorted(servers))
print("mcp_servers.nutrition.url:", nut.get("url"))
print("mcp_servers.nutrition.enabled:", nut.get("enabled"))
print("mcp_servers.nutrition keys:", sorted(nut))
print("skills.external_dirs:", dirs)
ready = bool(nut.get("url")) and sys.argv[2] in (dirs if isinstance(dirs, list) else [dirs])
raise SystemExit(0 if ready else 1)
PY
}
hermes_tz() {  # config.yaml's `timezone` only, no other value (empty when unset)
  "$PY" -I - "$CONFIG" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
print(c.get("timezone") or "")
PY
}
to_utc() {  # <HH:MM> <+HHMM>: "<M> <H>" in UTC for that local time, plain integers, wrapped at midnight
  local h=$((10#${1%%:*})) m=$((10#${1##*:})) off=$((10#${2:1:2} * 60 + 10#${2:3:2})) t
  if [ "${2:0:1}" = - ]; then off=$((-off)); fi
  t=$(( ((h * 60 + m - off) % 1440 + 1440) % 1440 ))
  echo "$((t % 60)) $((t / 60))"
}
cron_count() {  # lines of `hermes cron list --all` naming the job; grep -c reads all (no SIGPIPE)
  as_agent "$HERMES" cron list --all 2>&1 | grep -cF "$CRON_NAME" || true
}
cron_show() {  # the job's lines, with the ID line above the name; other jobs are not ours
  echo "== $CRON_NAME in 'hermes cron list --all' (lines naming it: $(cron_count))"
  as_agent "$HERMES" cron list --all 2>&1 | grep -F -B 2 -A 6 "$CRON_NAME" || echo "no $CRON_NAME job"
}
cron_remove() {  # by name; when Hermes cannot remove it by name, stop and let a human pick the id
  [ "$(cron_count)" -gt 0 ] || { echo "no $CRON_NAME job to remove"; return 0; }
  as_agent "$HERMES" cron remove "$CRON_NAME" || true  # the check below decides
  [ "$(cron_count)" -eq 0 ] \
    || { echo "$CRON_NAME is still listed: remove it by id ('hermes cron list --all' as $AGENT)" >&2; return 1; }
  echo "$CRON_NAME removed"
}

PROBLEMS=0
ok() { echo "ok: $*"; }
bad() { echo "PROBLEM: $*"; PROBLEMS=$((PROBLEMS + 1)); }
finish() {  # every check has printed; exit 1 when one failed
  if [ "$PROBLEMS" -gt 0 ]; then echo "$1: $PROBLEMS problem(s)" >&2; exit 1; fi
  echo "$1: all checks passed"
}

case "${1:-}" in
  preflight)
    need_src
    ver="$(as_agent "$HERMES" --version 2>&1 || true)"
    echo "hermes: $(sed -n 1p <<<"$ver")"
    echo "== config.yaml: the keys this step relies on"
    if nutrition_keys; then ok "mcp_servers.nutrition has a url and skills.external_dirs has $SKILLS_ROOT"
    else bad "mcp_servers.nutrition.url or $SKILLS_ROOT in skills.external_dirs is missing (install refuses)"; fi
    tz="$(hermes_tz)"
    if [ -z "$tz" ] || [ "$tz" = UTC ] || [ "$tz" = Etc/UTC ]; then ok "config.yaml timezone '$tz' (unset or UTC)"
    else bad "config.yaml timezone is '$tz', not unset or UTC (the cron step refuses)"; fi
    if [ "$(date +%z)" = "+0000" ]; then ok "node time zone +0000"
    else bad "node time zone is $(date +%z), not +0000 (the cron step refuses)"; fi
    echo "Europe/Berlin offset today: $(TZ=Europe/Berlin date +%z)"
    if [ -e "$SKILL_DIR" ]; then echo "note: $SKILL_DIR already exists"; else echo "$SKILL_DIR absent (first install)"; fi
    echo "$CRON_NAME lines in 'hermes cron list --all': $(cron_count)"
    echo "== Ultron's notes: type, mode and owner (the text is never shown)"
    stat -c '%a %U:%G %F %n' "$NOTES" "$NOTES/SKILL.md" "$NOTES/references" "$NOTES/references/nutrition-diary.md" || true
    links="$(home_links)"
    if [ -n "$links" ]; then
      bad "symlink under $AGENT_HOME ($links): install and rollback refuse"
    elif [ -f "$NOTES/SKILL.md" ]; then
      tmp="$(mktemp -d)"
      cp "$NOTES/SKILL.md" "$tmp/SKILL.md"
      rc=0
      out="$("$PY" -I "$SRC/ultron_nutrition_notes.py" "$tmp/SKILL.md" "$SRC/home-agent/nutrition-pointer-section.md" </dev/null 2>&1)" || rc=$?
      rm -f "$tmp/SKILL.md"
      rmdir "$tmp"
      echo "== the notes helper on a copy of $NOTES/SKILL.md (its change list, never the text)"
      printf '%s\n' "${out//"$tmp/SKILL.md"/"$NOTES/SKILL.md"}"
      if [ "$rc" -eq 0 ]; then ok "the helper can rewrite the notes"
      else bad "the helper stops on these notes (exit $rc): install would stop there too"; fi
    else
      bad "no $NOTES/SKILL.md"
    fi
    finish preflight
    ;;

  install)
    need_src
    refuse_links
    need_notes
    nutrition_keys \
      || { echo "config.yaml lacks mcp_servers.nutrition.url or $SKILLS_ROOT in skills.external_dirs: nothing was changed" >&2; exit 2; }
    bk="$BACKUPS/hermes-nutrition-$(date -u +%Y%m%dT%H%M%SZ)"
    install -d -m 700 "$bk"
    cp -p "$CONFIG" "$bk/config.yaml"
    cp -p "$NOTES/SKILL.md" "$bk/SKILL.md"
    cp -p "$NOTES/references/nutrition-diary.md" "$bk/nutrition-diary.md"
    same "$CONFIG" "$bk/config.yaml" && same "$NOTES/SKILL.md" "$bk/SKILL.md" \
      && same "$NOTES/references/nutrition-diary.md" "$bk/nutrition-diary.md" \
      || { echo "backup mismatch in $bk: nothing was changed" >&2; exit 1; }
    echo "backup OK: $bk  (rollback: rollback $bk)"
    # The skill is root-owned and read-only to Ultron: it cannot rewrite its own rules.
    install -d -m 755 -o root -g root /etc/episteck/hermes "$SKILLS_ROOT" "$SKILL_DIR"
    install -m 644 -o root -g root "$SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md"
    echo "== Ultron's notes: the nutrition section becomes a pointer (in place: owner and mode stay)"
    rc=0
    out="$("$PY" -I "$SRC/ultron_nutrition_notes.py" "$NOTES/SKILL.md" "$SRC/home-agent/nutrition-pointer-section.md" </dev/null 2>&1)" || rc=$?
    if [ "$rc" -ne 0 ]; then
      printf '%s\n' "$out" >&2
      if [ "$rc" -eq 3 ]; then
        echo "Ultron's notes changed since this plan was written: look at the nutrition section of $NOTES/SKILL.md by hand (the helper left the file untouched)." >&2
      fi
      echo "install stopped (helper exit $rc) before the diary note and the gateway restart. rollback: rollback $bk" >&2
      exit "$rc"
    fi
    printf '%s\n' "$out"
    install -o "$AGENT" -g "$AGENT" -m 644 "$SRC/home-agent/nutrition-diary-pointer.md" "$NOTES/references/nutrition-diary.md"
    stat -c '%a %U:%G %n' "$NOTES/SKILL.md" "$NOTES/references/nutrition-diary.md"
    cmp -s "$bk/config.yaml" "$CONFIG" \
      || { echo "config.yaml changed since the backup, not by this step: look before restarting the gateway (rollback: rollback $bk)" >&2; exit 1; }
    echo "config.yaml unchanged: no key changed"
    restart_gateway
    echo "rollback: rollback $bk"
    ;;

  cron)
    hm="${2:-}"
    re='^([01][0-9]|2[0-3]):[0-5][0-9]$'
    if ! [[ $hm =~ $re ]]; then echo "usage: cron <HH:MM> (Europe/Berlin, e.g. 21:45)" >&2; exit 2; fi
    need_src
    # The job loads the installed skill: it must be this commit's and have the check-in section.
    [ -f "$SKILL_DIR/SKILL.md" ] || { echo "run install first: the job loads $SKILL_DIR/SKILL.md" >&2; exit 2; }
    cmp -s "$SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md" \
      || { echo "the installed skill is not this commit's: run install first" >&2; exit 2; }
    grep -q '^## Evening check-in (cron)$' "$SKILL_DIR/SKILL.md" \
      || { echo "the installed skill has no 'Evening check-in (cron)' section" >&2; exit 2; }
    # This Hermes reads the expression in UTC (Finance's job needs it): node and config must agree.
    [ "$(date +%z)" = "+0000" ] || { echo "node time zone is not UTC: the UTC schedule would fire at the wrong hour" >&2; exit 1; }
    tz="$(hermes_tz)"
    if [ -n "$tz" ] && [ "$tz" != UTC ] && [ "$tz" != Etc/UTC ]; then
      echo "config.yaml timezone is '$tz', not UTC: the UTC schedule would fire at the wrong hour" >&2; exit 1
    fi
    off="$(TZ=Europe/Berlin date +%z)"
    case "$off" in
      +0100|+0200) ;;
      *) echo "TZ=Europe/Berlin gives offset '$off', not +0100 or +0200 (is tzdata installed?)" >&2; exit 1 ;;
    esac
    sched="$(to_utc "$hm" "$off")"
    # Re-running replaces the job (same name, this prompt), so there is never a second one.
    cron_remove
    created="$(as_agent "$HERMES" cron create --name "$CRON_NAME" --deliver telegram --failure-deliver local \
      --skill olin-nutrition "$sched * * *" "$CRON_PROMPT" 2>&1)" \
      || { printf '%s\n' "$created" >&2; echo "creating $CRON_NAME failed" >&2; exit 1; }
    printf '%s\n' "$created"  # Hermes names the new job's id here
    [ "$(cron_count)" -gt 0 ] || { echo "$CRON_NAME is not found by name in 'hermes cron list --all'," \
      "so a job may exist: remove it by id before re-running (id in the create output above)" >&2; exit 1; }
    cron_show
    echo "scheduled '$sched * * *' in UTC: $hm in Berlin at today's offset $off"
    echo "Berlin changes to summer time on the last Sunday of March and back on the last Sunday of October: re-run 'cron $hm' after each change to keep the check-in at $hm Berlin time."
    echo "rollback: rollback-cron (this job only) or rollback <backup-dir> (everything)"
    ;;

  verify)
    need_src
    echo "== the shared skill"
    stat -c '%a %U:%G %n' "$SKILLS_ROOT" "$SKILL_DIR" "$SKILL_DIR/SKILL.md" || true
    if [ "$(stat -c '%a %U:%G' "$SKILL_DIR/SKILL.md" 2>/dev/null || true)" = "644 root:root" ] \
      && cmp -s "$SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md"; then
      ok "the skill is root's, 644, and this commit's"
    else
      bad "the skill is not root's 644 copy of this commit's"
    fi
    if as_agent test -w "$SKILL_DIR/SKILL.md"; then bad "$AGENT can write the skill"
    else ok "$AGENT cannot write the skill"; fi
    if as_agent test -r "$SKILL_DIR/SKILL.md"; then ok "$AGENT can read the skill"
    else bad "$AGENT cannot read the skill"; fi
    if nutrition_keys; then ok "config.yaml: Ultron loads $SKILLS_ROOT and has the nutrition server"
    else bad "config.yaml: mcp_servers.nutrition.url or $SKILLS_ROOT in skills.external_dirs is missing"; fi
    echo "== Ultron's notes (drift is reported here, never fixed)"
    links="$(home_links)"
    if [ -n "$links" ]; then bad "symlink under $AGENT_HOME: $links"; fi
    for f in "$NOTES/SKILL.md" "$NOTES/references/nutrition-diary.md"; do
      mode="$(stat -c '%a %U:%G' "$f" 2>/dev/null || echo missing)"
      if [ "$mode" = "644 $AGENT:$AGENT" ]; then ok "$f is 644 $AGENT:$AGENT"
      else bad "$f is '$mode', not 644 $AGENT:$AGENT"; fi
    done
    if contains "$NOTES/SKILL.md" "$SRC/home-agent/nutrition-pointer-section.md" 2>/dev/null; then
      ok "the notes have this commit's ## Nutrition pointer"
    else
      bad "the notes do not have this commit's ## Nutrition pointer"
    fi
    if grep -qF get_daily_nutrition_gap "$NOTES/SKILL.md"; then bad "the notes still name get_daily_nutrition_gap"
    else ok "the notes do not name get_daily_nutrition_gap"; fi
    if cmp -s "$SRC/home-agent/nutrition-diary-pointer.md" "$NOTES/references/nutrition-diary.md"; then
      ok "references/nutrition-diary.md is this commit's pointer"
    else
      bad "references/nutrition-diary.md differs from this commit's pointer"
    fi
    echo "== nutrition MCP server (tool discovery)"
    mcp_out="$(as_agent "$HERMES" mcp test nutrition 2>&1 || true)"
    missing=""
    for t in "${NUTRITION_TOOLS[@]}"; do
      if ! grep -qF "$t" <<<"$mcp_out"; then missing="$missing $t"; fi
    done
    if [ -z "$missing" ]; then
      ok "hermes mcp test nutrition lists all ${#NUTRITION_TOOLS[@]} tools, propose_profile and get_period_summary among them"
    else
      bad "hermes mcp test nutrition does not list:$missing (401/502: no runtime grant for svc-nutrition)"
      grep -m 5 -iE 'error|fail|refused|denied|[45][0-9][0-9]' <<<"$mcp_out" || true
    fi
    echo "== gateway"
    if as_agent systemctl --user is-active --quiet hermes-gateway.service; then ok "hermes-gateway.service is active"
    else bad "hermes-gateway.service is not active"; fi
    as_agent systemctl --user show hermes-gateway.service -p ActiveState -p NRestarts || true
    echo "== evening check-in"
    if [ "$(cron_count)" -gt 0 ]; then ok "$CRON_NAME is scheduled"; else bad "$CRON_NAME is not scheduled"; fi
    cron_show
    finish verify
    ;;

  rollback-cron)
    cron_remove
    ;;

  rollback)
    bk="${2:-}"
    case "$bk" in
      "$BACKUPS"/hermes-nutrition-*) ;;
      *) echo "usage: rollback <backup-dir printed by install> ($BACKUPS/hermes-nutrition-<stamp>)" >&2; exit 2 ;;
    esac
    for f in config.yaml SKILL.md nutrition-diary.md; do
      [ -f "$bk/$f" ] || { echo "no $f in $bk: nothing was changed" >&2; exit 1; }
    done
    refuse_links
    # The job first: without the skill it would fail every evening.
    cron_remove || echo "WARNING: $CRON_NAME is still scheduled; remove it by id before anything else" >&2
    cp -p "$bk/SKILL.md" "$NOTES/SKILL.md"
    cp -p "$bk/nutrition-diary.md" "$NOTES/references/nutrition-diary.md"
    if same "$bk/SKILL.md" "$NOTES/SKILL.md" && same "$bk/nutrition-diary.md" "$NOTES/references/nutrition-diary.md"; then
      echo "notes restored byte for byte, with owner and mode:"
    else
      echo "WARNING: the notes differ from the backup in $bk" >&2
    fi
    stat -c '%a %U:%G %n' "$NOTES/SKILL.md" "$NOTES/references/nutrition-diary.md"
    if cmp -s "$bk/config.yaml" "$CONFIG"; then
      echo "config.yaml is as in the backup"
    else
      cp -p "$bk/config.yaml" "$CONFIG"
      if same "$bk/config.yaml" "$CONFIG"; then echo "config.yaml restored byte for byte"
      else echo "WARNING: config.yaml differs from the backup in $bk" >&2; fi
    fi
    # Only olin-nutrition: the skills root holds olin-finance.
    rm -f "$SKILL_DIR/SKILL.md"
    rmdir "$SKILL_DIR" 2>/dev/null || true
    restart_gateway
    ;;

  *) echo "usage: preflight | install | cron <HH:MM> | verify | rollback-cron | rollback <backup-dir>" >&2; exit 2 ;;
esac
