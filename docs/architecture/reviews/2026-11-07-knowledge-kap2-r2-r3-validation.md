# KAP-2 R2/R3 local correction — 2026-11-07

**Scope:** follow-up to the [recovery review](2026-10-24-knowledge-kap2-recovery-review.md) items R2 and R3, plus enforcement of the R5 latency gate. The baseline is `origin/main` `dbe6632` plus the [2026-11-07 decisions](../../../spike/knowledge-kap2-two-host/DECISION_SHEET.md#decisions-recorded-2026-11-07-owner-erick-acting-as-board). It covers the local, disconnected PERSON candidate only. The candidate stays inert on the Home bench: no import, hook, whitelisted method or schema reaches it. This work involved no SSH, remote experiment or production change.

## R2: rotate and retire writer principals on every recovery

**Defect (RED):** `recover_e2` always set `writer_epoch = publisher_epoch = 2`, and the gateway always connected as `gw_writer2`. After a second recovery, a `gw_writer2` session opened before it stayed connected. The same credential could still call `prepare_e2` carrying the new incarnation. The first failing assertion was `assert '2\t2' == '3\t3'` (epoch after a second recovery).

**Correction:**

- A `witness.writer_principals` registry binds each `(partition, epoch)` to exactly one DB principal. A principal moves `UNUSED → ACTIVE → RETIRED` and never returns.
- `prepare_event`/`commit_event` replace the per-epoch `prepare_e1/e2`/`commit_e1/e2` entry points. They accept a call only if the session's own `USER()` is the `ACTIVE` principal for the head's current epoch, so a credential that is still valid does not help a retired principal.
- `recover_partition` moves to epoch `old + 1` inside the head-locked transaction, and only with that epoch's `UNUSED` principal. Missing, already-active or retired principals reject; the head and registry stay unchanged and the gateway stays `CLOSED`.
- After the authority transaction commits, recovery does the account DDL:
  - it installs a credential the gateway **minted for this recovery**; only its `mysql_native_password` stored hash crosses to the witness;
  - it **locks** every retired principal's account;
  - it **kills** each retired principal's live sessions.
- The gateway drops its own pinned writer before rotation. It has no configured writer password any more.

Minting closes a gap found during this work. A physical restore of an older datadir also restores old account passwords and lock states, so a principal used *after* the snapshot reappears as `UNUSED`. With pre-provisioned passwords, the next recovery would have re-activated it with its old, possibly leaked, password. A minted credential cannot be revived by a restore.

**Evidence (real disposable MariaDB 10.11):**

- `test_repeated_recovery_retires_previous_writer_principal`: across three recoveries, epochs go 2→3→4. The pre-recovery session is killed and the account refuses logins with `4151`. Once re-enabled, a call with the current incarnation is rejected with `1644`.
- `test_recovery_without_fresh_writer_principal_stays_closed` (retired, missing row, already active): the recovery is rejected and nothing changes.
- `test_writer_call_queued_behind_recovery_cannot_reach_new_incarnation`: an old-writer call already blocked on the head lock when recovery starts either loses (killed or rejected) or lands in the old incarnation. The new incarnation has zero events.
- `test_physical_restore_cannot_revive_any_writer_credential`: after restoring a datadir taken at epoch 2 (registry shows epoch 2 `ACTIVE`, epoch 3 `UNUSED`), neither the snapshot-era credential nor the lost-history epoch-3 credential authenticates. Recovery installs a fresh epoch-3 credential.
- `test_database_principals_and_old_epoch_are_enforced`: retired, future (misprovisioned) and current principals have no DML. Neither writer nor recovery principal can call the private `_retire_writers`.

**Limits:** the candidate is single-partition. Per-partition registries are modelled, but multi-partition gateway serving and production credential custody (who provisions principals, where minted credentials live) remain R4. The account DDL runs after the authority commit; if it fails, the gateway stays closed and the next recovery moves to the next epoch. The epoch pool is operator-provisioned (24 in tests); running out means recovery is rejected.

## R3: unknown outcome at every mutation position

**Defect:** any failure after the witness PREPARE left the partition `PENDING` and the authority closed. That included an uncertain Home COMMIT acknowledgement. The only way out was a full recovery, which under ADR-0014 quarantines every Knowledge grant and forces per-Person reauthorization. The existing matrix also did not exercise Home COMMIT uncertainty. RED: all 12 position cases failed only at the missing resolver, after `not authority.open` had already passed. The existing code was fail-closed but unresolvable.

**Correction:** `PersonAuthority` records an unproven outcome whenever a witness call may have taken effect or the Home COMMIT was sent. It never rolls back over a sent COMMIT. `resolve_unknown()` then works as follows:

1. It requires the same authenticated issuer.
2. It **kills the old Home mutation session and waits until the server thread is gone**. Only then are Home's rows the durable outcome rather than a guess from a client error.
3. It re-runs the exact event on a fresh session under the partition lane:
   - If Home holds the event, it republishes the witness PREPARE/COMMIT idempotently (`HOME_COMMITTED`).
   - Otherwise it re-applies the identical request under the same event ID. The witness accepts this only for the exact revision and digest it already reserved (`REAPPLIED`). Because the old session is proven gone first, no late commit can race the re-application.
4. Any failure keeps Knowledge closed. `recover()` also retires an unresolved session before quarantining.

**Evidence:** `test_unknown_outcome_is_resolved_by_exact_event_readback` covers 6 positions × {revocation, grant}:

- prepare acknowledgement lost;
- Home COMMIT acknowledgement lost, transaction committed;
- Home COMMIT not delivered, session still alive with an open transaction;
- Home COMMIT not delivered, session dead;
- witness COMMIT not delivered;
- witness COMMIT acknowledgement lost.

Each case asserts five things:

- An independently admitted reader allows only where both stores had already committed and agree.
- Home's actual event row matches the true outcome, not the client error.
- The resolution path is the expected one and the revision is exactly `+1`.
- The old session is gone, and Home and witness agree on `(incarnation, revision, digest)` with the event `COMMITTED` exactly once.
- A later mutation proceeds normally.

`test_unknown_resolution_requires_the_same_authenticated_issuer` and `test_unretirable_old_session_keeps_partition_closed_until_recovery` cover the guards. A session that cannot be retired leaves the partition closed, and recovery still works.

**Limits:**
- Resolution needs the in-process record of the unknown event. If a Home process crashes mid-mutation, that memory is lost: the partition stays `PENDING` and the operator recovers, which quarantines grants. A fresh process cannot attach to the current incarnation anyway; it has to recover. A production attach/reconcile path belongs to R4.
- The resolver retires only the recorded session, using the mutator principal's right to kill its own sessions.
- Witness-side gateway closure (lost writer connection) still requires recovery, as specified (A5).

## R5: latency gate enforced

`home_runner.py` A10 now writes each distribution with `gate_ms`, `gate_breaches` and `GATE_PASS`/`GATE_FAIL`, then fails the step on any breach. The thresholds are per-call p95 ≤100 / p99 ≤200 ms and pair p95 ≤200 / p99 ≤400 ms; a missing or invalid metric counts as a breach. `test_latency_gate.py` covers the thresholds, each breach and the fail-closed inputs.

## Effect on the two-host package

- The witness runner's privilege probe never issues a legal write.
  - **Before any recovery (A1):** it checks that the epoch-1 writer, which is legitimately `ACTIVE`, has no direct DML, and that the next epoch's principal cannot log in.
  - **After a recovery (A2):** it checks that the retired epoch-1 writer is locked and, if unlocked, rejected with `1644`. The direct-DML probe uses the gateway's minted writer.
  - The first loopback run of this candidate failed A1. The probe had no pre-recovery writer, and its old `gw_writer1` write-procedure call would have been a real write in the old incarnation under the new design. The probe was fixed; it has no gateway impact.
- No runner HTTP request is added, so the 400-request cap and the single witness read per ordinary authorization are unchanged.
- The matrix performs about 20 recoveries, so the test fixture provisions 64 writer principals.
- Package file hashes changed. A remote run therefore needs review of this exact commit and a fresh exact-SHA authorization, as the decision sheet already requires.
- Nuremberg's pinned MariaDB 11.8 has not been exercised with the registry, account-lock or kill procedures.

## Results

See the [structured evidence](../../../spike/knowledge-kap2-two-host/evidence/2026-11-07-r2-r3/result.json).

**Verify:** `python -m json.tool spike/knowledge-kap2-two-host/evidence/2026-11-07-r2-r3/result.json`. The Linux/WSL test commands are recorded in that JSON.
