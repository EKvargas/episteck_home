# Knowledge Technology Gate — Empirical Spike Report

Status: **EVIDENCE REPORT — SPIKE EXECUTED AGAINST BOTH BACKENDS. TECHNOLOGY GATE CLOSED — SELECTION COMPLETE (Part G, §27): S1 relational canonical owner with structured retrieval, realized on SQLite 3.41.2. No implementation authorized.**

Authorized by: TG-PA-7 (`KNOWLEDGE_TECHNOLOGY_GATE_PHASE1.md` §18.1).

**Revision note (Gate closure record, 2026-09-25):** Parts A–F below are the evidence as
reviewed and are unchanged, apart from one canonical-value note in §20. The Architecture
Board accepted the final technology direction. Part G (§27) records that selection, the
Phase-1 §17 criteria disposition, the separation between the selected realization and its
tested configuration, and the pre-runtime obligations. Parts A–F still say "no technology
selected" because they were written before selection; that wording is historical, and
Part G supersedes it.

**Revision note (this rewrite):** the original version of this report covered a SQLite-only
run; PostgreSQL was NOT EXECUTED (no disposable instance available). This rewrite covers a
second execution pass against an already-available local PostgreSQL 15.8 instance (detected,
never provisioned, per the spike's own scope), plus corrections found and fixed during that
pass. **Numbers from the original SQLite-only run that were contaminated by a harness defect
(N+1 query pattern, §9) are marked SUPERSEDED below, not deleted** — the corrected numbers
replace them for any evidentiary purpose, but the superseded figures and why they were wrong
remain in this document for traceability.

**Revision note (R13 closure pass):** this pass adds one minimal end-to-end transport
closure test for R13 §16.7 condition 5 (§14), records the Product Architect timing
side-channel disposition (§21), and corrects §19/§20/§23/§25's interpretation of the
timing and P13-PostgreSQL evidence — in particular, removing the earlier §25 framing that
tied the PostgreSQL P13-R UNKNOWN to §17 item 9 and to entering Technology Gate selection
at all; that UNKNOWN bears on §17 item 6, evaluated per-realization after selection. **No
technology is selected by this pass either.**

This report separates five kinds of evidence throughout, because they answer different
questions and must not be conflated:

1. **Correctness/security evidence** — does the barrier hold (Layer A/B, §10–§13)
2. **Planner/query-shape evidence** — what the backend's own query planner chose to do, and
   why (§14–§16)
3. **Latency/performance evidence** — measured timings (§17–§20)
4. **Harness artifacts** — defects in the spike's OWN code, not backend properties (§9, §16)
5. **Remaining UNKNOWNs** — what this spike still cannot answer (§25)

---

## 1. Exact main baseline SHA

`523c6b849518c47f5093ce2524c9c15b083495fa` — verified equal to `origin/main` after
fetch, prior to branching. PR #30 (Phase 1 closure) confirmed merged.

## 2. Environment (this execution pass)

- OS: Windows 11 Enterprise, shell: Git Bash / Cygwin over PowerShell-hosted Python.
- Python interpreter: **3.11.8**, via a dedicated project-local virtual environment
  (`spike/knowledge-technology-gate/.spike-venv`) seeded from the same 3.11.8 base
  interpreter the original run used (`C:\Users\D064974\AppData\Roaming\pypoetry\venv`),
  to avoid installing spike-only dependencies (`psycopg[binary]`) into that shared,
  general-purpose venv. `pip install -e .` fails on a pre-existing flat-layout issue in
  the spike's own `pyproject.toml` (unrelated, not fixed here since it wasn't blocking);
  worked around by installing `psycopg[binary]>=3.2`, `cryptography>=43`, `pytest>=8`
  directly. pytest 9.1.1.
- **PostgreSQL: 15.8** (`postgresql-x64-15`, a pre-existing native Windows service, NOT
  Docker/WSL — outside this spike's original detection scope in `postgres_env.py`, which
  only checks `SPIKE_POSTGRES_DSN` or a container daemon; the operator set
  `SPIKE_POSTGRES_DSN` explicitly to point at this already-running instance, which is
  exactly the supported "already-available, detected, never provisioned" path).
  Authentication: `trust` on `127.0.0.1`/`::1` (pre-existing `pg_hba.conf`, not modified
  by this spike). Disposable database `olin_knowledge_gate_spike` created for this run
  (per the spike's own authorized scope: create a disposable database/role, drop it at
  teardown); the backend code itself isolates further via `CREATE SCHEMA`/`DROP SCHEMA`
  per session (`spike_kn`), so most experiments never even needed the database-level
  isolation, only the P13 contention harness's shared-schema multi-connection case did.
- **Not connected to production.** No `home.episteck.com` access, no production
  svc-nutrition, no production gateway, no Tailscale route, no production credentials.
  Home and all domain peers are in-process stubs (`home_stub/`, `domain_stub/`).
- **This execution pass ran from an isolated checkout** (`C:\aiprojects\episteck_home-claude`,
  branch `spike/knowledge-technology-gate`, HEAD verified equal to
  `origin/spike/knowledge-technology-gate` before any work began) — the original run's
  "shared checkout" caveat does not apply here.

## 3. Pinned SQLite/PostgreSQL versions

