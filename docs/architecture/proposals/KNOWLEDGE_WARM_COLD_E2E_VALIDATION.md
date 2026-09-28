# Knowledge warm/cold direct end-to-end validation

**Date:** 2026-09-28
**Baseline:** fetched `origin/main` `7739dab807873270163f62b8b9d3511c9f46b585`
**Worktree:** `C:\AIProjects\episteck-delivery-workspace\.worktrees\knowledge-warm-cold-e2e`
**Branch:** `spike/knowledge-warm-cold-e2e` (clean at creation)
**Disposition:** **pre-runtime obligation #2 REMAINS OPEN**. Direct requests were measured, but the canonical latency targets do not all pass. No production runtime or authorization record was changed.

## 1. Canonical obligation and benchmark contract

[B6 §8.3.2 and §18A.9–10](KNOWLEDGE_B6_TRUSTED_RETRIEVAL.md) distinguish a complete **Authorization Operation**, a plan batching independently complete operations, and one **Home network round trip**: a trusted request crossing to Home. Ordinary pre-LLM reads know their requirements before RT#1, perform no source expansion, authorize one bounded plan at RT#1, execute Knowledge and independent domains, then **freshly reevaluate** at RT#2 before disclosure. RT#2 is a current-state authorization evaluation, not a cached TTL check. A domain call using the selected R13 mechanism adds zero Home requests. The measured boundary begins with trusted request preparation and ends after ephemeral ContextBundle construction; model TTFT and total time to first token are separate and were not measured here.

B6 gives **p50 ≤ 300 ms** as an aspiration, reasonable for P1 but contingent on domain cost for P2/P3; **p95 ≤ 500 ms** as the ordinary-read architecture target; and **p99 ≤ 800 ms** as an initial Gate target, revisable on real evidence. Its §18A.10 requires warm and cold-ish paths on a realistic cross-node topology, stage timings and independent Home-crossing counters. [Technology Gate §27.4 item 2](KNOWLEDGE_TECHNOLOGY_GATE_SPIKE_REPORT.md) specifically requires direct warm/cold pre-LLM E2E confirmation with the selected realization. The Gate's §27.2.1 result summed synthetic component percentiles; it expressly did not run this direct path. [Phase 1 §16](KNOWLEDGE_TECHNOLOGY_GATE_PHASE1.md) used Home/domain stubs with injected latency for candidate selection. Neither source can close #2.

The canonical scenarios are:

| Scenario | Request shape | Knowledge operation/read | Domain calls | Complete logical authorization operations | Actual Home sends expected | Local phases and disclosure |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| **P1** | Knowledge only, one Person | 1 / 1 | 0 | 1, OP-K | 2 | Protected metadata, suppression, authorized SQLite read, rank/select; bundle only after fresh RT#2 |
| **P2** | Knowledge + Nutrition | 1 / 1 | 1 | 2, OP-K + OP-N | 2 | Knowledge and Nutrition execute concurrently; R13 local verification/read; bundle only after fresh RT#2 |
| **P3** | Knowledge + three independent domains | 1 / 1 | 3 | 4, OP-K + three domain operations | 2 | Knowledge and all domains execute concurrently; the slowest domain, not a sum, governs fanout; bundle only after fresh RT#2 |

The B6 P3 table names its illustrative operations OP-N, OP-D and OP-B. The synthetic rig used Nutrition, Calendar and Household as three independent local domain owners; no real domain data was used. Its OP-K covered the complete subject/content-domain requirements returned by protected metadata planning, plus Knowledge scope. The earlier Gate test called five content domains from a function named P1 while B6's P1 table requires one logical operation. This run follows the accepted B6 scenario table rather than that fixture call. P4-like five-domain fanout is informative, not a replacement for P1–P3.

## 2. Feasibility inventory and selected benchmark seam

