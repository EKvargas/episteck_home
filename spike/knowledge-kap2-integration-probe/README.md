# KAP-2 disposable integration probes

Status: **integration evidence incomplete**. PR #59's mechanism is accepted only as a candidate for validation. No production schema, fence, credentials, migration or endpoint is changed by this spike.

## Frappe probe

`episteck_home.probes.kap2_frappe.run_baseline` and `.run_guarded` are explicitly invoked probes, not endpoints or hooks. They refuse any site whose name does not begin `kap2-probe-` or that lacks `sites/<site>/KAP2_DISPOSABLE_SITE`. They create synthetic Users, Persons, Circle, membership, grant and delegated session and exercise actual Document `save`/`delete`, controller revoke, `frappe.db.set_value`, raw SQL and Administrator operations. `run_baseline` records observed outcomes; it does not count an exception as acceptance. `run_guarded` installs a **disposable-only** protected schema, SQL triggers, restricted site principal and an EXECUTE-only synthetic revocation procedure. Every guarded operation has an expected result: only `KAP2_GUARD_DENY` counts as a protected write denial, unexpected exceptions fail the run, and ordinary edits must change state. Neither path is registered as a production endpoint or hook. Both require whole-site teardown; rollback does not undo hooks or external side effects.

```text
bench --site kap2-probe-<isolated-site> execute episteck_home.probes.kap2_frappe.run_baseline
KAP2_DB_SOCKET=<private socket> KAP2_DB_ROOT_PASSWORD=<private synthetic root secret> \
  bench --site kap2-probe-<isolated-site> execute episteck_home.probes.kap2_frappe.run_guarded
```

The authoritative-source inventory to verify on that site is:

| Authority field/process | Current source and read path | Probe paths |
| --- | --- | --- |
| `User.enabled` | Frappe core `tabUser`; `identity/auth_hook.py` and `identity/session.py` read it. | Disable save, reenable `db.set_value`, disable SQL, Administrator reenable save. |
| `Person.linked_user` | `tabPerson`; `identity/actor.py` resolves User→Person. | Relink save/`db.set_value`, unlink SQL. |
| Delegated session status | `tabHome Delegated Session`; `identity/auth_hook.py` reads it; controller `revoke()` saves it. | Controller revoke, SQL reenable, `db.set_value` revoke. |
| Person grant state/target/actions | `tabConsent Grant`; `policy/wrappers.py` loads it directly for the existing Person API. | Save revoke, `db.set_value` reenable, SQL revoke, Administrator save, delete; wrapper allow observed after each transition. |
| Circle target and exit | `tabCircle` and `tabCircle Membership`; `api.py` reads membership. The current Person policy does not authorize from it. | Circle deletion, membership deletion, legacy grant state after exit. |

**Actual local integration, 2026-10-07:** an isolated WSL Ubuntu bench ran Frappe **15.99.0** (tag `5cca1fa7e38cfab74c78627c93a9210dc3fdbccc`), Bench 5.28, MariaDB 10.11.13 on a private socket, and the branch's `episteck_home` 0.1.0 on a marked disposable site. Fixture fields and controller `revoke()` were checked against the repository definitions before execution. Baseline allowed every tested authority mutation, including `set_value`, SQL, administrator, controller and deletes. The legacy wrapper changed from allow to deny on revoke, back to allow on `set_value` reactivation, then deny after SQL revoke; the grant stayed ACTIVE after Circle exit. This is observation, not guarded acceptance.

On a fresh site, `run_guarded` passed **23 explicit checks**: 15 authority paths returned the guard's own denial, 3 ordinary saves changed state, 1 ordinary read check succeeded, runtime trigger drop was privilege-denied, and initial state, central revocation/PENDING gap, and outcome publication matched expectations. The central procedure advanced a local protected sequence to 1 and revoked User/Person/session/grant/membership in one MariaDB transaction. A simulated external outcome remained PENDING while the legacy wrapper denied; COMMIT publication kept it denied. The site principal was reduced to SELECT/INSERT/UPDATE/DELETE and reconnected after grant cutover; without reconnect, its old session retained DDL power, a material integration finding. This synthetic schema is **not** the production fence or independent GCS witness. The current wrapper can still consult legacy grants outside this harness; production cutover and complete field/source inventory remain review gates. The local MariaDB lock-order probe covers reader-first and revocation-first concurrency; these orders have not yet been replayed through Frappe controllers.

