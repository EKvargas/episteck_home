# Disconnected KAP-2 witness gateway, Task 1

This is a disposable Linux/Python MariaDB protocol unit. It has no HTTP listener, Home API integration, persistent credentials or production install path. `gateway.py` holds a volatile default-closed gate and an exclusive local file lock; all witness authority transitions use the private MariaDB `gateway_schema.sql` procedures. The test harness creates socket-only MariaDB in a temporary directory, uses synthetic passwords/data, and removes its own temporary directory after each test.

From a Linux shell with MariaDB client/server tools and Python 3.11+:

```sh
python3 -m venv /tmp/kap2gw-venv
/tmp/kap2gw-venv/bin/python -m pip install -r spike/knowledge-kap2-transactional-witness/requirements-probe.txt
/tmp/kap2gw-venv/bin/python -m pytest -q spike/knowledge-kap2-transactional-witness/test_gateway.py
```

**Verify after creating these files:** run the last command, then `git diff --check`.

The SQL uses separate `gw_reader`, `gw_writer1`, `gw_writer2` and `gw_recovery` accounts. Writers receive `EXECUTE` only on their epoch-specific entry points; they cannot call the internal definer procedures or directly change tables. `gw_recovery` can install epoch 2's new incarnation and default-deny row, but has no table DML. The test's root connection provisions accounts and simulates a backup restore; it is not a serving credential. Epoch 1/2 routines are fixed synthetic examples, not a dynamic production rotation scheme. The `ready_hint` column exists only to prove the gateway ignores a restored permissive flag.

The unknown-outcome test models a lost **application acknowledgement after MariaDB committed**: a separate scoped connection performs the procedure, and the gateway recovers the exact PENDING or COMMITTED result by event ID. It does not simulate packet-level response loss or a cross-host Home commit gap. The gateway pins both reader and writer MariaDB sessions for the admitted incarnation. Every authorization and mutation checks both sessions with reconnection disabled; loss of either closes admission before an allow or mutation. The recovery session is short-lived and cannot open admission by itself: recovery opens fresh pinned sessions, reads back the new `DENY_ALL` row and checks both sessions before opening. Database restart closes admission. This Linux-only candidate also checks `/proc/self/fdinfo` for a `FLOCK` write lock owned by the gateway's own descriptor; a missing/uncertain ownership record, closed descriptor or replaced lock path closes admission. A restored `COMMITTED`/`ready_hint=1` row cannot open it.

Task 1 does not prove TLS caller authentication, operator custody, arbitrary writer epochs, Home mutation coverage, RT#1/RT#2 ordering, cross-host transactions, simultaneous database and Home restore, or latency. The proposed Board amendment remains unratified and KAP-2 remains open. A named witness operator and backup delegate are required before any persistent host installation.
