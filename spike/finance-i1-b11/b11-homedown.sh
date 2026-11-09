#!/bin/bash
# B11 Home-down probe runner. On episteck-node1:  ssh ... 'bash -s' < b11-homedown.sh
# Throwaway container from the LIVE Finance image: --network none, empty temp DB, throwaway
# pepper, fake Home credential, Home URL on a local port the probe controls. No real data,
# no real secret, no live unit touched. --rm removes it when the probe ends.
set -u
cd /
U=svc-finance
R=/run/user/$(id -u $U)
IMG=$(sudo -n -u $U sed -n 's/^Image=//p' /home/$U/.config/containers/systemd/finance-api.container)
echo "image: $IMG"
P=/tmp/b11probe/b11_homedown.py
sudo -n -u $U test -r $P || { echo "probe not readable by $U"; exit 1; }
sudo -n -u $U env XDG_RUNTIME_DIR=$R podman run --rm --name finance-b11-homedown \
  --network none --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  --memory 384m --memory-swap 384m \
  -v $P:/probe/b11_homedown.py:ro \
  -e FINANCE_DB=/tmp/probe.sqlite -e FINANCE_WORKSPACE_ID=ws-b11-probe \
  -e FINANCE_PEPPER_FILE=/tmp/pepper -e MCP_PORT=9936 \
  -e HOME_CONTROL_PLANE_URL=http://127.0.0.1:9999 \
  -e HOME_API_KEY=b11-probe-key -e HOME_API_SECRET=b11-probe-secret \
  "$IMG" sh -c '
    head -c 32 /dev/urandom > /tmp/pepper && chmod 600 /tmp/pepper || exit 1
    uvicorn app.main:app --host 127.0.0.1 --port 9935 --no-access-log > /tmp/api.log 2>&1 &
    python -m app.mcp.server > /tmp/mcp.log 2>&1 &
    python -I /probe/b11_homedown.py
    echo "== container log: authorization categories (counts)"
    cat /tmp/api.log /tmp/mcp.log | grep -o -E "(home|finance) authorization not (granted|possible): [a-z_]+" | sort | uniq -c
    echo "== container log: Traceback/ERROR line counts"
    grep -c -E "Traceback|ERROR" /tmp/api.log /tmp/mcp.log
  '
echo "== leftover container (expect none)"
sudo -n -u $U env XDG_RUNTIME_DIR=$R podman ps -a --filter name=finance-b11-homedown --format '{{.Names}}'
echo "== live units untouched"
sudo -n -u $U env XDG_RUNTIME_DIR=$R systemctl --user is-active finance-api finance-mcp
