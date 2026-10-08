# KAP-2 disposable GCS/KMS run, 2026-10-08

This is **candidate protocol evidence**, not KAP-2 production approval. Both regional runs used synthetic authority and distinct writer identities and SOFTWARE Ed25519 CryptoKeys. The probe ran on `ubuntu-4gb-ash-1`, the actual Ashburn Home host. No production app, database, credentials, retention policy or lock was changed. Root private keys existed only in the local preparation process; this archive contains public roots and signed registrations.

## Setup and isolation

- Isolated project: `episteck-home-kap2-probe` (number `417624540627`); regional buckets `kap2-probe-home-us-east4-417624540627` and `kap2-probe-home-europe-west3-417624540627`.
- Each region had one key ring, two separate SOFTWARE EC_SIGN_ED25519 CryptoKeys (one version each), two writer service accounts and one shared verifier. Writer grants were key-scoped and bucket-scoped. No service-account keys were downloaded.
- Uniform bucket access, public access prevention, no versioning, soft delete disabled, no retention policy or lock. Both allowed regions were selected for **synthetic** data only; no production residency decision follows.
- A project-filtered monthly budget notification of EUR 4.47 (approximately USD 5 at the 2026-10-07 ECB reference rate) was configured. It is not a spending cap.
- The in-memory token bundle was sent to the Ashburn process over SSH stdin. Public trust files and executable code were copied to `/tmp/kap2-gcs-probe-20261008` and hash-checked. No token file was stored on the host.

## Real GCS/KMS results

| Case | us-east4 | europe-west3 |
| --- | --- | --- |
| Conditional competing slot create | First history reached committed REVOKE at 67; initial runner output lost after cutover failure. | HTTP 200/412; competing outcome create rejected. |
| Pending / restore / timeout | US continuation verified existing committed REVOKE; initial detailed output unavailable. | PENDING blocked; stale pre-revocation local state denied; controlled HTTP response-drop **after real GCS acceptance** recovered exact bytes and published COMMIT. This tests read timeout recovery, not an uncontrolled network outage. |
| Old already-issued token | Immediate post-cutover old-key signing returned **200** while new-key signing and GCS create returned 403; new writer was not admitted. A focused recheck, after temporary old-key signer regrant and revoke, returned old-key 403 at 0.4 s and three all-403 rounds before admission. See `us-east4/takeover_recheck.json`. The first propagation delay was not timed. | Old-key signing returned 200 at 0.666, 21.285 and 41.92 s, then 403 at 62.715 s; three subsequent rounds returned 403 for both keys and journal create before new-writer admission. See `europe-west3/progress.json`. These samples do not prove in-flight writer drain or a universal propagation bound. |
| Epoch takeover and corrupt next slot | Fresh new identity signed epoch 2; verified commit 68. Corrupt slot blocked. See `us-east4/continuation.json`. | New identity was admitted only after denial rounds. An independent read-only Ashburn check verified root-registered signatures through COMMIT 68 and returned BROKEN for corrupt slot 69. See `europe-west3/read_only_verification.json`. Final runner stdout was lost when its SSH wrapper stalled; its checkpoint omits exact full-run request totals. |

The US continuation made 3 create, 1,781 GET and 260 LIST requests plus 3 KMS sign requests. Its conservative combined reservation, including the failed first process, was 148 create, 4,081 GET and 610 LIST (=4,839 object requests), below the 160/5,000 limits; this is a **bound, not an actual total**. The first process did not checkpoint exact counts. The EU runner enforced 160 create, 5,000 combined object requests and 160 signs per key internally, but its final counters were lost with stdout. Its checkpoint and independent read-only check are retained. Operator metadata/list checks were additional and are not counted in runner counters.

## Full-head discovery from Ashburn

Ten scans at each size; values are milliseconds. These are GCS chain discovery and verification measurements, **not end-to-end Knowledge authorization latency**.

| Region | Committed slots | p50 | p95 | LIST pages per scan | GET / LIST over 10 scans |
| --- | ---: | ---: | ---: | ---: | ---: |
| us-east4 | 68 | 9,983 | 11,172 | 20 | 1,370 / 200 |
| europe-west3 | 1 | 661 | 699 | 1 | 30 / 10 |
| europe-west3 | 16 | 7,138 | 7,889 | 5 | 330 / 50 |
| europe-west3 | 64 | 26,425 | 34,735 | 19 | 1,290 / 190 |
| europe-west3 | 68, independent check with corrupt slot 69 | 30,452 (one run) | — | 20 | 137 / 20 |

The US 1/16/64 measurements were lost with the initial runner output. Growing full-history scans are too slow to assume they meet the accepted live latency gate. A signed checkpoint/head design with its own rollback and freshness proof requires architectural review and measurement before activation.

## Unproved and next decisions

- No live retention behavior, production retention duration, or recovery after a locked policy was tested. No retention lock was set.
- IAM 403 sampling is insufficient to prove in-flight request drain. Serving takeover needs a separately proved drain/cutover barrier; no arbitrary serving lease or cached READY shortcut follows from this probe.
- The production trust root distribution, protected historical registrations, rotation/recovery after database restore, checkpoint strategy and outage behavior remain to be specified and validated.
- Full Home mutation-boundary coverage, transaction/read ordering, restore protection, migration and rollback remain KAP-2 integration work. The pure typed evaluator in PR #60 stays disconnected.
- The initial US transient 200 is an adverse result. Admission must wait for observed effective denial and a proved in-flight drain; the EU 62.715 s observation is not a bound for production.

The local synthetic protocol tests and Frappe disposable guard observations remain in the parent PR. No live result in this document establishes complete KAP-2 acceptance.