Reproduce on a newly installed marked disposable site, then verify complete removal with `bench --site <site> list-apps` before the run and `test ! -e sites/<site>` after `bench drop-site <site> --no-backup --force`. The drop target must be resolved and checked to be inside the isolated bench; also stop its private MariaDB and Redis processes. Never run against a shared or production site.

## Real GCS probe

`gcs_protocol.py` requires an **existing** `kap2-probe-*` bucket in the explicitly named project, labeled `kap2_probe=true`, plus an already authorized service account. It performs no bucket/IAM/retention/key/project mutation. `--preflight` checks environment configuration only and is read only; `--run` first compares bucket project number, rejects versioned buckets, checks the service's create/get/list permissions and absence of delete/update/retention/bucket-update permissions, then writes synthetic objects and deliberately leaves an invalid synthetic slot at the end. Use a disposable bucket/prefix only. It records existing locked-retention metadata and tests service-account self-`signBlob` plus public-key signature verification. A missing signature capability is reported, not treated as verified. [GCS conditional insert](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/insert), [bucket permission test](https://docs.cloud.google.com/storage/docs/json_api/v1/buckets/testIamPermissions), and [IAM signBlob](https://docs.cloud.google.com/iam/docs/reference/credentials/rest/v1/projects.serviceAccounts/signBlob) are the API references.

```text
python spike/knowledge-kap2-integration-probe/gcs_protocol.py --preflight
KAP2_GCS_BUCKET=kap2-probe-... KAP2_GCS_PROJECT=... KAP2_GCS_SERVICE_ACCOUNT=... python spike/knowledge-kap2-integration-probe/gcs_protocol.py --run
```

The live path tests conditional slot and outcome creation, two competing HTTP clients, exact-byte readback after a **simulated** lost acknowledgement, pending outcome denial, sequential chain verification, writer epoch transition, restore-before-revocation comparison, corruption denial, and an append during paginated listing. It measures ten full head discoveries at 1, 16 and 64 committed slots, with list-page counts, GET/create/list request totals and min/p50/p95/max times. These are object-store timings, never end-to-end Knowledge latency. Actual network timeout after a possibly accepted write, signed journal entry enforcement by readers, old-writer credential isolation and full production retention remain additional integration checks.

**Current result:** `--preflight` reports no isolated bucket, service identity or project variables. The active configured GCP project has zero buckets; the two visible projects include no isolated probe project. The prior Knowledge disposable GCS project, bucket and service account were deleted after its completed test. No new paid resource or retention lock may be created in this assignment; therefore `--run` was **not executed**, and live IAM, retention, signing, timeout recovery, growing-history latency and request counts remain unmeasured. The [concrete provisioning proposal](GCS_PROVISIONING_PROPOSAL.md) compares `us-east4` near Ashburn with Frankfurt subject to residency approval, scopes identities and budget, and states key-recovery questions.

## Local synthetic controls

`python3 spike/knowledge-kap2-fence-probe/probe_protocol.py` passes six in-memory cases. In WSL Ubuntu, `python3 spike/knowledge-kap2-fence-probe/probe_db.py` starts a private socket-only MariaDB 10.11.13 datadir and removes its own temporary state. It passes restricted-principal bypass denials, an EXECUTE-only transactional mutation, reader-first and revocation-first lock orders, external COMMIT-gap denial and restore mismatch. Its external witness is in memory. Neither local probe substitutes for real Frappe or GCS integration.

`python -m pytest spike/knowledge-kap2-integration-probe/test_gcs_protocol.py -q` passes three local scanner cases. The orphan-outcome case first failed (was incorrectly READY); the scanner now blocks it. These checks do not exercise Cloud Storage.

## Evidence-based recommendation and remaining decisions

Compare eligible `us-east4` and `europe-west3` regions from Ashburn; residency may rule out one. Retention must cover the maximum backup rollback horizon plus detection and recovery time with an explicit margin; those durations are not established, so **no numeric retention period or lock is recommended yet**. Keyless IAM signing needs durable historical public-key recovery before selection, because Google's `signBlob` public keys expire. Full journal scan plus an exact next-slot lookup is the current safe checkpoint strategy; signed durable checkpoints may be considered only after independent proof and must never become a cached READY authorization. Writer takeover requires proven isolation/revocation of the old identity and a measured upper bound on old in-flight work and disclosure, with clock margin; absent that evidence, remain BLOCKED rather than invent a serving lease.

Next validation requires an authorized isolated Frappe site with the app installed, and an existing isolated Home GCS bucket/service identity with create/get/list and signing access. The architect must review the resulting field-coverage, latency, retention and takeover evidence before production fence/schema implementation or activation.
