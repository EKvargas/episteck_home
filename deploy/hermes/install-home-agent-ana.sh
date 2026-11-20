#!/bin/bash
# Ana's Hermes agent ("Olin" on her Telegram bot) on episteck-node1: Linux user home-agent-ana,
# its own Hermes v0.21.2, the olin-nutrition skill, the evening check-in and the media purge.
# NOT run by CI, NOT run by an agent: the owner runs each step (plan 3, part B: B5 and B6);
# Claude runs only the read-only ones (preflight, login-check, verify).
#
# Extract the merged commit on the node first, from the repo root:
#   git archive <SHA> deploy/hermes | ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
#     'sudo -n install -d -m 755 /var/lib/episteck/hermes-ana && sudo -n tar -x -C /var/lib/episteck/hermes-ana'
# then, one step at a time:
#   ssh -F C:/Users/D064974/.ssh/config episteck-node1 'sudo -n bash -s -- <step> [arg]' < deploy/hermes/install-home-agent-ana.sh
#
# Steps: preflight | user | install | configure | env | telegram <id> | login | login-check
#        | gateway | cron <HH:MM> | purge | verify | stop | rollback-config <dir>
#        | remove yes-delete-home-agent-ana
# Ana's agent reaches only the Home gateway on 127.0.0.1:9937 (/gateway/home/, /gateway/nutrition/).
# The owner's agent (home-agent) is only read: its Hermes HEAD and installer hash, two lines of
# its .env (copied root-to-root), its gateway's restart count.
# Never prints .env, auth.json or a token; codex-login.log only as its URL and code lines.
set -euo pipefail
cd /

AGENT=home-agent-ana
HHOME=/home/$AGENT/.hermes
CONFIG=$HHOME/config.yaml
ENVF=$HHOME/.env
LOGIN_LOG=$HHOME/codex-login.log
HERMES=$HHOME/hermes-agent/venv/bin/hermes
VPY=$HHOME/hermes-agent/venv/bin/python
UNIT_DIR=/home/$AGENT/.config/systemd/user
SRC=/var/lib/episteck/hermes-ana/deploy/hermes
ANA_SRC=$SRC/home-agent-ana
SKILLS_ROOT=/etc/episteck/hermes-ana/skills
SKILL_DIR=$SKILLS_ROOT/olin-nutrition
GW=http://127.0.0.1:9937
BACKUPS=/var/backups/episteck
MIN_AVAILABLE_MB=900
MEMORY_MAX_BYTES=$((900 * 1024 * 1024))  # MemoryMax=900M in systemd/hermes-gateway-memory.conf

# Hermes v0.21.2 at the owner's commit. The installer is that commit's scripts/install.sh; its
# hash is checked before it runs, and preflight checks the owner's copy against the same hash.
HERMES_COMMIT=a89c1e1135a97dc1262926d93933357fbacd2bd2
INSTALLER_URL=https://raw.githubusercontent.com/NousResearch/hermes-agent/$HERMES_COMMIT/scripts/install.sh
INSTALLER_SHA256=38547c22f4dd2224ba68a13bc3479309abb17e295b2a2ef79c2d1b8293bd822e

# The owner's agent: read only.
OWNER=home-agent
OWNER_HERMES=/home/$OWNER/.hermes
OWNER_ENV=$OWNER_HERMES/.env

# The evening check-in, "MM HH * * *". Hermes reads cron expressions in config.yaml's `timezone`
# (the cron step refuses anything but Europe/Berlin), so daylight saving needs nothing. A failed
# run stays local: Ana never gets an error message. The prompt must not contain the job name
# (the job list is searched for it).
CRON_NAME=olin-nutrition-checkin
CRON_PROMPT='Scheduled evening check-in. Follow the skill section "Evening check-in (cron)".
1. Call mcp__home__whoami once, then mcp__nutrition__get_day_summary once with subject_person_id set to its actor_person_id and no date. Call no other tool and save nothing.
2. If day_status is COMPLETE, or a call returns an error other than an access refusal, your whole final response is exactly [SILENT].
3. If a call returns an access refusal, reply with the permission line from the skill and stop.
4. Otherwise write ONE short message in Spanish as that section says. It names the day it is about in Spanish words (for example jueves 20 de noviembre), taken from the date of get_day_summary, and ends with exactly: ¿Eso fue todo hoy?'

