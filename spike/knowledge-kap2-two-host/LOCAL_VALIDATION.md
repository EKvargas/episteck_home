# Local validation of the two-host package

**Scope:** one fresh loopback run on 2026-10-10 using WSL Ubuntu, Python 3.12, real disposable MariaDB processes, mTLS and synthetic PERSON authority. This is local integration evidence, **not** the Ashburn–Nuremberg acceptance run. The remote preflight and mandatory disposable Frappe step A9 were unexecuted in this run. The consolidated PR #71 handoff records the earlier local Frappe 15.99.0 result separately.

## Reproduction

In an isolated Linux/WSL environment with `mariadbd`, `mariadb`, `mariadb-admin`, `mariadb-install-db`, Python 3.11+, PyMySQL and `cryptography` installed:

```sh
python certs.py --out /tmp/kap2-pr71-certs-local-02 --server-ip 127.0.0.1 --local
python witness_runner.py --root /tmp/kap2-pr71-twohost-local-w-04 --evidence /tmp/kap2-pr71-witness-local-evidence-04.jsonl --bind 127.0.0.1 --loopback-only --port 19442 --ca /tmp/kap2-pr71-certs-local-02/ca.crt --cert /tmp/kap2-pr71-certs-local-02/server.crt --key /tmp/kap2-pr71-certs-local-02/server.key
# In a second shell, with PYTHONPATH pointing at this checkout's apps/episteck_home:
python home_runner.py --root /tmp/kap2-pr71-twohost-local-h-06 --evidence /tmp/kap2-pr71-home-local-evidence-06.jsonl --witness-host 127.0.0.1 --port 19442 --ca /tmp/kap2-pr71-certs-local-02/ca.crt --serving-cert /tmp/kap2-pr71-certs-local-02/serving.crt --serving-key /tmp/kap2-pr71-certs-local-02/serving.key --recovery-cert /tmp/kap2-pr71-certs-local-02/recovery.crt --recovery-key /tmp/kap2-pr71-certs-local-02/recovery.key --local
```

The server was then stopped with SIGTERM. The named Home and witness roots were absent in their respective fsynced cleanup events. The local certificate directory is temporary and must be removed after inspection. Remote execution instead requires the exact paths, clean SHA preflight and bench specified in [README.md](README.md).

## Observed result

All 11 executed matrix steps passed: mTLS role/credential isolation and CLOSED start; synthetic grant/self, named DML bypass and ordinary note; dependency/issuer/expiry invalidation; reader-first and writer-first revocation; writer connection loss; unknown PREPARE and COMMIT acknowledgements; gateway restart; physical Home/witness restore with first-read denial and selected reauthorization; and the latency/request-count screen. The final run did not use the iterative `--reset-local` flag.

| Measure | Fresh loopback observation |
| --- | ---: |
| Attempted client requests / cap | 269 / 400 |
| Witness authorize requests | 161 |
| Expected transport errors / rejected TLS attempt | 2 / 1 |
| Warm individual call p50 / p95 / p99 | 46.915 / 49.927 / 50.537 ms |
| Warm pair p50 / p95 / p99 / max | 106.630 / 110.356 / 115.905 / 115.905 ms |
| Cold individual call p50 / p95 / p99 | 48.460 / 51.373 / 52.819 ms |
| Cold pair p50 / p95 / p99 / max | 107.726 / 116.786 / 189.142 / 189.142 ms |

The screen used 30 warm and 30 cold pairs, two calls per pair and exactly one witness request per call. “Cold” reset only the witness TCP/TLS connection before the pair. These loopback measurements do not establish a cross-host latency result or the unratified KAP-2 budget. At 30 pairs, p99 is effectively a maximum.

**Evidence and cleanup verification:** `matrix_summary` reported all 11 steps `PASS`, 269 attempts and request counts by operation, role and outcome. `home_cleanup` recorded `root_absent=true`; `witness_cleanup` recorded `root_absent=true` and admission `CLOSED`. After removing the marked local certificate directory, `verify_cleanup.py` returned `complete=true` for both sides; it also found the witness listener absent. The remote Frappe and cleanup checks remain requirements for the authorized two-host gate.

**Verify this record:** `rg -n '269 / 400|unexecuted|root_absent' spike/knowledge-kap2-two-host/LOCAL_VALIDATION.md`.
