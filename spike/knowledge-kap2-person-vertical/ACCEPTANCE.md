# KAP-2 limited PERSON vertical: pre-run acceptance matrix

**Status:** criteria fixed before the disposable integration run. This is a local integration candidate based on PR #67 `a15d1083984b9d35af4dd9568c6fa924e67b8166` and the accepted Task 1 gateway in PR #66 `cd6abedac61f5305760d357ad74a70127c6fb607`. The transactional witness and default-closed fresh-incarnation recovery direction is frozen. No CIRCLE issuance, RT#1/RT#2 endpoint, production schema or service is activated.

The Home partition lane must be acquired on one pinned connection for the whole read decision or write sequence. A writer stages its Home mutation and complete post-state digest inside one transaction, publishes witness PENDING, commits Home, publishes matching witness COMMITTED, and only then releases the lane. A reader acquires the same lane, reads a consistent protected Home snapshot, recomputes its canonical digest, performs one fresh witness comparison and evaluates typed policy before releasing the lane. Lost lock or connection denies. The authorization linearization point is the witness comparison while the Home lane and snapshot remain held.

For this vertical, Home authority sources are: authenticated Frappe site→protected partition registry; Frappe session→enabled User→unique Person; active exact Person Consent Grant with validity; issuer Person/User link and enablement; protected current-incarnation grant/self activation rows; protected head/event/revision/digest; witness row and volatile admission gate. CIRCLE membership and role labels are never grant sources. Database guards must deny generic updates to the named authority fields; ordinary unrelated Home fields and existing read APIs must still work. The private mutator path is the sole writer of guarded fields in the disposable site.

| ID | Acceptance case | Required observation | Evidence class |
| --- | --- | --- | --- |
| A1 | Trusted binding | Supplied partition/issuer mismatch or service-site mismatch cannot activate or authorize; actual issuer comes from the authenticated enabled User→unique Person. | Real disposable Frappe + MariaDB |
| A2 | Grant/self allow | Current exact Person grant activation and separate Person self-activation allow only after matching witness COMMIT and full-state digest. CIRCLE self/issuance deny. | Real disposable Frappe + two MariaDB services |
| A3 | Revocation/expiry/dependency | Grant revoke, time expiry, issuer disable/relink and target dependency invalidation deny. Relevant mutations advance the protected lane; both reader-first and writer-first orders are exercised. | Real disposable Frappe + two MariaDB services |
| A4 | Commit/ack gaps | PENDING before Home commit, Home committed before witness COMMIT, lost acknowledgement and unresolved outcome never permit an unverified allow; exact retry is idempotent. | Real disposable MariaDB fault schedule |
| A5 | Restart/restore | First authorization after gateway/DB restart and combined older Home+witness restore denies; fresh recovery is default-deny and old grant/self rows remain quarantined. | Real disposable two-datadir restore |
| A6 | Principal/bypass | Old epoch principal and site runtime cannot mutate canonical state, use private procedures, or change guarded User/Person/Grant fields via save/delete, `db.set_value`, raw SQL or Administrator. Needed ordinary Frappe writes succeed. | Real disposable Frappe + MariaDB principals |
| A7 | Explicit reauthorization | Only a new authenticated issuer's exact current-incarnation grant act and that Person's self act restore their selected scope after recovery. No bulk import. | Real disposable Frappe + MariaDB |
| A8 | Home compatibility | Existing Person `check_access` and other Home read APIs return their baseline decisions; ordinary non-authority edits and session operations remain usable. | Real disposable Frappe |

**Fail criteria:** any old or unmatched grant authorizes; a reader uses a snapshot or witness value obtained before waiting on the lane; a staged state can hash to a witness digest without the evaluated rows matching; a generic site write changes an authority source outside the lane; recovery opens from restorable READY/COMMITTED data; required ordinary Home behavior is blanket-denied; or the disposable resources are not completely removed. Mark an unexecuted case UNEXECUTED, never PASS by inference or mock.

**Verify this file exists before running integration:** `test -f spike/knowledge-kap2-person-vertical/ACCEPTANCE.md`.

## Disposable result (2026-10-09)