# Hermes' own config load/save (hermes_cli.config), run as the agent in its venv:
#   set <yaml>   set every key of <yaml>, keep the rest of config.yaml, print the changed key paths
#   check <yaml> are those keys set, are the MCP servers exactly home and nutrition, is there a
#                Telegram home channel; prints key paths, never values
#   tz           print config.yaml's `timezone`
# Exits 1 when a key is not in effect.
CONFIG_PY='import sys, yaml
from hermes_cli.config import load_config, read_raw_config, save_config
missing = object()
def leaves(node, path=()):
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from leaves(value, path + (key,))
    elif path:
        yield path, node
def get(node, path):
    for key in path:
        node = node.get(key, missing) if isinstance(node, dict) else missing
    return node
mode, raw = sys.argv[1], read_raw_config()
if mode == "tz":
    print(raw.get("timezone") or "")
    raise SystemExit(0)
want = list(leaves(yaml.safe_load(sys.argv[2]) or {}))
bad = []
if mode == "set":
    changed = []
    for path, value in want:
        node = raw
        for key in path[:-1]:
            if not isinstance(node.get(key), dict):
                node[key] = {}
            node = node[key]
        if node.get(path[-1], missing) != value:
            node[path[-1]] = value
            changed.append(".".join(path))
    if changed:
        save_config(raw, preserve_keys={path for path, _ in want})
    print("changed:", ", ".join(changed) or "nothing")
    raw = load_config()
else:
    servers = sorted(raw.get("mcp_servers") or {})
    print("mcp_servers:", " ".join(servers))
    if servers != ["home", "nutrition"]:
        bad.append("mcp_servers")
    if get(raw, ("platforms", "telegram", "home_channel", "chat_id")) in (missing, None, ""):
        bad.append("platforms.telegram.home_channel")
bad += [".".join(path) for path, value in want if get(raw, path) != value]
print("not as wanted: " + ", ".join(bad) if bad else "every key is as wanted")
raise SystemExit(1 if bad else 0)'

as_user() {  # stdin is /dev/null so no command can swallow the rest of this piped script
  local who="$1" u
  shift
  u="$(id -u "$who")"
  runuser -u "$who" -- env "HOME=/home/$who" "XDG_RUNTIME_DIR=/run/user/$u" \
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus" "$@" </dev/null
}
as_agent() { as_user "$AGENT" "$@"; }
agent_config() { as_agent "$VPY" -I -c "$CONFIG_PY" "$@"; }
owner_restarts() { as_user "$OWNER" systemctl --user show hermes-gateway.service -p NRestarts --value 2>/dev/null || echo unknown; }

PROBLEMS=0
ok() { echo "ok: $*"; }
bad() { echo "PROBLEM: $*"; PROBLEMS=$((PROBLEMS + 1)); }
finish() {  # every check has printed; exit 1 when one failed
  if [ "$PROBLEMS" -gt 0 ]; then echo "$1: $PROBLEMS problem(s)" >&2; exit 1; fi
  echo "$1: all checks passed"
}

need_src() {
  local f
  for f in config-ana.yaml SOUL.md skills/olin-nutrition/SKILL.md systemd/ana-media-purge.service \
           systemd/ana-media-purge.timer systemd/hermes-gateway-memory.conf; do
    if [ ! -f "$ANA_SRC/$f" ]; then
      echo "extract deploy/hermes of the merged commit into /var/lib/episteck/hermes-ana first ($f is missing)" >&2
      exit 2
    fi
  done
}
need_user() {
  if ! id "$AGENT" >/dev/null 2>&1; then echo "run the user step first" >&2; exit 2; fi
}
need_hermes() {
  need_user
  if [ ! -x "$HERMES" ]; then echo "run the install step first" >&2; exit 2; fi
}
need_env() {
  need_hermes
  if [ ! -f "$ENVF" ]; then echo "run the env step first" >&2; exit 2; fi
}

