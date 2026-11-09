#!/bin/bash
# B11 read-only: are logs free of amounts, IBANs and bank account references? COUNTS ONLY.
# For a non-zero count it shows the matching line with every digit masked, max 3 lines.
cd /
IBAN='\b[A-Z]{2}[0-9]{2}( ?[A-Z0-9]{4}){3,7}\b'
MONEY='((€|EUR|USD|\$) ?-?[0-9][0-9.,]*[0-9]|-?[0-9][0-9.,]*[.,][0-9]{2} ?(€|EUR|USD))'
FIELDS='"?(amount_minor|balance_amount|amount)"? ?[:=] ?"?-?[0-9]'
EBREF='WwpbCiJh|identification_hash'
scan() { # $1 label, stdin text
  local t; t=$(cat)
  local n; n=$(printf '%s\n' "$t" | wc -l)
  printf '%-34s lines=%-7s' "$1" "$n"
  for pat in IBAN MONEY FIELDS EBREF; do
    printf ' %s=%s' "$pat" "$(printf '%s\n' "$t" | grep -c -E "${!pat}")"
  done
  echo
  printf '%s\n' "$t" | grep -E "$IBAN|$MONEY|$FIELDS|$EBREF" | head -3 | sed -E 's/[0-9]/#/g' | cut -c1-140 | sed 's/^/      /'
}
fin() { sudo -n -u svc-finance bash -c "export XDG_RUNTIME_DIR=/run/user/\$(id -u); journalctl --user -u $1 --since 2026-10-20 -o cat --no-pager" 2>/dev/null; }
for u in finance-api finance-mcp finance-sync; do fin $u | scan "journal $u"; done
sudo -n journalctl -u episteck-mcp-gateway --since 2026-10-20 -o cat --no-pager 2>/dev/null | scan "journal episteck-mcp-gateway"
for f in $(sudo -n ls /var/log/nginx/ 2>/dev/null | grep -i -E "gateway|bff" | grep -v -E "\.gz$"); do sudo -n cat "/var/log/nginx/$f" | scan "nginx $f"; done
for f in agent.log errors.log gateway.log; do sudo -n -u home-agent cat "/home/home-agent/.hermes/logs/$f" 2>/dev/null | scan "hermes logs/$f"; done
sudo -n -u home-agent bash -c 'cat /home/home-agent/.hermes/memories/*.md 2>/dev/null' | scan "hermes memories/*.md"
sudo -n journalctl --user-unit hermes-gateway --since 2026-11-07 -o cat --no-pager 2>/dev/null | scan "journal hermes-gateway (system view)"
