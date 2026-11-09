#!/bin/bash
# B11 read-only: real-user connection matrix (connect only, no request sent), live Finance
# image provenance, and the nft rules that mention the Finance ports. No data is read.
cd /
TCP='import socket,sys
try:
    socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=3).close(); print("CAN")
except OSError as e:
    print("CANNOT", type(e).__name__)'
UNIX='import socket,sys
s = socket.socket(socket.AF_UNIX)
try:
    s.connect(sys.argv[1]); print("CAN")
except OSError as e:
    print("CANNOT", type(e).__name__)
finally:
    s.close()'
echo "== TCP connect matrix"
for u in home-agent svc-home-gateway www-data svc-home-bff svc-finance svc-nutrition; do
  id "$u" >/dev/null 2>&1 || { echo "$u: no such user"; continue; }
  for port in 9934 9935 9936; do
    printf '%-17s uid=%-5s -> %s: %s\n' "$u" "$(id -u $u)" "$port" "$(sudo -n -u $u python3 -I -c "$TCP" $port)"
  done
done
echo "== mint socket"
M=/run/episteck/home-bff-mint/mint.sock
sudo -n stat -c '%U:%G %a %F' $M $(dirname $M)
for u in svc-home-gateway home-agent www-data svc-finance; do
  printf '%-17s -> mint.sock: %s\n' "$u" "$(sudo -n -u $u python3 -I -c "$UNIX" $M)"
done
echo "== nft rules for 9934/9935/9936"
sudo -n nft list ruleset 2>/dev/null | grep -n -E "table|chain|993[456]" | head -30
echo "== Finance image provenance"
U=svc-finance; R=/run/user/$(id -u $U)
IMG=$(sudo -n -u $U sed -n 's/^Image=//p' /home/$U/.config/containers/systemd/finance-api.container)
for q in finance-api finance-mcp finance-sync; do
  printf '%-13s Image=%s\n' "$q" "$(sudo -n -u $U sed -n 's/^Image=//p' /home/$U/.config/containers/systemd/$q.container)"
done
sudo -n -u $U env XDG_RUNTIME_DIR=$R podman image inspect "$IMG" --format 'id={{.Id}} digest={{.Digest}} revision={{index .Labels "org.opencontainers.image.revision"}}'
sudo -n -u $U env XDG_RUNTIME_DIR=$R podman ps --format '{{.Names}} {{.ImageID}} {{.Status}}' | grep -E "^finance"
echo "== Hermes finance MCP url"
sudo -n -u home-agent grep -n -A3 -E "^\s*finance:" /home/home-agent/.hermes/config.yaml | grep -E "finance:|url" | sed -E 's/(token|key|secret)[^ ]*/\1=<redacted>/Ig'
