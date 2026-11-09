# Local validation of the two-host package

## Attempt 03 root cause (replica, 2026-11-09)

**Replica:** [replica/Containerfile](replica/Containerfile) rebuilds the attempt-03 witness host locally with podman: Ubuntu 26.04.1, system Python 3.14.4, the pinned `mariadb-server 1:11.8.6-5ubuntu0.1` packages and PyMySQL 1.2.3. [replica/loopback_matrix.sh](replica/loopback_matrix.sh) runs the witness inside the replica and the Home runner on the host (Python 3.12 / MariaDB 10.11), as in the real topology. No remote host was contacted except one read-only RTT ping (see the decision sheet).

| Run (witness in replica) | Result |
| --- | --- |
| Commit `be46ade`, unchanged | A6 **FAIL** at 112 requests, `Aborted_clients=3`, `Com_kill=1`, only `gw_writer11` left. Matches attempt 03 exactly. |
| Same, instrumented (MariaDB general log, failing exception chain) | The pinned sessions ran over TLS: every failing stack passes through `ssl.py`, and the new unit test reads `Ssl_version=TLSv1.3`. After A5's expected writer `BrokenPipe` on the serving thread, the next recovery's reader failed on its first serving-thread read (`BrokenPipe`), twice; the first was masked by an expected deny. The server logged `Aborted connection … gw_reader … (Got an error writing communication packets)`. |
| Same, gateway forced to `ssl_disabled=True` (monkeypatch) | All 11 executed steps PASS, 329/400 requests, `Aborted_clients=0`. |
| Fixed gateway, unchanged runner | A1–A8 PASS. A9 restore FAIL: the witness restart took 2,482 ms against the client's 2 s timeout. |
| Fixed gateway + `TCP_NODELAY` (monkeypatch) | All 11 executed steps PASS. Warm call p50/p95 **5.4/8.3 ms**, compared with about 50 ms before. |
| **Final checkout (all three corrections), uninstrumented** | **All 11 executed steps PASS**, 329/400 requests, `Aborted_clients=0`, witness `CLOSED` and both roots absent at cleanup. Loopback call p50/p95: warm **3.2/5.1 ms**, cold **5.3/7.6 ms**. Pair p95: 27.9 ms warm, 33.2 ms cold. Remote preflight A0 and Frappe A9 are remote-only and were not executed. These loopback numbers are not the two-host gate. |

**Bisect:** with the same MariaDB 11.8.6 under Python 3.12, both new gateway tests also fail, so Python 3.14 is not the cause. A stock MariaDB 10.11 offers no TLS, so the original tests passed there with and without the correction.

