# Knowledge KAP-2 Incarnation Admission Implementation Plan

> For a future implementation session only. This PR prepares the plan; it does not authorize production installation, migration or deployment.

**Goal:** Make Knowledge RT#1/RT#2 fail closed through witness restart/restore and admit only current-incarnation, authenticated reauthorization while existing Home APIs retain their behavior.

**Architecture:** A Nuremberg witness gateway owns a private MariaDB instance and volatile default-closed admission. Home owns its guarded partition authority transaction and Knowledge-only grant activation overlay. RT#1/RT#2 use one fresh gateway read each under the Home lane; recovery creates a fresh incarnation and never imports an old Knowledge allow.

**Tech Stack:** Python 3.11+, Frappe 15, MariaDB/InnoDB, existing Home Redis security-state facility, Tailscale/private TLS. These are integration candidates, not provisioned services.

**Spec:** [KAP-2 incarnation admission amendment](../../architecture/proposals/KNOWLEDGE_KAP2_INCARNATION_ADMISSION_AMENDMENT.md) and [runtime contract §19](../../architecture/proposals/KNOWLEDGE_AUTHORIZATION_PLAN_RUNTIME_CONTRACT.md).

## Global constraints

- Keep PR #60's reviewed typed evaluator semantics; integrate it only after the fence is approved.
- Do not change existing Home `can_access`, ConsentGrant API responses or unrelated permissions.
- No Knowledge RT#1/RT#2 activation until the guarded mutation inventory, gate and restore tests pass.
- No direct Home/Frappe SQL access to the witness tables; no restorable `READY` flag as admission authority.
- Do not provision production resources, migrate or deploy from this documentation PR.

## Review focus

1. A gateway crash after Home has issued RT#1 must invalidate its context at RT#2.
2. Matching restored Home/witness rows must deny before the first recovered request.
3. A delayed old writer with valid credentials must not mutate the new incarnation.
4. A legitimate non-Knowledge ConsentGrant/API call must still work during Knowledge closure.
5. A reauthorization by the wrong Person or expired Circle steward must deny without changing the old grant.

## Future reviewable tasks

### Task 1 — Private witness and admission gateway

**Files to create:** `services/home-witness-gateway/` gateway package, versioned SQL migrations and `tests/test_admission.py`; no direct edits to existing Home APIs. **Input:** authenticated Home partition/event request. **Output:** current `(incarnation, revision, state, digest, epochs)` or a fail-closed error.

- [ ] Write disposable tests for startup `CLOSED`, restart/connection loss `CLOSED`, competing instance exclusion, obsolete epoch procedure denial and direct DML denial.
- [ ] Implement private MariaDB schema and definer procedures for exact-event PENDING/COMMITTED, epoch transition and current locking read; restrict read/mutate/recovery database principals separately.
- [ ] Implement a gateway listener that opens only after taking the exclusive process lock; startup and reconnect never load an `OPEN` flag from SQL. A database disconnect closes the listener's admission immediately.
- [ ] Run the gateway tests against a private socket-only MariaDB and verify the first request after restart denies. Commit this independently reviewable unit.

### Task 2 — Home Knowledge-only guarded authority and reauthorization

**Files to create:** `apps/episteck_home/episteck_home/knowledge_authority/` and `apps/episteck_home/tests/test_knowledge_authority.py`. **Files to inspect/integrate:** `policy/typed_access.py` from accepted PR #60, existing `policy/access.py`, `identity/session.py`, relevant DocType controllers and `api.py`. **Output:** a current-incarnation Knowledge authorization snapshot; existing Home policy results remain unchanged.

- [ ] First test old-grant quarantine, authenticated issuer reauthorization, Person self-activation, Circle dependency invalidation, partition mismatch and non-Knowledge API baseline results.
- [ ] Inventory every live writable authority source and protect canonical Knowledge projection/overlay so generic `save/delete`, `db.set_value`, raw SQL and administrator operations cannot bypass the revision lane. Retain ordinary Frappe writes.
- [ ] Add guarded Home transaction/event/digest handling with exact-event retry and separate Knowledge-only reauthorization records; do not edit or revoke unrelated ConsentGrant rows during recovery.
- [ ] Run policy, mutation, baseline API and privilege tests; commit the guarded authority unit separately.

### Task 3 — Recovery cutover and Knowledge context binding

**Files to create/modify:** recovery coordinator under `knowledge_authority/`, Knowledge RT#1/RT#2 handlers when KAP-3/4/8 are implemented, and focused context tests. **Output:** fresh incarnation, default-deny overlay and old-context rejection.

- [ ] Test restart, replacement, combined Home/witness rollback, Redis context restore, old writer completion and each lost-acknowledgement point before implementing cutover.
- [ ] Close admission; drain old privileged Home connections; mint new incarnation; install default-deny state in witness and Home; compare exact state and epochs; allow `REAUTH_ONLY`, then `OPEN` only after proof. Any uncertain step remains closed.
- [ ] Bind Home Knowledge context values and issued opaque revision to the current incarnation; RT#2 consumes once and rejects old incarnation even if Redis still has its key. Ensure in-flight Knowledge output cannot pass final release after denial.
- [ ] Run both reader-first and revocation-first races plus the recovered-first-request test; commit this integration unit separately.

### Task 4 — Disposable integration and acceptance report

**Files to create:** a reproducible disposable Frappe/MariaDB runner under `spike/knowledge-kap2-transactional-witness/` and sanitized evidence; no production configuration. **Output:** one reviewable pass/fail matrix for the seven acceptance groups in the amendment.

- [ ] Run two private database services and a disposable Frappe site with synthetic Persons, Circles, grants, sessions and Knowledge contexts.
- [ ] Exercise actual Frappe controller/API paths, restore and timeout schedules, old-principal takeover, direct SQL bypass attempts, legitimate Home baseline calls and authenticated reauthorization.
- [ ] Count exactly one remote witness read per RT#1/RT#2, record request errors and warm/cold full-path latency; do not claim KAP-10 from the disposable screen.
- [ ] Archive per-step outputs and teardown evidence; mark each amendment criterion PASS/FAIL/UNEXECUTED. Stop and return to architecture on any stated rejection condition.

## Gate before implementation

Architect review must accept the §19 contract wording, the domain-read basis boundary and the independently enforced gate threat model. The user must assign a witness operator and backup delegate before any installation. A later instruction must separately authorize disposable integration resources and any production work.
