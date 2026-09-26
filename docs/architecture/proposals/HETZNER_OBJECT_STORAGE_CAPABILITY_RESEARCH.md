# Hetzner Object Storage capability research for the Knowledge journal

Date checked: 2026-09-26. Scope: Phase 0 documentation research for the accepted [restore-freshness architecture](KNOWLEDGE_RESTORE_FRESHNESS.md), §5.3 and §12.2. This note records provider documentation, not an empirical probe. No account, bucket, credential or object was created.

## Phase 0 stop finding

**Hetzner Object Storage with Versioning and Object Lock cannot plausibly satisfy WS-1/S-3 as specified. Stop before provisioning this candidate.** Hetzner's [supported actions](https://docs.hetzner.com/storage/object-storage/supported-actions/) table groups **conditional PUT/DELETE operations on versioned buckets** under Objects → Not supported. Its [bucket FAQ](https://docs.hetzner.com/storage/object-storage/faq/buckets-objects/) says Object Lock automatically enables versioning, and a second PUT at the same key creates another version. Compliance retention prevents permanent deletion or early shortening of a retained version but still permits a newer version with the same key. Thus an existing journal entry identity is not rejected by the store, and a simple key lookup could return the newer content. A preflight HEAD followed by PUT is not store-enforced exclusive creation and cannot close the race between writers. The table's layout is compact, so a provider confirmation of this reading would be valuable, but it does not justify provisioning contrary to the Phase 0 stop rule. This is a documented capability conflict, not an experimentally established response code.

The same FAQ says a delete without a version ID can add a **delete marker** even under Compliance retention, making the ordinary latest-key view appear deleted. Any proposed version-aware scheme would still need to prove exclusive identity and authoritative complete history under the accepted contract; version retention alone does not establish either.

## Provider facts and WS mapping