**Review follow-up (PR #125):** the gateway test fixture now makes every MariaDB offer TLS with a throwaway self-signed certificate, as 11.4+ does by default. A guard test, `test_fixture_offers_tls_like_mariadb_11_8`, proves that TLS is on offer.
- **On the standard 10.11 stack:** without the gateway correction, `test_pinned_sessions_never_negotiate_tls` now **fails** (`TLSv1.3`). The cross-thread failure itself only reproduces on the replica's OpenSSL 3.5 / MariaDB 11.8 stack.
- **Probes:** the witness runner's privilege probes (`PrivateDB.connect`) are now socket-only too. `test_witness_probe_sessions_never_negotiate_tls` failed first.
- **Replica image:** pinned by base-image digest and the Ubuntu snapshot archive of 2026-11-09, so it still builds after Ubuntu supersedes 11.8.6.
- **`loopback_matrix.sh`:** now propagates the Home runner's exit status. On every exit it keeps the witness logs and removes the container and certificates.

**TDD record:**
- **Gateway:** `test_serving_thread_survives_writer_loss_and_later_recovery` and `test_pinned_sessions_never_negotiate_tls` failed in the replica (`GatewayClosed` from the reader ping; `('TLSv1.3',)`). They pass after `ssl_disabled=True`.
- **Transport:** `test_warm_rpc_has_no_small_write_stall` (median ≥ 20 ms) and `test_disposable_restarts_outlast_the_serving_timeout` (snapshot timed out at 2 s) failed locally. They pass after `disable_nagle_algorithm` and the restart-only timeout.

**Suites (final, run strictly in sequence):**
- **Local, Python 3.12 / MariaDB 10.11:** the four KAP-2 spike packages pass **106/106**. The Home contracts, typed-policy, authority and disconnected-inertness tests pass **55/55**.
- **Replica matrix via `loopback_matrix.sh` on the pinned image:** all 11 executed steps PASS, 329/400 requests, script exit 0, no leftover container or certificates. Loopback warm call p50/p95: 3.1/5.8 ms. A forced certificate failure exits 1 and cleans up.
- **Overlap failure:** an earlier overlapping run gave one setup **error** (`mariadb-install-db` hit a shared-`/tmp` temp-table collision, `Unknown table 'mysql.tmp_proxies_priv'`) while a replica matrix ran alongside. The overlapping matrix failed the same way in its Home bootstrap. Both pass alone, so run them one after the other.
- **Replica:** the gateway suite passes 33/33. The two-host transport tests cannot run in the replica because its Python 3.14 *client* enforces strict X.509, and `certs.py`'s CA has no KeyUsage (`CA cert does not include key usage extension`). They fail the same way without these corrections. The real Home client is Ashburn's Python 3.12, so the run is unaffected. This is recorded as a follow-up.

```sh
podman build -t localhost/kap2-witness-replica:11.8.6 spike/knowledge-kap2-two-host/replica
spike/knowledge-kap2-two-host/replica/run_pytest.sh -q spike/knowledge-kap2-transactional-witness
HOME_PY=/path/to/venv/bin/python spike/knowledge-kap2-two-host/replica/loopback_matrix.sh
```

**R2/R3/R5 loopback (2026-11-07):** one fresh loopback run of the A1–A11 matrix on the final R2/R3 candidate, in WSL against real disposable MariaDB 10.11 with mTLS. The [R2/R3 validation record](../../docs/architecture/reviews/2026-11-07-knowledge-kap2-r2-r3-validation.md) has the full context.

- **Result:** all 11 executed steps `PASS`. Remote preflight A0 and Frappe A9 were not executed.
- **Requests:** 329 of 400 attempted, including 161 authorizations and 20 recoveries.
- **Latency gate:** `GATE_PASS` at both temperatures.

| Temperature | Call p95 / p99 | Pair p95 / p99 |
| --- | ---: | ---: |
| Warm | 51.8 / 53.5 ms | 119.8 / 184.5 ms |
| Cold | 53.1 / 53.4 ms | 120.0 / 120.9 ms |

Both roots were absent at cleanup, and witness admission ended `CLOSED`. An earlier run on this candidate failed A1 because of the privilege probe, which was then fixed (see the record). These are single-host loopback numbers: they are not cross-host latency and not the authorized two-host gate.

**Subsequent R1/R6 correction (2026-10-24):** see the [local validation record](../../docs/architecture/reviews/2026-10-24-knowledge-kap2-r1-r6-validation.md) and [structured evidence](evidence/2026-10-24-r1-r6/result.json). These changes stage admission through exact Home confirmation and retain known incarnation history. The new focused loopback mTLS regression exercises the recovery handshake and role isolation against two private MariaDB instances; its archived witness trace has 30 requests, three expected role denials, one expected CLOSED prepare denial and a CLOSED cleanup event. It is not another full A0–A11 run, Frappe control or latency screen. The previous evidence and measurements below are unchanged historical records.

**Latest continuation:** the [2026-10-24 help-check regression and recovery review](#2026-10-24-help-check-regression-and-recovery-review) follows both stopped remote preparation attempts. The 2026-10-10/12 loopback results below remain historical evidence. No local check establishes Nuremberg MariaDB 11.8 compatibility or two-host acceptance.

**Scope:** one fresh loopback run on 2026-10-10 using WSL Ubuntu, Python 3.12, real disposable MariaDB processes, mTLS and synthetic PERSON authority. This is local integration evidence, **not** the Ashburn–Nuremberg acceptance run. The remote preflight and mandatory disposable Frappe step A9 were unexecuted in this run. The consolidated PR #71 handoff records the earlier local Frappe 15.99.0 result separately.

## Reproduction

In an isolated Linux/WSL environment with `mariadbd`, `mariadb`, `mariadb-admin`, `mariadb-install-db`, Python 3.11+, PyMySQL and `cryptography` installed:

```sh
python certs.py --out /tmp/kap2-pr71-certs-local-02 --server-ip 127.0.0.1 --local
python witness_runner.py --root /tmp/kap2-pr71-twohost-local-w-04 --evidence /tmp/kap2-pr71-witness-local-evidence-04.jsonl --bind 127.0.0.1 --loopback-only --port 19442 --ca /tmp/kap2-pr71-certs-local-02/ca.crt --cert /tmp/kap2-pr71-certs-local-02/server.crt --key /tmp/kap2-pr71-certs-local-02/server.key
# In a second shell, with PYTHONPATH pointing at this checkout's apps/episteck_home:
python home_runner.py --root /tmp/kap2-pr71-twohost-local-h-06 --evidence /tmp/kap2-pr71-home-local-evidence-06.jsonl --witness-host 127.0.0.1 --port 19442 --ca /tmp/kap2-pr71-certs-local-02/ca.crt --serving-cert /tmp/kap2-pr71-certs-local-02/serving.crt --serving-key /tmp/kap2-pr71-certs-local-02/serving.key --recovery-cert /tmp/kap2-pr71-certs-local-02/recovery.crt --recovery-key /tmp/kap2-pr71-certs-local-02/recovery.key --local
```

The server was then stopped with SIGTERM. The named Home and witness roots were absent in their respective fsynced cleanup events. The local certificate directory is temporary and must be removed after inspection. Remote execution instead requires the exact paths, clean SHA preflight and bench specified in [README.md](README.md).

## Observed result

All 11 executed matrix steps passed: mTLS role/credential isolation and CLOSED start; synthetic grant/self, named DML bypass and ordinary note; dependency/issuer/expiry invalidation; reader-first and writer-first revocation; writer connection loss; unknown PREPARE and COMMIT acknowledgements; gateway restart; physical Home/witness restore with first-read denial and selected reauthorization; and the latency/request-count screen. The final run did not use the iterative `--reset-local` flag.

| Measure | Fresh loopback observation |
| --- | ---: |
| Attempted client requests / cap | 269 / 400 |
| Witness authorize requests | 161 |
| Expected transport errors / rejected TLS attempt | 2 / 1 |
| Warm individual call p50 / p95 / p99 | 46.915 / 49.927 / 50.537 ms |
| Warm pair p50 / p95 / p99 / max | 106.630 / 110.356 / 115.905 / 115.905 ms |
| Cold individual call p50 / p95 / p99 | 48.460 / 51.373 / 52.819 ms |
| Cold pair p50 / p95 / p99 / max | 107.726 / 116.786 / 189.142 / 189.142 ms |

The screen used 30 warm and 30 cold pairs, two calls per pair and exactly one witness request per call. “Cold” reset only the witness TCP/TLS connection before the pair. These loopback measurements do not establish a cross-host latency result or the unratified KAP-2 budget. At 30 pairs, p99 is effectively a maximum.

**Evidence and cleanup verification:** `matrix_summary` reported all 11 steps `PASS`, 269 attempts and request counts by operation, role and outcome. `home_cleanup` recorded `root_absent=true`; `witness_cleanup` recorded `root_absent=true` and admission `CLOSED`. After removing the marked local certificate directory, `verify_cleanup.py` returned `complete=true` for both sides; it also found the witness listener absent. The remote Frappe and cleanup checks remain requirements for the authorized two-host gate.

**Verify this record:** `rg -n '269 / 400|unexecuted|root_absent' spike/knowledge-kap2-two-host/LOCAL_VALIDATION.md`.

## 2026-10-12: acquisition correction and fresh loopback validation

The reviewed remote attempt at `bd21543a663c7997daa27e1e8f7569a6ba353ed5` remains **A0 failed, matrix unexecuted, 0/400 attempts**. This continuation performed no SSH or remote resource action. The six original package Python files (`certs.py`, `home_runner.py`, `preflight.py`, `transport.py`, `verify_cleanup.py`, `witness_runner.py`) were compared byte-for-byte after line-ending normalization against that baseline and are unchanged. The tracked acquisition command differs from the historical PR comment only in its bootstrap-SQL file check, as described in [ACQUISITION_REVIEW.md](ACQUISITION_REVIEW.md).

**Local environment:** WSL Ubuntu 24.04, Python 3.12.3, MariaDB `10.11.13-MariaDB-0ubuntu0.24.04.1`, PyMySQL 1.2.3 and pytest 9.1.1, using the existing `/home/d064974/kap2-twohost-venv-20261010` environment. No package installation or dependency acquisition was performed. Certificates were generated with OpenSSL; the CA and all test keys remained local and were removed after the run.

**Package check:** original shell filesystem-check block: **2 failed, 4 passed**, specifically MariaDB-layout acceptance and legacy-layout rejection failed. Corrected block: **6 passed**. The package's complete `python -m pytest spike/knowledge-kap2-two-host -q` run passed all six tests; `bash -n acquire_mariadb.sh`, Python compilation and `git diff --check` passed. The fixture tests exercise actual shell checks, not archive extraction, wrappers or MariaDB 11.8 runtime.

**Fresh integration result:** one local loopback run, no `--reset-local`, real private MariaDB on each logical side and mTLS on `127.0.0.1:19442`. All **11 executed steps PASS**, with **269/400 attempted client requests** and **268 witness HTTP requests** (the rejected anonymous TLS attempt appears only in the Home ledger). There were 161 authorize requests, two expected denied-role transport errors and one rejected anonymous TLS attempt. The latency screen made 120 authorizations: 30 warm and 30 cold pairs, exactly one witness request per call and two per pair.

| Measure | Warm | Cold |
| --- | ---: | ---: |
| Individual call p50 / p95 / p99 | 46.671 / 49.378 / 50.545 ms | 48.646 / 50.352 / 51.617 ms |
| Pair p50 / p95 / p99 / max | 100.863 / 107.049 / 107.238 / 107.238 ms | 104.630 / 107.015 / 107.137 / 107.137 ms |

**Committed evidence:** [structured result and exact local command arguments](evidence/2026-10-12-local-review/result.json), [Home JSONL](evidence/2026-10-12-local-review/home.jsonl) and [witness JSONL](evidence/2026-10-12-local-review/witness.jsonl). SHA-256: Home `86a929accab09f846d947cb4212c7b8331ccc8c61f77c9316cd94587d82a8d8b`; witness `0c71703d8cb5224fa37280bc9eaf65dccaf0b0410da4a15dff6f2b30da8c5d19`. JSONL contains synthetic step/request/timing evidence, with no keys or passwords.

**Local cleanup:** Home root `/tmp/kap2-pr71-twohost-local-h-review-20261012-01` and witness root `/tmp/kap2-pr71-twohost-local-w-review-20261012-01` were removed by their runners. The witness was stopped with SIGTERM and recorded CLOSED cleanup; `127.0.0.1:19442` had no listener. The exact marked certificate directory `/tmp/kap2-pr71-certs-local-review-20261012-01` was removed after its resolved path, marker and owner were checked. `verify_cleanup.py` returned `complete=true` for both logical sides. Earlier local artifacts and all historical branches/worktrees were preserved.

**Unexecuted:** remote exact-SHA/path/transport/bench preflight A0, mandatory remote Frappe 15.99.0 A9, Nuremberg's extracted MariaDB 11.8 runtime, two-host latency and remote cleanup. The local measurements remain KAP-2 policy/witness evidence with an unratified budget; they do not close KAP-2 or replace the new separately authorized two-host gate.

**Verify the committed evidence without another matrix run:**

```sh
python - <<'PY'
import hashlib
import json
from pathlib import Path

root = Path("spike/knowledge-kap2-two-host/evidence/2026-10-12-local-review")
result = json.loads((root / "result.json").read_text())
for name, expected in result["sha256"].items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
assert len(result["matrix"]["steps"]) == 11
assert set(result["matrix"]["steps"].values()) == {"PASS"}
assert result["matrix"]["request_counts"]["total"] == 269
assert all(side["complete"] for side in result["cleanup"].values())
print(json.dumps({"evidence_verified": True, "scope": result["scope"]}))
PY
```

## 2026-10-24: help-check regression and recovery review

**Scope:** local shell-fixture tests, help-only characterization, contract/policy unit tests and read-only review. No SSH, remote preparation, MariaDB package acquisition, database integration run, Frappe site, physical restore, matrix or latency measurement was performed. The 2026-10-12 second remote attempt remains A0 failed, matrix unexecuted and 0/400 requests.

Using the existing WSL Python 3.12.3 environment `/home/d064974/kap2-twohost-venv-20261010`, the six existing acquisition filesystem tests first passed. New tests executing the actual help-check tail produced **2 failed, 13 passed** before the shell correction: exit-1 valid help failed, and unexpected exit 0 succeeded. After requiring exit 1 and three recognizable usage markers, and adding two more incomplete-output cases, the complete package suite passed **17 tests in 2.73 s**. `sh -n acquire_mariadb.sh` passed. A direct subprocess execution of the same check against the installed local MariaDB help command returned 0; the help command itself returned 1. This does not test the extracted 11.8.6 bootstrap/runtime.

The contracts/typed-policy/authority unit suite initially failed collection in `test_authorization_plan.py`, `test_context.py` and `test_knowledge.py` because `rfc8785` was absent. The repo declares `rfc8785==0.1.4`; it was installed from the local pip cache into the isolated disk-backed `/home/d064974/kap2-pr71-review-deps-20261024` directory, then the suite passed **51 tests in 1.74 s**. An earlier `/tmp` dependency target did not persist to the next WSL invocation and was not used for the passing run. No repository dependency declaration changed.

One initial local diagnostic was misquoted across PowerShell/WSL and attempted default MariaDB initialization; it failed to write `/var/lib/mysql` due to permissions and was stopped. Subsequent commands passed argument arrays directly. The direct `--help` call returned its expected usage and exit 1 without stderr. This incident produced no successful initialization and is not verification evidence for the candidate; no production host was contacted.

The local second-attempt result SHA-256 matched the public comment: `37f6347ea5ca83fa0c37f9a38f9fa6a1de82000a04e9db89c292c52002fbe14f`. Both committed 2026-10-12 loopback JSONL hashes also matched their structured result, whose 11 executed steps, 269 requests and local cleanup flags were intact. Verification of those records does not rerun or extend their claims. For the second remote attempt, resource absence was recorded but both cleanup verifiers returned `complete=false` because no runner JSONL existed; A11 remains unexecuted.

The [recovery review](../../docs/architecture/reviews/2026-10-24-knowledge-kap2-recovery-review.md) records the independent review and open proof items. The [structured local result](evidence/2026-10-24-local-review/result.json) includes reproduction commands, RED/GREEN counts and explicit scope boundaries.

```sh
python -m pytest -p no:cacheprovider spike/knowledge-kap2-two-host -q
sh -n spike/knowledge-kap2-two-host/acquire_mariadb.sh
PYTHONPATH=/home/d064974/kap2-pr71-review-deps-20261024:apps/episteck_home:packages/home-contracts/src python -m pytest -p no:cacheprovider -q packages/home-contracts/tests apps/episteck_home/tests/test_typed_access_policy.py apps/episteck_home/tests/test_knowledge_authority.py
python -m json.tool spike/knowledge-kap2-two-host/evidence/2026-10-24-local-review/result.json
git diff --check
```
