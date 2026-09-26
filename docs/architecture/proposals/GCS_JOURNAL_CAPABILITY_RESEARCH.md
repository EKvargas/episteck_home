# Google Cloud Storage control-journal capability research — Phase 0C

Status: **Phase 0C documentation screen retained below; Board-approved live result and current selection in the addendum**

Reviewed: 2026-09-26

Scope: the accepted [Knowledge restore-freshness contract](KNOWLEDGE_RESTORE_FRESHNESS.md) §5.3 and §12.2. This note does not change that contract. Sources below are first-party Google Cloud documentation.

## Create-once identity (S-3 / WS-1)

| Documented fact | Consequence for the candidate |
|---|---|
| `ifGenerationMatch=0` permits an object write only if no live object of that name exists. An existing live object produces HTTP `412 Precondition Failed`. It also permits a write if **only noncurrent versions** exist. [Request preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions). | Use the precondition on every journal append. It is an atomic service check suitable for concurrent writers while an accepted object remains live. A `412` signals an occupied key, not permission failure. |
| Google says `storage.objects.create` adds new objects; replacing an existing object requires **both** `storage.objects.create` and `storage.objects.delete`. The JSON `objects.insert` method states the same rule explicitly. [IAM permissions](https://docs.cloud.google.com/storage/docs/access-control/iam-permissions), [Objects: insert](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/insert). | Grant create but withhold delete. A normal upload that omits the precondition cannot overwrite a live accepted object. This is a service-enforced permission check independent of client discipline; verify the exact error in a live negative test. |
| The predefined `roles/storage.objectCreator` allows creation but expressly excludes view, delete and overwrite. `roles/storage.objectViewer` grants `storage.objects.get` and `storage.objects.list`. Both can be granted at bucket scope. [IAM roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles), [IAM scope and inheritance](https://docs.cloud.google.com/storage/docs/access-control/iam). | Creator plus Viewer is a viable initial permission set. A custom role limited to `storage.objects.create`, `storage.objects.get`, and `storage.objects.list` gives a smaller service surface; either way, audit inherited project and group grants. |
| Object Versioning retains replaced or deleted live versions as noncurrent; noncurrent versions are omitted unless a request explicitly includes them. [Object Versioning](https://docs.cloud.google.com/storage/docs/object-versioning). | **Do not enable Object Versioning for the initial probe.** It is unnecessary for the journal and complicates the proof surface. Even if enabled later, the service identity must lack delete, so it cannot make the accepted version noncurrent. An administrator changing versioning or deleting an object is a distinct operational residual. |

**Preliminary WS-1: PASS-PLAUSIBLE, not PASS.** The joint control is an atomic `ifGenerationMatch=0` and an IAM grant without `storage.objects.delete`. Google explicitly documents both halves. The accepted identity must be one deterministic object name per `(partition, generation, revision)`; arbitrary alternative names for the same logical revision are detectable by complete listing and chain verification, but the key naming scheme itself remains implementation work. Inference: two simultaneous conditional creates of the same live key cannot both satisfy the precondition; test the race and record exact responses rather than claiming an undocumented concurrency status beyond `412`.

## Immutability under the Knowledge credential (S-4 / WS-2)

The service identity should have only the three object permissions above, scoped to one dedicated bucket, and no inherited broader role. Specifically it must have no `storage.objects.delete`, `storage.objects.update`, `storage.objects.setRetention`, `storage.objects.overrideUnlockedRetention`, `storage.buckets.update`, `storage.buckets.setIamPolicy`, or project-level IAM administration. Google documents the object permissions and their meanings in [IAM permissions](https://docs.cloud.google.com/storage/docs/access-control/iam-permissions), and the retention-management permissions in [using Object Retention Lock](https://docs.cloud.google.com/storage/docs/using-object-lock). Bucket-scoped grants are additive with project grants, so review the effective identity rather than the bucket policy alone. [Cloud Storage IAM](https://docs.cloud.google.com/storage/docs/access-control/iam).

The probe bucket should use **uniform bucket-level access** to remove object ACL behavior from the effective-access analysis and **public access prevention** to keep the bucket private. The service should not receive Owner, Editor, Storage Admin, Object Admin, or Object User. The broad Object User role includes delete and update. [IAM roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles), [uniform bucket-level access](https://docs.cloud.google.com/storage/docs/uniform-bucket-level-access), [public access prevention](https://docs.cloud.google.com/storage/docs/public-access-prevention).

### Retention choices

| Mechanism | Documented behavior | Assessment |
|---|---|---|
| **Bucket Lock** | A bucket retention policy prevents object deletion or replacement until each object's age exceeds its retention period. Locking permanently prevents the policy from being reduced or removed; even a locked policy can be increased. A locked bucket cannot be deleted until all objects have fulfilled retention. A locked policy also applies to existing objects. [Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock). | Best fit for uniformly protected journal entries, with retention configured by an operator before any service writes. It adds protection against administrator mistakes beyond service IAM, for the protected life. The service needs no retention-management permission. |
| **Object Retention Lock** | Per-object `Locked` retention cannot be shortened or removed. An object with unexpired retention cannot be deleted or replaced, but when Object Versioning is enabled it can still be made noncurrent. The feature must be enabled on the bucket and cannot then be disabled. [Object Retention Lock](https://docs.cloud.google.com/storage/docs/object-lock). | Useful when individual entries need distinct retain-until dates; unnecessary complexity for a uniform journal policy. Creating per-object retention requires `storage.objects.setRetention`, which should **not** be granted to the service. An operator-side retention step after service acknowledgment would leave a protection gap. |
| **IAM-only** | Without delete permission, the service cannot delete or replace an accepted object. [IAM permissions](https://docs.cloud.google.com/storage/docs/access-control/iam-permissions). | S-4 is phrased around the Knowledge credential and a protected life, so this is the fundamental service control. Locked retention adds administrator-error protection and must be considered against B4 retention/expiry requirements before production duration is set. |

**Preliminary WS-2: PASS-PLAUSIBLE, not PASS**, conditional on no inherited permission or alternate identity enabling delete, update, retention or policy modification, no lifecycle deletion during the required protected life, and a negative live test of the service principal. Bucket Lock does not provide perpetual immutability: after retention expiry, an administrator with delete rights can remove an entry. The accepted architecture separately lists provider-admin deletion as an operational residual; it does not grant such rights to the service. [Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock), [accepted residual U4](KNOWLEDGE_RESTORE_FRESHNESS.md).

**Versioning warning:** Both [Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock) and [Object Retention Lock](https://docs.cloud.google.com/storage/docs/object-lock) say an unexpired retained **live** object can nevertheless be made noncurrent in a versioned bucket. A normal list then omits it. Do not treat physical retention of a noncurrent generation as proof of logical visibility. For this candidate, keep versioning disabled and withhold delete from the service. A live probe must check bucket configuration and attempt both ordinary and generation-specific deletion with the service identity.

**Administrative and provider boundary:** an authorized project or bucket administrator can change IAM, grant itself access, set lifecycle policy, and after retention expiry delete objects. A locked bucket retention policy cannot be shortened or removed, and locked retained objects block bucket deletion until their period ends. Google as provider remains outside the service-credential threat model. The probe cannot empirically prove provider-internal actions; it relies on the documented Cloud Storage service contract. [Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock), [IAM roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles).

## Other gates: documentation pointers for the main report

| Gate | Preliminary screen | Primary source and remaining evidence |
|---|---|---|
| WS-3 durable acceptance | PASS-PLAUSIBLE | Google documents immediate independent reads and metadata after a successful write. Its [availability and durability page](https://docs.cloud.google.com/storage/docs/availability-durability) says regional writes are confirmed only after redundancy across at least two zones and describes an 11-nines annual durability design target. A live probe must confirm returned generation/checksum and fresh independent read. A lost response remains ambiguous. [Consistency](https://docs.cloud.google.com/storage/docs/consistency). |
| WS-4 isolation | PASS-PLAUSIBLE | A dedicated project and bucket-scoped service account keep the Google principal separate from the Hetzner restic credential. Effective grants must be checked; no production backup secret is needed. [IAM scope and inheritance](https://docs.cloud.google.com/storage/docs/access-control/iam). |
| WS-5 authoritative completeness | PASS-PLAUSIBLE | Google explicitly documents strong global object read-after-write and object-listing consistency, including a new object in the immediately following list. A complete list needs every page; do not infer completeness from one truncated response. Versioning disabled and no service delete protect accepted entries from being hidden by this identity. [Consistency](https://docs.cloud.google.com/storage/docs/consistency), [Objects: list](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/list). |
| WS-6 failure classification | PASS-PLAUSIBLE | The API exposes `412` precondition failures and distinct general [error statuses](https://docs.cloud.google.com/storage/docs/json_api/v1/status-codes). Timeouts or lost responses remain ambiguous and must be reconciled by GET/list; full status mapping needs the live probe. |

These are the **as-of-Phase-0C** documentation-screen classifications only. The later live PASS results and selection are recorded in the addendum.

**Pagination boundary for WS-5:** Google's [list API](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/list) explicitly says a new object created **after** a listing starts can be missed by subsequent pages if its name falls into an already-listed portion of the namespace. That does not contradict the requirement for objects acknowledged **before** the query began, but it means a multi-page scan is not a snapshot at its end. A verifier must delimit its proof and fail closed if a concurrent writer could invalidate the proposed `H(p)` proof; the live probe and Board review must check this exact concurrency case. This is an inference about the accepted protocol, not a further Google guarantee.

## Live negative tests needed for WS-1 and WS-2

After Board review, an isolated synthetic service account should write one object named for `TEST-PARTITION-0001/generation-test-1/revision-1`. Attempt: (1) second conditional write with different bytes; (2) second **unconditional** write; (3) simultaneous conditional writes on a fresh revision key; (4) delete live and generation-specific object; (5) metadata update; (6) retention alteration; (7) bucket policy/versioning/lifecycle changes. Record HTTP status, error code, generation, checksum, GET bytes, and full listing after each attempt. A test is a configuration check, not a substitute for Google's published IAM and consistency guarantees. All payloads remain synthetic.

**Phase 0C cleanup implication:** permanently locking a bucket retention policy is irreversible and may prevent deleting the test objects and bucket until the selected short probe retention expires. No production retention duration is chosen here. The actual live configuration and expiry are recorded in the addendum. [Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock).

## Structured result

```json
{
  "candidate": "Google Cloud Storage, dedicated project and europe-west3 private bucket",
  "phase": "0C documentation screen",
  "resource_created": false,
  "ws_1": "PASS-PLAUSIBLE",
  "ws_2": "PASS-PLAUSIBLE",
  "ws_3": "PASS-PLAUSIBLE",
  "ws_4": "PASS-PLAUSIBLE",
  "ws_5": "PASS-PLAUSIBLE",
  "ws_6": "PASS-PLAUSIBLE",
  "store_selected": false,
  "service_permissions": ["storage.objects.create", "storage.objects.get", "storage.objects.list"],
  "bucket_versioning": "disabled for initial probe",
  "retention_preference": "short locked bucket policy for a probe; production duration undecided",
  "remaining_gate": "Board review and empirical non-production WS-1..WS-7 probe"
}
```

Verify this file after creation:

```powershell
git diff --no-index --check -- /dev/null docs/architecture/proposals/GCS_JOURNAL_CAPABILITY_RESEARCH.md
git status --short --branch
```

For the `--no-index` check, exit code 1 indicates that a new file differs from an empty file; no output indicates no whitespace errors.

## Live non-production probe addendum — 2026-09-26

The Architecture Board-authorized live run is reported in [the main report §12](KNOWLEDGE_JOURNAL_STORE_PROBE_REPORT.md#12-google-cloud-storage--live-non-production-ws-1ws-7-probe). Its [raw API observations](../../../spike/knowledge-journal-store-probe/gcs_live_observations.json), [fault-injection observations](../../../spike/knowledge-journal-store-probe/gcs_failure_observations.json), and isolated [probe code](../../../spike/knowledge-journal-store-probe/gcs_live_probe.py) are preserved. This addendum does not alter the Phase 0C source analysis above.

The actual resource was disposable project/bucket `episteck-kn-probe-260926-5512` in `EUROPE-WEST3`, Standard, uniform bucket-level access, public access prevention, versioning disabled, and a **locked 3,600-second** bucket retention policy. Its service account's sole bucket role had exactly `storage.objects.create`, `storage.objects.get`, `storage.objects.list`; it had no project role or user-managed key. The service account was disabled after testing.

| Gate | Live result | Decisive sample |
|---|---|---|
| WS-1 | **PASS** | Conditional first/duplicate `200/412`; unconditional overwrite `403`; same-key race `200/412`. |
| WS-2 | **PASS** | Restricted delete, metadata/retention, bucket IAM/retention/delete attempts `403`; operator protected-object delete and locked-retention shortening also `403`. A malformed retention request initially produced `400`; a corrected request produced `403`. |
| WS-3 | **PASS** | Immediate fresh GET and metadata `200` with exact original bytes; documented regional durability remains the provider guarantee. |
| WS-4 | **PASS** | Effective IAM only on the dedicated bucket, no service project role, bucket-list/metadata/IAM-read `403`, and no Hetzner credential or backup resource used. |
| WS-5 | **PASS** | Multi-page chain proof + exact next-revision GET incorporated an append after listing, reaching `H=5`; gap and bad hash chain `BLOCKED`; incomplete pagination `UNVERIFIED`. Strong listing/lookup consistency is the documented guarantee. |
| WS-6 | **PASS** | GCS `200/412/403/404` observed; local fault injections classified connection failure, timeout, `429`, `503`, post-send lost response, and incomplete pagination. |
| WS-7 | Informational | Local Windows workstation, network location not confirmed Nuremberg: append n=100 p50 704.734 ms, p95 868.261 ms, p99 912.563 ms. |

The [GCS list API](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/list) remains non-snapshot across pages. The successful WS-5 result is for the accepted S-6 proof boundary: documented strong visibility of entries acknowledged before a query, exhaustive pages, contiguous history, and a final exact next-revision lookup. A request error or uncertain boundary still means `H(p) = UNKNOWN`.

**Disposition:** GCS is **SELECTABLE** under the tested isolated configuration; pre-runtime obligation #6 can be marked **OPERATIONALLY CLOSED**. Obligation #1 remains **OPEN**, and no Knowledge runtime is implemented. Cleanup is pending the latest synthetic object's retention expiry at `2026-09-26T16:29:42.402Z`; the bucket then contains only disposable data. The existing Hetzner Storage Box and backups were untouched.

Verify the addendum:

```powershell
rg -n '^## Live non-production|SELECTABLE|16:29:42' docs/architecture/proposals/GCS_JOURNAL_CAPABILITY_RESEARCH.md
git diff --no-index --check -- /dev/null docs/architecture/proposals/GCS_JOURNAL_CAPABILITY_RESEARCH.md
```
