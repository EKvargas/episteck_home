# Direct warm/cold pre-LLM latency protocol

This protocol was fixed before latency collection. It implements only pre-runtime
obligation #2. All identifiers and content are synthetic. It does not call the
production Home API or production domain repositories.

## Canonical contract

B6 §18A.9–10 defines ordinary reads as base retrieval with known requirements,
no source expansion, one bounded Home Authorization Plan evaluation (RT#1),
local Knowledge and independent domain execution, then one fresh Home
re-evaluation (RT#2) before an ephemeral ContextBundle is constructed. A Home
network crossing is one actual trusted request sent to the Ashburn Home
authority, independent of the number of complete authorization operations in
its plan. The pre-LLM timer starts with trusted request preparation and stops
after ContextBundle construction; model TTFT is separate. Accepted architecture
targets are p50 ≤ 300 ms (aspirational for domain paths), p95 ≤ 500 ms and
p99 ≤ 800 ms (initial, revisable from evidence).

| Scenario | Request | Knowledge reads | Domain calls | Logical authorization operations | Home crossings | Disclosure |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| P1 | Single synthetic Person, Knowledge only | 1 | 0 | 1 (OP-K) | 2 | After fresh RT#2 |
| P2 | Knowledge + Nutrition | 1 | 1 | 2 (OP-K, OP-N) | 2 | After fresh RT#2 |
| P3 | Knowledge + 3 independent domains | 1 | 3 | 4 (OP-K, OP-N, OP-D, OP-B) | 2 | After fresh RT#2 |

OP-K's complete requirement set includes the Knowledge scope and all candidate
subjects/content domains; the separately executed domain operation is also
complete. One domain call must have one allowed signed basis. The five-domain
P4 analogue, if run, is informative and uses six operations, two crossings.
The old `test_p1_p5_baseline_and_fanout.py` passes five `domains` to its P1
orchestration call, even though B6's P1 table requires one operation. This
probe follows B6's canonical table and reports that fixture discrepancy.

## Feasibility inventory before measurement

| Piece | State | Evidence / gap |
| --- | --- | --- |
| Knowledge orchestration harness | PRODUCTION-SHAPED BUT DISPOSABLE | `scenarios/orchestration.py` is synthetic and uses `HomeStub`; no Knowledge runtime exists. |
| Home API/client | AVAILABLE for legacy access; MISSING for this plan | `api.py` exposes `check_access` and single-subject `check_access_many`; no plan endpoint or R13 issuer. Nutrition's client calls those legacy methods. |
| Authorization Plan representation | PRODUCTION-SHAPED BUT DISPOSABLE | `home_stub/stub.py` has complete `AuthorizationOperation` and plan decisions. |
| RT#1 / RT#2 | PRODUCTION-SHAPED BUT DISPOSABLE | The spike has in-process Home evaluations, with fresh RT#2 semantics; no network plan service. |
| Selected SQLite access path | AVAILABLE as spike code and pinned image | `SQLiteKnowledgeBackend`; the Nuremberg validation image has Python 3.11.8 / SQLite 3.41.2. A persistent local benchmark DB must use the accepted FULL profile. |
| R13 basis and verifier | PRODUCTION-SHAPED BUT DISPOSABLE | `test_r13_production_shape.py` exercises signed exact-operation bases, peer URI SAN/SPKI, trust and replay via loopback TLS. Not deployed. |
| Actual Home transport client | MISSING for plan/R13 | Existing clients can only call legacy Home endpoints. A disposable HTTPS plan client must count actual sends. |
| Nutrition/domain endpoints | AVAILABLE legacy; MISSING for R13 | Nutrition API/MCP run on Nuremberg loopback, but invoke legacy Home checks. A disposable local mTLS endpoint must perform R13 verification and synthetic repository reads. |
| Tailscale/TLS topology | AVAILABLE | Nuremberg `100.81.4.57`, Ashburn `100.71.79.33`; Tailscale ping succeeded. Temporary HTTPS must bind only to Ashburn's tailnet IP. |
| Benchmark instrumentation/counters | PRODUCTION-SHAPED BUT DISPOSABLE | Old spike has phase timings and inferred HomeStub counts; direct transport counting and full phase timers are missing. |

The minimum isolated seam is an Ashburn private TLS responder that evaluates
synthetic complete operations, signs one exact R13 basis per allowed domain
operation, and freshly re-evaluates at RT#2. Nuremberg runs a disposable
orchestrator on the pinned SQLite image and local mTLS domain verifiers with
atomic replay claims. It uses no production authorization records, credentials,
family data, public route, or service port. If this seam cannot be deployed or
the verified peer identity/trust semantics cannot be preserved, do not collect
acceptance latency; report #2 OPEN.

## Measurement conditions

* **Warm:** one already started orchestration process; initialized persistent
  SQLite connection and naturally warm file/page cache; loaded trust state;
  reusable TLS Home **and domain** connections; no artificial sleeps. Exclude
  setup and explicit warmup requests. An initial exploratory run accidentally
  opened fresh domain TLS for every warm P2/P3/P4 request. Those raw rows are
  retained but excluded from acceptance; pooled reruns use harness v2.
* **Cold:** a new orchestration process for every observation, fresh SQLite
  connection and Home TLS connection, loaded trust state, no prior request
  specific state. OS page cache is left untouched. This is a process/connection
  cold boundary, not a host reboot.
* **Counts:** 200 successful measured warm requests and 100 independent cold
  requests per P1/P2/P3. Preserve outliers. Failure probes are separate.
* **Timing:** use `time.perf_counter_ns()` around the complete request and each
  phase. Record transport sends at the actual Home client request boundary,
  authorization operations separately, domain calls at domain transport, and
  verifier/repository counts at the domain server. Raw rows contain only metrics,
  scenario, iteration, timestamp, benchmark version, git SHA and topology.
* **Baseline:** record Nuremberg↔Ashburn RTT, fresh TLS setup, reused TLS
  request latency, RT request/response byte counts, and host load. These
  explain but never replace the direct E2E distribution.
* **Acceptance:** evaluate P1/P2/P3 and warm/cold independently at p50/p95/p99.
  Each successful ordinary request must have two actual Home sends; fanout
  must not raise that count. No component arithmetic is an E2E observation.
* **Failure arms:** RT#1 unavailable, RT#2 unavailable, bad R13 signature,
  stale trust, replay and domain failure must withhold disclosure. Their
  timings do not enter success percentiles. This does not close #3.

Remote components, keys, temporary databases, image and ports are removed
after collection; cleanup and production health are checked and recorded.
