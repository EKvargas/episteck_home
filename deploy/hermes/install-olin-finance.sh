#!/bin/bash
# Olin Finance on Hermes home-agent (B9): the skill plus the `finance` MCP entry; (I2) the
# scheduled job that delivers Finance's questions and notices to the owner's Telegram.
# NOT run by CI, NOT run by an agent. Runbooks: docs/runbooks/finance-i1-nuremberg-bringup.md,
# step 11, and docs/runbooks/finance-i2-exchanges.md (the cron step).
#
# Extract the merged commit on the node first (runbook), then from the repo root:
#   ssh -F C:/Users/D064974/.ssh/config episteck-node1 'sudo -n bash -s -- <step> [args]' < deploy/hermes/install-olin-finance.sh
#
# Steps: preflight | install | cron | verify | memory-scan | rollback-cron | rollback <backup-dir>
# Never reads .env, auth.json or memory contents. The change report prints key paths, and
# values only for the three keys this step sets.
set -euo pipefail
cd /

AGENT=home-agent
HHOME=/home/$AGENT/.hermes
CONFIG=$HHOME/config.yaml
HERMES=$HHOME/hermes-agent/venv/bin/hermes
PY=/usr/bin/python3
SRC=/var/lib/episteck/hermes-b9/deploy/hermes
SKILLS_ROOT=/etc/episteck/hermes/skills
SKILL_DIR=$SKILLS_ROOT/olin-finance
SCANNER=/etc/episteck/hermes/memory_hygiene.py
MCP_URL=http://127.0.0.1:9934/gateway/finance/
BACKUPS=/var/backups/episteck

# I2 (spec F9): twice a day, 15 minutes after the finance-sync timer (06:20/18:20). Hermes
# 0.21.2 has no `--timezone` for cron: it reads cron expressions in the system zone, unless
# config.yaml sets `timezone`. Both must be UTC (the cron step checks).
# `--deliver telegram` goes to home-agent's Telegram home channel: the owner's private chat.
CRON_NAME=olin-finance-pending
CRON_SCHEDULE='35 6,18 * * *'
# The job loads the olin-finance skill (`--skill`); this prompt is the delivery contract.
# Keep it free of figures and of the job name (the job list is searched for the name).
CRON_PROMPT='Scheduled Olin Finance delivery. Follow the skill section "Scheduled delivery (cron)".
1. Call mcp__finance__finance_pending exactly once, with for_delivery=true. Call no other tool: do not answer, dismiss or record anything, and save nothing to memory.
2. If it returns no items, your whole final response is exactly [SILENT] and nothing else.
3. If it returns a refusal (ok false), reply with one short Spanish line from the skill refusal table and stop. Do not retry.
4. Otherwise write ONE message in Spanish: questions first, then the confirmations ("pendiente de tu confirmación", with the created_at date of each), then the notices. For each item give its code (P<n>), the question, echo or notice with every figure copied exactly from the result, and every option with its number n exactly as returned and its label: never renumber, reorder or drop one.
5. A possible duplicate takes no number: tell the owner to answer «P<n> es otro» o «P<n> es el mismo».
6. End with how to answer: "Responde «P<n> <número>», «P<n> sí», «P<n> corregir» o «P<n> cancelar», o solo «P<n>» y te muestro los botones."'

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
need_src() {
  [ -f "$SRC/home-agent/skills/olin-finance/SKILL.md" ] && [ -f "$SRC/memory_hygiene.py" ] \
    || { echo "extract deploy/hermes into /var/lib/episteck/hermes-b9 first (runbook step 11)" >&2; exit 2; }
}
finance_keys() {  # the keys this runbook step owns, read from config.yaml without other values
  "$PY" -I - "$CONFIG" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1])) or {}
print("mcp_servers:", sorted((c.get("mcp_servers") or {}).keys()))
print("mcp_servers.finance:", (c.get("mcp_servers") or {}).get("finance"))
print("skills.external_dirs:", (c.get("skills") or {}).get("external_dirs"))
PY
}
changed_keys() {  # dotted key paths that differ between two config files
  "$PY" -I - "$1" "$2" <<'PY'
import sys, yaml
def flat(node, prefix=""):
    if not isinstance(node, dict):
        return {prefix[:-1]: node}
    out = {}
    for key, value in node.items():
        out.update(flat(value, f"{prefix}{key}."))
    return out
old = flat(yaml.safe_load(open(sys.argv[1])) or {})
new = flat(yaml.safe_load(open(sys.argv[2])) or {})
shown = {"mcp_servers.finance.url", "mcp_servers.finance.enabled", "skills.external_dirs"}
changed = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
for key in changed:
    tag = "added" if key not in old else "removed" if key not in new else "changed"
    print(f"{tag}: {key}" + (f" = {new.get(key)!r}" if key in shown else ""))
unexpected = [k for k in changed if k not in shown]
print("UNEXPECTED keys changed: " + ", ".join(unexpected) if unexpected else "only the finance keys changed")
PY
}
hermes_tz() {  # config.yaml's `timezone` only, no other value (empty when unset)
  "$PY" -I - "$CONFIG" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1])) or {}