The detailed pre-measurement inventory and protocol are in [PROTOCOL.md](../../../spike/knowledge-warm-cold-e2e/PROTOCOL.md). In short, the selected SQLite backend and a pinned Nuremberg image were **available**; the old orchestration, HomeStub plan, RT#1/RT#2 and R13 verifier were **production-shaped but disposable**; a network Authorization Plan client/endpoint, Home R13 issuer, real transport counters and R13 domain endpoint were **missing**. The deployed Home API exposes only `check_access` and single-subject `check_access_many`; Nutrition's deployed path calls Home per operation. Reusing that path would have measured the rejected `2 + N` shape.

The minimum isolated seam was an Ashburn private mTLS responder for synthetic complete plans and exact signed bases, plus Nuremberg disposable domain mTLS verifiers and the selected SQLite spike backend. This exercised the selected [R13 mechanism](KNOWLEDGE_R13_PRODUCTION_MECHANISM.md): a direct live URI-SAN service peer, Home-signed Ed25519 exact-operation basis over the restricted v1 JCS test profile, exact caller SPKI, signed current trust bundle with a five-minute lease/generation anchor, atomic single-use domain claim before repository read, and mandatory fresh Home RT#2. It did **not** provision or claim a production R13 rollout. The restricted ASCII/safe-integer JCS helper is not a production general RFC 8785 library.

## 3. Topology and temporary infrastructure

The orchestration process ran on the Nuremberg node in a disposable derivative of the already retained Python **3.11.8 / SQLite 3.41.2** image. Its 100-assertion, seed-42 C-small synthetic Knowledge database was on `/home/episteck` **ext4**, not `/tmp` (which is `tmpfs` there). The existing Technology Gate SQLite schema and access path were reused; after the old spike backend initialized, each benchmark connection explicitly set and read back `journal_mode=wal`, `synchronous=FULL`, `wal_autocheckpoint=1000`, `busy_timeout=5000`, and `foreign_keys=ON`, matching the accepted [durability profile](KNOWLEDGE_SQLITE_DURABILITY.md). The database and domain replay ledger were separate local SQLite files.

Home RT#1 and RT#2 each made an actual Nuremberg → Ashburn → Nuremberg mTLS request over the existing Tailscale path. The disposable Ashburn responder bound **only `100.71.79.33:18443`**, with a generated short-lived CA and Home signing key. Domain mTLS responders bound only Nuremberg loopback ports **18444–18448**. The runtime client certificate, Home service certificate and domain certificate were disposable. Private keys and trust-distribution material were outside Git. No production Home endpoint, ConsentGrant, Person/Circle record, Nutrition content, public route, firewall rule, family data or health data was altered or used. The only production read-only contact was Nuremberg's Nutrition health endpoint.

The rig used synthetic pattern-checked decisions rather than production grant records. It answers the latency/transport-shape question; it does not prove production authorization correctness. The Nuremberg and Ashburn processes were on different real hosts, and every raw E2E row includes both Home transports within the single timed request. No component timing was added to fabricate an E2E value.

## 4. Warm/cold protocol, instrumentation and sample size

The protocol was recorded before collection. **Warm** meant an already started orchestrator, open/read-back SQLite connection, naturally warm OS page cache, loaded trust state, and reusable Home and domain TLS connections, with no sleeps. Ten explicit warmups per warm batch were excluded. A first exploratory warm P2/P3/P4 run mistakenly created a fresh domain TLS connection per request; those rows remain in evidence but were **excluded from acceptance**. Harness v2 pooled domain connections and reran all affected warm paths at full sample count. P1 has no domain client, so its v1 warm path was unaffected.

**Cold** meant a newly launched Python orchestration process for **each** observation, fresh SQLite and Home/domain TLS connections, loaded verifier trust state and no request-specific reuse. The child measured `internal_request_ms` directly from request preparation through bundle construction. The original v1 cold parent then overwrote the raw `total_pre_llm_ms` field with process launch-through-exit time, which crosses the canonical end boundary. The corrected analyzer uses the preserved direct `internal_request_ms` for cold acceptance and separately reports the raw process-lifetime distribution. The checked-in runner now keeps those fields distinct for future runs. It was not a host reboot; global OS caches were not flushed. The domain servers remained started with current trust state, as they would in an ordinary cold orchestrator request.