mem_available_mb() {
  awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo
}
check_memory() {
  local mb
  mb="$(mem_available_mb)"
  if [ "$mb" -ge "$MIN_AVAILABLE_MB" ]; then ok "MemAvailable ${mb} MB (needs ${MIN_AVAILABLE_MB} MB)"
  else bad "MemAvailable ${mb} MB is below ${MIN_AVAILABLE_MB} MB"; fi
}
check_identity() {  # the firewall tells the agents apart by uid: a uid of its own, no gateway group
  local uid taken
  uid="$(id -u "$AGENT")"
  case " $(id -nG "$AGENT") " in
    *" episteck-gw "*) bad "$AGENT is in episteck-gw" ;;
    *) ok "$AGENT is not in episteck-gw" ;;
  esac
  taken="0 1003 $(id -u svc-home-gateway 2>/dev/null || true) $(id -u www-data 2>/dev/null || true)"
  case " $taken " in
    *" $uid "*) bad "$AGENT has uid $uid, which root, home-agent, svc-home-gateway or www-data has" ;;
    *) ok "$AGENT has uid $uid (not 0, 1003, svc-home-gateway's or www-data's)" ;;
  esac
}
check_hermes() {  # Ana's Hermes is v0.21.2 at the pinned commit
  local ver head
  ver="$(as_agent "$HERMES" --version 2>&1 || true)"
  case "$ver" in
    *v0.21.2*) ok "$(sed -n 1p <<<"$ver")" ;;
    *) bad "hermes --version does not say v0.21.2" ;;
  esac
  head="$(as_agent git -C "$HHOME/hermes-agent" rev-parse HEAD 2>/dev/null || true)"
  if [ "$head" = "$HERMES_COMMIT" ]; then ok "Hermes checkout at $HERMES_COMMIT"
  else bad "Hermes checkout is at '$head', not $HERMES_COMMIT"; fi
}

parse_enabled() {  # `hermes tools list` output on stdin -> the enabled toolset names, sorted
  sed 's/\x1b\[[0-9;]*m//g' | awk '/^MCP servers:/ {mcp = 1} !mcp && $2 == "enabled" {print $3}' \
    | LC_ALL=C sort | paste -sd ' ' -
}
enabled_toolsets() {  # on platform $1
  as_agent "$HERMES" tools list --platform "$1" 2>&1 | parse_enabled
}
env_names() {  # the key names in Ana's .env, never a value
  awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/ {print $1}' "$ENVF" | LC_ALL=C sort | paste -sd ' ' -
}
allowed_users_count() {  # how many Telegram users may talk to the bot, never who
  awk -F= '$1 == "TELEGRAM_ALLOWED_USERS" {n += split($2, ids, ",")} END {print n + 0}' "$ENVF"
}
login_lines() {  # the line after "Open this URL" and the line after "Enter this code", nothing else
  awk '/Open this URL|Enter this code/ {want = NR + 1; next} NR == want {gsub(/\033\[[0-9;]*m/, ""); gsub(/^[ \t]+|[ \t]+$/, ""); print}' "$LOGIN_LOG"
}
smoke() {  # provider model: a one-shot answer must contain the word ok
  local out
  out="$(as_agent "$HERMES" chat -q "Responde solo: ok" --oneshot -Q --provider "$1" -m "$2" 2>&1 || true)"
  if grep -qiw ok <<<"$out"; then ok "$1 / $2 answered ok"
  else bad "$1 / $2 did not answer ok; its last lines:"; tail -n 3 <<<"$out"; fi
}

gateway_active() { as_agent systemctl --user is-active --quiet hermes-gateway.service; }
restart_gateway() {
  if gateway_active; then
    as_agent systemctl --user restart hermes-gateway.service
    sleep 5
    as_agent systemctl --user show hermes-gateway.service -p ActiveState -p NRestarts
  else
    echo "gateway not running: nothing to restart"
  fi
}
gateway_report() {  # state, restarts, the memory cap the kernel enforces, the resident size
  local cg max pid
  as_agent systemctl --user show hermes-gateway.service -p ActiveState -p NRestarts -p MemoryMax || true
  cg="$(as_agent systemctl --user show hermes-gateway.service -p ControlGroup --value 2>/dev/null || true)"
  max="$(cat "/sys/fs/cgroup$cg/memory.max" 2>/dev/null || echo missing)"
  if [ -n "$cg" ] && [ "$max" = "$MEMORY_MAX_BYTES" ]; then ok "cgroup memory.max $max (900M)"
  else bad "cgroup memory.max is '$max', not $MEMORY_MAX_BYTES: MemoryMax is not in effect"; fi
  pid="$(as_agent systemctl --user show hermes-gateway.service -p MainPID --value 2>/dev/null || true)"
  if [ "${pid:-0}" -gt 0 ]; then echo "gateway RSS: $(ps -o rss= -p "$pid" | awk '{print int($1 / 1024)}') MB"
  else bad "the gateway has no main process"; fi
}

