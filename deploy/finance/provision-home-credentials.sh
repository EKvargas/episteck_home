#!/bin/bash
# [OWN TERMINAL] Give svc-finance its Home machine credential. Prints NO secret.
#
# 1. Creates the Frappe API user finance-service@episteck.invalid on Home (Website User,
#    no roles: same shape as nutrition-auth-service and home-mcp-service). Idempotent.
# 2. Generates its API key/secret ON the Home host and streams them straight into
#    svc-finance's secrets/home-auth.env (mode 600) on Nuremberg. They never reach this
#    machine's disk, a command line, or the terminal.
# 3. Sets site config home_finance_machine_user, the only caller from which Home accepts
#    a svc-finance delegation.
#
# Refuses to overwrite an existing home-auth.env: generating a key rotates the secret and
# would silently break a working service. Pass --rotate to do it on purpose.
set -euo pipefail

SSH_CFG=${SSH_CFG:-C:/Users/D064974/.ssh/config}
HOME_SSH="ssh -F $SSH_CFG episteck-home"
NODE_SSH="ssh -F $SSH_CFG episteck-node1"
SITE=home.episteck.com
MUSER=finance-service@episteck.invalid
ENVFILE=/srv/episteck/services/finance/secrets/home-auth.env
ROTATE=no
[ "${1:-}" = "--rotate" ] && ROTATE=yes

if [ "$ROTATE" = no ] && $NODE_SSH "sudo -n test -e $ENVFILE"; then
  echo "refusing: $ENVFILE already exists (use --rotate to replace it)" >&2
  exit 2
fi

echo "== 1/3 Home user"
$HOME_SSH 'bash -s' <<REMOTE
set -eu
cd ~/frappe-bench
if [ -z "\$(bench --site $SITE execute frappe.db.exists --args '["User","$MUSER"]' 2>/dev/null)" ]; then
  bench --site $SITE execute frappe.client.insert --kwargs '{"doc":{"doctype":"User","email":"$MUSER","first_name":"Finance Service","user_type":"Website User","enabled":1,"send_welcome_email":0}}' >/dev/null 2>&1
  echo "created $MUSER"
else
  echo "exists $MUSER"
fi
REMOTE

echo "== 2/3 credential -> node (no output expected)"
$HOME_SSH 'bash -s' <<REMOTE | $NODE_SSH "cd /; sudo -n -u svc-finance sh -c 'umask 077; cat > $ENVFILE.tmp && mv $ENVFILE.tmp $ENVFILE'"
set -euo pipefail
cd ~/frappe-bench
secret=\$(bench --site $SITE execute frappe.core.doctype.user.user.generate_keys --kwargs '{"user":"$MUSER"}' 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["api_secret"])')
key=\$(bench --site $SITE execute frappe.db.get_value --args '["User","$MUSER","api_key"]' 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin))')
[ -n "\$secret" ] && [ -n "\$key" ]
printf 'HOME_CONTROL_PLANE_URL=https://$SITE\nHOME_API_KEY=%s\nHOME_API_SECRET=%s\nHOME_API_TIMEOUT_SECONDS=3\n' "\$key" "\$secret"
REMOTE

# Shape check only: counts lines, prints no value.
lines=$($NODE_SSH "sudo -n grep -c '^HOME_[A-Z_]*=.\+' $ENVFILE")
[ "$lines" = 4 ] || { echo "home-auth.env malformed ($lines/4 lines)" >&2; exit 1; }
$NODE_SSH "sudo -n stat -c '%a %U %n' $ENVFILE"

echo "== 3/3 site config"
$HOME_SSH "cd ~/frappe-bench && bench --site $SITE set-config home_finance_machine_user $MUSER"
echo "done. Restart finance-api and finance-mcp so they pick up the credential."
