# KAP-2 R1/R6 local correction — 2026-10-24

**Scope:** follow-up to the [recovery review](2026-10-24-knowledge-kap2-recovery-review.md), against baseline `f5b163c30258291f865abf231374bd51448616a3`. Local disconnected PERSON candidate only. PR #71 remains draft/unmerged; no push, remote experiment or production changes are authorized by this work.

## R1: close through cross-store proof

`Gateway.recover` now installs witness default-deny and replaces its pinned sessions while leaving volatile admission CLOSED. Home closes the gateway before connecting for recovery, resets its Knowledge overlay and reads back Home/witness under the partition advisory lane. It submits its exact `(incarnation, 0, DENY_ALL)` Home readback to `confirm_home`, which rechecks the recovery generation, partition, process lock, pinned connections and witness head before entering REAUTH_ONLY. Serving decisions and mutations still deny. `open_admission` rechecks those facts before OPEN; Home checks its lane immediately before and after that call. Home recovery exceptions, lane cleanup failure and connection cleanup failure close admission. Process-local serialization orders gateway transitions and use of its pinned DB sessions.

This fixes the observed witness-only early opening. The Home readback is supplied by the trusted Home recovery coordinator; the gateway does not independently query Home. REAUTH_ONLY is a closed intermediate stage in this bounded candidate: serving mutation credentials remain denied until OPEN. It is not a new human reauthorization API.

Tests begin with allowing authority where relevant and inject Home connection/reset/readback/connection-cleanup failures, Home lane acquisition/ownership/release failures, witness changes, writer loss, process-lock loss and invalid/stale confirmation. A separate previously admitted Home worker waits on the recovery lane and then denies old permission. Standalone gateway tests explicitly provide synthetic coordinator proof instead of treating witness recovery as permission to serve.

## R6: reject retained known collisions

`witness.incarnations` retains every head encountered by successful recovery, including the initial head and incarnations with no authority event. Recovery rejects identifiers found in any retained head, event or registry entry across partitions. A globally unique registry key and the existing locked head transaction serialize registration and head replacement. Rejection rolls back the transaction and leaves admission closed; no automatic collision retry is added. Serving/recovery principals gain no direct registry DML rights.

Forced candidate tests cover A→B→A with events, without events, an initial head, event-only retained history and another partition's history. This guarantees rejection against retained known history, not detection of identifiers lost with an older physical backup. Lost history still relies on the contract's 256-bit random collision assumption.

## Independent review

A fresh read-only reviewer found one material timing defect: Home checked its advisory lane before confirmation but could lose it during confirmation and still open admission. The `after-confirm` regression released the real Home advisory lock after successful confirmation and failed because OPEN was reached. Home now rechecks ownership immediately before and after opening. Final regression/suite outcomes are recorded in the evidence; the reviewer did not perform a second review. The same review found no material R6 defect.

The reviewer set aside R2–R5 completion, production source/context/custody/Board gates and separated-host guarantees. Those remain open because this work changes only the two identified local defects. No production or whole-amendment acceptance is inferred.

## Evidence and remaining limits

**Final affected suite: 121 passed in 431.47s**, including real private-database recovery/restore tests and the focused loopback mTLS regression. Repository-root pytest stopped at 23 collection/environment errors, individually retained in `root-suite-limitations.json`; this is not a green repository-wide suite. The legacy Task-2 Frappe probe was adapted to confirm its stored Home head and parsed locally; no full disposable Frappe run was repeated.

The [structured evidence](../../../spike/knowledge-kap2-two-host/evidence/2026-10-24-r1-r6/result.json) records final commands, outcomes, initial failures and limitations. The existing 2026-10-12 and acquisition-only 2026-10-24 evidence remain historical and unchanged.

The disposable transport adapter now carries recovery-only close/confirm/open calls. This changes control-plane request counts and requires review of a fresh exact commit before any separately authorized remote attempt; prior runner hashes and measured counts cannot be reused for this candidate. The remote matrix retains its 400-request cap and ordinary authorization still makes one witness call per Home decision.

Production proof remains open: detecting loss of Home's lane while an open RPC is in flight, loss of a remote close acknowledgement, all Home authority writers, RT#2 contexts, CIRCLE, repeated epoch/principal retirement, unknown Home commit outcomes, credential custody and Board ratification. The coordinator checks here do not create an atomic distributed transaction or independently monitor a remote Home connection. R1's original early-opening defect is corrected locally; the complete production gate obligation is not closed.

**Verify:** `python -m json.tool spike/knowledge-kap2-two-host/evidence/2026-10-24-r1-r6/result.json`; `git diff --check`. Linux/WSL test commands are retained in that JSON.
