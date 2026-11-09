# KAP-2 two-host gate: decisions before execution

## Attempt 03 root cause and corrections (2026-11-09, local only)

**Root cause (reproduced, then fixed under TDD):** PyMySQL 1.2 negotiates unverified TLS whenever the server offers it ("PREFERRED" mode). MariaDB 11.4+ offers TLS by default; 10.11 does not. On Nuremberg's 11.8.6, the witness gateway's pinned unix-socket sessions were therefore TLS sessions, which nobody intended. In A5 the writer kill correctly broke the writer on the serving HTTP thread. On that thread, the first read on the reader pinned by the next recovery then failed with a spurious `BrokenPipe`. PyMySQL dropped the socket (the server logged `Aborted connection … gw_reader … error writing communication packets`), and the gateway closed admission: A6's 503. A5's final check hit the same failure but expected a deny, which masked it. Python 3.12 fails the same way, so the Python version was a red herring.

**Reproduction:** a local container replica of the witness host, defined in [replica/](replica/): Ubuntu 26.04.1, Python 3.14.4, `mariadb-server 1:11.8.6-5ubuntu0.1`, PyMySQL 1.2.3. It reproduced attempt 03 exactly: A6 FAIL at 112 requests, `Aborted_clients=3`, only `gw_writer11` left. `Com_kill=1` across the run rules out the gateway's own retire-KILL loop, because MariaDB counts statements inside procedures. See [LOCAL_VALIDATION.md](LOCAL_VALIDATION.md#attempt-03-root-cause-replica-2026-11-09).

**Corrections (each with a test that failed first):**

| Defect | Effect on a remote run | Correction |
| --- | --- | --- |
| Gateway sessions silently negotiated TLS on MariaDB 11.4+ | A6 FAIL (attempt 03) | `gateway.py`: `ssl_disabled=True`. The witness is socket-only by design. |
| The witness reply's header and body writes stalled behind Nagle and delayed ACK | About 45 ms added to every loopback call. Across hosts, a further round trip plus about 40 ms, inflating A10. | `witness_runner.py`: `TCP_NODELAY` on accepted connections. Loopback call p50 fell from about 50 ms to 5–6 ms. |
| A 2 s client timeout on the A9 witness DB restarts; MariaDB 11.8 took 1.9–2.5 s | A9 restore failed intermittently in the replica | `transport.py`: a 30 s bound **only** for `snapshot`/`restore`. All serving and recovery-transition calls keep 2 s. |

No pass criterion, request cap, path, port, credential route or retry rule changed.

**Latency feasibility: a decision for Erick before any attempt 04.** A read-only ping from Ashburn to Nuremberg's Tailscale address (direct path, 2026-11-09) measured an RTT of **min 95.6 / avg 99.3 / max 194.7 ms** over 30 packets. A10 times one Home `authorize()` per call, which contains exactly one witness round trip. So even with all corrections:

| A10 metric (ratified gate) | Physical floor on this topology | Expected |
| --- | --- | --- |
| Warm call p95 ≤ 100 ms | 1 RTT + about 5 ms local work ≈ 100–105 ms | Likely breach |
| Cold call p95 ≤ 100, p99 ≤ 200 ms | Half the cold calls open TCP and TLS 1.3 first: ≥ 3 RTT ≈ 290 ms | **Certain breach** |
| Warm pair p95 ≤ 200 ms | 2 RTT + local work + the runner's two evidence fsyncs inside the pair window ≈ 210–230 ms | Likely breach |
| Cold pair p95 ≤ 200, p99 ≤ 400 ms | ≥ 4 RTT ≈ 390 ms | **Certain p95 breach** |

An attempt 04 on Ashburn↔Nuremberg with the unchanged gate is therefore expected to pass correctness (A0–A9, A11) but fail A10. That is the gate rejecting a transatlantic synchronous witness, not a defect. Before authorizing, decide one of the following:
1. **Keep the gate and change the topology:** a witness host in Home's region, on a separate host and failure domain. The remote run then targets that host.
2. **Keep the topology and revise the gate:** a Board decision, for example RTT-relative or warm-only limits, recorded before the run.
3. **Run attempt 04 unchanged** to obtain the formal remote measurement, accepting the expected A10 failure and another Mealie window.

## Attempt 03 — authorized and stopped at A6 (2026-11-09)

**Authorization (Erick, 2026-11-09):** one disposable attempt at `56c7c3f7efc5ece30feecf903da996dd77053f95` between Ashburn (178.156.197.34) and Nuremberg (91.98.132.9, Tailscale 100.81.4.57, re-verified on the host at start). Operator Erick, no backup delegate. It approves the preparation steps, one test run, the marked restore and the cleanup listed below, the latency gate, unchanged A0–A11 criteria and the capacity checks. **Exception:** Mealie may be stopped for the run window, then restarted and health-checked.

