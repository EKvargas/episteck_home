#!/bin/bash
# Olin Finance on Hermes home-agent (B9): the skill plus the `finance` MCP entry.
# NOT run by CI, NOT run by an agent. Runbook: docs/runbooks/finance-i1-nuremberg-bringup.md, step 11.
#
# Extract the merged commit on the node first (runbook), then from the repo root:
#   ssh -F C:/Users/D064974/.ssh/config episteck-node1 'sudo -n bash -s -- <step> [args]' < deploy/hermes/install-olin-finance.sh
#
# Steps: preflight | install | verify | memory-scan | rollback <backup-dir>
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

case "${1:-}" in
  preflight)
    need_src
    as_agent "$HERMES" --version | head -n 1
    echo "== gateway finance route as home-agent (expect an HTTP status, not a refused connection)"
    as_agent curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' "$MCP_URL" || true
    finance_keys
    [ -e "$SKILL_DIR" ] && echo "note: $SKILL_DIR already exists" || echo "skill dir absent (expected)"
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
    as_agent "$HERMES" mcp test finance 2>&1 | tail -n 20 || true
    ;;

  memory-scan)
    [ -f "$SCANNER" ] || { echo "run install first" >&2; exit 2; }
    as_agent "$PY" -I "$SCANNER" "$HHOME/memories" && echo "memory scan: clean" \
      || echo "memory scan: findings above (counts only). Review the memory entries yourself, in your own terminal."
    ;;

  rollback)
    bk="${2:?usage: rollback <backup-dir printed by install>}"
    [ -f "$bk/config.yaml" ] || { echo "no config.yaml in $bk" >&2; exit 1; }
    cp -p "$bk/config.yaml" "$CONFIG"
    [ "$(sha256sum < "$CONFIG")" = "$(sha256sum < "$bk/config.yaml")" ] && echo "config.yaml restored byte for byte"
    rm -f "$SKILL_DIR/SKILL.md" "$SCANNER"
    rmdir "$SKILL_DIR" "$SKILLS_ROOT" /etc/episteck/hermes 2>/dev/null || true
    restart_gateway
    ;;

  *) echo "usage: preflight | install | verify | memory-scan | rollback <backup-dir>" >&2; exit 2 ;;
esac