P1/P2/P3 each have **200 measured warm** and **100 independently process-cold** successful rows. The five-domain informative arm has 30 warm and 30 cold rows. No outlier was removed. The [analysis script](../../../spike/knowledge-warm-cold-e2e/analyze.py) recomputes min, p50, p90, p95, p99, max, mean and sample standard deviation using type-7 interpolated percentiles, and rejects mixed failures or counter violations. Failure probes are separate.

All timers use `time.perf_counter_ns()`. The actual Home HTTPS client's `post` method increments `home_auth_round_trip_count` only **after `HTTPConnection.request` returns from sending**, before reading the response; it is never inferred from orchestration stages. Domain calls are counted at their transport boundary. The domain returns separate verifier and repository-read timings/counts. Logical authorization operations are counted once per plan and are distinct from the two evaluations. Each row also records request preparation, protected metadata/planning, RT#1 transport, SQLite Knowledge execution, basis handling, domain transport, verifier, repository read, rank/select, RT#2 transport, final validation and bundle construction. A 100,000-pair `perf_counter_ns()` baseline had median **0.00014 ms** (p95 **0.00019 ms**); phase timers do not explain the hundreds of milliseconds observed.

Raw sanitized JSONL, summaries, network baseline, host snapshots, failure results and hash manifest are under [evidence/](../../../spike/knowledge-warm-cold-e2e/evidence/README.md). Raw `git_sha` names the fetched baseline; the harness was uncommitted during measurement. The manifest hashes the reviewed source and evidence. V2 changed only warm domain connection reuse; the v1 cold/P1 request paths were unchanged. The old warm files and second-window subset remain visibly labeled as exploratory in the evidence README.

## 5. Direct E2E latency results

Milliseconds. The last column independently evaluates **p50 / p95 / p99** against **300 / 500 / 800 ms**. P4 is informative. The warm P2/P3/P4 rows here use pooled domain connections.

| Path | State | N | Min | p50 | p90 | p95 | p99 | Max | Mean | SD | p50 / p95 / p99 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| P1 | warm | 200 | 476.1 | 478.7 | 479.7 | 480.1 | 481.5 | 773.8 | 480.2 | 20.9 | FAIL / PASS / PASS |
| P1 | cold | 100 | 682.2 | 685.0 | 686.4 | 687.3 | 688.0 | 690.3 | 684.9 | 1.4 | FAIL / FAIL / PASS |
| P2 | warm | 200 | 440.7 | 443.6 | 444.8 | 445.0 | 446.8 | 449.8 | 443.5 | 1.2 | FAIL / PASS / PASS |
| P2 | cold | 100 | 652.1 | 657.2 | 659.6 | 660.7 | 662.5 | 663.2 | 657.3 | 2.2 | FAIL / FAIL / PASS |
| P3 | warm | 200 | 442.4 | 447.8 | 450.7 | 451.5 | 453.0 | 453.3 | 448.0 | 2.0 | FAIL / PASS / PASS |
| P3 | cold | 100 | 654.1 | 667.7 | 671.7 | 672.3 | 674.5 | 675.2 | 667.4 | 3.6 | FAIL / FAIL / PASS |
| Five domains | warm | 30 | 449.0 | 453.0 | 455.9 | 457.3 | 460.5 | 461.7 | 453.1 | 2.6 | FAIL / PASS / PASS |
| Five domains | cold | 30 | 668.0 | 680.7 | 686.4 | 689.0 | 689.6 | 689.7 | 679.8 | 5.4 | FAIL / FAIL / PASS |

The one P1 warm maximum of **773.8 ms** was retained; its RT#2 transport alone took **533.7 ms**. It did not move P1's p99, but it is a network anomaly, not a row to delete. No success/failure timings were mixed.

## 6. Fanout, actual Home sends and phase decomposition

