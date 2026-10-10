# Task 1 local MariaDB gateway evidence — 2026-10-09

**Environment:** local WSL Ubuntu, MariaDB client/server 10.11.13, Python 3.12.3, PyMySQL 1.1.2, pytest 8.4.2. A private `mariadbd --skip-networking` instance and synthetic accounts/data were created in a new temporary directory for each test, then stopped and removed by the fixture. No Ashburn, Nuremberg, GCS, production site or Home API was touched.

**Reproduce:** from the repository root in a Linux shell after the README's venv setup:

```sh
/tmp/kap2gw-venv/bin/python -m pytest -q spike/knowledge-kap2-transactional-witness/test_gateway.py
```

Original Task 1 result: `6 passed in 34.04s`. The unchanged home-contracts suite also passed `37 passed in 0.60s` at that point. Architect correction regressions first ran red against the real private database: released-but-open `flock` and writer-only connection kill both incorrectly allowed; replaced lock path denied. After the gateway correction, the focused real MariaDB suite passed: `9 passed in 47.42s`. No mocks were used in these nine tests. Home-contracts was not repeated because no contract code changed.

| Real local case | Observed result |
| --- | --- |
| First read before recovery; concurrent same-process and independent-process gateway starts | First read denied; both contenders rejected by the exclusive file lock. |
| Fresh recovery from a restored-looking `COMMITTED`/`ready_hint=1` row | New 256-bit incarnation installed; row readback was `COMMITTED`, revision zero, `DENY_ALL`, `ready_hint=0`; authorization still denied. |
| PENDING, duplicate PREPARE/COMMIT, conflicting duplicate, exact-event readback | PENDING denied; identical retries did not advance twice; conflict rejected and original event unchanged; exact event readback returned PENDING then COMMITTED. |
| Old and wrong principal, direct SQL | Epoch-1 writer failed after epoch-2 recovery; it could not call epoch-2 procedure. Reader, old writer and recovery principal lacked direct head DML; epoch-2 writer could not call recovery procedure. |
| Gateway restart, DB restart, process-lock loss | Previously permissive current-incarnation read denied on DB loss and marked gateway CLOSED; gateway restart began CLOSED; lost lock denied and closed. |
| Released `flock` with descriptor still open, independent contender holding the same lock | Previously permissive authorization denied; original gateway closed and both PREPARE and COMMIT rejected. |
| Replaced lock path, closed descriptor | Both deny authorization and close admission; mutation rejected after path replacement. |
| Writer connection killed while reader remained usable | Next previously permissive authorization denied and closed admission; mutation rejected; recovery installed a different default-deny incarnation. |
| Actual private-datadir restore of old `COMMITTED`/`ready_hint=1`/permissive rows after a synthetic revoke | First post-restore read denied while gateway CLOSED; a new incarnation remained default-deny and did not admit old permissive rows. |

**Unknown-outcome limit:** the test commits PREPARE and COMMIT on a separate scoped connection, discards that application's acknowledgement, and then retries/reads the exact event through the gateway. It does not drop a server response packet after execution, model a separate Home commit, or prove multi-host crash recovery. Fixed epoch-1/epoch-2 procedures are a disposable principal-fencing probe, not a general epoch-registration system. The gateway has no network listener or authenticated remote caller boundary. Production admission, Board ratification, operator assignment, Frappe mutation coverage and RT#1/RT#2 behavior remain unproved.
