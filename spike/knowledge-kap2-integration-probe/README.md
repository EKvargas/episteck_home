# KAP-2 disposable integration probes

Status: **integration evidence incomplete**. PR #59's mechanism is accepted only as a candidate for validation. No production schema, fence, credentials, migration or endpoint is changed by this spike.

## Frappe probe

`episteck_home.probes.kap2_frappe.run` is an explicitly invoked probe, not an endpoint or hook. It refuses any site whose name does not begin `kap2-probe-` or that lacks `sites/<site>/KAP2_DISPOSABLE_SITE`. Use an already provisioned, isolated Frappe 15 test site with the branch's `episteck_home` app installed. The probe creates synthetic Users, Persons, Circle, membership, grant and delegated session within one transaction; it records actual Document `save`/`delete`, controller revoke, `frappe.db.set_value`, raw SQL and Administrator operations, then rolls back to its savepoint. No real person's data is queried. Ordinary User/Person/Circle note/name saves and reads are included to expose an overbroad guard. The site and any external side effects must remain disposable; Frappe hooks are not assumed to be rolled back by a DB savepoint.

```text
bench --site kap2-probe-<isolated-site> execute episteck_home.probes.kap2_frappe.run
```

The authoritative-source inventory to verify on that site is:

| Authority field/process | Current source and read path | Probe paths |
| --- | --- | --- |
| `User.enabled` | Frappe core `tabUser`; `identity/auth_hook.py` and `identity/session.py` read it. | Disable save, reenable `db.set_value`, disable SQL, Administrator reenable save. |
| `Person.linked_user` | `tabPerson`; `identity/actor.py` resolves User→Person. | Relink save/`db.set_value`, unlink SQL. |
| Delegated session status | `tabHome Delegated Session`; `identity/auth_hook.py` reads it; controller `revoke()` saves it. | Controller revoke, SQL reenable, `db.set_value` revoke. |
| Person grant state/target/actions | `tabConsent Grant`; `policy/wrappers.py` loads it directly for the existing Person API. | Save revoke, `db.set_value` reenable, SQL revoke, Administrator save, delete; wrapper allow observed after each transition. |
| Circle target and exit | `tabCircle` and `tabCircle Membership`; `api.py` reads membership. The current Person policy does not authorize from it. | Circle deletion, membership deletion, legacy grant state after exit. |

**Activation gate:** current Frappe tables are writable authority sources. The proposed protected `home_auth` schema and cutover are not implemented, so this probe cannot yet prove that a legacy write is unable to reactivate canonical authority. A future guarded integration run must demonstrate that the canonical reader ignores or rejects every legacy reactivation, while ordinary Frappe operations continue. Any silent reactivation is a failure. Local WSL has Bench 5.28.0 but no importable Frappe package or isolated site; this probe was compiled, **not executed**. No production site was used.

## Real GCS probe

`gcs_protocol.py` requires an **existing** `kap2-probe-*` bucket in the explicitly named project, labeled `kap2_probe=true`, plus an already authorized service account. It performs no bucket/IAM/retention/key/project mutation. `--preflight` checks environment configuration only and is read only; `--run` first compares bucket project number, rejects versioned buckets, checks the service's create/get/list permissions and absence of delete/update/retention/bucket-update permissions, then writes synthetic objects and deliberately leaves an invalid synthetic slot at the end. Use a disposable bucket/prefix only. It records existing locked-retention metadata and tests service-account self-`signBlob` plus public-key signature verification. A missing signature capability is reported, not treated as verified. [GCS conditional insert](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/insert), [bucket permission test](https://docs.cloud.google.com/storage/docs/json_api/v1/buckets/testIamPermissions), and [IAM signBlob](https://docs.cloud.google.com/iam/docs/reference/credentials/rest/v1/projects.serviceAccounts/signBlob) are the API references.

```text
python spike/knowledge-kap2-integration-probe/gcs_protocol.py --preflight
KAP2_GCS_BUCKET=kap2-probe-... KAP2_GCS_PROJECT=... KAP2_GCS_SERVICE_ACCOUNT=... python spike/knowledge-kap2-integration-probe/gcs_protocol.py --run
```

The live path tests conditional slot and outcome creation, two competing HTTP clients, exact-byte readback after a **simulated** lost acknowledgement, pending outcome denial, sequential chain verification, writer epoch transition, restore-before-revocation comparison, corruption denial, and an append during paginated listing. It measures ten full head discoveries at 1, 16 and 64 committed slots, with list-page counts, GET/create/list request totals and min/p50/p95/max times. These are object-store timings, never end-to-end Knowledge latency. Actual network timeout after a possibly accepted write, signed journal entry enforcement by readers, old-writer credential isolation and full production retention remain additional integration checks.

**Current result:** `--preflight` reports no isolated bucket, service identity or project variables. The active configured GCP project has zero buckets; the two visible projects include no isolated probe project. The prior Knowledge disposable GCS project, bucket and service account were deleted after its completed test. No new paid resource or retention lock may be created in this assignment; therefore `--run` was **not executed**, and live IAM, retention, signing, head latency and request counts remain unmeasured.

## Local synthetic controls

`python3 spike/knowledge-kap2-fence-probe/probe_protocol.py` passes six in-memory cases. In WSL Ubuntu, `python3 spike/knowledge-kap2-fence-probe/probe_db.py` starts a private socket-only MariaDB 10.11.13 datadir and removes its own temporary state. It passes restricted-principal bypass denials, an EXECUTE-only transactional mutation, reader-first and revocation-first lock orders, external COMMIT-gap denial and restore mismatch. Its external witness is in memory. Neither local probe substitutes for real Frappe or GCS integration.

`python -m pytest spike/knowledge-kap2-integration-probe/test_gcs_protocol.py -q` passes three local scanner cases. The orphan-outcome case first failed (was incorrectly READY); the scanner now blocks it. These checks do not exercise Cloud Storage.

## Evidence-based recommendation and remaining decisions

Use a **separate Home-owned Frankfurt (`europe-west3`) regional bucket** if a future authorized probe confirms the protocol and Ashburn latency; the prior Knowledge probe used that region successfully, but it did not measure this Home path. Retention must cover the maximum backup rollback horizon plus detection and recovery time with an explicit margin; those durations are not established, so **no numeric retention period or lock is recommended yet**. Prefer keyless IAM signing with separately recoverable operator authority and documented key rotation/recovery; no Home signing identity has been proven. Full journal scan plus an exact next-slot lookup is the current safe checkpoint strategy; signed durable checkpoints may be considered only after independent proof and must never become a cached READY authorization. Writer takeover requires proven isolation/revocation of the old identity and a measured upper bound on old in-flight work and disclosure, with clock margin; absent that evidence, remain BLOCKED rather than invent a serving lease.

Next validation requires an authorized isolated Frappe site with the app installed, and an existing isolated Home GCS bucket/service identity with create/get/list and signing access. The architect must review the resulting field-coverage, latency, retention and takeover evidence before production fence/schema implementation or activation.
