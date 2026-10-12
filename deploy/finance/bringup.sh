#!/bin/bash
# Operator bring-up for svc-finance on the Nuremberg node. NOT run by CI, NOT run by an agent.
#
# From a clean checkout of the merged commit, on your machine:
#   ssh -F C:/Users/D064974/.ssh/config episteck-node1 'sudo -n bash -s -- <step> [args]' < deploy/finance/bringup.sh
#
# Steps (see docs/runbooks/finance-i1-nuremberg-bringup.md for order, verification and rollback):
#   preflight | create-user | create-dirs | build SHA | install SHA | enable-timer |
#   verify | apply-backup | rollback-units | rollback-backup | purge --i-understand-this-deletes-financial-data
#
# This script never reads, prints or creates secret CONTENT. Secrets are placed by you, in
# your own terminal, as described in the runbook.
set -euo pipefail
cd /

SVC=svc-finance
BASE=/srv/episteck/services/finance
BACKUP=/etc/episteck/backup/episteck-backup.sh
MARKER="# --- 2b. Finance SQLite"

step="${1:-}"
shift || true

svc_uid() { id -u "$SVC"; }
as_svc() {
  local u; u="$(svc_uid)"
  runuser -u "$SVC" -- env "XDG_RUNTIME_DIR=/run/user/$u" \
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus" "$@"
}
remove_units() {
  as_svc systemctl --user disable --now finance-sync.timer 2>/dev/null || true
  as_svc systemctl --user stop finance-sync finance-api finance-mcp 2>/dev/null || true
  rm -f "/home/$SVC/.config/containers/systemd/finance-"*.container "/home/$SVC/.config/systemd/user/finance-sync.timer"
  as_svc systemctl --user daemon-reload
}
need_sha() { [[ "${1:-}" =~ ^[0-9a-f]{7,40}$ ]] || { echo "usage: $step <commit-sha>" >&2; exit 2; }; }