print(c.get("timezone") or "")
PY
}
cron_count() {  # lines of `hermes cron list` naming the job; grep -c reads all (no SIGPIPE)
  as_agent "$HERMES" cron list 2>&1 | grep -cF "$CRON_NAME" || true
}
cron_show() {  # the job's lines (with the ID line around the name); other jobs are not ours
  echo "== $CRON_NAME in 'hermes cron list' (lines naming it: $(cron_count))"
  as_agent "$HERMES" cron list 2>&1 | grep -F -B 2 -A 5 "$CRON_NAME" || echo "no $CRON_NAME job"
}
cron_remove() {  # by name; when Hermes cannot remove it by name, stop and let a human pick the id
  [ "$(cron_count)" -gt 0 ] || { echo "no $CRON_NAME job to remove"; return 0; }
  as_agent "$HERMES" cron remove "$CRON_NAME" || true  # the check below decides
  [ "$(cron_count)" -eq 0 ] \
    || { echo "$CRON_NAME is still listed: remove it by id (hermes cron list as $AGENT)" >&2; return 1; }
  echo "$CRON_NAME removed"
}

case "${1:-}" in
  preflight)
    need_src
    as_agent "$HERMES" --version | head -n 1
    echo "== gateway finance route as home-agent (expect an HTTP status, not a refused connection)"
    as_agent curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' "$MCP_URL" || true
    finance_keys
    [ -e "$SKILL_DIR" ] && echo "note: $SKILL_DIR already exists" || echo "skill dir absent (expected)"
    echo "node time zone offset: $(date +%z) (the cron step needs +0000); $CRON_NAME lines: $(cron_count)"
    echo "config.yaml timezone: '$(hermes_tz)' (the cron step needs empty or UTC)"
    ;;

  install)
    need_src
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"; bk="$BACKUPS/hermes-b9-$stamp"
    install -d -m 700 "$bk"
    cp -p "$CONFIG" "$bk/config.yaml"
    [ "$(sha256sum < "$CONFIG")" = "$(sha256sum < "$bk/config.yaml")" ] || { echo "backup mismatch" >&2; exit 1; }
    echo "backup OK: $bk  (rollback: rollback $bk)"
    install -d -m 755 -o root -g root /etc/episteck/hermes "$SKILLS_ROOT" "$SKILL_DIR"
    install -m 644 -o root -g root "$SRC/home-agent/skills/olin-finance/SKILL.md" "$SKILL_DIR/SKILL.md"
    install -m 644 -o root -g root "$SRC/memory_hygiene.py" "$SCANNER"
    as_agent "$HERMES" config set mcp_servers.finance.url "$MCP_URL"
    as_agent "$HERMES" config set mcp_servers.finance.enabled true
    as_agent "$HERMES" config set skills.external_dirs "$SKILLS_ROOT"
    echo "== config keys changed against the backup"
    changed_keys "$bk/config.yaml" "$CONFIG"
    stat -c '%a %U %n' "$CONFIG"
    restart_gateway
    ;;

  cron)
    # After install: the job loads the installed skill. Re-running replaces the job (same
    # name, current prompt), so there is never a second one. No config.yaml key changes.
    need_src
    [ -f "$SKILL_DIR/SKILL.md" ] || { echo "run install first: the job loads $SKILL_DIR/SKILL.md" >&2; exit 2; }
    cmp -s "$SRC/home-agent/skills/olin-finance/SKILL.md" "$SKILL_DIR/SKILL.md" \
      || { echo "the installed skill is not this commit's: run install first" >&2; exit 2; }
    grep -q '^## Scheduled delivery' "$SKILL_DIR/SKILL.md" \
      || { echo "the installed skill has no 'Scheduled delivery' section (an I1 skill?)" >&2; exit 2; }
    [ "$(date +%z)" = "+0000" ] || { echo "node time zone is not UTC: '$CRON_SCHEDULE' would fire at the wrong hours" >&2; exit 1; }
    tz="$(hermes_tz)"
    if [ -n "$tz" ] && [ "$tz" != UTC ] && [ "$tz" != Etc/UTC ]; then
      echo "config.yaml timezone is '$tz', not UTC: '$CRON_SCHEDULE' would fire at the wrong hours" >&2; exit 1
    fi
    cron_remove
    created="$(as_agent "$HERMES" cron create --name "$CRON_NAME" --deliver telegram --skill olin-finance \
      "$CRON_SCHEDULE" "$CRON_PROMPT" 2>&1)" \
      || { printf '%s\n' "$created" >&2; echo "creating $CRON_NAME failed" >&2; exit 1; }
    printf '%s\n' "$created"  # Hermes names the new job's id here
    [ "$(cron_count)" -gt 0 ] || { echo "$CRON_NAME is not found by name in 'hermes cron list'," \
      "so a job may exist: remove it by id before re-running (id in the create output above)" >&2; exit 1; }
    cron_show
    echo "rollback: rollback-cron (this job only) or rollback <backup-dir> (everything)"
    ;;

  verify)
    need_src
    stat -c '%a %U %n' "$SKILLS_ROOT" "$SKILL_DIR" "$SKILL_DIR/SKILL.md" "$SCANNER"
    cmp -s "$SRC/home-agent/skills/olin-finance/SKILL.md" "$SKILL_DIR/SKILL.md" \
      && echo "skill matches the shipped commit" || echo "MISMATCH: skill differs from the shipped commit"
    as_agent test -w "$SKILL_DIR/SKILL.md" && echo "WARNING: home-agent can write the skill" \
      || echo "home-agent cannot write the skill (expected)"
    finance_keys
    as_agent systemctl --user show hermes-gateway.service -p ActiveState -p NRestarts
    echo "== skill as Hermes sees it"
    as_agent "$HERMES" skills list 2>&1 | grep -i 'olin-finance' || echo "olin-finance not in 'hermes skills list' (external skills may not be listed there)"
    echo "== finance MCP server (tool discovery; 401/502 means no runtime grant for svc-finance)"
    mcp_out="$(as_agent "$HERMES" mcp test finance 2>&1 || true)"
    printf '%s\n' "$mcp_out" | tail -n 40
    echo "finance tools listed: $(printf '%s\n' "$mcp_out" | grep -oE 'finance_[a-z]+(_[a-z]+)*' | sort -u | wc -l) (expect 15)"
    echo "== scheduled delivery (I2): expect one job, '$CRON_SCHEDULE', telegram, skill olin-finance"
    cron_show
    ;;

  memory-scan)
    [ -f "$SCANNER" ] || { echo "run install first" >&2; exit 2; }
    # Cron run outputs keep figures and names (even [SILENT] runs): a count, never their text.
    echo "cron output files: $(find "$HHOME/cron/output" -type f 2>/dev/null | wc -l) under $HHOME/cron/output (retention is the owner's decision; runbook checklist (e))"
    as_agent "$PY" -I "$SCANNER" "$HHOME/memories" && echo "memory scan: clean" \
      || echo "memory scan: findings above (counts only). Review the memory entries yourself, in your own terminal."
    ;;

  rollback-cron)
    cron_remove
    ;;

  rollback)
    bk="${2:?usage: rollback <backup-dir printed by install>}"
    [ -f "$bk/config.yaml" ] || { echo "no config.yaml in $bk" >&2; exit 1; }
    # The job first: without the skill and the finance server it would fail twice a day,
    # and a failed cron run always delivers its error to Telegram.
    cron_remove || echo "WARNING: $CRON_NAME is still scheduled; remove it by id before anything else" >&2
    cp -p "$bk/config.yaml" "$CONFIG"
    [ "$(sha256sum < "$CONFIG")" = "$(sha256sum < "$bk/config.yaml")" ] && echo "config.yaml restored byte for byte"
    rm -f "$SKILL_DIR/SKILL.md" "$SCANNER"
    rmdir "$SKILL_DIR" "$SKILLS_ROOT" /etc/episteck/hermes 2>/dev/null || true
    restart_gateway
    ;;

  *) echo "usage: preflight | install | cron | verify | memory-scan | rollback-cron | rollback <backup-dir>" >&2; exit 2 ;;
esac