- **SQLite: 3.41.2** (via Python 3.11.8's bundled `sqlite3` stdlib module), engine
  module version 2.6.0. Unchanged from the original run.
- **PostgreSQL: 15.8** (`PostgreSQL 15.8, compiled by Visual C++ build 1941, 64-bit`).
  `psycopg` 3.3.6 (matches the version the original report pinned as
  "confirmed installable/importable" but never actually connected with).

## 4. Experiment architecture

Unchanged from the original report:

```
scenarios/ (P1-P13, negatives)
    -> scenarios/orchestration.py   (the one pre-LLM pipeline every scenario drives:
                                      metadata planning -> suppression filter -> Home
                                      RT#1 -> content access -> domain fan-out -> Home
                                      RT#2 -> ephemeral bundle)
    -> backends/  (S1-SQLite and S1-PostgreSQL both implemented AND executed this pass)
    -> home_stub/ (RT#1/RT#2, calibrated ~111.57ms latency, mutable authority)
    -> domain_stub/ (1/3/5 concurrent synthetic domain peers, R14 measured excluding auth)
    -> r13/ (Ed25519 application-layer holder-of-key experiment)
corpus/generator.py  (seeded synthetic corpus, feeds identical logical data to both backends)
bench/run_bench.py   (latency + counter matrix, JSON output)
```

## 5. Synthetic schema

Unchanged from the original report — one logical schema (`backends/model.py`), realized
identically in `sqlite_backend.py` and `postgres_backend.py`, differing only in the S2
full-text mechanism (SQLite FTS5 vs PostgreSQL `tsvector`/GIN, the spike's own intentional
divergence point).

| Size | Assertions | Suppressions | Bindings | Grants | Persons |
|---|---|---|---|---|---|
| C-small | 100 | 11 | 10 | 23 | 3 |
| C-medium | 5,000 | 371 | 522 | 49 | 6 |
| C-large | 100,000 | 7,340 | 11,022 | 87 | 10 |

## 6. Corpus generator

Unchanged from the original report — deterministic (`random.Random(seed)`), verified
byte-identical across backends for a fixed seed.

---

# PART A — HARNESS DEFECTS FOUND AND FIXED THIS PASS

These are properties of the SPIKE'S OWN CODE, not of either backend. Listed first because
they explain why several numbers below differ from the original report and are marked
SUPERSEDED.

## 7. Correction 10 completion: S1-PostgreSQL Layer B was entirely missing

The original report's correction 10 added Layer B (backend plan-evidence) for S1's
exact-version content lookup on SQLite, but `PostgresKnowledgeBackend` had no
`explain_content_barrier` method at all — calling the existing S1 Layer B test against
PostgreSQL raised `AttributeError`, meaning this path had never actually been exercised.
**Fixed:** added `explain_content_barrier` to `postgres_backend.py`, mirroring the SQLite
method (`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on the same `version_id = ANY(...)`
query `fetch_content` runs).

## 8. New Layer B classifier: `layer_b_postgres_exact_lookup` (S1)

Applying the existing S2-oriented `layer_b_postgres` heuristic (Seq-Scan-without-join ⇒
FAIL) to the S1 exact-lookup query produced a **false FAIL**: PostgreSQL's planner chooses
`Seq Scan` over `assertion_version` for `WHERE version_id = ANY(authorized_ids)` at every
tested corpus size (C-small/medium/large), because the filter predicate itself **is** the
authorized set and a full scan-with-filter is cheaper than per-ID index probes at this
selectivity/table-size — ordinary cost-based planning, not an unbounded access pattern.
The S1 query has no join at all, so the S2 heuristic's join-detection logic doesn't even
apply.

**Fixed:** a dedicated `layer_b_postgres_exact_lookup` function (`backends/instrumentation.py`)
classifies PASS only when ALL of:
1. Layer A already proved zero unauthorized IDs were requested (checked by the caller).
2. The plan's only scan of `assertion_version` has a predicate directly on `version_id`
   against the authorized set.
3. No node touches a full-text/GIN/aggregate structure.
4. No `Join`/`SubPlan`/`InitPlan` node broadens the candidate set.
5. The plan shape is a single-relation scan the function recognizes with confidence.

Ambiguous or unrecognized shapes return UNKNOWN, never a guessed PASS. 5 unit tests
(`scenarios/test_s1_backend_plan_evidence.py`) cover: Seq Scan + exact filter (PASS),
Index/Bitmap scan + exact filter (PASS), missing/broadened predicate (UNKNOWN/FAIL),
ambiguous plan (UNKNOWN), closed-set verdicts.

## 9. N+1 query pattern in `plan_metadata()` — the original C-large ~133ms cause

**SUPERSEDED FINDING.** The original report (§9, §19 item 3) measured C-large metadata
planning at **p50=133.251ms** and interpreted this as approaching the calibrated Home
crossing floor, suggesting corpus-size-driven local retrieval cost was becoming
significant "much sooner than Phase-1 §4.2 predicted."

**This interpretation was wrong.** Both backends' `plan_metadata()` issued one subject
query + one domain query PER CANDIDATE (N+1): **20,201 individual SQL statements** for
10,100 candidates at C-large (1 candidate-ID query + 2 × 10,100). This is a query-COUNT
problem in the harness, not an index-absence or corpus-size-driven storage-cost finding.
Verified directly: profiling showed `fetchall()` calls accounted for 79% of SQLite's
wall-clock time at C-large, and PostgreSQL's original P13 read baseline (C-medium, 861
candidates → 1,723 statements) measured 377ms, dominated by round-trip count.

**Fixed:** both backends now batch subject/domain lookups via a shared
`backends.common.chunk_ids` helper (fixed batch size 500, identical strategy on both
realizations — never independently tuned per backend). Query count dropped from 20,201 to
43 at C-large. Two regression tests (`scenarios/test_plan_metadata_query_scaling.py`)
prove query count is O(batches), not O(candidates), for both backends — they fail loudly
if the N+1 pattern ever returns.

**What the fix actually changed (see §17–§18 for full numbers):** P13's read latencies
dropped dramatically on both backends (round-trip count was the dominant cost there). The
standalone C-large metadata-planning benchmark, measured in isolation, did NOT get faster
— see §16 for why: a different, pre-existing query (unaffected by this fix) turned out to
be the real dominant cost at C-large.

## 10. S2-PostgreSQL classifier was join-presence-only, not drive-order-aware

Once S2 was actually executed against PostgreSQL (§13), the original `layer_b_postgres`
heuristic (any join present ⇒ PASS) proved wrong for the same reason as §8: a join being
present is not sufficient evidence the barrier holds — it matters which side of the join
DRIVES. Fixed; see §13 for the full finding and §8's sibling fix pattern.

---

# PART B — CORRECTNESS / SECURITY EVIDENCE (Layer A / Layer B)

## 11. Instrumentation method (unchanged from original report)

Two-layer model (`backends/instrumentation.py`):
- **Layer A (primary, mandatory):** `ContentAccessLog` records every logical content ID
  the application layer actually requested; ground truth about what was asked for.
- **Layer B (corroboration only):** `EXPLAIN QUERY PLAN` (SQLite) / `EXPLAIN (ANALYZE,
  BUFFERS, FORMAT JSON)` (PostgreSQL). Never overrides a Layer-A FAIL; can downgrade a
  Layer-A PASS to FAIL or UNKNOWN if backend-internal access pattern evidence contradicts
  or cannot confirm it.

## 12. S1 (exact-version lookup) barrier evidence — BOTH backends now executed

| Corpus | S1-SQLite Layer A | S1-SQLite Layer B | S1-PostgreSQL Layer A | S1-PostgreSQL Layer B |
|---|---|---|---|---|
| C-small | PASS | PASS | PASS | PASS |
| C-medium | PASS | PASS | PASS | PASS |
| C-large | PASS | PASS | PASS | PASS |

**S1-PostgreSQL Layer A:** zero unauthorized logical content IDs requested at any tested
size — confirmed via the real `fetch_content` path, not just the EXPLAIN probe.

**S1-PostgreSQL Layer B:** PASS via `layer_b_postgres_exact_lookup` (§8) — the query's
predicate is directly `version_id = ANY(authorized_ids)`, no join, no FTS/aggregate node.
The plan is a `Seq Scan` at every tested size (see §16 for why the planner picks this and
why that's expected, not a defect) — a Seq Scan alone is not a FAIL under this classifier
because the filter predicate itself is the authorization boundary.

**Overall S1 disposition: PASS on both backends.**

## 13. S2 (native full-text) barrier evidence — BOTH backends now executed

### SQLite — unchanged from original report

| Corpus | Layer A | Layer B | Combined |
|---|---|---|---|
| C-small | PASS | FAIL | **FAIL** |
| C-medium | PASS | FAIL | **FAIL** |
| C-large | PASS | FAIL | **FAIL** |

FTS5's `MATCH` operator requires evaluating against its own internal index (a global
posting list) regardless of join order with the authorized-scope temp table — verified via
an explicit `CROSS JOIN` experiment in the original run. Unchanged; not re-verified this
pass (no reason to — the finding is structural to FTS5, not something a harness fix could
affect).

### PostgreSQL — executed for the first time this pass

**Layer A: PASS.** C-medium corpus, search term `"prefers-cuisine"` (one of the corpus
generator's fixed topic vocabulary). 844 authorized candidates; 67 rows matched and
returned; `unauthorized_logical_content_ids_requested = 0`. The application never received
an unauthorized row.

**Layer B: FAIL**, via the corrected drive-order-aware `layer_b_postgres` (§10). The real
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plan for the barrier query (temp authorized-scope
table JOIN `assertion_version` WHERE `content_tsv @@ plainto_tsquery`) is:

```
Nested Loop (Actual Rows: 67)
  -> Seq Scan on assertion_version (OUTER/driving side)
       Filter: content_tsv @@ tsquery('prefers-cuisin' & 'prefer' & 'cuisin')
       Actual Rows: 474, Rows Removed by Filter: 4526   [474 + 4526 = the FULL 5000-row table]
  -> Index Only Scan on authorized_scope_probe (INNER side)
       Index Cond: version_id = av.version_id
```

**The full-text predicate is evaluated against the ENTIRE `assertion_version` table (all
5,000 rows) BEFORE the authorized-scope join ever restricts anything.** This is "correct
final results, wrong internal ordering" — the exact same failure mode as SQLite's FTS5
(§13 above), now confirmed structurally for PostgreSQL's `tsvector`/GIN path, closing the
original report's §19-item-1 open question ("is this SQLite-specific, or does PostgreSQL's
GIN path deserve a fair separate test").

**Corroboration (planner-choice sensitivity check, not a barrier design change):** the
same query was re-run with `SET LOCAL enable_nestloop`... no — with `enable_seqscan = off`
forcing the planner toward the GIN index. The resulting plan is `Bitmap Heap Scan` on
`assertion_version` (using `idx_av_fts`) as the OUTER/driving side, joined to the
authorized-scope table SECOND — **the same drive order**. Using the GIN index does not
change which side drives; this rules out "it's just because the planner picked a naive Seq
Scan" as an explanation. The barrier query itself was never modified for either
observation.

**Overall S2 disposition: FAIL on BOTH backends now tested.** The original report's
§19-item-1 question is answered: this is not SQLite/FTS5-specific. PostgreSQL's
`tsvector`/GIN full-text mechanism exhibits the same barrier-ordering failure with the
tested query shape. Per the spike's own instruction ("do not tune around the security
requirement"), no workaround was attempted on either backend — the question is whether the
*native* full-text mechanism can express the barrier via a plain join, and for the tested
shape, neither backend's does.

**Scope of this finding, stated precisely:** this is a finding about the tested S2 barrier
query shape (temp table + plain JOIN) against these two backends' native full-text
mechanisms on this schema — **not** a general claim that "PostgreSQL full-text search is
insecure" or that no PostgreSQL full-text barrier construction could ever work (a
materialized-CTE-first form, a different join hint, or a different extension might behave
differently — untested, out of this spike's scope).

## 14. R13 adversarial results

All 10 required cases plus case9/case10 structural checks pass, application-layer Ed25519
holder-of-key. Not re-executed this pass (backend-independent; correction 12/§19
scope did not touch this experiment). See original findings, preserved:

| Case | Result |
|---|---|
| 1–6 | FAIL CLOSED — PASS |
| 7 | SUCCEEDS — PASS |
| 8 | OBSERVED — PASS |
| 9 | PASS |
| 10 | PASS (`home_auth_round_trip_count == 2`) |

### §16.7 condition 5 minimum transport-backed closure test (this pass)

The Architecture Review determined that the primary in-process P12 case 2b test
(`test_case2b_correct_key_wrong_authenticated_identity_fails_closed`) does not establish a
genuinely authenticated service identity, because `claimed_service_identity` there is a
caller-supplied string — the exact reason `classify_r13()` records `R13-B` as
`UNKNOWN — INSUFFICIENT EVIDENCE`. The secondary mTLS harness (correction 7,
`r13/transport_identity.py`) establishes transport-derived identity, but its one
composition test closed the TLS connection before calling
`DomainVerifier.verify_and_execute` in process, so it never exercised the 2b arm over the
authenticated stream itself.

`scenarios/test_r13_transport_case2b_closure.py` (new, this pass) closes exactly that gap
with one minimal test,
`test_case2b_transport_authenticated_wrong_service_with_genuine_key_fails_closed`, plus a
same-wire-path positive control. Both reuse `EphemeralServiceCA` /
`TransportIdentityServer` primitives from `r13/transport_identity.py` and
`DomainVerifier` / `HomeBasisMinter` / `TrustedKeyRegistry` / `sign_proof` from
`r13/holder_of_key.py` **unmodified** — the only new code is test-only wire plumbing (a
JSON basis+proof exchange sent over the already-authenticated TLS socket, verified by the
unmodified `DomainVerifier`), not a new production or spike mechanism.

**Attack arm result:** a client TLS-authenticated as `svc-attacker` (trusted certificate,
real mTLS handshake — not forged, not rejected at transport) sent, over that same
connection, a basis bound to `svc-nutrition` plus a proof signed with the GENUINE
`svc-nutrition` Ed25519 private key, and a payload field falsely claiming
`service_identity=svc-nutrition`. Results:

| Assertion | Result |
|---|---|
| A. TLS handshake succeeds | **PASS** — trusted cert, real handshake |
| B. `transport_identity == "svc-attacker"` | **PASS** — derived from `getpeercert()`, payload's false claim ignored |
| C. the svc-nutrition proof is genuinely valid | **PASS** — verified independently of the `DomainVerifier` call |
| D. `execution.executed == False` | **PASS** |
| E. rejection reason is specifically the identity mismatch, not TLS/signature failure | **PASS** — `"claimed service identity != basis-bound identity (fail closed)"` |

**Positive control, same wire path** (trusted `svc-nutrition` cert, fresh basis, genuine
`svc-nutrition` proof): `execution.executed == True`. This rules out the attack-arm
rejection being an artifact of the exchange harness itself rather than the identity
mismatch.

**Disposition:** §16.7 condition 5 is recorded **MET at the spike's experimental scope**.
The primary in-process `R13-B` classification in `classify_r13()` is **unchanged and
remains `UNKNOWN` by construction** — this closure test does not retroactively make the
caller-supplied-string experiment authenticated; it is a separate, composed piece of
evidence. The secondary local mTLS evidence closes the authenticated 2b obligation for
this authorized synthetic spike specifically. **This is NOT production identity-fabric
validation and selects no technology** — single-host 127.0.0.1 loopback, throwaway
ephemeral CA, no production certificate authority, no external network, no long-lived key
material.

## 15. Every B1–B6 security pass condition (updated)

| Requirement | Result | Evidence |
|---|---|---|
| Protected metadata resolvable without content (H2) | **PASS** (both backends) | §16; SELECT list structurally excludes `content_text` |
| Authorization-constrained retrieval, no retrieve-then-filter (H3) | **PASS for S1 (both backends); FAIL for S2 (both backends)** | §12, §13 |
| Suppression before candidacy (H5) | **PASS** (SQLite; not re-verified on PostgreSQL this pass) | Original P7 |
| Exact-version lifecycle (H4) | **PASS** (schema supports it, SQLite scenario coverage) | Original P9 |
| Materialization bindings testable without rebuild (H6) | **PASS** (SQLite) | Original P9, P11 |
| Restore freshness / unknown fails closed (H7) | **PASS** (backend-independent logic) | Original P10 |
| Final revalidation is fresh re-eval, not TTL (H8) | **PASS** (SQLite) | Original P8 |
| No authorization per candidate (H9) | **PASS** (by construction) | Both backends: one bounded query, not N |
| ContextBundle never persisted (H10) | **PASS** (structural) | Unchanged |
| R13 non-bearer boundary (H12) | **PASS**, experimental realization only | §14 |
| R14 raw domain latency measured | **PASS** (synthetic 10ms injection) | Unchanged |

---

# PART C — PLANNER / QUERY-SHAPE EVIDENCE

This section exists because §9's N+1 fix did NOT resolve the C-large latency finding the
way expected — the real cause is a separate, pre-existing query's execution plan, and that
distinction matters for interpreting the numbers in Part D correctly.

## 16. C-large PostgreSQL: the real dominant cost, precisely bounded

After the N+1 fix (§9), C-large `plan_metadata()` on PostgreSQL still costs **~2.8–3.1
seconds** per call — dramatically MORE than the original (N+1-contaminated) SQLite figure
of 133ms, and more than the post-fix SQLite figure (~180–220ms, §17). This needed its own
investigation rather than being attributed to "PostgreSQL is slower."

**Decomposition of one representative C-large `plan_metadata()` call** (component costs
are approximate — this is a wall-clock decomposition across several separately-timed runs,
not one atomically-instrumented call, per the accepted scope for this investigation):

| Component | Approximate cost | Method |
|---|---|---|
| Connection setup | Not on the critical path — `plan_metadata` reuses one already-open connection for the whole call; a bare `SELECT 1` on an idle connection measured p50=0.091ms, ruling out per-statement transport cost | Isolated microbenchmark |
| Initial candidate-selection query (3-table join) | **~2,525–2,858ms — the dominant cost** | `EXPLAIN ANALYZE` + wall-clock, same query, two measurements |
| Batched subject lookups (21 batches, post-§9-fix) | ~103–128ms total | Direct timing, two runs |
| Batched domain lookups (21 batches, post-§9-fix) | ~103–128ms total | Direct timing, two runs |
| Client-side row materialization / Python processing | Present but secondary (one isolated batch: ~14ms of ~37ms wall-clock was client-side); not separately re-measured for the full 21-batch run | Single-batch decomposition |
| **Total wall clock** | **~3,088ms** (sum of measured components for one full run) | Direct summation |

Per the accepted reporting convention for this investigation: **server-side query
execution — specifically the initial candidate-selection query's execution plan — is the
dominant identified contributor.** This candidate-selection query is a SINGLE SQL
statement that existed before and is unaffected by §9's batching fix.

### Root cause of the candidate-selection query's cost: a nested-loop plan choice

`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on the candidate-selection query (the
3-table join: `assertion_version` ⋈ `assertion_subject` ⋈ `assertion_domain`, filtered by
partition/lifecycle/subject/domain) shows:

```
Unique (rows=10100, time=2524.0ms)
  Sort (rows=11652, time=2520.7ms)
    Nested Loop (rows=11652, time=2467.7ms)
      Nested Loop (rows=10100, time=1837.1ms)          <-- dominant node
        Index Scan on assertion_version (rows=73964, time=114.2ms)
        Bitmap Heap Scan on assertion_subject (rows=0, loops=73964, time=0.015ms)  <-- looped 73,964 times
      Index Only Scan on assertion_domain (rows=1, loops=10100, time=0.055ms)
```

The planner chose a nested-loop join that probes `assertion_subject` **73,964 times** (once
per matching `assertion_version` row, before the subject/domain filters narrow the set),
even though each individual probe is fast. 73,964 fast probes accumulate to ~1.8 seconds.

**Corroboration observation (per Product Architect directive — session-local only, never
persisted, never applied to the actual spike query code):** the identical query was
re-run inside a transaction with `SET LOCAL enable_nestloop = off`, then rolled back to the
session default (confirmed via `SHOW enable_nestloop` = `on` after `COMMIT`). Result:

| | Baseline (default planner) | `enable_nestloop = off` (observation only) |
|---|---|---|
| Execution Time | 2,525.4ms | **134.5ms** |
| Plan | Nested Loop (73,964-iteration inner probe) | Hash Join (two-level, no per-row looping) |
| Returned rows | 10,100 | 10,100 (identical) |

**~19x speedup with a logically-identical result**, using a Hash Join plan instead. This
demonstrates the finding is **planner-choice sensitivity for this specific schema/data/query
shape** — almost certainly a cardinality-estimation mismatch (the baseline plan's
`Plan Rows` estimates were far below the `Actual Rows` observed at several nodes, a classic
underestimate that steers the planner toward a nested loop it would not choose with better
statistics).

**This is explicitly NOT generalized into a claim about PostgreSQL's architecture.** The
benchmark query and the harness were NOT modified to force this alternate plan — `run_bench.py`
still measures the default-planner cost (§17), because that is what an unmodified,
out-of-the-box PostgreSQL session would actually do with this data shape, and forcing a
planner setting in the benchmark would no longer be measuring "ordinary operation" per the
spike's own documented connection-configuration philosophy (`PG_SESSION_NOTES`,
`postgres_backend.py`). The nestloop-off result is recorded as **corroboration that the
cost is a planner decision, not an inherent property of the query or the data**, not as a
proposed fix.

---

# PART D — LATENCY / PERFORMANCE EVIDENCE (measured, post-§9-fix numbers)

**Latency composition convention (unchanged from original report):**
- **MEASURED**: actually timed on this host, this pass. Not network measurements.
- **CALIBRATED/INJECTED**: the ~111.57–112.24ms Home crossing sleep, replayed from Phase-1
  doc E7, not re-measured.
- **COMPOSED**: any total summing a MEASURED stage with a CALIBRATED stage.

## 17. p50/p95/p99 tables — SQLite (N=30 unless noted, warmup=3)

| Stage | Corpus | p50 (ms) | p95 (ms) | p99 (ms) | Status |
|---|---|---|---|---|---|
| metadata_planning | C-small | 0.253 | 0.427 | 0.432 | MEASURED — **SUPERSEDED: was 0.124ms, N+1-contaminated (§9)** |
| content_access | C-small | 0.057 | 0.064 | 0.065 | MEASURED |
| metadata_planning | C-medium | 10.631 | 16.802 | 21.496 | MEASURED — **SUPERSEDED: was 6.323ms, N+1-contaminated (§9)** |
| content_access | C-medium | 1.932 | 2.175 | 2.679 | MEASURED |
| metadata_planning | **C-large** | **204.505** | 218.256 | 221.883 | MEASURED — **SUPERSEDED: was 133.251ms, N+1-contaminated (§9); see below** |
| content_access | C-large | 27.223 | 69.532 | 70.259 | MEASURED |
| home_crossing | N/A | 112.091 | 112.240 | 112.240 | CALIBRATED (n=10, UNDERPOWERED) |
| domain_fanout n=1 | N/A | 11.427 | 12.470 | 12.470 | MEASURED (n=15, UNDERPOWERED) |
| domain_fanout n=3 | N/A | 12.348 | 13.190 | 13.190 | MEASURED (n=15, UNDERPOWERED) |
| domain_fanout n=5 | N/A | 12.364 | 12.814 | 12.814 | MEASURED (n=15, UNDERPOWERED) |
| r13_execution | N/A | 0.141 | 0.154 | 0.168 | MEASURED |

**On the C-large metadata-planning number going UP (133ms → 204ms) despite the N+1 fix
reducing query count 20,201 → 43:** this is real and reproducible (measured across 3
separate runs, 180–221ms range). §16 explains why for PostgreSQL (a specific, pre-existing
query's nested-loop plan choice); the SQLite side's smaller regression (a few ms at
C-small/medium, ~70ms at C-large) is attributable to the batched queries' larger individual
`fetchall()` result-materialization cost outweighing the round-trip savings for an
in-process engine — confirmed via profiling (§9), NOT re-investigated to the same depth as
the PostgreSQL case since SQLite has no query planner "wrong choice" of the kind found in
§16. **The original 133ms figure and its interpretation (approaching the Home-crossing
floor due to corpus-size-driven cost) are SUPERSEDED and should not be used for any
technology comparison** — they were an artifact of query count, not of index absence or
storage cost, and the corrected number reflects a different (partially harness-batching,
partially inherent) cost profile that has not been fully isolated to the same precision as
the PostgreSQL case in §16.

## 18. p50/p95/p99 tables — PostgreSQL S1 (executed for the first time this pass)

| Corpus | metadata_planning p50 | content_access p50 | Status |
|---|---|---|---|
| C-small | ~few ms (not separately benchmarked in the SQLite-only `bench_results.json` matrix; see §12 for correctness evidence at this size) | — | Not run through `run_bench.py`'s PostgreSQL-specific latency matrix (SQLite-only by design; see §21) |
| C-large | **~2,800–3,100ms** (§16 decomposition) | not separately isolated | MEASURED, dominant cost explained in §16 |

**No PostgreSQL equivalent of the SQLite C-small/C-medium latency matrix exists in
`bench_results.json`** — `run_bench.py`'s `barrier_evidence_for_size`/latency-stage
functions are SQLite-only by original design (§21), and this pass did not extend that
script (scope discipline: no benchmark-methodology changes without review, per the
governing directive for this pass). The C-large PostgreSQL number came from dedicated,
separately-run measurements (§16), not the bench matrix.

## 19. Content-access outcome distributions (allow/deny/no-content), SQLite

N=200 each, Home latency injection disabled.

| Path | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| Allow | 1.161 | 1.461 | 1.858 |
| No-content | 1.122 | 1.559 | 1.796 |
| Deny | 1.151 | 1.629 | 2.086 |

**Corrected interpretation.** The original prose claimed a stable allow/deny timing
separation; these measurements do not re-establish that claim. The three distributions
overlap substantially across their full p50/p95/p99 range (Allow p50 1.161 vs. Deny p50
1.151; Allow p95 1.461 vs. No-content p95 1.559 vs. Deny p95 1.629; Allow p99 1.858 vs.
No-content p99 1.796 vs. Deny p99 2.086) — these localhost, no-Home-latency-injection
measurements neither establish a stable timing oracle between the three outcomes nor rule
one out. The absolute figures are also lower than the original report's ~5.7–7.5ms,
likely reflecting host variance / prior warm-up conditions between runs, which further
undercuts treating either run's numbers as a settled distributional claim.

**Product Architect disposition:** further evidence required before runtime approval —
not a Technology Gate condition. See the dedicated subsection below (§21) for the full
disposition and what future timing evidence would need to show. **No technology-selection
consequence follows from these measurements** — the mitigation, if one is needed, is
application/orchestration-level and does not discriminate between S1-SQLite and
S1-PostgreSQL.

## 20. P13 — B4 cleanup contention, two-phase methodology, BOTH backends

Methodology (P13-R reads / P13-W writes, sequential foreground + one bounded background
cleanup writer) unchanged from the original report's accepted design — see
`bench/contention.py` module docstring for the full rationale.

### SQLite (S1-SQLite) — classification: **PASS**, order-effect CONFIRMED STABLE

Single-pair measurement (200 samples per phase, post-§9 harness):

| Phase | p50 (ms) | p95 (ms) | p99 (ms) | busy/timeout/err |
|---|---|---|---|---|
| Read baseline | 12.376 | 16.492 | 50.678 | 0/0/0 |
| Read cleanup-active | 19.454 | 22.219 | 58.153 | 0/0/0 |
| Write baseline | 0.066 | 0.125 | 0.184 | 0/0/0 |
| Write cleanup-active | 0.057 | 0.107 | 0.155 | 0/0/0 |

Read p95 delta: +5.727ms (ratio 1.347). Write p95 delta: -0.018ms (ratio 0.856, i.e.
noise-level, no material write contention observed).

**Canonical-value note (Gate closure record hygiene).** The numbers in this table and in
the order-effect table below are the **canonical** S1-SQLite P13 values. The committed
`bench/report_data/p13_two_phase_contention.json` does not match them. That file was
written in commit `77bfb03`, before the §9 N+1 fix and before the PostgreSQL pass, and was
never regenerated. It shows read p95 25.944 → 32.455 ms (+6.511 ms, ratio 1.251) and marks
PostgreSQL "NOT EXECUTED". It is now annotated `SUPERSEDED — NOT CANONICAL` and keeps its
original numbers for traceability. **The mismatch has no decision impact:** both runs
classify PASS with 0/0/0 busy/timeout/error and a bounded read-p95 increase of about 6 ms.

**Order-effect symmetry check** (4-run alternating baseline/active/baseline/active, same
corpus/workload/sample count, requested specifically because the PostgreSQL side showed an
inversion — see below):

| Run | Condition | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|
| 1 | baseline | 11.935 | 15.227 | 18.120 |
| 2 | cleanup-active | 19.131 | 22.874 | 24.126 |
| 3 | baseline | 11.576 | 14.125 | 16.563 |
| 4 | cleanup-active | 18.392 | 22.065 | 25.074 |

**Baseline and active each cluster tightly regardless of sequence position** (baseline:
11.58–11.94ms, ~3% spread; active: 18.39–19.13ms, ~4% spread). The ~60% relative slowdown
under cleanup contention is directionally reproducible and NOT order-dependent.
**Classification: PASS — a valid, order-independent two-phase contention measurement.**

### PostgreSQL (S1-PostgreSQL) — read-phase classification: **UNKNOWN — ORDER-CONFOUNDED**

Two independently-run single-pair measurements exist (200 samples per phase each), and
they DISAGREE IN DIRECTION:

| Run | Read baseline p50 | Read cleanup-active p50 | Direction |
|---|---|---|---|
| First measurement | 80.548ms | 28.999ms | active FASTER than baseline |
| Second measurement (independent re-run) | 79.511ms | 158.357ms | active SLOWER than baseline |

**Order-effect check** (4-run alternating baseline/active/baseline/active, same
methodology as SQLite above):

| Run | Condition | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|
| 1 | baseline | 120.490 | 146.500 | 159.871 |
| 2 | cleanup-active | 149.785 | 191.568 | 208.949 |
| 3 | baseline | 88.023 | 118.440 | 124.742 |
| 4 | cleanup-active | 40.955 | 64.070 | 72.486 |

**Same-condition runs vary by up to ~3x within this single sequence** (baseline:
88.0–120.5ms; active: 41.0–149.8ms), with a dominant monotonic downward trend across ALL
FOUR runs regardless of condition — consistent with warm-up/cache effects (buffer cache,
connection/plan state) outweighing whatever contention signal the baseline/active
alternation is meant to isolate.

**Classification: the read-phase contention result is UNKNOWN — INSUFFICIENT EVIDENCE /
ORDER-CONFOUNDED.** Neither single-pair measurement above should be read as evidence that
cleanup contention makes PostgreSQL reads faster OR slower — both are historical
observations preserved for traceability, not evidence of a real effect. **P13's original
purpose (Phase-1 §8.3/§16.5: is this the decisive SQLite-vs-PostgreSQL discriminator) is
NOT answered for PostgreSQL reads by this spike.** A trustworthy PostgreSQL P13-R
measurement would need either a longer warm-up period before the baseline phase, or a
methodology that separates warm-up decay from contention effect (e.g. many short
alternating windows averaged, rather than two large sequential blocks) — not attempted
here, left for a future pass if this remains decision-relevant.

**Corrected §17 framing (this pass).** SQLite P13 answered the contract question its
cleanup-contention experiment exists to answer: single-writer cleanup contention is
measurable but bounded in the tested workload, with no busy/timeout/error failures —
**PASS**. PostgreSQL P13-R remains genuinely **UNKNOWN — ORDER-CONFOUNDED**, but this is
**not a universal prerequisite for entering Technology Gate selection**. The relevant §17
criterion is **item 6** — the selected realization must meet the B6 §18A.8 latency
targets, or those targets must be revised on measured evidence — so if S1-PostgreSQL is
the realization ultimately selected, this UNKNOWN is unresolved evidence that must be
addressed under item 6 before the Gate can close *for that selection*. §17 item 9 requires
only that a shape and version-specific realization be selected with version-specific
verification; it does **not** require a fair SQLite-vs-PostgreSQL comparative P13 result,
so item 9 is not blocked by this UNKNOWN at all. (An earlier framing of this finding
incorrectly tied the PostgreSQL P13-R UNKNOWN to item 9 and to a "fair comparison"
requirement between the two realizations that §17 does not state; see the corrected §25
below.)

**Write-phase data** (baseline p50=1.373ms, cleanup-active p50=1.525ms; second measurement
1.298/1.368ms) is small in absolute terms and did not show the same order sensitivity in
either measurement — reported at face value, though it was not independently
order-checked with the same 4-run methodology as reads.

**Classification: S1-PostgreSQL — read phase UNKNOWN — ORDER-CONFOUNDED; write phase PASS
(both measurements consistent, small absolute magnitude, no busy/timeout/error).**

busy/timeout/error counts: 0/0/0 across every PostgreSQL P13 run, every phase, in both
measurements.

---

# PART E — UNCHANGED FROM ORIGINAL REPORT

## 21. R14, R13-A/B, allow/deny timing side-channel, PA timing disposition, teardown

R14 and the base R13-A/B split are not re-executed or re-investigated this pass; findings
preserved as originally reported, with the R13-B line updated for this pass's closure
test:
- R14 raw domain-read isolation: measured (`bench/report_data/r14_domain_read.json`), real
  but synthetic 10ms base latency injection, not a real domain service measurement.
- R13-A (crypto proof-of-possession): PASS. R13-B (transport-identity, primary in-process
  experiment): UNKNOWN — INSUFFICIENT EVIDENCE, unchanged by construction (`classify_r13()`
  not modified). R13-B (secondary local mTLS experiment, correction 7): PASS. **This pass
  additionally closes §16.7 condition 5 at the spike's experimental scope** via the new
  end-to-end transport-authenticated P12 case 2b closure test (§14) — a composed result
  building on the existing mTLS harness and holder-of-key verifier, not a change to either.
- Allow/deny/no-content timing separation: present, not remediated (see §19 for this
  pass's re-measured, smaller-magnitude figures and corrected interpretation).
- Teardown: `teardown.py` unchanged; this pass additionally created and must drop the
  disposable `olin_knowledge_gate_spike` PostgreSQL database (not automated by
  `teardown.py`, which only handles SQLite files and a `spike_kn` schema drop — the
  database-level drop is a manual operator step, see §26).

### Product Architect disposition: timing side-channel

**TIMING SIDE-CHANNEL: REQUIRES FURTHER EVIDENCE — NOT A TECHNOLOGY-SELECTION BLOCKER.**

Reason:
- It is required acceptance evidence under PA-10d / B6.
- It is not one of §16.7's eight Gate pass conditions.
- It is not a §18A.11 technology disqualifier.
- The mitigation, if the further evidence shows one is needed, is
  application/orchestration-level and does not discriminate between S1-SQLite and
  S1-PostgreSQL.

It **must** be closed before Knowledge runtime implementation approval — it is a
pre-runtime-approval obligation, not a precondition for entering Technology Gate
selection.

**Future required timing evidence (not run in this pass):**
- allow / deny / no-content, measured under calibrated Home latency enabled (this pass's
  §19 measurements have Home latency injection disabled)
- compare full distributions, not averages
- explicitly determine whether timing reveals information beyond already-visible response
  semantics
- if stable leakage remains, choose and test an application-level mitigation under PA-10d

---

# PART F — REMAINING UNKNOWNS

## 22. What this pass answered from the original report's open questions (§19)

1. **"Is S2/FTS5's barrier failure SQLite-specific, or does PostgreSQL's GIN path deserve
   a fair test?"** — **Answered: NOT SQLite-specific.** PostgreSQL's `tsvector`/GIN
   mechanism shows the same drive-order failure with the tested query shape (§13).
2. **Allow/deny timing separation** — re-measured, smaller magnitude this pass (§19), still
   unremediated, still needs Product Architect interpretation on whether it matters given
   the dominant network floor.
3. **C-large metadata-planning cost approaching the Home-crossing floor** — **superseded
   premise.** The original 133ms figure was an N+1 artifact (§9); the corrected picture is
   more nuanced (§16: one specific pre-existing query's planner choice, not a
   corpus-size/index-absence story) and does not support the original interpretation
   either way.
4. **R13's transport-identity simulation fidelity** — **partially closed this pass.** The
   §16.7 condition 5 end-to-end transport closure test (§14) demonstrates the composed
   mechanism (transport-derived identity + Ed25519 holder-of-key) fails closed on the
   decisive case 2b arm, at the spike's local-mTLS experimental scope. What remains open:
   this is not evidence about a production identity fabric, service mesh, or key
   distribution — only that the mechanism, composed, behaves correctly in a single-host
   loopback harness. The primary in-process `R13-B` claim (`classify_r13()`) is unchanged
   and stays UNKNOWN by construction.

## 23. What remains genuinely UNKNOWN after this pass

- **P13 read-phase SQLite-vs-PostgreSQL comparison** (§20) — the decisive discriminator
  Phase-1 §14.1 asks for is NOT established for PostgreSQL; order-confounded. This is
  relevant evidence under §17 item 6 (latency targets) if S1-PostgreSQL is the realization
  selected; it is not a prerequisite for entering selection itself (§20, §25).
- **S2-PostgreSQL disposition beyond the tested query shape** — untested whether a
  differently-constructed barrier query (materialized CTE, different join hint) could
  express the barrier correctly on PostgreSQL; this spike tested one shape only, mirroring
  what was tested on SQLite.
- **Whether the C-large nested-loop planner choice (§16) is reproducible on a different
  PostgreSQL instance/version/statistics state** — observed on exactly one instance, one
  data load; not confirmed as a general property of this schema shape.
- **PostgreSQL S1/S2 latency at C-small/C-medium** — only C-large was decomposed in detail;
  no equivalent bench-matrix entries exist for the smaller sizes on PostgreSQL (§18).
- **Timing side-channel** (§21) — requires further evidence before Knowledge runtime
  implementation approval; not a Technology Gate blocker (§21 PA disposition).
- The primary in-process R13-B claim (§14, §21 — unchanged, still UNKNOWN by construction),
  R14 real domain measurement, and generator cross-validation.

## 24. Whether any B1–B6 contradiction emerged

**No**, unchanged from the original report's conclusion. Every failure or limitation found
this pass (S2 on both backends, the P13 order-confound, the C-large planner-choice finding)
is evidence Phase-1 anticipated needing measurement to resolve — none requires reopening
B1–B6. The S2-PostgreSQL FAIL is the same CONDITIONAL outcome Phase-1 §14 explicitly
allowed for, now confirmed on a second backend.

## 25. Whether the empirical evidence is sufficient to begin final Technology Gate selection

**These are two different questions, and this report previously ran them together:**
*evidence sufficient to ENTER final Product Architect selection* is not the same claim as
*the Technology Gate is CLOSED*. This section answers the first question. Closing the Gate
(§17 items 1–9, all of them, for whichever realization is ultimately selected) is a
separate, later determination the Product Architect makes once a realization is chosen and
its applicable §17 criteria are satisfied.

**Yes — empirical evidence is now ready for final Product Architect Technology Gate
selection, subject to the selected realization satisfying its applicable §17 criteria
once chosen.** Against Phase-1 §17's acceptance criteria, checked against what this pass
and the R13 closure test (§14) actually established:

- §16.7 condition 5 (the R13 non-bearer boundary holds) is now **MET at the spike's
  experimental scope** (§14) — the previously outstanding closure gap for case 2b over an
  authenticated transport is closed.
- §17 item 9 (selected shape, version-specific realization AND verification) requires only
  that a shape and version-specific realization be selected with version-specific
  verification — it does **not** require a fair SQLite-vs-PostgreSQL comparative P13
  result. Both realizations are executed and verified against this pass's synthetic
  workload; item 9 is not blocked by the PostgreSQL P13-R UNKNOWN.
- §17 item 6 (the selected realization meets the B6 §18A.8 latency targets, or those
  targets are revised on measured evidence) is the criterion the PostgreSQL P13-R
  UNKNOWN actually bears on (§20). **This is a per-realization criterion, evaluated after
  a realization is selected** — it is not a precondition for entering selection, but if
  S1-PostgreSQL is the realization chosen, this UNKNOWN is unresolved evidence that must
  be addressed under item 6 before the Gate closes for that choice.
- S2's disposition (§17 item 3) is now **FAIL on both tested backends** with the tested
  query construction — a closed question in the sense that both realizations were tested,
  not a question resolved in favor of native full-text on either backend. If S2-shaped
  access is a hard requirement for the selected shape, this is a real constraint on that
  selection, addressed at selection time rather than a blocker to starting selection.
- The C-large latency comparison (§16–§18) reveals a planner-sensitivity finding that was
  not anticipated by the original report and has not been investigated for reproducibility
  across instances/versions — relevant context for whichever realization is selected, not
  a selection blocker itself.
- The timing side-channel (§21) is a pre-runtime-implementation-approval obligation
  (PA-10d/B6), not a §16.7 Gate pass condition and not a §18A.11 technology disqualifier —
  it does not block entering selection.

**No technology has been selected by this report or this pass.** What remains before the
Gate can be considered CLOSED for whichever realization is chosen: if S1-PostgreSQL, a
P13 read methodology that separates warm-up decay from contention effect (§20) to satisfy
§17 item 6; if S2-shaped retrieval remains a candidate requirement, a second
S2-PostgreSQL query construction attempt with Product Architect review; and, before
Knowledge runtime implementation (regardless of which realization is selected), closure
of the timing side-channel evidence per the §21 PA disposition.

---

## 26. Teardown status (this pass)

- All SQLite backend instances used `:memory:` (no on-disk cleanup needed) except P13's
  concurrency tests, which use pytest's own `tmp_path` fixture.
- **PostgreSQL: the disposable `olin_knowledge_gate_spike` database and its `spike_kn`
  schema(s) were NOT dropped as part of this report-writing pass** — they remain in place
  pending the corrections/report-review cycle, in case further measurement is requested
  before closure. Dropping them is a single operator command
  (`DROP DATABASE olin_knowledge_gate_spike`) once no further PostgreSQL work against this
  spike is expected; not automated by `teardown.py` in this pass (out of scope for a
  report-rewrite pass per the governing directive — no further benchmark-methodology or
  harness changes without review).

---

# PART G — TECHNOLOGY GATE CLOSURE RECORD

## 27. Technology Gate closure record (2026-09-25)

This part records the Architecture Board's decision. It adds no measurement, reruns nothing
and reopens nothing. It interprets only evidence already in Parts A–F. PostgreSQL, S2, P13
and R13 are **not reopened**.

### 27.1 Selection

| | Decision |
|---|---|
| **Selected shape** | **S1 — relational canonical owner with structured retrieval** (Phase-1 §5.3, §6, §14) |
| **Selected realization** | **SQLite 3.41.2** (§3; `bench/report_data/bench_results.json` → `sqlite_version`) |
| **Not selected** | S1-PostgreSQL (not reopened; its P13-R UNKNOWN (§20) and C-large planner finding (§16) are recorded evidence, not open Gate work). S2 native full-text (FAIL on both tested backends, §13). S3a/S3b remain DEFERRED as Phase-1 §13.2 recorded. |

### 27.2 Phase-1 §17 acceptance criteria — disposition for S1 / SQLite 3.41.2

| # | Criterion (Phase-1 §17) | Disposition | Basis |
|---|---|---|---|
| 1 | TG-PA-1 … TG-PA-7 dispositions recorded | **PASS** | Phase-1 §18 |
| 2 | §16.8 spike report received | **PASS** | This report |
| 3 | Every §16.7 pass condition **met** | **PASS** for S1 on SQLite | §15. Condition 5 (R13) is met **at the spike's experimental scope** (§14) |
| 4 | `home_auth_round_trip_count` does not grow with `domain_call_count`, authorization unweakened | **PASS** | P1–P4 assert `== 2` at 0/1/3/5 domains (`scenarios/test_p1_p5_baseline_and_fanout.py`); R13 case 10 `== 2` (§14) |
| 5 | R14 measured | **PASS** at spike scope (synthetic 10 ms injection); real measurement is pre-runtime obligation 5 (§27.4) | §21; `r14_domain_read.json` |
| 6 | B6 §18A.8 targets met at the corpus sizes that matter | **PASS — accepted for Technology Gate selection on conservative composed evidence.** Direct warm/cold end-to-end measurement remains a **REQUIRED PRE-RUNTIME obligation** (§27.4) | §27.2.1 |
| 7 | No B6 §18A.11 disqualifier applies to the selected shape | **PASS** | §12, §15 (no per-candidate authorization, no global-retrieve-then-filter, suppression before candidacy, bindings testable without rebuild, crossings flat, lazy expansion). S2's barrier failure disqualified S2, which is not selected |
| 8 | Protected metadata resolvable without content (R2); bindings testable without rebuild | **PASS** | §15 (H2, H6) |
| 9 | Shape **and** version-specific realization selected, with version-specific verification | **PASS** | §27.1. All SQLite evidence in this report was produced on 3.41.2 (§3), re-verified against the same base interpreter at closure |
| 10 | B1–B6 remain unamended by the selection | **PASS** | §24. No contradiction emerged |

#### 27.2.1 Item 6 — conservative composed evidence

The composition sums per-stage **p95s**, which overstates the true combined p95. It uses
**two** calibrated Home crossings at p95 (2 × 112.240 ms) and the worst measured fan-out
p95 (13.190 ms, n=3). All inputs are from §17 and use the tested SQLite configuration.

| Corpus | metadata p95 | content p95 | 2 × Home p95 | fan-out p95 | R13 p95 | **Composed p95** | Target |
|---|---:|---:|---:|---:|---:|---:|---:|
| C-small (realistic first year) | 0.427 | 0.064 | 224.480 | 13.190 | 0.154 | **≈ 238 ms** | ≤ 500 |
| C-medium (mature multi-year, ~50× realistic) | 16.802 | 2.175 | 224.480 | 13.190 | 0.154 | **≈ 257 ms** | ≤ 500 |
| C-large (*deliberately beyond any realistic corpus*, Phase-1 §16.3) | 218.256 | 69.532 | 224.480 | 13.190 | 0.154 | ≈ 526 ms | not a size that matters |

The same composition at p99 gives ≈ 262 ms at C-medium, against a ≤ 800 ms target. B4
cleanup contention adds about 6 ms of read p95 (§20 canonical). The realistic sizes leave
more than 240 ms of headroom against the p95 target.

C-large exceeds 500 ms only on the deliberately pessimistic sum-of-p95s. It is recorded
here openly because it marks where structured retrieval starts to approach the target,
which is the evolution trigger Phase-1 §13.3 requires. It does not bear on item 6, which is
scoped to "the corpus sizes that matter".

**Why this is composed rather than measured:** the Home crossing is CALIBRATED/INJECTED
(Phase-1 E7), not measured on a realistic topology, and no warm/cold end-to-end pre-LLM
orchestration run exists (§17 composition convention). That limitation is what §27.4 item 2
carries forward.

### 27.3 SQLite configuration — selected vs tested vs production

| | Value | Status |
|---|---|---|
| **SELECTED** | **SQLite 3.41.2** as the S1 relational canonical-owner realization | Selected by this Gate |
| **EMPIRICALLY TESTED CONFIGURATION** | `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000` | The configuration all SQLite evidence in this report was measured under. **Not part of the selection** |
| **PRODUCTION DURABILITY CONFIGURATION** | — | **NOT YET APPROVED BY THIS GATE** |

**Reason:** B4 requires suppression to be a **durable** positive record that commits
immediately (B4 §1, principle 1). In WAL mode, `synchronous=NORMAL` does not sync the WAL
at every commit. The most recent committed transactions can therefore be lost on power
loss or OS crash. An application crash does not lose them. So the tested configuration is
not shown to satisfy B4's durability requirement, and this Gate does not claim it does.

**Before runtime implementation approval**, the implementation must do one of the
following:

- choose and test a durability configuration that satisfies B4 (for example, evaluate
  `synchronous=FULL`), re-validating **only** the minimum affected
  performance/contention evidence: the P13 write/cleanup path and the §27.2.1 composition
  inputs it touches; or
- provide an equivalent durable control-state mechanism that satisfies B4.

### 27.4 Pre-runtime obligations (carried forward, not discharged by this Gate)

All six must be resolved before Knowledge runtime implementation approval.

1. **Production durability mode or mechanism satisfying B4.** Required decision per §27.3.
2. **Direct warm/cold end-to-end latency confirmation.** Measure warm and cold pre-LLM
   orchestration end to end, on a realistic topology, with the selected runtime
   realization. This confirms item 6 by direct measurement. It is **not run now**.
3. **Timing side-channel closure.** Per the §21 Product Architect disposition (PA-10d / B6).
4. **Production R13 mechanism.** §14 established the non-bearer boundary only at the
   spike's local-mTLS experimental scope. The production identity fabric, key distribution
   and the §11.4.1 binding realization remain pre-runtime work.
5. **Real R14 / domain measurement.** The spike's R14 used a synthetic 10 ms domain latency
   injection (§21). An actual applicable domain-service read must be measured on the
   realistic topology.
6. **Restore-freshness realization.** B4 C1 requires a concrete anti-resurrection /
   control-state freshness authority, or an equivalent freshness proof. The spike verified
   fail-closed behavior when freshness cannot be proven (§15, H7). It did not select or
   implement the production mechanism.

### 27.5 What closing the Gate does not authorize

Closing the Technology Gate authorizes **no** implementation, migration, schema deployment
or production runtime (Phase-1 §17: selection is a separate decision from implementation
approval). The Process register remains OPEN independently. B1–B6 remain RESOLVED and
unamended.

**Teardown:** the disposable PostgreSQL database `olin_knowledge_gate_spike` is
intentionally **not** dropped by this closure record (§26). Dropping it is a separate
operator step.

### 27.6 Gate status

**TECHNOLOGY GATE CLOSED — SELECTION COMPLETE**

- **SQLite 3.41.2 is selected** as the S1 relational canonical-owner realization.
- **Six pre-runtime obligations remain** (§27.4):
  1. production durability mode or mechanism satisfying B4 (§27.3)
  2. direct warm/cold end-to-end latency confirmation
  3. timing side-channel closure
  4. production R13 mechanism
  5. real R14 / domain measurement
  6. restore-freshness realization
- **Closing the Gate does not authorize implementation, migration, schema deployment or
  production runtime** (§27.5).

---

**TECHNOLOGY GATE CLOSED — SELECTION COMPLETE: S1 / SQLite 3.41.2 (§27).**

**SPIKE EXECUTED AGAINST BOTH SQLITE AND POSTGRESQL, WITH KNOWN REMAINING GAPS (§23).**

**NO KNOWLEDGE RUNTIME IMPLEMENTED. NO PRODUCTION CHANGE.**
