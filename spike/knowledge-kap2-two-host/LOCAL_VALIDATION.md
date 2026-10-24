# Local validation of the two-host package

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