**Result: rejected run, not retried.** Evidence and full diagnosis: [result.json](evidence/2026-11-09-two-host-attempt-03/result.json).

| Criterion | Outcome |
| --- | --- |
| Capacity | Without the exception, a read-only check failed (1,946 MiB available memory). With Mealie stopped, both gates passed immediately before start: 2,202,001,408 B available memory, 1,967,071,232 B free `/tmp`. Mealie was down 12:46:05–12:54:23 UTC, then healthy. |
| A0 | **PASS.** Exact pinned MariaDB 11.8.6 acquisition, then 13/13 preflight checks on each runner, including the Frappe 15.99.0 bench. No ACL was needed: `tailscale0` is accepted. |
| A1–A5 | **PASS** (106 requests). R2 rotation and account locking were correct on MariaDB 11.8 for 10 rotations. |
| A6 | **FAIL.** In the setup of `unknown_prepare_acknowledgement`, after a fresh recovery, the witness refused the ordinary grant `prepare` (HTTP 503, 0.689 ms). |
| A7–A10 | **UNEXECUTED.** No latency was measured. 112/400 requests in total. |
| A11 | Both runners recorded root removal. `verify_cleanup.py` passed on Nuremberg. Ashburn returned `complete=false` only because A9 never ran (no Frappe result); this is preserved, not converted into a pass. |

**Diagnosis (read-only, before SIGTERM):** the database never rejected the call: the only SQL `SIGNAL` was A2's expected probe, and the writer session executed nothing after connecting. The witness gateway's pinned **reader** session, opened by A6's recovery and pinged by `confirm_home`/`open_admission`, was gone about 100 ms later. `_require_open` then closed admission. **The root cause is not proven.** The same sequence passes locally on MariaDB 10.11 with Python 3.12; the remote witness ran MariaDB 11.8.6 with Python 3.14.4.

**Cleanup:** Nuremberg's transient account, home, MariaDB prefix and staging were removed. Ashburn's `kap2-probe` was retained, with its own group only, sudo denied and staging removed. No production bench, site, database, code or service changed apart from the recorded Mealie stop and restart.

**Next:** reproduce A5→A6 locally with MariaDB 11.8.6 and Python 3.14, and correct it under TDD. Then review the new exact commit and obtain a **new** authorization. This authorization is consumed.

## Decisions recorded 2026-11-07 (owner Erick, acting as Board)