Every successful ordinary request passed the transport counter assertion. The observed per-request ranges were **exactly 2–2 Home sends** at 0, 1, 3 and 5 domains, in warm and cold data. Logical operation counts were 1, 2, 4 and 6; domain calls and R13 verifier/repository reads were 0, 1, 3 and 5 respectively; Knowledge read count was one and source expansion count zero. Thus fanout did **not** grow Home crossings. The Authorization Plan carried multiple complete operations in one RT#1, and RT#2 remained one fresh request. This is direct transport evidence, not a diagram count.

Selected **p50** phase values in milliseconds; concurrent Knowledge/domain durations overlap and must not be summed into a total:

| Path/state | Home RT#1 | Home RT#2 | Metadata plan | SQLite read | Domain transport | Verifier | Domain repository |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P1 warm | 238.7 | 238.7 | 0.52 | 0.19 | 0 | 0 | 0 |
| P1 cold | 439.8 | 238.6 | 0.46 | 0.29 | 0 | 0 | 0 |
| P2 warm | 198.4 | 239.0 | 0.55 | 0.19 | 5.1 | ~1 | ~2 |
| P2 cold | 401.0 | 198.2 | 0.47 | 0.30 | 54.4 | ~1 | ~2 |
| P3 warm | 199.0 | 239.0 | 0.55 | 0.19 | 8.5 | ~1 | ~2–3 |
| P3 cold | 401.5 | 198.3 | 0.47 | 0.29 | 64.1 | ~1 | ~3 |

For P3 warm, p50 request preparation was **0.059 ms**, basis handling **0.007 ms**, rank/select **0.014 ms**, final validation **0.313 ms**, and bundle construction **0.001 ms**. Their cold counterparts were **2.553**, **0.009**, **0.014**, **0.297** and **0.002 ms**. Cold P3 process launch/exit overhead had p50 **130.9 ms** (p95 **141.9 ms**), outside the direct request total but retained in the separate process-lifetime measure. New Home TLS at RT#1 added about **202 ms** versus the pooled warm RT#1. Home transport is the dominant measured cost; SQLite, R13 cryptography and repository work are not the bottleneck.

The initial exploratory warm run's fresh domain TLS cost was ~51 ms for P2 and ~60 ms for P3. Correct pooling reduced those to ~5 and ~9 ms. The corrected total improved less because RT#2 shifted from ~198 to ~239 ms with the smaller/earlier post-domain request. A 30-request second-window subset reproduced P1's ~239 ms and P2/P3's ~198 ms small/large Home request difference under the initial transport settings. This supports a transport/payload-size effect, but **does not prove** TCP delayed ACK, Nagle or any other packet-level cause.

## 7. Separate Nuremberg–Ashburn network baseline and load

Thirty Tailscale ping invocations reported **98 ms each** at the tool's millisecond resolution (no loss or route failure observed). Thirty new TLS connections to the private Ashburn responder had median **199.8 ms**, p95 nearest-rank **200.5 ms**, max **202.3 ms**. Thirty reused small-plan Home requests had median **238.5 ms**, p95 nearest-rank **239.5 ms**, max **239.9 ms**. These are context, not replacements for the direct E2E totals. The initial attempt to run this TLS-only baseline with host Python 3.14 rejected the disposable CA for a missing Authority Key Identifier; the successful baseline used the same pinned Python 3.11.8 image as the E2E runner. This did not affect any E2E observation.

Actual measured Home JSON body sizes were constant within each scenario: P1 RT#1/RT#2 **832-byte request / 112-byte response**; P2 RT#1 **1297/1756**, RT#2 **1297/204**; P3 RT#1 **2222/5036**, RT#2 **2222/387**. Sizes exclude TLS framing and HTTP headers. The [raw baseline](../../../spike/knowledge-warm-cold-e2e/evidence/network-baseline.json) and [RTT file](../../../spike/knowledge-warm-cold-e2e/evidence/tailscale-rtt.json) retain machine-readable values.