The matrix above was written before the run. The code uses two separate local
MariaDB processes, and the Frappe run uses a newly marked site on an existing
disposable bench. Neither proves remote witness operation or production safety.

| ID | Result | Evidence and limit |
| --- | --- | --- |
| A1 | PASS for direct human PERSON | Real Frappe session User and protected site/service registry; caller partition/issuer mismatches and unbound service deny in `test_trusted_binding_recovery_grant_and_self`. Delegated machine context is outside this vertical. |
| A2 | PASS for PERSON | Real Frappe grant/self allow only after current-incarnation activation and COMMIT. Real MariaDB digest mismatch denies. CIRCLE requirement denies; CIRCLE issuance is absent. |
| A3 | PASS for named sources | Real MariaDB grant revoke, dependency off, expiry at read time, issuer User disable and Person unlink deny. Reader-first and writer-first schedules use the same Home lane. Expiry does not need a wall-clock revision mutation. Other Home authority sources are outside this vertical. |
| A4 | PASS for tested schedules | Real MariaDB PREPARE before Home commit holds the lane; a waiting reader times out closed. Home commit with missing COMMIT yields PENDING denial. Lost COMMIT acknowledgement closes local admission despite a committed event; exact duplicate event retry is idempotent. |
| A5 | PASS for first-read closure; physical restore UNEXECUTED | Real Home and witness DB restart each deny on first read. Older Home and witness **rows** replayed together into the two live disposable databases still deny after gateway restart, then fresh recovery quarantines prior activations. This is not a physical datadir or remote backup restore. |
| A6 | PASS for demonstrated paths | Real Frappe save/delete, `db.set_value`, raw SQL and Administrator cannot change named User/Person/Consent Grant fields. Site and old principals cannot directly change protected head; ordinary Person note write succeeds. The private mutator credential remains trusted and is not a production privilege design. |
| A7 | PASS for PERSON | Real Frappe fresh recovery denies old grant and self activations. The authenticated owner separately activates the selected grant and self permission in the new incarnation; the grantee then allows. |
| A8 | PASS for tested APIs | Existing `check_access` decision matches its baseline; Frappe ordinary Person note update and delegated session open/close pass. This is not an exhaustive Home regression. |

Reproduce the MariaDB suite (14 tests):

```sh
PYTHONPATH=apps/episteck_home /tmp/kap2gw-venv/bin/python -m pytest -q spike/knowledge-kap2-person-vertical/test_integrated.py
```

Reproduce the disposable Frappe run from WSL (the runner validates the bench,
creates only a marked synthetic site, then drops it and stops its private
MariaDB/Redis services):

```sh
PYTHONPATH=apps/episteck_home /tmp/kap2gw-venv/bin/python spike/knowledge-kap2-person-vertical/run_frappe.py --bench /tmp/kap2-frappe-bench-20261007-c --evidence spike/knowledge-kap2-person-vertical/frappe_evidence.json
```

`frappe_evidence.json` records eight true probe assertions and four true cleanup
assertions. It contains no real identity values. The acceptance results are local
integration evidence only; there was no live Home/Knowledge authorization path.

### Boundary and remaining work

The protected registry binds the Frappe site and fixed service to one partition
and site database. The authenticated session User must be enabled and resolve to
one Person. For each active incarnation, the digest hashes the protected
activation rows and the exact User enablement/Person links, Consent Grant
fields, and dependency flags those rows use, plus partition, incarnation and
revision. The reader recomputes that digest from one Home transaction, compares
the stored head, then calls the fresh witness while still holding the same
MariaDB advisory lane. This is an evaluated-state digest, not merely an event
chain digest.

Disposable site triggers cover INSERT of grants and linked Persons; DELETE and
authority-field UPDATE of User, Person and Consent Grant. Protected tables are
unwritable by the site principal. The `ha_mutator` credential, schema installer,
and host remain inside the trusted boundary of this **candidate**. A production
integration needs procedure-only mutator privileges, exhaustive source/field
inventory, credential isolation, real backup/restore exercises, operator and
delegate assignment, Board ratification, remote witness operation, and
latency/recovery proof. No Frappe hook or existing API calls this module. Its
direct-human PERSON scope excludes delegated sessions as an authority source,
CIRCLE issuance, and RT#1/RT#2.