cron_count() {  # lines of `hermes cron list --all` naming the job; grep -c reads all (no SIGPIPE)
  as_agent "$HERMES" cron list --all 2>&1 | grep -cF "$CRON_NAME" || true
}
cron_show() {  # the job's lines, with the ID line above the name
  echo "== $CRON_NAME in 'hermes cron list --all' (lines naming it: $(cron_count))"
  as_agent "$HERMES" cron list --all 2>&1 | grep -F -B 2 -A 6 "$CRON_NAME" || echo "no $CRON_NAME job"
}
cron_remove() {  # by name; when Hermes cannot remove it by name, stop and let a human pick the id
  if [ "$(cron_count)" -eq 0 ]; then echo "no $CRON_NAME job to remove"; return 0; fi
  as_agent "$HERMES" cron remove "$CRON_NAME" || true  # the check below decides
  if [ "$(cron_count)" -ne 0 ]; then
    echo "$CRON_NAME is still listed: remove it by id ('hermes cron list --all' as $AGENT)" >&2
    return 1
  fi
  echo "$CRON_NAME removed"
}
do_stop() {  # no check-in, no gateway, no purge timer; config, .env, sessions and login stay
  if [ -x "$HERMES" ]; then
    cron_remove || echo "WARNING: $CRON_NAME is still scheduled: remove it by id" >&2
  fi
  as_agent systemctl --user disable --now hermes-gateway.service || true
  as_agent systemctl --user disable --now ana-media-purge.timer || true
  as_agent systemctl --user show hermes-gateway.service ana-media-purge.timer -p Id -p ActiveState \
    -p UnitFileState || true
}
backup_dir() {  # a new root-only directory under /var/backups/episteck
  local dir
  dir="$BACKUPS/hermes-ana-$(date -u +%Y%m%dT%H%M%SZ)"
  install -d -m 700 "$dir"
  echo "$dir"
}