| Decision | Disposition |
| --- | --- |
| Knowledge-only recovery amendment (contract §19) | **RATIFIED for v1.** Now [ADR-0014](../../docs/architecture/adr/0014-knowledge-authorization-recovery-incarnation.md), renumbered from the colliding 0010. Any witness restart, including a routine reboot, closes Knowledge and needs per-Person reauthorization. A later high-water design may supersede it. |
| Witness accountability | **Erick** is the accountable operator and credential custodian. **No backup delegate** (accepted risk for a personal/family deployment). Without the operator, the witness stays CLOSED and Knowledge denies. |
| KAP-2 latency screen (R5) | **Accepted as a pass/fail gate:** per-call p95 ≤100 ms / p99 ≤200 ms; synthetic pair p95 ≤200 ms / p99 ≤400 ms. See [README](README.md#latency-allocation--accepted-as-a-gate-2026-11-07). |
| One disposable remote run | Authorized and executed on 2026-11-09 at `56c7c3f`; it stopped at A6 (see above). A further attempt needs a new exact-SHA authorization. |

These decisions do not complete KAP-2. R2 and R3 (local proof), R4 (CIRCLE, production Home writers, RT#2 contexts, reauthorization interface, credential custody) and the two-host run stay open.

**Local R1/R6 follow-up:** the [validation record](../../docs/architecture/reviews/2026-10-24-knowledge-kap2-r1-r6-validation.md) describes the changed recovery handshake and retained-history check. Review the final new commit, including added recovery control calls, before deciding on any remote attempt. Prior exact-SHA authorizations do not cover it. Full production recovery proof and R2–R5 remain open.

**Review target:** consolidated PR #71's executable synthetic PERSON package. The 2026-11-07 section above records Board ratification, the operator appointment and the latency gate; this sheet still records no remote-run authorization.

**Current gate (2026-10-24):** both separately authorized attempts are stopped at A0, with no matrix execution (**0/400 attempts** each). The first at `bd21543a663c7997daa27e1e8f7569a6ba353ed5` failed the SQL-path check. The second at `6166594bd91482455440e8e938306769100136bd` passed that correction but failed because the pinned install script's help intentionally exits 1. Review the narrow [help-status correction](ACQUISITION_REVIEW.md#2026-10-24-help-status-correction) and [recovery review](../../docs/architecture/reviews/2026-10-24-knowledge-kap2-recovery-review.md), then authorize one **new** finite attempt at the exact corrected commit. The earlier experiment supervisor/delegate assignment was for that stopped attempt, not a permanent production appointment. This continuation records no new remote authorization.

The table below is the original 2026-10-24 request, kept for history. The first two rows are decided above.

| Decision | Requested disposition and consequence |
| --- | --- |
| Knowledge-only recovery amendment | **Decided 2026-11-07: ratified.** Original request: Board ratifies or rejects proposed contract §19 / ADR-0010 (now ADR-0014). If ratified, any witness restart, replacement, lost admission continuity or uncertain recovery closes Knowledge authorization, invalidates old Knowledge contexts, creates a new incarnation and quarantines previous Knowledge grants and Person self-activations. Users must explicitly reauthorize each chosen Knowledge permission with current authenticated authority; no bulk restoration occurs. Existing Home/Nutrition permissions and APIs continue under their present rules. The disposable gate may test the candidate before ratification, but production activation may not use it without the Board record. |
| Witness accountability | **Decided 2026-11-07: Erick, no backup delegate.** Original request: Erick names the accountable witness operator and backup delegate, with credential custody, host/service lifecycle, port/ACL, monitoring, backup provenance, incident closure, restore drill, evidence archive and cleanup responsibilities. No person is assumed appointed. The operator can close/recover infrastructure but cannot reauthorize as a Person. |
| One disposable remote run | **Erick: explicitly authorize the exact actions below** after reviewing the package, chosen Tailscale IP, operator/delegate, expected host capacity and proposed KAP-2 latency screen. This PR and prior cloud authorizations do not grant this remote execution. |

**Actions requiring that fresh remote authorization:** reuse and reverify the intentionally retained non-sudo Ashburn `kap2-probe` account; recreate Nuremberg's disposable non-sudo `kap2-probe` account through an administrator; obtain the exact pinned MariaDB archives on Nuremberg using the corrected `acquire_mariadb.sh` (download/extract only, no system installation); create isolated Python environments and a Frappe 15.99.0 bench on Ashburn; place the exact reviewed checkout and short-lived mTLS certificates in the named `/tmp` paths; temporarily allow Ashburn-to-Nuremberg Tailscale TCP `19442`; run two private socket-only MariaDB services, the Nuremberg mTLS listener and the Ashburn synthetic runner; make and restore **only** their marked physical datadir copies; create/remove one marked disposable Frappe site with synthetic Persons/grants; archive sanitized evidence; stop all test processes; remove Nuremberg's temporary account, bench, checkout, certificates, experiment staging and temporary ACL; retain Ashburn's account and verify its non-sudo boundary; verify experiment resource absence with `verify_cleanup.py`. The CA private key stays on the operator machine. No production Frappe bench/site, Home data, app code, API, main branch, systemd service, credential, migration or cloud resource may change.

**Required authorization record:** name the exact corrected PR head SHA, both named hosts and verified Nuremberg Tailscale IPv4, accountable operator and backup delegate; approve the above preparation, one matrix attempt, marked physical restore and disposal inventory; accept the predeclared screen below and unchanged A0–A11 criteria. Preserve the previously reviewed Nuremberg capacity gates: at least **1.75 GiB free `/tmp`** and **2 GiB available memory** immediately before starting, with the **1,232 MiB** planning allocation described in the acquisition review. A prerequisite failure stops the attempt; no automatic retry, alternate path, package version or acquisition method is authorized. A subsequent attempt requires another authorization. Board ratification is recorded (2026-11-07); production activation also needs KAP-2 completion.

**Budget decision (accepted as a gate 2026-11-07):** contract §13 has whole-path p95 ≤500 ms and initial p99 ≤800 ms, but no KAP-2 allocation. The KAP-2 screen is per-call p95 ≤100 ms / p99 ≤200 ms and synthetic-pair p95 ≤200 ms / p99 ≤400 ms, and any breach fails A10. These are not whole-path claims, and 30 pairs per temperature cannot establish a stable p99. Hard transport cutoff is 400 attempted requests, with no automatic retries.

**Reject the run** for any old permission allowing after restart/restore, uncertain allow, wrong principal crossing its route/DB boundary, generic protected-write bypass, reader/writer order inversion, unverified cleanup, missing Frappe compatibility, request-cap breach or incomplete evidence. A passing disposable PERSON run would still leave CIRCLE, full Home authority-source cutover, RT#1/RT#2 and later Knowledge/live gates open.

**Verify:** `rg -n 'Board:|Erick:|Actions requiring|Budget decision|Reject the run' spike/knowledge-kap2-two-host/DECISION_SHEET.md`.
