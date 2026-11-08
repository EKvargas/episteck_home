# Finance I1 B11 probes

Live verification scripts for Olin Finance I1 (B11). The results are in
[`docs/architecture/FINANCE_I1_VALIDATION.md`](../../docs/architecture/FINANCE_I1_VALIDATION.md).

Every script prints status codes, refusal codes, field names, account slugs, dates, booleans
and counts. None prints an amount, a delegation, a token or a bank identifier. They need
`episteck` sudo on `episteck-node1`. Run them from Git Bash on the laptop; `-F` is needed there
because Git Bash's ssh does not read the Windows config.

| Script | What it proves | Writes |
| --- | --- | --- |
| `b11_probe.py agent` (as `home-agent`) | gateway allow, forged header replaced, `tools/list` schema, no direct 9936 | nothing |
| `b11_probe.py gateway` (as `svc-home-gateway`) | direct 9936 without or with a garbage delegation is refused; a minted delegation works once, its replay is refused | mints 1 delegation |
| `b11_probe.py expired` (as `svc-home-gateway`) | a delegation used after the 120 s TTL is refused | mints 1 delegation |
| `b11-homedown.sh` + `b11_homedown.py` | Home refused, hanging, 500, malformed 200: Finance answers 503 / `service_unavailable` and no data; Home 401: `session_invalid` | a throwaway container (`--rm`, `--network none`, empty temp DB, throwaway pepper) |
| `b11-matrix.sh` | real-user TCP matrix for 9934/9935/9936, mint socket, nft rules, image provenance | nothing |
| `b11-logscan.sh` | Finance, gateway, nginx and Hermes logs hold no IBAN, amount, amount field or Enable Banking reference | nothing |
| `b11-first-check.sh` | provider, model and Finance status codes behind the owner's Telegram questions after the 2026-11-07 22:07 switch | nothing |

## Run

```bash
H="ssh -F C:/Users/D064974/.ssh/config episteck-node1"
# delegation probes
$H 'D=/tmp/b11probe; mkdir -p $D && chmod 755 $D && cat > $D/b11_probe.py && chmod 644 $D/b11_probe.py' < b11_probe.py
$H 'cd / && sudo -n -u home-agent python3 -I /tmp/b11probe/b11_probe.py agent'
$H 'cd / && sudo -n -u svc-home-gateway python3 -I /tmp/b11probe/b11_probe.py gateway'
$H 'cd / && sudo -n -u svc-home-gateway python3 -I /tmp/b11probe/b11_probe.py expired'   # ~130 s
# Home down
$H 'cat > /tmp/b11probe/b11_homedown.py && chmod 644 /tmp/b11probe/b11_homedown.py' < b11_homedown.py
$H 'bash -s' < b11-homedown.sh
# read-only checks
$H 'bash -s' < b11-matrix.sh
$H 'bash -s' < b11-logscan.sh
# clean up
$H 'rm -rf /tmp/b11probe'
```

The `gateway` and `expired` modes mint real delegations from the owner's runtime grant. If
the grant has expired, the allow rows fail closed. That is also a valid result, but the
allow path then needs a fresh grant at `/runtime` before it can be proven.
