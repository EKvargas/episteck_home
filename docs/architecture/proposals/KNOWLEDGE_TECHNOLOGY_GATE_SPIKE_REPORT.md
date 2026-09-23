# Knowledge Technology Gate — Empirical Spike Report

Status: **EVIDENCE REPORT — SPIKE EXECUTED AGAINST BOTH BACKENDS. NO TECHNOLOGY SELECTED.**

Authorized by: TG-PA-7 (`KNOWLEDGE_TECHNOLOGY_GATE_PHASE1.md` §18.1).

**Revision note (this rewrite):** the original version of this report covered a SQLite-only
run; PostgreSQL was NOT EXECUTED (no disposable instance available). This rewrite covers a
second execution pass against an already-available local PostgreSQL 15.8 instance (detected,
never provisioned, per the spike's own scope), plus corrections found and fixed during that
pass. **Numbers from the original SQLite-only run that were contaminated by a harness defect
(N+1 query pattern, §9) are marked SUPERSEDED below, not deleted** — the corrected numbers
replace them for any evidentiary purpose, but the superseded figures and why they were wrong
remain in this document for traceability.

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

## 14. R13 adversarial results (unchanged from original report)

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

Unchanged in kind from the original report (a small, measurable timing separation between
allow/deny paths exists, though the absolute figures here are lower than the original
report's ~5.7–7.5ms, likely reflecting host variance / prior warm-up conditions between
runs — reported for completeness, not re-analyzed for the timing-side-channel finding,
which is unchanged in substance: allow does strictly more work than deny).

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

## 21. R14, R13-A/B, allow/deny timing side-channel, teardown

Not re-executed or re-investigated this pass; findings preserved as originally reported:
- R14 raw domain-read isolation: measured (`bench/report_data/r14_domain_read.json`), real
  but synthetic 10ms base latency injection, not a real domain service measurement.
- R13-A (crypto proof-of-possession): PASS. R13-B (transport-identity): UNKNOWN —
  INSUFFICIENT EVIDENCE for the primary claim; PASS for the secondary local mTLS
  transport-identity experiment (correction 7).
- Allow/deny/no-content timing separation: present, not remediated (see §19 for this
  pass's re-measured, smaller-magnitude figures).
- Teardown: `teardown.py` unchanged; this pass additionally created and must drop the
  disposable `olin_knowledge_gate_spike` PostgreSQL database (not automated by
  `teardown.py`, which only handles SQLite files and a `spike_kn` schema drop — the
  database-level drop is a manual operator step, see §26).

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
4. **R13's transport-identity simulation fidelity** — unchanged, still open.

## 23. What remains genuinely UNKNOWN after this pass

- **P13 read-phase SQLite-vs-PostgreSQL comparison** (§20) — the decisive discriminator
  Phase-1 §14.1 asks for is NOT established for PostgreSQL; order-confounded.
- **S2-PostgreSQL disposition beyond the tested query shape** — untested whether a
  differently-constructed barrier query (materialized CTE, different join hint) could
  express the barrier correctly on PostgreSQL; this spike tested one shape only, mirroring
  what was tested on SQLite.
- **Whether the C-large nested-loop planner choice (§16) is reproducible on a different
  PostgreSQL instance/version/statistics state** — observed on exactly one instance, one
  data load; not confirmed as a general property of this schema shape.
- **PostgreSQL S1/S2 latency at C-small/C-medium** — only C-large was decomposed in detail;
  no equivalent bench-matrix entries exist for the smaller sizes on PostgreSQL (§18).
- Everything already listed as unchanged-UNKNOWN in §21 (R13-B primary claim, R14 real
  domain measurement, generator cross-validation).

## 24. Whether any B1–B6 contradiction emerged

**No**, unchanged from the original report's conclusion. Every failure or limitation found
this pass (S2 on both backends, the P13 order-confound, the C-large planner-choice finding)
is evidence Phase-1 anticipated needing measurement to resolve — none requires reopening
B1–B6. The S2-PostgreSQL FAIL is the same CONDITIONAL outcome Phase-1 §14 explicitly
allowed for, now confirmed on a second backend.

## 25. Whether the empirical evidence is sufficient to begin final Technology Gate selection

**No — the original report's negative answer stands, for updated reasons.** Against
Phase-1 §17's acceptance criteria:
- §17 item 9 (selected shape, version-specific realization AND verification) — both
  realizations are now verified, but §14.1's decisive P13 comparison remains
  order-confounded for reads (§20), so the two realizations are not yet FAIRLY compared on
  the dimension Phase-1 itself calls decisive.
- S2's disposition (§17 item 3) is now **FAIL on both tested backends** — a closed
  question in the sense that both realizations were tested, but NOT a question resolved in
  favor of native full-text on either backend; if S2-shaped access is required, neither
  backend's native mechanism passed with the tested query construction.
- The C-large latency comparison (§16–§18) reveals a planner-sensitivity finding that was
  not anticipated by the original report and has not been investigated for reproducibility
  across instances/versions.

**What would close the remaining gap:** a P13 read methodology that separates warm-up
decay from contention effect (§20); and, if S2-shaped retrieval remains a candidate
requirement, a second S2-PostgreSQL query construction attempt with Product Architect
review before any further tuning.

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

**NO TECHNOLOGY SELECTED BY THIS REPORT.**

**SPIKE EXECUTED AGAINST BOTH SQLITE AND POSTGRESQL, WITH KNOWN REMAINING GAPS (§23).**

**NO PRODUCTION CHANGE.**