case "${1:-}" in
  preflight)
    check_memory
    gb="$(df -P -BG / | awk 'NR == 2 {sub("G", "", $4); print $4}')"
    if [ "$gb" -ge 5 ]; then ok "${gb} GB free on /"; else bad "${gb} GB free on / (needs 5 GB)"; fi
    if [ "$(date +%z)" = "+0000" ]; then ok "node time zone +0000"
    else bad "node time zone is $(date +%z), not +0000"; fi
    if id "$AGENT" >/dev/null 2>&1; then
      check_identity
      echo "== $GW/gateway/home/ as $AGENT (expect an HTTP status, not 000)"
      as_agent curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' "$GW/gateway/home/" \
        || bad "no HTTP status from $GW/gateway/home/"
    else
      ok "$AGENT does not exist yet (the user step creates it)"
    fi
    head="$(as_user "$OWNER" git -C "$OWNER_HERMES/hermes-agent" rev-parse HEAD 2>/dev/null || true)"
    if [ "$head" = "$HERMES_COMMIT" ]; then ok "the owner's Hermes is at $HERMES_COMMIT"
    else bad "the owner's Hermes HEAD is '$head', not $HERMES_COMMIT"; fi
    sum="$(sha256sum "$OWNER_HERMES/hermes-agent/scripts/install.sh" 2>/dev/null | awk '{print $1}' || true)"
    if [ "$sum" = "$INSTALLER_SHA256" ]; then ok "the owner's install.sh has the pinned sha256"
    else bad "the owner's install.sh sha256 is '$sum', not $INSTALLER_SHA256"; fi
    finish preflight
    ;;

  user)
    if id "$AGENT" >/dev/null 2>&1; then echo "$AGENT exists"; else useradd -m -s /bin/bash "$AGENT"; fi
    chmod 700 "/home/$AGENT"
    loginctl enable-linger "$AGENT"
    id "$AGENT"
    check_identity
    bus="/run/user/$(id -u "$AGENT")/bus"
    for _ in $(seq 1 10); do
      if [ -S "$bus" ]; then break; fi
      sleep 1
    done
    if [ -S "$bus" ]; then ok "$AGENT's user systemd is up"; else bad "no user systemd bus at $bus yet"; fi
    finish user
    ;;

  install)
    need_user
    check_memory
    if [ "$PROBLEMS" -gt 0 ]; then finish install; fi
    f="/home/$AGENT/hermes-install-$HERMES_COMMIT.sh"
    as_agent curl -fsSL --max-time 120 -o "$f" "$INSTALLER_URL"
    sum="$(sha256sum "$f" | awk '{print $1}')"
    if [ "$sum" != "$INSTALLER_SHA256" ]; then
      rm -f "$f"
      echo "the downloaded installer has sha256 $sum, not $INSTALLER_SHA256: not running it" >&2
      exit 1
    fi
    ok "installer sha256 matches the pin"
    as_agent bash "$f" --commit "$HERMES_COMMIT" --skip-setup --skip-browser --skip-computer-use --no-skills
    rm -f "$f"
    check_hermes
    finish install
    ;;

  configure)
    # Persona, skill and config.yaml keys. Safe to re-run: unchanged keys are left alone.
    need_src
    need_hermes
    if [ -f "$CONFIG" ]; then
      bk="$(backup_dir)"
      cp -p "$CONFIG" "$bk/config.yaml"
      [ "$(sha256sum < "$CONFIG")" = "$(sha256sum < "$bk/config.yaml")" ] || { echo "backup mismatch" >&2; exit 1; }
      echo "backup OK: $bk  (rollback: rollback-config $bk)"
    else
      echo "no config.yaml yet: nothing to back up"
    fi
    install -m 644 -o "$AGENT" -g "$AGENT" "$ANA_SRC/SOUL.md" "$HHOME/SOUL.md"
    # The skill is root-owned and read-only to Ana's agent: it cannot rewrite its own rules.
    install -d -m 755 -o root -g root /etc/episteck/hermes-ana "$SKILLS_ROOT" "$SKILL_DIR"
    install -m 644 -o root -g root "$ANA_SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md"
    echo "== config.yaml: the keys of config-ana.yaml (paths only)"
    agent_config set "$(< "$ANA_SRC/config-ana.yaml")" || bad "a config-ana.yaml key is not in effect"
    # On Telegram and in cron jobs only the skills and clarify toolsets stay; MCP tools stay.
    for p in telegram cron; do
      extra=()
      for ts in $(enabled_toolsets "$p" || true); do
        case "$ts" in skills|clarify) ;; *) extra+=("$ts") ;; esac
      done
      if [ "${#extra[@]}" -gt 0 ]; then
        as_agent "$HERMES" tools disable "${extra[@]}" --platform "$p"
      fi
      echo "== hermes tools list --platform $p"
      as_agent "$HERMES" tools list --platform "$p" 2>&1 || true
      now="$(enabled_toolsets "$p" || true)"
      if [ "$now" = "clarify skills" ]; then ok "$p toolsets: $now"
      else bad "$p toolsets enabled: '$now' (want: clarify skills)"; fi
    done
    restart_gateway
    finish configure
    ;;

  env)
    # Ana's .env: the Kimi fallback lines, copied root-to-root from the owner's .env and never
    # shown. The bot token arrives later through the secret drop (slot telegram-ana).
    need_hermes
    if [ ! -f "$ENVF" ]; then
      install -m 600 -o "$AGENT" -g "$AGENT" /dev/null "$ENVF"
      echo "created an empty .env (600)"
    fi
    sed -i -e '$a\' "$ENVF"  # a final newline before anything is appended
    for key in KIMI_API_KEY KIMI_BASE_URL; do
      if grep -q "^$key=" "$ENVF"; then
        ok "$key is already set"
      elif grep -q "^$key=" "$OWNER_ENV"; then
        grep -m 1 "^$key=" "$OWNER_ENV" >> "$ENVF"
        ok "$key copied from the owner's .env"
      elif [ "$key" = KIMI_BASE_URL ]; then
        echo "note: KIMI_BASE_URL is not in the owner's .env either: Hermes' default Kimi URL applies"
      else
        bad "$key is not in the owner's .env"
      fi
    done
    chown "$AGENT:$AGENT" "$ENVF"
    chmod 600 "$ENVF"
    echo "keys in .env: $(env_names)"
    finish env
    ;;

  telegram)
    # Who may talk to the bot, and where the check-in goes: one Telegram user id. Run it with the
    # owner's id for the test phase, then with Ana's.
    tg_id="${2:-}"
    re='^[0-9]{5,15}$'
    if ! [[ $tg_id =~ $re ]]; then echo "usage: telegram <numeric Telegram user id>" >&2; exit 2; fi
    need_env
    bk="$(backup_dir)"
    cp -p "$ENVF" "$bk/.env"
    if [ -f "$CONFIG" ]; then cp -p "$CONFIG" "$bk/config.yaml"; fi
    echo "backup OK: $bk  (rollback-config $bk restores config.yaml; the old .env is next to it)"
    sed -i -e '/^TELEGRAM_ALLOWED_USERS=/d' -e '/^TELEGRAM_HOME_CHANNEL=/d' -e '$a\' "$ENVF"
    printf 'TELEGRAM_ALLOWED_USERS=%s\nTELEGRAM_HOME_CHANNEL=%s\n' "$tg_id" "$tg_id" >> "$ENVF"
    chown "$AGENT:$AGENT" "$ENVF"
    chmod 600 "$ENVF"
    echo "allowed Telegram users: $(allowed_users_count); keys in .env: $(env_names)"
    echo "== config.yaml: Telegram on, home channel set (paths only)"
    agent_config set "$(printf '{"platforms": {"telegram": {"enabled": true, "home_channel": {"platform": "telegram", "chat_id": "%s", "user_id": "%s"}}}}' "$tg_id" "$tg_id")" \
      || bad "the Telegram keys are not in effect"
    restart_gateway
    finish telegram
    ;;

  login)
    # A device login for the openai-codex credential "ana-codex". The owner approves it with the
    # owner's own ChatGPT account. It waits in the background for that approval.
    need_hermes
    pkill -u "$AGENT" -f 'auth add openai-codex' || true
    install -m 600 -o "$AGENT" -g "$AGENT" /dev/null "$LOGIN_LOG"
    as_agent setsid -f env PYTHONUNBUFFERED=1 "$HERMES" auth add openai-codex --type oauth --no-browser \
      --label ana-codex >> "$LOGIN_LOG" 2>&1
    for _ in $(seq 1 20); do
      if grep -q 'Enter this code' "$LOGIN_LOG"; then break; fi
      sleep 1
    done
    sleep 1  # the code is printed on the line after its label
    shown="$(login_lines)"
    if [ -z "$shown" ]; then
      echo "no device code after 20 s: run login again (the log stays private, never printed)" >&2
      exit 1
    fi
    printf '%s\n' "$shown"
    echo "Open the URL, sign in with the owner's ChatGPT account and enter the code. Then run login-check."
    ;;

  login-check)
    need_hermes
    creds="$(as_agent "$HERMES" auth list openai-codex 2>&1 | grep -F ana-codex || true)"
    if [ -n "$creds" ]; then ok "credential: $creds"; else bad "no ana-codex credential (run login)"; fi
    smoke openai-codex gpt-5.6-sol
    smoke kimi-coding kimi-k2.6
    finish login-check
    ;;

  gateway)
    need_src
    need_env
    n="$(grep -c '^TELEGRAM_BOT_TOKEN=' "$ENVF" || true)"
    if [ "$n" -lt 1 ]; then echo "no TELEGRAM_BOT_TOKEN yet: drop it in secret-drop slot telegram-ana" >&2; exit 2; fi
    n="$(as_agent "$HERMES" auth list openai-codex 2>&1 | grep -cF ana-codex || true)"
    if [ "$n" -lt 1 ]; then echo "no ana-codex credential: run login and login-check first" >&2; exit 2; fi
    before="$(owner_restarts)"
    # Not started by the install: the memory cap must be in place before the first start.
    as_agent "$HERMES" gateway install --no-start-now
    as_agent mkdir -p "$UNIT_DIR/hermes-gateway.service.d"
    install -m 644 -o "$AGENT" -g "$AGENT" "$ANA_SRC/systemd/hermes-gateway-memory.conf" \
      "$UNIT_DIR/hermes-gateway.service.d/memory.conf"
    as_agent systemctl --user daemon-reload
    as_agent systemctl --user enable --now hermes-gateway.service
    sleep 10
    gateway_report
    after="$(owner_restarts)"
    if [ "$before" = "$after" ]; then ok "home-agent gateway NRestarts unchanged ($after)"
    else bad "home-agent gateway NRestarts changed from $before to $after"; fi
    finish gateway
    ;;

  cron)
    hm="${2:-}"
    re='^([01][0-9]|2[0-3]):[0-5][0-9]$'
    if ! [[ $hm =~ $re ]]; then echo "usage: cron <HH:MM> (Europe/Berlin, e.g. 21:30)" >&2; exit 2; fi
    HH="${hm%%:*}"
    MM="${hm##*:}"
    need_src
    need_hermes
    # The job loads the installed skill: it must be this commit's and have the check-in section.
    [ -f "$SKILL_DIR/SKILL.md" ] || { echo "run configure first: the job loads $SKILL_DIR/SKILL.md" >&2; exit 2; }
    cmp -s "$ANA_SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md" \
      || { echo "the installed skill is not this commit's: run configure first" >&2; exit 2; }
    grep -q '^## Evening check-in (cron)$' "$SKILL_DIR/SKILL.md" \
      || { echo "the installed skill has no 'Evening check-in (cron)' section" >&2; exit 2; }
    tz="$(agent_config tz)"
    if [ "$tz" != Europe/Berlin ]; then
      echo "config.yaml timezone is '$tz', not Europe/Berlin: '$MM $HH * * *' would fire at the wrong hour" >&2
      exit 1
    fi
    # Re-running replaces the job (same name, this prompt), so there is never a second one.
    cron_remove
    created="$(as_agent "$HERMES" cron create --name "$CRON_NAME" --deliver telegram --failure-deliver local \
      --skill olin-nutrition "$MM $HH * * *" "$CRON_PROMPT" 2>&1)" \
      || { printf '%s\n' "$created" >&2; echo "creating $CRON_NAME failed" >&2; exit 1; }
    printf '%s\n' "$created"  # Hermes names the new job's id here
    if [ "$(cron_count)" -eq 0 ]; then
      echo "$CRON_NAME is not found by name in 'hermes cron list --all', so a job may exist:" \
        "remove it by id before re-running (id in the create output above)" >&2
      exit 1
    fi
    cron_show
    ;;

  purge)
    need_src
    need_user
    as_agent mkdir -p "$UNIT_DIR"
    install -m 644 -o "$AGENT" -g "$AGENT" "$ANA_SRC/systemd/ana-media-purge.service" "$ANA_SRC/systemd/ana-media-purge.timer" "$UNIT_DIR/"
    as_agent systemctl --user daemon-reload
    as_agent systemctl --user enable --now ana-media-purge.timer
    as_agent systemctl --user list-timers ana-media-purge.timer --no-pager
    ;;

  verify)
    need_src
    need_env
    echo "== user"
    id "$AGENT"
    check_identity
    stat -c '%a %U:%G %n' "/home/$AGENT" "$HHOME" "$ENVF" "$CONFIG" "$HHOME/SOUL.md" "$SKILLS_ROOT" \
      "$SKILL_DIR" "$SKILL_DIR/SKILL.md" || true
    home_mode="$(stat -c '%a' "/home/$AGENT" || true)"
    env_mode="$(stat -c '%a %U' "$ENVF" || true)"
    skill_mode="$(stat -c '%a %U:%G' "$SKILL_DIR/SKILL.md" 2>/dev/null || true)"
    if [ "$home_mode" = 700 ]; then ok "home is 700"; else bad "home is $home_mode, not 700"; fi
    if [ "$env_mode" = "600 $AGENT" ]; then ok ".env is 600 and $AGENT's"
    else bad ".env is '$env_mode', not 600 and $AGENT's"; fi
    if [ "$skill_mode" = "644 root:root" ] \
      && cmp -s "$ANA_SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md"; then
      ok "the skill is root's, 644, and this commit's"
    else
      bad "the skill is not root's 644 copy of this commit's"
    fi
    if as_agent test -w "$SKILL_DIR/SKILL.md"; then bad "$AGENT can write the skill"
    else ok "$AGENT cannot write the skill"; fi
    if as_agent test -r "$SKILL_DIR/SKILL.md"; then ok "$AGENT can read the skill"
    else bad "$AGENT cannot read the skill"; fi
    if cmp -s "$ANA_SRC/SOUL.md" "$HHOME/SOUL.md"; then ok "SOUL.md is this commit's"
    else bad "SOUL.md differs from this commit's"; fi
    echo "== Hermes"
    check_hermes
    echo "== config.yaml (paths only)"
    agent_config check "$(< "$ANA_SRC/config-ana.yaml")" || bad "config.yaml is not as wanted (paths above)"
    for p in telegram cron; do
      now="$(enabled_toolsets "$p" || true)"
      if [ "$now" = "clarify skills" ]; then ok "$p toolsets: $now"
      else bad "$p toolsets enabled: '$now' (want: clarify skills)"; fi
    done
    echo "== .env (key names only)"
    names="$(env_names)"
    echo "keys: $names"
    for key in TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS TELEGRAM_HOME_CHANNEL KIMI_API_KEY; do
      case " $names " in *" $key "*) ;; *) bad "$key is missing" ;; esac
    done
    users="$(allowed_users_count)"
    lines="$(grep -c '^TELEGRAM_ALLOWED_USERS=' "$ENVF" || true)"
    if [ "$users" = 1 ] && [ "$lines" = 1 ]; then ok "one Telegram user is allowed"
    else bad "allowed Telegram users: $users in $lines line(s), want exactly 1"; fi
    echo "== model login"
    n="$(as_agent "$HERMES" auth list openai-codex 2>&1 | grep -cF ana-codex || true)"
    if [ "$n" -ge 1 ]; then ok "ana-codex credential present"; else bad "no ana-codex credential"; fi
    echo "== gateway"
    if gateway_active; then ok "hermes-gateway.service is active"; else bad "hermes-gateway.service is not active"; fi
    gateway_report
    echo "home-agent gateway NRestarts: $(owner_restarts) (must not change)"
    echo "== evening check-in"
    if [ "$(cron_count)" -ge 1 ]; then ok "$CRON_NAME is scheduled"; else bad "$CRON_NAME is not scheduled"; fi
    cron_show
    echo "== media purge"
    if as_agent systemctl --user is-enabled --quiet ana-media-purge.timer \
      && as_agent systemctl --user is-active --quiet ana-media-purge.timer; then
      ok "ana-media-purge.timer is enabled and active"
    else
      bad "ana-media-purge.timer is not enabled and active"
    fi
    as_agent systemctl --user list-timers ana-media-purge.timer --no-pager || true
    echo "== network as $AGENT"
    code="$(as_agent curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$GW/gateway/home/" 2>/dev/null || true)"
    if [ -n "$code" ] && [ "$code" != 000 ]; then ok "the Home gateway answers HTTP $code"
    else bad "no HTTP status from $GW/gateway/home/"; fi
    rc=0; as_agent curl -sS --max-time 5 -o /dev/null http://127.0.0.1:9934/ 2>/dev/null || rc=$?
    if [ "$rc" = 28 ]; then ok "the owner's gateway port times out for $AGENT (curl exit 28)"
    else bad "the owner's gateway port gave curl exit $rc for $AGENT, not 28 (a timeout)"; fi
    echo "== memory"
    free -m
    finish verify
    ;;

  stop)
    need_user
    do_stop
    echo "stopped: config, .env, sessions and the login are kept under $HHOME"
    ;;

  rollback-config)
    bk="${2:?usage: rollback-config <backup-dir printed by configure or telegram>}"
    [ -f "$bk/config.yaml" ] || { echo "no config.yaml in $bk" >&2; exit 1; }
    need_hermes
    cp -p "$bk/config.yaml" "$CONFIG"
    if [ "$(sha256sum < "$CONFIG")" = "$(sha256sum < "$bk/config.yaml")" ]; then
      echo "config.yaml restored byte for byte"
    fi
    restart_gateway
    ;;

  remove)
    if [ "${2:-}" != yes-delete-home-agent-ana ]; then
      echo "nothing done: remove deletes the user and its home; run it as: remove yes-delete-home-agent-ana" >&2
      exit 2
    fi
    if id "$AGENT" >/dev/null 2>&1; then
      do_stop
      bk="$(backup_dir)"
      if [ -d "$HHOME" ]; then
        # Its state, not the Hermes checkout (the pinned commit reinstalls it).
        tar -C "/home/$AGENT" --exclude=.hermes/hermes-agent -czf "$bk/hermes.tar.gz" .hermes
        chmod 600 "$bk/hermes.tar.gz"
        echo "backup: $bk/hermes.tar.gz"
      fi
      uid="$(id -u "$AGENT")"
      loginctl disable-linger "$AGENT" || true
      systemctl stop "user@$uid.service" || true
      userdel -r "$AGENT"
      echo "$AGENT removed"
    else
      echo "no $AGENT user"
    fi
    rm -f "$SKILL_DIR/SKILL.md"
    rmdir "$SKILL_DIR" "$SKILLS_ROOT" /etc/episteck/hermes-ana 2>/dev/null || true
    ;;

  *)
    echo "usage: preflight | user | install | configure | env | telegram <id> | login | login-check | gateway" \
      "| cron <HH:MM> | purge | verify | stop | rollback-config <dir> | remove yes-delete-home-agent-ana" >&2
    exit 2
    ;;
esac
