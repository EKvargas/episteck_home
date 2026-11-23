#!/bin/bash
# Olin Nutrition on the owner's Hermes agent "Ultron" (user home-agent, Hermes v0.21.2), plan 2:
# the shared olin-nutrition skill, Ultron's own nutrition notes turned into pointers to it, and
# the evening check-in. Ultron also runs Finance (install-olin-finance.sh): its skills root, its
# config.yaml and its UTC cron times stay as they are.
# NOT run by CI, NOT run by an agent: the owner runs install, cron, mirror and the rollbacks;
# Claude runs only the read-only steps (preflight, verify).
# Runbook: docs/runbooks/nutrition-profile-rollout.md.
#
# Extract the merged commit on the node first, from the repo root:
#   git archive <SHA> deploy/hermes | ssh -F "$HOME/.ssh/config" episteck-node1 \
#     'sudo -n install -d -m 755 /var/lib/episteck/hermes-nutrition && sudo -n tar -x -C /var/lib/episteck/hermes-nutrition'
# then, one step at a time:
#   ssh -F "$HOME/.ssh/config" episteck-node1 'sudo -n bash -s -- <step> [arg]' < deploy/hermes/install-olin-nutrition.sh
#
# Steps: preflight | install | cron <HH:MM> | mirror <on|off> | verify | rollback-cron
#        | rollback <backup-dir>
# Never reads .env, auth.json, tokens or memory files. Never prints Ultron's notes, nor a
# config.yaml value other than the nutrition server's url and enabled, skills.external_dirs,
# timezone and cron.mirror_delivery. Root never writes into /home/home-agent: every write there
# runs as home-agent (as_agent, as_agent_from), since Ultron can run code and could swap a path
# for a symlink. As defence in depth, install, mirror and rollback still refuse when a path they
# write, or a directory leading to it, is a symlink (home_links).
set -euo pipefail
cd /

AGENT=home-agent
AGENT_HOME=/home/$AGENT
HHOME=$AGENT_HOME/.hermes
CONFIG=$HHOME/config.yaml
HERMES=$HHOME/hermes-agent/venv/bin/hermes
VPY=$HHOME/hermes-agent/venv/bin/python
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
# Two of them are new in plan 1: install refuses until the live server lists them.
PLAN1_TOOLS=(propose_profile get_period_summary)

# The evening check-in, "M H * * *" in UTC: this Hermes reads cron expressions in the system zone
# (config.yaml has no `timezone`; Finance's job needs UTC), so the cron step converts the Berlin
# time with today's Berlin offset and must be re-run after each daylight-saving change. A failed
# run stays local. The prompt must not contain the job name (the job list is searched for it).
CRON_NAME=olin-nutrition-checkin
CRON_PROMPT='Scheduled evening check-in. Follow the skill section "Evening check-in (cron)".
1. Call mcp__home__whoami once, then mcp__nutrition__get_day_summary once with subject_person_id set to its actor_person_id and no date. Call no other tool and save nothing.
2. If day_status is COMPLETE, or a call returns an error other than an access refusal, your whole final response is exactly [SILENT].
3. If a call returns an access refusal, reply with the permission line from the skill and stop.
4. Otherwise write ONE short message in English as that section says. It names the day it is about as day and month, no weekday (for example 20 November), taken from the date of get_day_summary. It gives the free sugars against the reference and the uncounted items, or says that nothing is logged yet. For energy_kcal and protein_g in nutrients, it gives known against target only when the target of that nutrient is not null, and leaves out a nutrient whose target is null, even when profile_version is set. A day with no targets gets the free sugars part only. The message ends with exactly: Was that everything today?'

# The mirror step: cron.mirror_delivery through Hermes' own config load/save (hermes_cli.config),
# run as the agent in its venv like CONFIG_PY `set` in install-home-agent-ana.sh. <on|off> sets
# that one key and keeps the rest of config.yaml; it prints the key path, never another value,
# and exits 1 unless the loaded config has the value.
MIRROR_PY='import sys
from hermes_cli.config import load_config, read_raw_config, save_config
want = sys.argv[1] == "on"
raw = read_raw_config()
if not isinstance(raw.get("cron"), dict):
    raw["cron"] = {}
