# KAP-2 acquisition correction and recovery review

> **For agentic workers:** Use superpowers:executing-plans for inline execution. Use an independent reviewer under superpowers:requesting-code-review.

**Goal:** Remove the evidenced A0 help-status false failure and prepare an honest recovery-design review before any new two-host attempt.

**Architecture:** Keep the existing pinned, extract-only MariaDB acquisition and disconnected PERSON candidate. Recognize the pinned install script's help result only with expected usage output. Review recovery without changing the governing contract or recording Board approval.

**Tech stack:** POSIX shell, Python 3.11+, pytest; existing local WSL environment.

**Spec:** `spike/knowledge-kap2-two-host/DECISION_SHEET.md`, runtime contract §19, ADR-0010 and the final PR #71 attempt comment `6132455875` (2026-10-12).

## Constraints and review focus

- Work in the existing consolidated worktree; preserve historical branches and evidence.
- No SSH, MariaDB dependency acquisition, remote run, merge, deployment, migration or production change. The already declared Python test dependency may be installed in an isolated local test directory.
- Preserve pinned packages, private prefix, wrappers, port 19442, 400-attempt cap, no retries and A0–A11 criteria.
- Help exit 1 with recognizable usage must pass; empty/error output or any other exit must fail. Help remains insufficient to prove database bootstrap/runtime compatibility.
- Review independently enforced CLOSED admission, quarantine, writer fencing, unknown outcomes, human reauthorization and ordinary Home compatibility.
- A review recommendation is neither Board ratification nor authorization for a remote attempt.

## Task 1: Correct and verify the A0 help check

Files: modify `spike/knowledge-kap2-two-host/acquire_mariadb.sh` and `test_acquisition.py`; update acquisition/local-validation records and current README/decision-sheet status.

- [x] Confirm the archived failure and run the existing six-test baseline.
- [x] Add behavioral tests executing the actual help-check shell tail with a local executable fixture; cover status 1 + valid help, missing/malformed help, and unexpected statuses.
- [x] Run the new tests against the unchanged check and record the expected failure.
- [x] Replace only the final help check with status capture and expected usage checks; run the complete package suite and shell syntax check.
- [x] Record exact verification and remaining remote limitations without replacing historical results.

## Task 2: Review recovery and consolidate the next gate

Files: create `docs/architecture/reviews/2026-10-24-knowledge-kap2-recovery-review.md` and a structured JSON result beside the two-host package.

- [x] Trace the accepted/proposed recovery invariants to candidate code and named tests; obtain independent review findings.
- [x] Separate disposable-candidate findings from production proof gaps; do not claim unexecuted tests passed.
- [x] Update the handoff with the second stopped attempt, correction and review disposition.
- [x] Verify local evidence hashes and targeted existing contract/authority tests, review the final diff, and report the concrete next gate.

**Verify:** `python -m pytest spike/knowledge-kap2-two-host -q` (Linux/WSL); `git diff --check`.

## Execution record

- Existing linked worktree confirmed; baseline package suite: 6 passed.
- Regression RED: 2 failed, 13 passed against the unchanged acquisition check. Both failures were the intended exit-status assumptions.
- Corrected package suite, including two additional incomplete-output cases: 17 passed. POSIX shell syntax passed. Actual installed local MariaDB help-only check passed; this is not MariaDB 11.8 bootstrap evidence.
- Ruling: use inline execution for the already authorized narrow correction, plus an independent read-only reviewer; no further implementation-method decision is needed.
- Ruling: install only the existing `rfc8785==0.1.4` test dependency under `/home/d064974/kap2-pr71-review-deps-20261024` because the reused environment could not collect three contract test modules. An initial `/tmp` installation did not persist to the next WSL invocation, so use the disk-backed home path. This permits local Python test setup, not MariaDB acquisition or remote preparation.
- Local diagnostic incident: a PowerShell/WSL quoting error attempted default MariaDB initialization and failed on filesystem permissions. The probe was stopped. Correctly passed direct subprocess arguments returned help exit 1; subsequent commands use direct argument arrays. No claim of disposable or production database acceptance follows from this diagnostic.
- Task 1 complete: 17 package tests passed, with demonstrated RED before correction; shell syntax and actual local help-only check passed.
- Task 2 complete: independent review returned `READY_FOR_LOCAL_COMMIT_AND_REVIEW`, no blocking correction findings; R1–R6 remain open. JSON, local links and historical evidence hashes verified.
- Final combined verification: 68 passed in 1.73 s; six original package Python runners and all authority/contract implementation files unchanged; `git diff --check` passed.