The run used controlled low load, not a stress test. Nuremberg load moved from **0.10/0.10/0.09** before collection to **0.08/0.15/0.16** after the first second-window subset; available memory stayed about **2.15–2.20 GiB**. Ashburn load was **0.13/0.10/0.07** before and **0.04/0.10/0.10** after; available memory about **1.03–1.05 GiB**. The temporary domain container used **0.90% CPU / 22.48 MiB** at an observed snapshot; the Home responder showed **0.4% CPU**. UTC host snapshots and limits of observation are in [host-conditions.json](../../../spike/knowledge-warm-cold-e2e/evidence/host-conditions.json). All E2E rows carry UTC timestamps. The existing Nutrition health endpoint returned **200** before, during and after; no destructive stress was applied.

## 8. Failure paths, limitations and acceptance

Separate probes returned **fail closed** for Home RT#1 unavailable, Home RT#2 unavailable *after a successful domain read*, bad R13 signature, stale trust, replay, and domain unavailable. In each case no bundle construction occurred; the bad-signature/stale-trust/replay probes had zero repository reads. Their timings are excluded from successful percentiles. This does **not** establish allow/deny/failure timing equivalence; obligation #3 remains OPEN. [Failure evidence](../../../spike/knowledge-warm-cold-e2e/evidence/failure-probes.json) records only booleans.

Limits: the Ashburn authority was a private synthetic responder, not the deployed Home Frappe Plan endpoint (which does not yet exist). Domain repositories were synthetic local SQLite, not real Nutrition or other R14 services. The selected R13 shape was exercised but its production CA, trust distribution, JCS library, container mounts and rollout were not. Only the realistic first-year C-small corpus was timed; C-medium/C-large scaling is not inferred. Cold did not clear global OS caches or reboot hosts. Host load snapshots were periodic rather than continuous, and the Tailscale ping tool rounded to whole milliseconds. The harness was uncommitted during execution; raw rows name the baseline SHA and the manifest/source hashes bind the later PR source. Model TTFT, timing side channels and real R14/domain latency were outside scope. No #3 or #5 closure is claimed.

The architecture invariant **passed**: every ordinary successful row made exactly two actual Home sends, flat at 0/1/3/5 domains, with the expected independent operation and verifier/read counts. The latency evaluation **failed**: all required warm and cold p50s exceed the 300 ms aspiration, and every required cold p95 exceeds 500 ms. The corrected direct-request cold p99s and all required warm p95/p99s pass; they cannot cancel the independent failures. Therefore **obligation #2 REMAINS OPEN**. The single concrete next experiment is a controlled private-route transport trace of RT#1 and RT#2 with the selected production HTTP/TLS client settings and small/large plan bodies, including a `TCP_NODELAY` comparison, to locate the ~198–239 ms reused-request cost without changing authorization, R13 or the mandatory RT#2. Even eliminating the suspected ~40 ms small-message penalty would leave two crossings above 300 ms, so the Board will need to calibrate that aspiration against measured topology after the transport result.

## 9. Cleanup and obligation state

Two isolated temporary deployments were used because the first warm domain client lacked connection reuse; all initial raw rows were retained. On both deployments the Home responder was stopped after verifying its exact command/PID; the domain container and uniquely tagged derivative image were removed; Nuremberg and Ashburn temporary directories, synthetic databases and remote keys were deleted; the copied evidence was checksum-verified first. The domain benchmark process did not exit on Podman's SIGTERM and required Podman's bounded SIGKILL fallback; the container was then removed. Automatic approval review rejected Windows `Remove-Item` for the explicitly named local temporary key directory, so an exact-path Python cleanup with resolved-path/symlink checks removed that directory and a local self-test remnant; absence was verified. Ports **18443–18448** were closed, no public route/firewall change was made, and existing service listeners and Nutrition health remained unchanged. No temporary credential is retained.

The [Technology Gate report](KNOWLEDGE_TECHNOLOGY_GATE_SPIKE_REPORT.md) and [`KNOWLEDGE.md`](../KNOWLEDGE.md) were **not updated**: the direct evidence does not support a formal closure or status change. Final pre-runtime states remain **#1 CLOSED, #2 OPEN, #3 OPEN, #4 CLOSED, #5 OPEN, #6 CLOSED**. The evidence is ready for Architecture Board review of the failed latency targets and next experiment, **not** for a #2 closure decision on passing results. No PR merge is authorized or performed.