| Item | Official documentation and implication | Phase 0 classification / exact test if the blocker is resolved |
|---|---|
| WS-1, S-3: exclusive create | [Supported actions](https://docs.hetzner.com/storage/object-storage/supported-actions/) excludes conditional PUT on versioned buckets; [bucket FAQ](https://docs.hetzner.com/storage/object-storage/faq/buckets-objects/) says Object Lock requires versioning and repeated PUT creates another version. | **FAIL from documented capability.** A future provider change would require two independent clients to PUT different synthetic payloads to the same key with `If-None-Match: *`; exactly one must succeed and the loser must receive a conflict, without altering the accepted latest view. |
| WS-2, S-4: immutable history | [Bucket FAQ](https://docs.hetzner.com/storage/object-storage/faq/buckets-objects/) distinguishes Versioning (manual deletion remains possible), Legal Hold (can be removed without special permission), Governance retention (can be bypassed with permission), and Compliance retention (retained version cannot be permanently deleted or retention shortened). It also says delete markers may be added under Compliance retention. [Retention how-to](https://docs.hetzner.com/storage/object-storage/howto-protect-objects/protect-object-lock-retention/) describes bucket default and per-object retention, and removal of bucket default for future objects. | **FAIL for immutable logical entry identity; individual-version retention untested.** A suitable test would use a Compliance default, verify actual version retention, then attempt overwrite, unversioned delete, version-specific delete, retention shortening, and bucket-default change with the Knowledge credential. The documented overwrite and delete-marker behavior conflicts with a latest-key immutable-history interpretation. |
| WS-3, S-5: durable acceptance | [Storage comparison](https://docs.hetzner.com/storage/general/which-storage-is-right-for-me/) identifies erasure coding for Object Storage but also recommends independent backups. The reviewed official pages do not say that a successful PUT response is a durable commit point or state a durability SLA for that response. | **UNKNOWN.** A fresh connection read after PUT is experimentally testable; the durable-acceptance semantics require an explicit provider guarantee, which the reviewed pages do not establish. |
| WS-4, S-2: credential isolation | [S3 credentials FAQ](https://docs.hetzner.com/storage/object-storage/faq/s3-credentials/) says a key has read/write access to every bucket in its project by default, and documents separate projects and bucket policies to allow or deny named keys and actions. The existing restic repository is a Storage Box, so its SFTP credential is a separate mechanism; synthetic access-denial tests would still be required. | **UNKNOWN empirically.** Use a non-production journal bucket/key and synthetic backup target/credential; test all read/write/delete directions. Never use production backup credentials. |
| WS-5, S-6: authoritative complete `H(p)` | Hetzner describes an S3-compatible API and [version listing](https://docs.hetzner.com/storage/object-storage/howto-protect-objects/protect-versioning/), but the reviewed official Object Storage documentation does not state a strong read-after-write, list, or authoritative absence guarantee across connections. S3 compatibility alone does not import Amazon S3 consistency guarantees into Hetzner's service. Version listing also does not itself prove a query saw every acknowledged higher revision. | **UNKNOWN, hard gate.** Query from a new client immediately after another client's acknowledged create; enumerate all pages and versions; test a higher revision created before query start, a missing next revision, and truncation. Observed success cannot substitute for a documented consistency guarantee. Any ambiguous read makes `H(p)` UNKNOWN. |
| WS-6, S-7: failure classification | The [S3 API support statement](https://docs.hetzner.com/storage/object-storage/supported-actions/) does not by itself prove the exact error outcomes needed by this client. | **UNKNOWN.** Exercise successful create/read, denied credential, conflicting create (if supported in a future configuration), unreachable endpoint/timeout, and truncated or otherwise ambiguous enumeration, capturing HTTP status, S3 error code and client exception. |
| WS-7: latency | No provider latency measurement substitutes for measurement from the Nuremberg-side client. | **UNKNOWN; informational.** Measure synthetic append p50/p95 only after a candidate clears mandatory gates. |

## Authentication and operational notes

- An S3 access key plus secret authenticates requests; Hetzner says each pair accesses all buckets in the same project by default. A dedicated project or explicit bucket policy is needed for least privilege. The [credential guide](https://docs.hetzner.com/storage/object-storage/faq/s3-credentials/) documents per-key principals and action restrictions, including `s3:GetObjectVersion` for version reads.
- Object Lock must be enabled **at bucket creation** and cannot be enabled later; it automatically enables versioning. [Bucket FAQ](https://docs.hetzner.com/storage/object-storage/faq/buckets-objects/).
- A protected bucket flag in Console prevents bucket deletion until removed, but it does not replace per-object immutable-history and exclusive-create semantics. [Bucket FAQ](https://docs.hetzner.com/storage/object-storage/faq/buckets-objects/).
- A bucket-wide Compliance default is preferable to requiring each writer to attach retention on every PUT, but the [retention guide](https://docs.hetzner.com/storage/object-storage/howto-protect-objects/protect-object-lock-retention/) documents removal of the default for future objects. The Knowledge credential's ability to change that configuration would need explicit denial and testing.
- Physical copies, retention lifetime, deletion after expiry, metadata leakage, and operational recovery must be evaluated for any selectable provider. No such selection follows from this note.

## Documentation-dependent claims that an experiment cannot establish

1. Durability of a successful append response over host, device, and provider failures (WS-3).
2. Cross-client read-after-write, listing completeness and authoritative absence semantics over **all** executions, rather than the observed sample (WS-5).
3. Enforced retention behavior throughout the protected lifetime, including provider-admin effects (WS-2). A short probe can test the Knowledge credential but not passage of the full retention period.

## Recommendation

Do not provision Hetzner Object Storage for this probe while its documented versioned-bucket conditional PUT limitation remains. Object Storage is **not selectable** under WS-1/S-3; WS-3 and WS-5 also lack the required documented guarantees in the reviewed pages. Evaluate Storage Box only against the unchanged WS-1..WS-6 contract. If no candidate establishes every mandatory item, leave physical selection and obligation #6 operational closure open. The accepted architecture, B1-B6 and obligation #1 are unchanged.

## Hetzner Storage Box + Borg append-only — Phase 0B

Date checked: 2026-09-26. This addition preserves the Object Storage result above. It reviews official Hetzner and Borg documentation only; there was no new Storage Box, key, repository, archive, live command, or production-backup access. The integrated gate decision is in [the probe report](KNOWLEDGE_JOURNAL_STORE_PROBE_REPORT.md#9-hetzner-storage-box--borg-append-only--phase-0b).

### Provider and version boundary

Hetzner's [Storage Box Borg guide](https://docs.hetzner.com/storage/storage-box/access/access-ssh-rsync-borg/) documents SSH port 23, subaccount usernames, and remote executables `borg-1.1`, `borg-1.2` (default), and `borg-1.4`. It recommends specifying the remote path for version compatibility. The same guide explicitly says an append-only restricted client can execute archive deletions, which mark archives deleted until an unrestricted write/delete removes them. The [German version of the guide](https://docs.hetzner.com/de/storage/storage-box/access/access-ssh-rsync-borg/) also says forced commands and client restrictions are supported; the English guide does not spell out their configuration. Borg's own [serve documentation](https://borgbackup.readthedocs.io/en/stable/usage/serve.html) shows an `authorized_keys` forced command with `--append-only` and `--restrict-to-repository`/`--restrict-to-path`, but these options restrict access **within Borg**, not all other Storage Box protocols. Any deployment would need to verify the key cannot fall through to SFTP/SCP/shell or password access. The documented failure below does not depend on that unresolved configuration detail.

Borg 1.4 [requires unique current archive names](https://borgbackup.readthedocs.io/en/stable/usage/create.html). Borg 2's current development [create documentation](https://borgbackup.readthedocs.io/en/latest/usage/create.html) says archive names need not be unique; its distinct permission features cannot be assumed available on Hetzner's documented Borg 1.x executables. No Borg 2 proposal was evaluated as a Storage Box capability.

### Semantic findings against the journal

| Topic | Official fact | Consequence |
|---|---|---|
| Append-only scope | Borg [notes](https://borgbackup.readthedocs.io/en/stable/usage/notes.html) and [`serve`](https://borgbackup.readthedocs.io/en/stable/usage/serve.html) say it prevents overwrite/deletion of committed segment files; `delete`, `prune`, and read remain permitted. `compact` does not reclaim in append-only mode. | It is physical segment retention, not an immutable archive manifest. |
| Delete, prune, rename | Restricted-client delete/prune creates a newer transaction in which archives are marked deleted. [Hetzner](https://docs.hetzner.com/storage/storage-box/access/access-ssh-rsync-borg/), [Borg notes](https://borgbackup.readthedocs.io/en/stable/usage/notes.html). [`borg rename`](https://borgbackup.readthedocs.io/en/stable/usage/rename.html) changes an archive name and ID. | An accepted archive can disappear from the active list; its logical name can then be reused. WS-1 and WS-2 fail. |
| Unrestricted/admin write | Borg warns that an unrestricted write after restricted deletions can permanently remove marked data; direct `rm` bypasses append-only altogether. [Borg notes](https://borgbackup.readthedocs.io/en/stable/usage/notes.html). | Admin access is a separate residual; it must never be the Knowledge credential. It also makes operator cleanup dangerous without integrity review. |
| Acceptance and interruption | Borg says commands are [transactional](https://borgbackup.readthedocs.io/en/stable/usage/notes.html): fully committed or uncommitted after failure; append-only logs stable transaction numbers. Borg's [FAQ](https://borgbackup.readthedocs.io/en/stable/faq.html) describes checkpoint archives after interrupted create. | A clean completed Borg command is meaningful within Borg, but Hetzner durable acknowledgment and immediate fresh-reader visibility were not established. WS-3 remains UNKNOWN. |
| Listing and head completeness | [`borg list`](https://borgbackup.readthedocs.io/en/stable/usage/list.html) lists the current repository/archive view, defaults to hiding checkpoint archives, and offers filters/`--first`/`--last` and JSON output. Borg's [notes](https://borgbackup.readthedocs.io/en/stable/usage/notes.html) describe recovery of older transactions by manual rollback, not an active immutable history query. | Even a syntactically complete current listing can omit an accepted archive after a restricted-client deletion. WS-5 fails. Transaction rollback is not automatic `H(p)` verification. |
| Locks and concurrent writers | Borg [`serve`](https://borgbackup.readthedocs.io/en/stable/usage/serve.html) documents repository-lock failure after an SSH disconnect and keepalive/lock-wait controls. | Locks serialize operations but do not preserve names after deletion, identify writer epochs, or prove stale readers have stopped. They cannot replace the accepted lease. |
| Corruption and direct file access | Borg [notes](https://borgbackup.readthedocs.io/en/stable/usage/notes.html) recommend integrity checking before unrestricted writing and warn that non-Borg tools can remove repository files despite append-only mode. | Corruption/rollback may be manually diagnosable; ordinary restricted-client listing still cannot prove complete accepted history. |
| Box accounts and snapshots | Hetzner [overview](https://docs.hetzner.com/storage/storage-box/general/) says main accounts access all subaccount directories. [Snapshots](https://docs.hetzner.com/storage/storage-box/snapshots/) are point-in-time, stored on the same box, and restore rolls newer state back. | A journal subaccount on the existing restic box is not reverse-isolated from a main-account backup key and shares a box failure domain. A separate journal box could plausibly address WS-4, but snapshots do not fix WS-1/2/5. |

### Preliminary classification and stop

```json
{
  "candidate": "Hetzner Storage Box with Borg 1.x append-only",
  "phase": "0B documentation gate",
  "WS-1": "FAIL",
  "WS-2": "FAIL",
  "WS-3": "UNKNOWN",
  "WS-4": "FAIL for existing main-account box topology; UNKNOWN for separate dedicated box",
  "WS-5": "FAIL",
  "WS-6": "UNKNOWN",
  "selectable": false,
  "live_probe_justified": false,
  "resources_created": false
}
```

WS-6 remains UNKNOWN as an overall gate: Borg [documents exit-code levels and optional specific codes](https://borgbackup.readthedocs.io/en/stable/usage/general.html), while SSH timeout, permission denial, post-send ambiguity, lock contention, and corruption were not exercised on Hetzner. This cannot rescue the definitive WS-1/2/5 failures. Storage Box + Borg append-only is eliminated under the unchanged architecture. No live probe plan should be provisioned. AWS remains untouched in this phase.

## AWS S3 general-purpose bucket — Phase 0C cross-reference

The AWS documentation screen is recorded separately in [the main probe report §10](KNOWLEDGE_JOURNAL_STORE_PROBE_REPORT.md#10-aws-s3-general-purpose-bucket--phase-0c). It does not revise either Hetzner elimination. AWS is a candidate with WS-1..WS-6 **PASS-PLAUSIBLE**, pending Board review of the stated non-production probe and effective credential policy. No AWS resources or credentials were used. The research note remains the primary-source record for the Hetzner decisions.

Verify this note:

```powershell
git diff --check -- docs/architecture/proposals/HETZNER_OBJECT_STORAGE_CAPABILITY_RESEARCH.md
Get-Content docs/architecture/proposals/HETZNER_OBJECT_STORAGE_CAPABILITY_RESEARCH.md
```

## Google Cloud Storage Phase 0C cross-reference

The Google Cloud Storage documentation screen is recorded in [the main probe report §11](KNOWLEDGE_JOURNAL_STORE_PROBE_REPORT.md#11-google-cloud-storage-frankfurt--phase-0c) and the [GCS capability research note](GCS_JOURNAL_CAPABILITY_RESEARCH.md). The later Board-approved [live probe and selection](KNOWLEDGE_JOURNAL_STORE_PROBE_REPORT.md#12-google-cloud-storage--live-non-production-ws-1ws-7-probe) passed WS-1..WS-6 in a dedicated disposable GCP project. This does not change either accepted Hetzner elimination or the existing restic Storage Box. AWS work remains deferred.

Verify this cross-reference:

```powershell
rg -n 'Google Cloud Storage Phase 0C|GCS capability research' docs/architecture/proposals/HETZNER_OBJECT_STORAGE_CAPABILITY_RESEARCH.md
git diff --no-index --check -- /dev/null docs/architecture/proposals/HETZNER_OBJECT_STORAGE_CAPABILITY_RESEARCH.md
```
