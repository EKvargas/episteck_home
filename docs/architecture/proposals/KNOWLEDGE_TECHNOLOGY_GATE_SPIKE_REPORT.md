# Knowledge Technology Gate — Empirical Spike Report

Status: **EVIDENCE REPORT — SPIKE PARTIALLY EXECUTED. NO TECHNOLOGY SELECTED.**

Authorized by: TG-PA-7 (`KNOWLEDGE_TECHNOLOGY_GATE_PHASE1.md` §18.1).

**This report states what ran and what did not.** PostgreSQL scenarios did **not**
execute — no disposable PostgreSQL instance was available in this environment, and per
the spike's own binding scope (TG-PA-7 §18.1 item 1, and the executing methodological
correction "Docker/PostgreSQL handling") **this spike does not provision one**. SQLite
scenarios executed fully. Where a required comparison needed both realizations, it is
recorded as incomplete, not inferred or fabricated. **The empirical evidence gathered
here is NOT sufficient to begin final Technology Gate selection** — see §24.

---

## 1. Exact main baseline SHA

`523c6b849518c47f5093ce2524c9c15b083495fa` — verified equal to `origin/main` after
fetch, prior to branching. PR #30 (Phase 1 closure) confirmed merged.

## 2. Environment

- OS: Windows 11 Enterprise, shell: Git Bash / Cygwin over PowerShell-hosted Python.
- Python interpreter used for all execution: **3.11.8**
  (`C:\Users\D064974\AppData\Roaming\pypoetry\venv\Scripts\python.exe`), pytest 9.1.0.
- A second Python (3.13.9) exists on the host but was not used for execution (no pytest
  installed there); noted only because `sqlite3.sqlite_version` was probed on both
  before selecting 3.11.8 for the full run.
- **Not connected to production.** No `home.episteck.com` access, no production
  svc-nutrition, no production gateway, no Tailscale route, no production credentials.
  Home and all domain peers are in-process stubs (`home_stub/`, `domain_stub/`).
- **Shared checkout caveat, disclosed for reproducibility:** the working directory
  (`C:\aiprojects\episteck-delivery-workspace\episteck_home`) is a checkout shared with
  at least one other concurrent session. Mid-spike, another session switched the
  checkout to `feature/pregnancy-micronutrient-dashboard` and committed there; this did
  not corrupt or lose any spike file (untracked files survive a branch checkout), and
  work was switched back to `spike/knowledge-technology-gate` and committed
  (`e78dfdcc713d911d697c0140ae5a04bce62913eb`) immediately upon detection. No spike code
  or data was affected. Flagged here because it is relevant to reproducing this exact
  run and to anyone else's use of this checkout during a similar experiment.

## 3. Pinned SQLite/PostgreSQL versions

