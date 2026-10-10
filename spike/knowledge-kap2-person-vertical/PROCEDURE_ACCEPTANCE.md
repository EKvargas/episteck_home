# KAP-2 local PERSON foundation: pre-run acceptance matrix

**Baseline:** PR #68 `0c8c0006ec115b9084e1393df572b5a753771bcc`. The selected MariaDB witness and default-closed fresh-incarnation recovery remain fixed. This is a disconnected disposable candidate, not full KAP-2 acceptance.

| ID | Required observation | Evidence |
| --- | --- | --- |
| P1 | Serving `ha_mutator` has only read and named procedure execution rights. It cannot directly INSERT/UPDATE/DELETE binding, head, events, activations, dependency, User, Person, or Consent Grant. Schema installer and recovery principal are distinct. | Real MariaDB grants and rejected direct SQL. |
| P2 | Named procedures require the current partition lane and exact Home head, validate source/issuer for grant, self, revoke, dependency, disable and unlink, and stage changes without committing. Python preserves witness PREPARE -> Home commit -> witness COMMIT and exact-event retry. | Real two-MariaDB mutation and race suite. |
| P3 | If Home connection or lock is lost during witness comparison, or transaction rollback/lane release fails after policy computes allow, authorization returns deny and admission closes. No extra Home crossing is added. | Targeted fault injection against the integrated reader. |
| P4 | Existing grant, self, revoke, dependency, expiry, both race orders, commit-gap, idempotency, digest and generic Frappe bypass cases pass with restricted serving principals. Ordinary tested Home APIs remain usable. | Full local MariaDB suite and marked disposable Frappe run. |
| P5 | Physical backup of both stopped disposable MariaDB datadirs at matching permissive state, later revocation, and restoration of both older datadirs still deny on first read. New incarnation quarantines old grants/self acts; authenticated selected reauthorization restores only those scopes. | Real local datadir copies and restart; keep prior row-replay result separate. |

Fail the milestone for any unverified allow, direct serving DML success, restore-based permission revival, loss of named path coverage, or uncleaned disposable service/site. Label any incomplete criterion explicitly.

**Verify:** `test -f spike/knowledge-kap2-person-vertical/PROCEDURE_ACCEPTANCE.md && test -f docs/superpowers/plans/2026-10-10-kap2-person-procedures.md`.

## Result: local disposable integration (2026-10-10)

| ID | Result | Evidence |
| --- | --- | --- |
| P1 | PASS | `test_serving_and_recovery_principals_have_no_direct_authority_dml` rejects eight direct serving writes to protected Home and Frappe sources, denies serving recovery procedure use, denies recovery direct DML/event use, and rejects a mutation procedure call without lane ownership. The serving account has SELECT plus EXECUTE on `stage_person_mutation` and `record_person_event`; `ha_recovery` has SELECT of binding/head plus EXECUTE on `reset_person_incarnation`. The root installer is not passed to the Frappe probe. A separate `ha_fixture` exists only in the Python test harness for deliberate tampering/row replay. |
| P2 | PASS within local scope | All named PERSON grant/self/restrictive changes, exact duplicate retry, protected head revision, digest and both revocation lock orders pass against real MariaDB. Definer procedures require the caller's live partition advisory lock and exact Home head. No procedure commits; the existing caller transaction and witness PREPARE/Home commit/witness COMMIT order remain. |
| P3 | PASS for targeted losses | `test_computed_allow_is_discarded_after_home_lane_failure` kills the pinned Home reader connection or releases its lock after a true witness comparison. Both decisions deny and set local admission CLOSED. Lane cleanup now raises on a failed release. The reader still uses one protected Home transaction and one fresh witness comparison. |
| P4 | PASS for named paths | Full two-MariaDB suite: **18 passed in 221.91 s**. Marked disposable Frappe 15.99.0 run: nine positive assertions for grant/self, generic save/delete/`db.set_value`/SQL/Administrator denial, serving-principal denial of unrelated DocType read and protected DML, ordinary Person edit, existing `check_access`, session open/close and fresh selected reauthorization. `frappe_evidence.json` records four cleanup assertions as true. |
| P5 | PASS for local cold physical restore | The test stops both databases after a permissive grant and self activation, copies both datadirs, restarts and creates a later incarnation with an allow followed by revocation, then stops both and restores both older physical datadirs. It verifies the restored Home and witness heads match the older permissive pair and source is ACTIVE; the first authorization denies. Fresh recovery quarantines old activations; self reauthorization restores only self, and later exact grant reauthorization restores the grantee. The earlier row-replay test remains separate. |

The physical schedule crosses a database stop/restart and thus performs the
later revocation in a new incarnation. It does not prove a production backup
protocol, remote witness restore independence, or a same-incarnation hot
physical snapshot. The synthetic Frappe probe supplies the recovery secret
only to its explicit `recover` call; production separation of recovery
operators/processes remains unimplemented. CIRCLE, delegated machine context,
exhaustive Home authority fields, remote host failure, latency and live gates
are outside this local PERSON foundation. KAP-2 remains open.

**Cleanup:** The Frappe runner reported `site_removed`, `private_db_stopped`,
`private_witness_stopped` and `private_redis_stopped` all true. The local test
fixture stopped both databases and removed its temporary datadirs. After
verification, the separate WSL bench, test venv and Yarn directories were
removed; their absence was checked. No production site, credential, migration
or service was changed.

**Reproduction:** Use Python 3.11+, PyMySQL and pytest with
`PYTHONPATH=apps/episteck_home python -m pytest -q -s spike/knowledge-kap2-person-vertical/test_integrated.py`.
For Frappe, use the existing marked-site runner
`python spike/knowledge-kap2-person-vertical/run_frappe.py --bench <disposable-frappe-15.99.0-bench> --evidence spike/knowledge-kap2-person-vertical/frappe_evidence.json`.