if raw["cron"].get("mirror_delivery") is not want:
    raw["cron"]["mirror_delivery"] = want
    save_config(raw, preserve_keys={("cron", "mirror_delivery")})
    print("changed: cron.mirror_delivery")
else:
    print("changed: nothing")
now = (load_config().get("cron") or {}).get("mirror_delivery")
print("cron.mirror_delivery in effect:", "true" if now is True else "false" if now is False else "unset")
raise SystemExit(0 if now is want else 1)'

as_agent() {  # stdin is /dev/null so no command can swallow the rest of this piped script
  local u; u="$(id -u "$AGENT")"
  runuser -u "$AGENT" -- env "HOME=/home/$AGENT" "XDG_RUNTIME_DIR=/run/user/$u" \
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus" "$@" </dev/null
}
as_agent_from() {  # <file> <command...>: as_agent with stdin from that file, which root opens;
  # never the script's stdin. Root hands a backup to a write the agent makes in its own home.
  local src="$1" u; shift
  u="$(id -u "$AGENT")"
  runuser -u "$AGENT" -- env "HOME=/home/$AGENT" "XDG_RUNTIME_DIR=/run/user/$u" \
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus" "$@" <"$src"
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
home_links() {  # the symlinks among the paths install, mirror or rollback writes (as the agent) or
  # reads (as root, for a backup), and the directories leading to them, all in the agent's home;
  # on one line (empty when none)
  local p found=""
  for p in "$AGENT_HOME" "$HHOME" "$CONFIG" "$HHOME/skills" "$NOTES" "$NOTES/SKILL.md" \
           "$NOTES/references" "$NOTES/references/nutrition-diary.md"; do
    if [ -L "$p" ]; then found="$found $p"; fi
  done
  echo "${found# }"
}
refuse_links() {  # no step goes on through a symlink in the agent's home: stop before any change
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
mirror_value() {  # config.yaml's cron.mirror_delivery only, no other value: true, false or unset
  "$PY" -I - "$CONFIG" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
v = c["cron"].get("mirror_delivery") if isinstance(c.get("cron"), dict) else None
print("true" if v is True else "false" if v is False else "unset" if v is None else "not a boolean")
PY
}
config_drift() {  # <before> <after>: the key paths other than cron.mirror_delivery that differ,
  # never a value; exit 1 when there is one
  "$PY" -I - "$1" "$2" <<'PY'
import sys, yaml
missing = object()
def flat(node, prefix=""):
    if isinstance(node, dict) and node:
        out = {}
        for key, value in node.items():
            out.update(flat(value, f"{prefix}{key}."))
        return out
    return {prefix[:-1]: node}
def others(path):
    c = yaml.safe_load(open(path, encoding="utf-8")) or {}
    cron = c.get("cron")
    if isinstance(cron, dict):
        cron = {k: v for k, v in cron.items() if k != "mirror_delivery"}
    if cron is None or cron == {}:
        c.pop("cron", None)
    else:
        c["cron"] = cron
    return flat(c)
old, new = others(sys.argv[1]), others(sys.argv[2])
changed = sorted(k for k in old.keys() | new.keys() if old.get(k, missing) != new.get(k, missing))
print("other keys changed: " + ", ".join(changed) if changed else "no other key changed")
raise SystemExit(1 if changed else 0)
PY
}
plan1_live() {  # exit 0 when the live nutrition server lists the plan-1 tools (this plan's backend)
  local out t
  out="$(as_agent "$HERMES" mcp test nutrition 2>&1 || true)"
  for t in "${PLAN1_TOOLS[@]}"; do
    grep -qF "$t" <<<"$out" || return 1
  done
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
WARNINGS=0
warn() {  # a rollback part that did not end as it should: rollback goes on, then exits 1
  echo "WARNING: $*" >&2
  WARNINGS=$((WARNINGS + 1))
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
    echo "cron.mirror_delivery: $(mirror_value) (unset is off; the mirror step sets it)"
    if plan1_live; then echo "plan 1 backend: live ('hermes mcp test nutrition' lists ${PLAN1_TOOLS[*]})"
    else echo "plan 1 backend: not live yet ('hermes mcp test nutrition' does not list ${PLAN1_TOOLS[*]}): install refuses until it is (runbook C1)"; fi
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
    plan1_live \
      || { echo "the live nutrition server does not list ${PLAN1_TOOLS[*]}: roll out the plan 1 backend first (runbook C1). Nothing was changed" >&2; exit 2; }
    # Root only reads the agent's files here, into a root-only directory.
    bk="$BACKUPS/hermes-nutrition-$(date -u +%Y%m%dT%H%M%SZ)"
    install -d -m 700 "$bk"
    cp -p "$CONFIG" "$bk/config.yaml"
    cp -p "$NOTES/SKILL.md" "$bk/SKILL.md"
    cp -p "$NOTES/references/nutrition-diary.md" "$bk/nutrition-diary.md"
    same "$CONFIG" "$bk/config.yaml" && same "$NOTES/SKILL.md" "$bk/SKILL.md" \
      && same "$NOTES/references/nutrition-diary.md" "$bk/nutrition-diary.md" \
      || { echo "backup mismatch in $bk: nothing was changed" >&2; exit 1; }
    if [ -f "$SKILL_DIR/SKILL.md" ]; then  # an earlier install's skill: rollback puts it back
      cp -p "$SKILL_DIR/SKILL.md" "$bk/olin-nutrition-SKILL.md"
      same "$SKILL_DIR/SKILL.md" "$bk/olin-nutrition-SKILL.md" \
        || { echo "backup mismatch in $bk: nothing was changed" >&2; exit 1; }
      echo "the installed olin-nutrition skill is backed up too: rollback restores it"
    fi
    echo "backup OK: $bk  (rollback: rollback $bk)"
    if contains "$bk/SKILL.md" "$SRC/home-agent/nutrition-pointer-section.md"; then
      echo "WARNING: this backup holds already-rewritten notes; roll back with the first install's backup" >&2
    fi
    # The skill is root-owned and read-only to Ultron: it cannot rewrite its own rules.
    install -d -m 755 -o root -g root /etc/episteck/hermes "$SKILLS_ROOT" "$SKILL_DIR"
    install -m 644 -o root -g root "$SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md"
    echo "== Ultron's notes: the nutrition section becomes a pointer (in place, written as $AGENT)"
    rc=0
    out="$(as_agent "$PY" -I "$SRC/ultron_nutrition_notes.py" "$NOTES/SKILL.md" "$SRC/home-agent/nutrition-pointer-section.md" 2>&1)" || rc=$?
    if [ "$rc" -ne 0 ]; then
      printf '%s\n' "$out" >&2
      if [ "$rc" -eq 3 ]; then
        echo "Ultron's notes changed since this plan was written: look at the nutrition section of $NOTES/SKILL.md by hand (the helper left the file untouched)." >&2
      fi
      echo "install stopped (helper exit $rc) before the diary note and the gateway restart. rollback: rollback $bk" >&2
      exit "$rc"
    fi
    printf '%s\n' "$out"
    # As the agent too: the new file is home-agent's, 644.
    as_agent install -m 644 "$SRC/home-agent/nutrition-diary-pointer.md" "$NOTES/references/nutrition-diary.md"
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

  mirror)
    # cron.mirror_delivery: on, a cron delivery (this check-in, and Finance's) is also stored in
    # the DM session, so a bare "yes" after the check-in has it as context. The owner decides.
    case "${2:-}" in
      on) want=on; val=true ;;
      off) want=off; val=false ;;
      *) echo "usage: mirror <on|off> (cron.mirror_delivery)" >&2; exit 2 ;;
    esac
    refuse_links
    [ -x "$VPY" ] || { echo "no Hermes venv python at $VPY: nothing was changed" >&2; exit 2; }
    before="$(mirror_value)"
    if [ "$before" = "$val" ] || { [ "$val" = false ] && [ "$before" = unset ]; }; then
      echo "cron.mirror_delivery is $before: nothing to change"
      exit 0
    fi
    bk="$BACKUPS/hermes-nutrition-mirror-$(date -u +%Y%m%dT%H%M%SZ)"
    install -d -m 700 "$bk"
    cp -p "$CONFIG" "$bk/config.yaml"
    same "$CONFIG" "$bk/config.yaml" || { echo "backup mismatch in $bk: nothing was changed" >&2; exit 1; }
    echo "backup OK: $bk  (config.yaml only; cron.mirror_delivery was $before)"
    echo "== config.yaml: cron.mirror_delivery through Hermes' own load/save, as $AGENT"
    as_agent "$VPY" -I -c "$MIRROR_PY" "$want" \
      || { echo "cron.mirror_delivery is not $val in effect: the gateway was not restarted (backup: $bk)" >&2; exit 1; }
    [ "$(mirror_value)" = "$val" ] \
      || { echo "config.yaml does not say cron.mirror_delivery: $val: the gateway was not restarted (backup: $bk)" >&2; exit 1; }
    config_drift "$bk/config.yaml" "$CONFIG" \
      || { echo "a key other than cron.mirror_delivery changed (paths above): the gateway was not restarted; compare with $bk/config.yaml" >&2; exit 1; }
    restart_gateway
    if [ "$before" = true ]; then back=on; else back=off; fi
    echo "cron.mirror_delivery: $val (it was $before; to go back: mirror $back)"
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
    echo "cron.mirror_delivery: $(mirror_value) (the owner's choice; unset is off)"
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
    cron_remove || warn "$CRON_NAME is still scheduled; remove it by id before anything else"
    # The notes are written by the agent, fed from the backups root opens: root never writes into
    # the agent's home. tee writes in place, so each file keeps its inode, owner and mode.
    as_agent_from "$bk/SKILL.md" tee "$NOTES/SKILL.md" >/dev/null \
      || warn "could not write $NOTES/SKILL.md as $AGENT"
    as_agent_from "$bk/nutrition-diary.md" tee "$NOTES/references/nutrition-diary.md" >/dev/null \
      || warn "could not write $NOTES/references/nutrition-diary.md as $AGENT"
    if same "$bk/SKILL.md" "$NOTES/SKILL.md" \
      && same "$bk/nutrition-diary.md" "$NOTES/references/nutrition-diary.md" \
      && [ "$(stat -c '%a %U:%G' "$bk/SKILL.md" "$bk/nutrition-diary.md")" \
           = "$(stat -c '%a %U:%G' "$NOTES/SKILL.md" "$NOTES/references/nutrition-diary.md")" ]; then
      echo "notes restored byte for byte, owner and mode as in the backup:"
    else
      warn "the notes differ from the backup in $bk (content, owner or mode)"
    fi
    stat -c '%a %U:%G %n' "$NOTES/SKILL.md" "$NOTES/references/nutrition-diary.md" || true
    # config.yaml is never restored: install does not change it, so a difference is someone
    # else's (Finance, a model change, the mirror step) and stays.
    if cmp -s "$bk/config.yaml" "$CONFIG"; then
      echo "config.yaml is as in the backup"
    else
      warn "config.yaml differs from the install-time backup in $bk; not touched"
    fi
    # Only olin-nutrition: the skills root holds olin-finance. A skill an earlier install left
    # comes back; otherwise the skill goes.
    if [ -f "$bk/olin-nutrition-SKILL.md" ]; then
      install -d -m 755 -o root -g root "$SKILL_DIR"
      install -m 644 -o root -g root "$bk/olin-nutrition-SKILL.md" "$SKILL_DIR/SKILL.md"
      if same "$bk/olin-nutrition-SKILL.md" "$SKILL_DIR/SKILL.md"; then
        echo "$SKILL_DIR/SKILL.md restored from the earlier install (in $bk)"
      else
        warn "$SKILL_DIR/SKILL.md differs from the earlier install's copy in $bk"
      fi
    else
      rm -f "$SKILL_DIR/SKILL.md"
      if [ -d "$SKILL_DIR" ] && ! rmdir "$SKILL_DIR" 2>/dev/null; then
        echo "note: $SKILL_DIR is not empty, so it stays (its SKILL.md is gone): look at it by hand"
      fi
    fi
    restart_gateway
    if [ "$WARNINGS" -gt 0 ]; then
      echo "rollback: $WARNINGS warning(s) above (the gateway was restarted)" >&2
      exit 1
    fi
    echo "rollback: done"
    ;;

  *) echo "usage: preflight | install | cron <HH:MM> | mirror <on|off> | verify | rollback-cron | rollback <backup-dir>" >&2; exit 2 ;;
esac