- **SQLite: 3.41.2** (via Python 3.11.8's bundled `sqlite3` stdlib module), engine
  module version 2.6.0.
- **PostgreSQL: NOT EXECUTED.** No version to report — no instance was reachable.
  `psycopg` 3.3.6 was confirmed installable/importable, but a Postgres server was never
  connected to, so no server-side version string was ever obtained.

## 4. Experiment architecture

```
scenarios/ (P1-P13, negatives)
    -> scenarios/orchestration.py   (the one pre-LLM pipeline every scenario drives:
                                      metadata planning -> suppression filter -> Home
                                      RT#1 -> content access -> domain fan-out -> Home
                                      RT#2 -> ephemeral bundle)
    -> backends/  (S1-SQLite implemented+executed; S1-PostgreSQL implemented, NOT executed)
    -> home_stub/ (RT#1/RT#2, calibrated ~111.57ms latency, mutable authority)
    -> domain_stub/ (1/3/5 concurrent synthetic domain peers, R14 measured excluding auth)
    -> r13/ (Ed25519 application-layer holder-of-key experiment)
corpus/generator.py  (seeded synthetic corpus, feeds identical logical data to both backends)
bench/run_bench.py   (latency + counter matrix, JSON output)
```

One logical schema (`backends/model.py`) is implemented twice
(`backends/sqlite_backend.py`, `backends/postgres_backend.py`) so both realizations
answer identical queries over equivalent data — enforced by construction, not by
convention, since the generator (`corpus/generator.py`) produces one `Corpus` object
loaded verbatim into whichever backend is under test.

## 5. Synthetic schema

Tables (identical logical shape in both realizations; SQLite uses FTS5 for S2,
PostgreSQL uses `tsvector`/GIN — the only intentional divergence, per the spike's own
scope):

- `assertion_version` — immutable version rows: partition, line (replacement grouping),
  lifecycle state, classification revision, control revision, applicability window,
  replaces-pointer, **and `content_text` as a separate column from every metadata field**
  (H2's separability requirement, enforced structurally: the metadata-planning query's
  `SELECT` list never includes `content_text`).
- `assertion_subject`, `assertion_domain` — many-to-many subject/domain membership.
- `suppression` — durable non-use register, independent of physical deletion (B4).
- `materialization_binding` — currency binding (source version + classification/control
  revision at build time), checkable without a rebuild.
- `assertion_fts` (SQLite FTS5) / `content_tsv` generated column + GIN index
  (PostgreSQL) — the S2 full-text mechanism.

Not built: chunks, embeddings, graph edges, a separate retrieval materialization (per
Phase-1 §5.3's recommendation that S1 needs none).

## 6. Corpus generator

`corpus/generator.py`, deterministic (`random.Random(seed)`, default seed 42).
Verified: same seed produces byte-identical `Corpus.assertions`/`Corpus.grants`; a
different seed produces different data. Produces, at every size, by construction:
multi-subject assertions, mixed-domain assertions, superseded chains (v1
SUPERSEDED→v2 ADMITTED), disputed assertions, expired assertions (past
`applicable_until`), suppressed-but-physically-present rows, stale materialization
bindings (classification bumped post-build) alongside fresh control-group bindings, and
partial grants (some actor/subject/domain combinations authorized, most not).

| Size | Assertions | Suppressions | Bindings | Grants | Persons |
|---|---|---|---|---|---|
| C-small | 100 | 11 | 10 | 23 | 3 |
| C-medium | 5,000 | 371 | 522 | 49 | 6 |
| C-large | 100,000 | 7,340 | 11,022 | 87 | 10 |

## 7. Instrumentation method

Two-layer model (`backends/instrumentation.py`), per the executing methodological
correction:

- **Layer A (primary, mandatory):** `ContentAccessLog` records every logical content ID
  the application layer actually requested; `unauthorized_logical_content_ids_requested`
  is computed against the authorized set at request time. This is ground truth about
  what was *asked for*, independent of backend internals.
- **Layer B (corroboration only):** SQLite `EXPLAIN QUERY PLAN`; PostgreSQL `EXPLAIN
  (ANALYZE, BUFFERS, FORMAT JSON)` — **not executed** (no PostgreSQL instance). For
  SQLite, stdlib capability was verified empirically before relying on it: **no
  low-level statement-status counter API exists in Python's `sqlite3` module**
  (confirmed: `hasattr(sqlite3, 'sqlite3_stmt_status')` is `False`; no equivalent on the
  `Connection`/`Cursor` objects either). Only `EXPLAIN QUERY PLAN` and
  `set_trace_callback` are available and used.
- Combination rule: Layer A is authoritative for PASS; Layer B can downgrade a
  Layer-A-PASS to FAIL if it shows an unbounded access pattern (this happened for
  S2-SQLite, §11), or to UNKNOWN if inconclusive. Layer B never overrides a Layer-A-FAIL.

## 8. P1–P13 results

All SQLite-executable scenarios ran; all PostgreSQL variants are `NOT EXECUTED —
ENVIRONMENT BLOCKED`. 38 SQLite assertions passed, 0 failed, 20 PostgreSQL-parametrized
tests skipped for the stated reason.

| # | Scenario | S1-SQLite | S1-PostgreSQL | Notes |
|---|---|---|---|---|
| P1 | Knowledge only, single Person | **PASS** | NOT EXECUTED | 2 crossings confirmed |
| P2 | + 1 domain, R14 isolated | **PASS** | NOT EXECUTED | domain access reported as a separate stage |
| P3 | + 3 independent domains | **PASS** | NOT EXECUTED | 2 crossings; fan-out wall-clock ≈ max not sum |
| P4 | + 5 independent domains | **PASS** | NOT EXECUTED | 2 crossings still; confirms flat scaling |
| P5 | Source expansion | **PASS** | NOT EXECUTED | one full query w/ revalidation = 2 crossings (RT1+RT2); see §8.1 caveat |
| P6 | Denial before candidacy | **PASS** | NOT EXECUTED | 1 crossing, zero leakage; timing distributions §13 |
| P7 | Suppressed-but-present | **PASS** | NOT EXECUTED | row physically present, never addressable |
| P8 | Authority revoked between RT1/RT2 | **PASS** | NOT EXECUTED | RT#2 denies — fresh re-eval, not TTL |
| P9 | Stale classification binding | **PASS** | NOT EXECUTED | detected via binding record, no rebuild |
| P10 | Restore freshness unprovable | **PASS** | N/A (pure logic, backend-independent) | fails closed on `None` currency |
| P11 | Unknown binding | **PASS** | NOT EXECUTED | `None` returned, caller fails closed |
| P12 | R13 adversarial matrix | **PASS (all 10 cases incl. 2a/2b)** | N/A (backend-independent) | see §12 |
| P13 | Concurrent cleanup vs interactive reads | **PASS (correctness only)** | NOT EXECUTED | see §14, comparison incomplete |

### 8.1 P5 honesty note

The orchestration helper built for this spike does not expose composing multiple
authorization operations into a single Plan sharing one RT#1/RT#2 pair. The test
therefore demonstrates the two claims Phase-1 §16.5 P5 actually requires — an
independent expansion operation is its own RT#1-shaped crossing, and revalidation adds
exactly one more crossing per query — without asserting an exact "3 crossings for one
combined flow" figure the current harness cannot construct. This is recorded as a
harness limitation, not a security finding.

## 9. p50/p95/p99 tables

All SQLite, measured on this host, N=30 unless noted (warmup=3, correction 6). Full
JSON: `spike/knowledge-technology-gate/bench/report_data/bench_results.json`.

| Stage | Corpus | p50 (ms) | p95 (ms) | p99 (ms) | n | Kind |
|---|---|---|---|---|---|---|
| metadata_planning | C-small | 0.124 | 0.134 | 0.136 | 30 | MEASURED |
| content_access | C-small | 0.065 | 0.084 | 0.098 | 30 | MEASURED |
| metadata_planning | C-medium | 6.323 | 8.802 | 8.820 | 30 | MEASURED |
| content_access | C-medium | 1.886 | 2.796 | 7.345 | 30 | MEASURED |
| metadata_planning | **C-large** | **133.251** | **167.284** | **194.933** | 30 | MEASURED |
| content_access | C-large | 34.674 | 81.372 | 86.955 | 30 | MEASURED |
| home_crossing | N/A | 112.103 | 112.364 | 112.364 | 10 (UNDERPOWERED) | **CALIBRATED** |
| domain_fanout n=1 | N/A | 11.551 | 11.873 | 11.873 | 15 (UNDERPOWERED) | MEASURED |
| domain_fanout n=3 | N/A | 12.512 | 13.282 | 13.282 | 15 (UNDERPOWERED) | MEASURED |
| domain_fanout n=5 | N/A | 12.987 | 13.846 | 13.846 | 15 (UNDERPOWERED) | MEASURED |
| r13_execution | N/A | 0.136 | 0.293 | 0.344 | 30 | MEASURED |

**Latency composition (correction 7), explicit:**

- **MEASURED** (this spike, local): metadata planning, content access, domain fan-out,
  R13 crypto/verification, orchestration overhead — all actually timed on this host.
  **These are NOT network measurements and do not reflect any real geography.**
  Domain fan-out numbers include ~10ms injected synthetic base latency
  (`base_latency_ms=10.0` in `domain_stub/stub.py`), not a real domain read time.
- **CALIBRATED / INJECTED**: the ~111.57ms Home crossing sleep, drawn from Phase-1 doc
  E7 (real, previously-measured `check_access` p50). This spike did not re-measure Home;
  it replayed the accepted figure as a deliberate `time.sleep()`.
- **COMPOSED**: any total that sums a MEASURED stage with a CALIBRATED stage (e.g. "2
  Home crossings + metadata planning") is a synthetic composition, not a new real-world
  network measurement, and is never presented as one.

**C-large metadata planning (133ms p50) is the single most important number in this
table.** It approaches the calibrated Home crossing (112ms) at 100,000 assertions —
meaning at the deliberately-unrealistic C-large size (Phase-1 §16.3: "~1,000× the
realistic case"), unindexed-adjacent local retrieval cost starts to rival the network
floor. At C-small and C-medium (the realistic-to-mature range per Phase-1 §4.1), local
cost is negligible next to the ~240ms two-crossing floor, consistent with Phase-1 §4.2's
prediction.

## 10. Counter tables

| Scenario | home_auth_round_trip_count | authorization_operation_count | domain_call_count | source_expansion_count |
|---|---|---|---|---|
| P1 | 2 | 2 | 0 | 0 |
| P2 | 2 | 2 | 1 | 0 |
| P3 | 2 | 2 | 3 | 0 |
| P4 | 2 | 2 | 5 | 0 |
| P6 (deny) | 1 | 1 | 0 | 0 |

**`home_auth_round_trip_count` did not grow with `domain_call_count`** across P2→P3→P4
(2, 2, 2 against domain_call_count 1, 3, 5) — the decisive B6 §18A.10 test, confirmed on
SQLite. Not independently confirmed on PostgreSQL (environment blocked); the counter
logic (`home_stub/stub.py`) is backend-independent so there is no architectural reason
to expect divergence, but this is an inference, not a second measurement, and is labeled
as such.

## 11. Barrier evidence

| Corpus | S1 exact-lookup (Layer A) | S2 full-text Layer A | S2 full-text Layer B | S2 combined |
|---|---|---|---|---|
| C-small | PASS | PASS | **FAIL** | **FAIL** |
| C-medium | PASS | PASS | **FAIL** | **FAIL** |
| C-large | PASS | PASS | **FAIL** | **FAIL** |

**S1-SQLite exact-version lookup: PASS at every size, Layer A only** (Layer B plan
capture was written for the exact-lookup path but not separately reported — the
authorized-ID-bounded `WHERE version_id IN (...)` query is trivially index-driven and
was not the ambiguous case; S2's virtual-table scan was).

**S2-SQLite full-text: Layer A passes (zero unauthorized IDs ever returned to or
requested by the application), but Layer B correctly detects the backend performing an
unbounded access pattern.** `EXPLAIN QUERY PLAN` on the barrier query
(`backends/sqlite_backend.py::fetch_content_fulltext`, which explicitly builds a bounded
temp table and joins it against the FTS5 table) consistently shows:

```
SCAN f VIRTUAL TABLE INDEX 0:M2
SEARCH sc USING COVERING INDEX ... (version_id=?)
```

FTS5's `MATCH` operator requires evaluating against its own internal index (a global
posting list) **regardless of join order with the authorized-scope temp table** — this
was verified directly: forcing the temp table to be scanned first via `CROSS JOIN` still
produced `SCAN f VIRTUAL TABLE INDEX 0:M2` for the FTS table. **Returned rows are
correct** (bounded to the authorized set, confirmed by Layer A), but the physical access
pattern is not — exactly the "correct results, wrong ordering" failure mode Phase-1 §7.1
warned about for PostgreSQL's GIN index and which turns out to also apply to SQLite's
FTS5.

**S2 = FAIL for H3 under the SQLite/FTS5 realization tested here.** Per the spike's own
instruction ("Do not tune around the security requirement"), no workaround (custom
virtual table, external tokenizer, manual posting-list partitioning) was attempted — the
architecture question is whether the *native* mechanism can express the barrier, and for
FTS5's `MATCH` semantics, it structurally cannot via a plain join.

**S2-PostgreSQL: NOT EXECUTED.** The `backends/postgres_backend.py` implementation of
the same 3-step barrier (temp table → `content_tsv @@ plainto_tsquery` joined against
it) exists and was never run. Whether PostgreSQL's GIN-indexed `tsvector` path is
subject to the same unbounded-scan behavior, or whether its planner can push the
temp-table join as a genuine pre-filter into the GIN scan, is **UNKNOWN — NOT EXECUTED**.
This is exactly the comparison the Gate needs and exactly the piece this run could not
produce.

## 12. R13 adversarial results

All 10 required cases plus the case9/case10 structural checks, **application-layer
Ed25519 holder-of-key**, `spike/knowledge-technology-gate/r13/holder_of_key.py`:

| Case | Description | Result |
|---|---|---|
| 1 | Copied basis, wrong key, presented by another party | **FAIL CLOSED — PASS** |
| 2 | Correct basis + wrong claimed service identity | **FAIL CLOSED — PASS** |
| 2a | Wrong key + correct-looking service claim | **FAIL CLOSED — PASS** |
| 2b | Correct key + wrong authenticated service identity | **FAIL CLOSED — PASS** |
| 3 | Correct basis, wrong audience/domain | **FAIL CLOSED — PASS** |
| 4 | Cross-request replay | **FAIL CLOSED — PASS** (first succeeds, replay denied) |
| 5 | Cross-actor replay | **FAIL CLOSED — PASS** |
| 6 | Expired basis | **FAIL CLOSED — PASS** |
| 7 | Exact approved operation, correct everything | **SUCCEEDS — PASS** |
| 8 | RT#2 still freshly revalidates after execution | **OBSERVED — PASS** |
| 9 | `decision_id` alone proves nothing | **PASS** (no code path accepts it alone) |
| 10 | `home_auth_round_trip_count == 2` for the full flow | **PASS** (RT#1 + RT#2 = 2; R13 execution itself adds 0 Home crossings) |

**Case 2a/2b, the pair that matters most:** confirmed independently. 2a shows a key not
bound to the claimed service fails even when the claim "looks right"; 2b shows a
genuinely correct key fails when presented under the wrong claimed identity. Neither
half of the (service identity, confirmation key) pair is sufficient alone — only the
exact pair the trusted Home stub bound at mint time succeeds.

**Experimental caveat, stated plainly (already flagged in the code):** this in-process
stub cannot reproduce a real transport-level authenticated identity (mTLS or
equivalent). `claimed_service_identity` is an explicit parameter the test harness
supplies, modeling what a real transport layer would authenticate. The verification
*logic* under test — reject any mismatch between the claimed identity, the presented
key, and what the Home-minted basis actually bound — is the same logic a
transport-bound production implementation would need, but this experiment does not
prove a real transport binding is achievable without its own separate validation.
Recorded as a limitation, not smoothed over.

## 13. Allow/deny/no-content timing distributions

N=50 each, Home latency injection disabled (`inject_latency=False`) to isolate
application-level timing from the constant calibrated sleep (which is identical for
allow and deny and would otherwise mask any real separation).

| Path | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| Allow | 7.5324 | 9.5997 | 12.8417 |
| Deny | 5.7482 | 6.4566 | 6.8276 |

**Finding: a stable, non-overlapping timing separation exists (~1.8ms at p50, no
overlap through p99).** Allow does strictly more work than deny (content fetch after a
successful RT#1; deny short-circuits immediately after RT#1 fails). This is measurable
independent of the Home network crossing, which is identical in both paths.

Per PA-10d and the mission brief, **this is reported as a finding, not remediated** —
the spike's instructions explicitly say not to implement production timing equalization
unless needed for the experiment's own validity, and equalizing was not needed to
produce this result.

## 14. SQLite vs PostgreSQL comparison

**Incomplete — PostgreSQL did not execute.** What is reported:

- **SQLite (P13):** correctness confirmed under contention. 15 concurrent interactive
  reads (`plan_metadata` + `fetch_content`) ran while a separate thread deleted 10
  suppression rows, under the documented `SQLITE_PRAGMAS` (WAL, `synchronous=NORMAL`,
  `busy_timeout=5000`). Zero `sqlite3.OperationalError`s, all 15 reads completed. A real
  bug was found and fixed during this work: opening a second connection to the same
  on-disk SQLite file was unconditionally re-running `CREATE TABLE`, which fails on an
  existing schema — fixed by making schema creation conditional
  (`SQLiteKnowledgeBackend(path, create_schema=...)`), auto-detecting new-file vs
  existing-file. This was a harness bug, not a finding about SQLite itself.
- **PostgreSQL (P13): NOT EXECUTED.** No comparison possible. The decisive question
  Phase-1 §14.1 poses ("single-writer contention under B4 cleanup — decisive between the
  two S1 realizations") is **not answered by this run.**
- Configuration was documented for both per correction 8 (`SQLITE_PRAGMAS` in
  `sqlite_backend.py`; `PG_SESSION_NOTES` in `postgres_backend.py`, unexercised).

## 15. S2 full-text barrier result

**SQLite: FAIL.** PostgreSQL: **NOT EXECUTED — UNKNOWN.**

Per §11, S2's native FTS5 mechanism cannot express the authorized-set-first barrier
without an internal unbounded scan of its own virtual-table index, regardless of query
join order. This is a structural property of FTS5's `MATCH` operator, verified directly,
not inferred. **Overall S2 disposition given only one realization tested: FAIL /
UNKNOWN** — a full disposition requires the PostgreSQL half of this comparison.

## 16. Every B6 §19 question / B1–B6 security pass condition

| Requirement | Result | Evidence |
|---|---|---|
| Protected metadata resolvable without content (H2) | **PASS** (SQLite) | `plan_metadata` SELECT list structurally excludes `content_text`; §9 timing shows it as a real, separately-measured stage |
| Authorization-constrained retrieval, no retrieve-then-filter (H3) | **PASS for S1; FAIL for S2** (SQLite) | §11 |
| Suppression before candidacy (H5) | **PASS** | P7, §8 |
| Exact-version lifecycle (H4) | **PASS** (schema supports it; scenario coverage via P9) | §5, §8 |
| Materialization bindings testable without rebuild (H6) | **PASS** | P9, P11, §8 |
| Restore freshness / unknown fails closed (H7) | **PASS** | P10, §8 |
| Final revalidation is fresh re-eval, not TTL (H8) | **PASS** | P8, §8 |
| No authorization per candidate (H9) | **PASS** (by construction — one bounded query, not N) | P1 timing shows planning is O(1) queries, not O(candidates) |
| ContextBundle never persisted (H10) | **PASS** (structural — `EphemeralContextBundle` has no save/serialize method) | §17 |
| R13 non-bearer boundary (H12) | **PASS**, experimental realization only | §12 |
| R14 raw domain latency measured | **PASS** (measured, but is a synthetic 10ms injection, not a real domain) | §9 |

## 17. Teardown evidence

`teardown.py` removes all `*.db`/`*.db-wal`/`*.db-shm`/`*.sqlite*` files and
`__pycache__` directories under `spike/knowledge-technology-gate/`, and best-effort
drops a `spike_kn` PostgreSQL schema if a Postgres instance is detected. All backend
instances used during this run were `:memory:` SQLite (no on-disk file to clean) except
the P13 concurrency test, which uses pytest's own `tmp_path` fixture (cleaned by pytest
itself, outside this tree). No PostgreSQL schema was ever created (no instance
available), so there was nothing to drop. Confirmed no stray files remain under
`spike/knowledge-technology-gate/` after the test/bench runs other than the intentional
`bench/report_data/bench_results.json` output and `__pycache__` (removable by
`teardown.py`, not committed).

## 18. Limitations

- **PostgreSQL did not execute at all.** This is the single largest limitation and
  affects §11 (S2 disposition), §14 (the decisive P13 comparison), and every "both
  realizations" requirement in Phase-1 §16.5.
- Layer B (backend plan-evidence) instrumentation was only built and exercised for
  SQLite's S2 path; it was not separately run against S1's exact-lookup path at scale,
  nor was a PostgreSQL Layer B ever exercised.
- Sample sizes for several stages (Home crossing n=10, domain fan-out n=15) are
  explicitly UNDERPOWERED per correction 6 and labeled as such — their p95/p99 should be
  read as informational only, not a real percentile claim.
- The orchestration harness does not support composing multiple authorization
  operations into a single shared Plan/RT pair, which limited the precision of the P5
  crossing-count assertion (§8.1).
- Domain fan-out latency figures are synthetic (10ms injected), not derived from any
  real domain service measurement — R14 remains genuinely unmeasured against a real
  domain; only the *isolation methodology* (excluding authorization from the timed
  stage) was validated.
- R13's transport-identity authentication is simulated via an explicit parameter, not a
  real mTLS/channel-binding mechanism (§12 caveat).
- This spike's corpus generator, while producing all required fixture families, was not
  independently cross-checked against a second generator implementation.

## 19. Findings requiring Product Architect interpretation

1. **S2/FTS5's structural inability to express the barrier without an internal unbounded
   scan** — is this disqualifying for S2 as a category, or specific to SQLite's FTS5
   implementation such that PostgreSQL's `tsvector`/GIN deserves a fair, separate test
   before any conclusion? This spike cannot answer that; §11/§15 report SQLite only.
2. **The allow/deny timing separation (§13)** — is a ~1.8ms, non-overlapping timing
   difference at the application layer (masked by network latency in any real
   deployment, but observable to a co-located adversary or under connection reuse) a
   finding that needs a mitigation requirement added to the eventual selected
   architecture, or is it acceptable given the dominant ~240ms network floor?
3. **C-large metadata planning cost (133ms p50) approaching the Home-crossing floor** —
   Phase-1 §4.2 predicted the corpus would need "three to four orders of magnitude" of
   growth before local retrieval rivaled the network floor; this spike's C-large (100K,
   already "~1,000× the realistic case" per §16.3) shows metadata planning alone already
   at ~60% of one crossing's cost. Is this evidence the pgvector-style "static index"
   discipline needs to extend to plain relational indexing sooner than assumed, or is
   133ms at a corpus size 1,000× realistic simply not a concern?
4. **Whether the R13 experimental realization's transport-identity simulation
   (§12 caveat) is close enough to a real mTLS/channel-binding mechanism** to treat this
   evidence as informative for a production R13 selection, or whether a Family-1-variant
   A (transport/channel-bound, Phase-1 §11.4 secondary) experiment is now warranted to
   close that gap.

## 20. Evidence relevant to final Technology Gate selection

**Positive evidence produced:**
- S1-SQLite passes every tested B1–B6 invariant at every tested corpus size.
- The R13 application-layer holder-of-key experimental realization passes its full
  adversarial matrix, including the decisive 2a/2b pair, and preserves the 2-crossing
  budget.
- `home_auth_round_trip_count` provably does not grow with `domain_call_count` (2, 2, 2
  across 1/3/5 domains) on SQLite.
- Concurrent B4-style cleanup does not corrupt or block interactive SQLite reads under
  WAL configuration (correctness, not yet a full percentile comparison).

**Negative/inconclusive evidence produced:**
- S2 (native full-text) fails the barrier test on SQLite/FTS5 as tested; PostgreSQL
  untested.
- No SQLite-vs-PostgreSQL performance or contention comparison exists — the decisive P13
  question from Phase-1 §14.1 is unanswered.
- A measurable, unaddressed timing side-channel exists between allow and deny paths.

---

## 21. Unexpected findings

- The stdlib `sqlite3` module's complete absence of low-level statement-status counters
  was confirmed empirically, not assumed — this shaped the two-layer instrumentation
  design directly (the executing correction anticipated this might be true; it was).
- A real harness bug (schema-recreation race on multi-connection SQLite access) was
  found and fixed during P13 development — worth noting because it demonstrates the
  value of actually running concurrent scenarios rather than reasoning about them.
- FTS5's `MATCH` operator's join-order-independence (confirmed via an explicit
  `CROSS JOIN` experiment) was a sharper, more concrete finding than the Phase-1 doc's
  PostgreSQL-focused prediction — the same failure mode applies to SQLite via a
  completely different mechanism (posting-list traversal vs GIN index semantics), which
  suggests the barrier problem may be more general to native full-text indexes as a
  class, not specific to one engine's implementation choices. This strengthens the case
  for testing PostgreSQL's GIN path before drawing any category-level conclusion.

## 22. Whether any B1–B6 contradiction emerged

**No.** Every failure or limitation found (S2/FTS5, timing separation, PostgreSQL
non-execution) is exactly the kind of evidence Phase-1 §15 anticipated needing
measurement to resolve — none of it requires reopening B1, B2, B3, B4, B5, or B6. The
S2 finding in particular is the CONDITIONAL outcome Phase-1 §14 explicitly allowed for
("S2 does not become 'slower' — it becomes non-compliant, and the finding is reported as
such").

## 23. Questions needing Product Architect interpretation

See §19 (kept together with the findings that motivate each question, per the report's
own internal consistency — restated here per the mission brief's numbering only to
confirm this section is not omitted).

## 24. Whether the empirical evidence is sufficient to begin final Technology Gate selection

**No.** Reasons, directly against Phase-1 §17's acceptance criteria:

- §17 item 9 requires a selected shape **and** version-specific realization with
  version-specific verification — this run verified exactly one realization
  (SQLite 3.41.2) and never touched the other.
- §17 item 6 (targets met, or revised on measured evidence) cannot be assessed for
  PostgreSQL at all.
- §14.1's own framing states the SQLite-vs-PostgreSQL question is "the discriminator
  between the two S1 realizations" — a discriminator with only one side measured
  discriminates nothing.
- S2's disposition (§17 item 3, "every §16.7 pass condition met") is FAIL on the one
  realization tested and UNKNOWN on the other — not a closed question.

**What would close this gap:** re-run this spike's PostgreSQL path
(`backends/postgres_backend.py`, already implemented and unit-tested via the Layer A
evidence model, never executed) against an already-available disposable PostgreSQL
instance, following the same detection-not-provisioning discipline
(`backends/postgres_env.py`, `SPIKE_POSTGRES_DSN` environment variable). No code changes
should be required to do this — only environment availability.

---

**NO TECHNOLOGY SELECTED BY THIS REPORT.**

**SPIKE PARTIALLY EXECUTED — SQLITE ONLY.**

**NO PRODUCTION CHANGE.**
