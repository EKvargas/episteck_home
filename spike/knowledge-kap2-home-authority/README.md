# KAP-2 Task 2 disconnected Home authority candidate

This draft adds the exact accepted PR #60 typed evaluator, a Knowledge-only current-incarnation activation overlay, an internal Frappe fact loader, and an EXECUTE-only disposable Home event/revision lane. No hooks, whitelisted methods, HTTP endpoints, DocTypes, migrations or production credentials are added. Existing Home APIs continue using their existing policy.

The overlay requires a fresh witness match and explicit current-incarnation activation for every grant or Person self-access. It rechecks the underlying typed grant, issuer and dependency at evaluation. Person grant reauthorization in the Frappe loader checks the authenticated User→Person, current source grant, exact scope and trusted partition argument. Circle issuance is closed because today's `Circle Membership.role_in_circle` is descriptive and no authoritative typed Circle grant source exists. The synthetic typed evaluator still denies invalid Circle dependencies, membership-only access and Circle self-access.

The `home_schema.sql` procedures provide a disposable local transaction: exact event, one revision, activation and digest move together. The witness PREPARE precedes the Home commit; witness COMMIT follows it. Reads of a PENDING witness row deny. An unknown outcome must be reconciled by exact event ID; there is no automatic retry that guesses success. The Home site principal has no protected-schema privileges. The marked Frappe probe connects its authenticated Person proof to this real local gateway and Home event lane for one grant and one self-activation, then reads the activation rows back into the policy snapshot. The separate `kap2_frappe.py` probe copied unchanged from PR #61 exercises the named legacy source guards against actual Frappe operations; its candidate reader uses an in-memory witness. These components are not wired into RT#1/RT#2 serving.

## Verify

On WSL Ubuntu with Python 3.11+, MariaDB and the Task 1 probe dependencies:

```sh
PYTHONPATH=apps/episteck_home /tmp/kap2gw-venv/bin/python -m pytest -q \
  apps/episteck_home/tests/test_access_policy.py \
  apps/episteck_home/tests/test_typed_access_policy.py \
  apps/episteck_home/tests/test_knowledge_authority.py \
  spike/knowledge-kap2-home-authority/test_lane.py
git diff --check
```

For the Frappe probe, pass an existing **disposable** Frappe 15.99.0 bench with `episteck_home` installed. The runner creates a uniquely named marked site, private socket-only MariaDB and two nonpersistent Redis processes. It refuses occupied Redis ports and drops only its named site, then stops its private services. It must not be pointed at a production bench.

```sh
PYTHONPATH=apps/episteck_home /tmp/kap2gw-venv/bin/python \
  spike/knowledge-kap2-home-authority/run_frappe.py \
  --bench /tmp/kap2-frappe-bench-20261007-c \
  --evidence spike/knowledge-kap2-home-authority/evidence/2026-10-09/frappe_results.json
```

## Remaining safety work

- The partition argument must come from a trusted site/service registry. The temporary Frappe loader has no production partition registry and no private authenticated channel to the mutator.
- The event digest is calculated by the trusted writer over the event and previous digest. The disposable SQL procedure verifies exact-event equality, not a full canonical policy projection; complete source inventory and digest encoding remain required.
- The Task 1 witness and Home store are both local in the transaction test and marked Frappe probe. The Frappe process receives synthetic root credentials only for setup on its disposable site. A separated host, authenticated service boundary, crash/unknown-outcome recovery, full Home source guarding and RT#1/RT#2 ordering remain unproved.
- The guarded Frappe probe covers named source fields and ordinary operations, not every migration, background job, privileged maintenance path or future schema source. Its triggers are disposable candidate guards, not a production migration.
- Board ratification, witness operator and backup delegate are pending. KAP-2 is open; do not activate this module.