case "$step" in
  preflight)
    echo "== ports 9935/9936 (must print 'free')"
    ss -tlnH | grep -E ':(9935|9936)\b' || echo "free"
    echo "== existing svc users"; getent passwd | grep -E '^svc-' | cut -d: -f1,3
    echo "== $SVC exists?"; id "$SVC" 2>&1 || echo "no (expected before create-user)"
    echo "== tools"; for t in podman sqlite3 loginctl runuser; do command -v "$t" >/dev/null && echo "ok $t" || echo "MISSING $t"; done
    echo "== resources"; df -h / | tail -1; free -m | sed -n '1,2p'
    echo "== backup timer"; systemctl is-active episteck-backup.timer || true
    ;;

  create-user)
    if id "$SVC" >/dev/null 2>&1; then echo "$SVC already exists (uid $(svc_uid))"; else
      useradd -m -s /bin/bash "$SVC"
    fi
    chmod 700 "/home/$SVC"
    grep -q "^$SVC:" /etc/subuid && grep -q "^$SVC:" /etc/subgid || { echo "no subuid/subgid range for $SVC" >&2; exit 1; }
    loginctl enable-linger "$SVC"
    echo "created/ready: $SVC uid=$(svc_uid)"
    ;;

  create-dirs)
    install -d -o root -g root -m 755 "$BASE"
    install -d -o "$SVC" -g "$SVC" -m 700 "$BASE/data" "$BASE/secrets" "$BASE/config" "$BASE/build"
    ls -ld "$BASE" "$BASE"/*
    ;;

  build)
    need_sha "${1:-}"
    src="$BASE/build/$1"
    [ -f "$src/services/finance/Dockerfile" ] || { echo "extract the commit archive into $src first" >&2; exit 2; }
    chown -R "$SVC:$SVC" "$src"
    ( cd "$src" && as_svc podman build -t "localhost/episteck-finance:$1" -f services/finance/Dockerfile . )
    as_svc podman image ls --noheading localhost/episteck-finance
    ;;

  install)
    need_sha "${1:-}"
    src="$BASE/build/$1/deploy/finance"; home="/home/$SVC"
    [ -f "$BASE/secrets/pepper" ] || { echo "missing $BASE/secrets/pepper (see runbook, own terminal)" >&2; exit 1; }
    [ "$(stat -c %a "$BASE/secrets/pepper")" = "600" ] || { echo "pepper must be mode 600" >&2; exit 1; }
    grep -q '^FINANCE_WORKSPACE_ID=' "$BASE/config/finance.env" || { echo "config/finance.env needs FINANCE_WORKSPACE_ID=" >&2; exit 1; }
    install -d -o "$SVC" -g "$SVC" -m 700 "$home/.config/containers/systemd" "$home/.config/systemd/user"
    for unit in finance-api finance-mcp finance-sync; do
      sed "s/REPLACE_WITH_COMMIT_SHA/$1/" "$src/$unit.container" > "$home/.config/containers/systemd/$unit.container"
    done
    cp "$src/finance-sync.timer" "$home/.config/systemd/user/finance-sync.timer"
    chown -R "$SVC:$SVC" "$home/.config"
    as_svc systemctl --user daemon-reload
    as_svc systemctl --user start finance-api finance-mcp
    as_svc systemctl --user --no-pager --lines=0 status finance-api finance-mcp || true
    ;;

  enable-timer)
    as_svc systemctl --user enable --now finance-sync.timer
    as_svc systemctl --user list-timers --no-pager
    ;;

  verify)
    echo "== listeners (loopback only)"; ss -tlnH | grep -E ':(9935|9936)\b'
    echo "== health"; curl -sS --max-time 5 http://127.0.0.1:9935/health; echo
    echo "== overview without a session must be 401"
    curl -sS --max-time 5 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9935/overview
    echo "== overview with any session must be 503 until Phase B wires Home (fail closed)"
    curl -sS --max-time 5 -o /dev/null -w "%{http_code}\n" -H 'X-Episteck-Delegation: not-a-real-token' http://127.0.0.1:9935/overview
    echo "== containers"; as_svc podman ps --format '{{.Names}} {{.Status}}'
    echo "== timers"; as_svc systemctl --user list-timers --no-pager
    echo "== recent sync result"; as_svc journalctl --user -u finance-sync --no-pager -n 5 -o cat 2>/dev/null || true
    echo "== data dir modes"; stat -c '%a %U %n' "$BASE/data" "$BASE/secrets" "$BASE/config"
    ;;

  apply-backup)
    [ -f "$BACKUP" ] || { echo "backup script not found" >&2; exit 1; }
    if grep -q "$MARKER" "$BACKUP"; then echo "finance block already present"; exit 0; fi
    cp -p "$BACKUP" "$BACKUP.bak-finance"
    python3 - "$BACKUP" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
anchor = "# --- 3. restic backup"
block = '''# --- 2b. Finance SQLite: hot-consistent copy + integrity check (secrets are never staged) ---
log "Finance: consistent SQLite copy"
FDB=/srv/episteck/services/finance/data/finance.sqlite
if [ -f "$FDB" ]; then
  if sqlite3 "$FDB" ".backup '$STAGE/finance.sqlite'" && [ "$(sqlite3 "$STAGE/finance.sqlite" 'PRAGMA integrity_check;')" = "ok" ]; then
    log "Finance DB staged"
  else
    log "ERROR: finance sqlite backup or integrity check failed"; rc=1; rm -f "$STAGE/finance.sqlite"
  fi
else
  log "INFO: finance.sqlite not present yet"
fi

'''
assert anchor in text and "--tag nutrition --tag mealie" in text
text = text.replace(anchor, block + anchor, 1)
text = text.replace("--tag nutrition --tag mealie", "--tag nutrition --tag mealie --tag finance", 1)
open(path, "w").write(text)
PY
    bash -n "$BACKUP" && echo "patched OK; original kept at $BACKUP.bak-finance"
    diff -u "$BACKUP.bak-finance" "$BACKUP" || true
    ;;

  rollback-backup)
    [ -f "$BACKUP.bak-finance" ] || { echo "no backup of the script to restore" >&2; exit 1; }
    cp -p "$BACKUP.bak-finance" "$BACKUP" && echo "restored original backup script"
    ;;

  rollback-units)
    remove_units
    echo "units removed; data and secrets kept in $BASE"
    ;;

  purge)
    [ "${1:-}" = "--i-understand-this-deletes-financial-data" ] || {
      echo "DESTRUCTIVE: deletes the finance database and secrets. Re-run with --i-understand-this-deletes-financial-data" >&2; exit 2; }
    remove_units 2>/dev/null || true
    rm -rf --one-file-system "$BASE"
    loginctl disable-linger "$SVC" || true
    userdel -r "$SVC" || true
    echo "svc-finance, its data and its secrets are gone (restic snapshots are untouched)"
    ;;

  *)
    echo "unknown step '$step' (see header)" >&2; exit 2
    ;;
esac
