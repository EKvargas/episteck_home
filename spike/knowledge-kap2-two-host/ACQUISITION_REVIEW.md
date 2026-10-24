# Nuremberg acquisition correction for architectural review

**Current status (2026-10-24):** local help-status correction prepared after the second stopped remote attempt; no new remote execution performed or authorized here. See the [latest section](#2026-10-24-help-status-correction). The sections below that precede it retain the historical 2026-10-12 SQL-path correction and its then-current scope. Historical branches, worktrees and experiment comments are preserved.

## Evidence and narrow correction

The [authorized attempt record](https://github.com/EKvargas/episteck_home/pull/71#issuecomment-6130380784) at `bd21543a663c7997daa27e1e8f7569a6ba353ed5` reports an A0 failure before runner preflight, private database initialization or matrix execution: **0/400 attempts**. The extracted Nuremberg MariaDB 11.8 package had `root/usr/share/mariadb/mariadb_system_tables.sql`; the reviewed command required the absent `root/usr/share/mysql/mysql_system_tables.sql`.

[acquire_mariadb.sh](acquire_mariadb.sh) copies the [exact reviewed acquisition command](https://github.com/EKvargas/episteck_home/pull/71#issuecomment-6102306877), changing only this check:

```diff
-test -f "$prefix/usr/share/mysql/mysql_system_tables.sql"
+test -f "$prefix/usr/share/mariadb/mariadb_system_tables.sql"
```

There is no path search or legacy fallback. The four executable checks, plugin directory `root/usr/lib/mysql/plugin`, wrapper `--basedir=root/usr`, private prefix, library checks and version/help commands remain exactly as reviewed. A new unexpected layout or runtime failure must stop preparation and be reported for review.

The command remains Nuremberg-only, as `kap2-probe`, under `/home/kap2-probe/mariadb-11.8.6`. It pins `mariadb-server`, `mariadb-server-core`, `mariadb-client`, `mariadb-client-core`, `mariadb-common` and `libmariadb3` to `1:11.8.6-5ubuntu0.1`, and `libpcre2-posix3` to `10.46-1build1`. It uses `apt download` and `dpkg-deb --extract`; no installation, maintainer script or system service is invoked. The witness environment still needs the reviewed private `PATH` and `LD_LIBRARY_PATH`; executing this shell script cannot export them into a parent shell.

```sh
# Only in a separately authorized Nuremberg preparation session:
sh spike/knowledge-kap2-two-host/acquire_mariadb.sh
export PATH="/home/kap2-probe/mariadb-11.8.6/bin:$PATH"
export LD_LIBRARY_PATH="/home/kap2-probe/mariadb-11.8.6/root/usr/lib/x86_64-linux-gnu"
```

The previously reviewed capacity gates remain **1.75 GiB free `/tmp`** and **2 GiB available memory**, rechecked immediately before starting. The planning allocation remains 512 MiB live datadir + 512 MiB physical copy + 64 MiB checkout + 16 MiB certificates/evidence + 128 MiB database/tmp overhead = **1,232 MiB**. Packages and the Python environment stay under the account home, outside `/tmp`. This is a planning ceiling, not a measured MariaDB 11.8 peak.

## Account and disposal correction

The [latest operator correction](https://github.com/EKvargas/episteck_home/pull/71#issuecomment-6130429841) intentionally retains Ashburn's `kap2-probe` account for future isolated Knowledge work. The recorded key login, own-group-only membership and sudo denial remain historical evidence; this continuation performs no SSH. Experiment staging was removed; Nuremberg's disposable account/home and extracted dependency prefix were removed. A11 was not executed as a runner criterion because no runner started.

For a newly authorized attempt, reverify and reuse Ashburn's existing account; do not rerun the historical create-user command or delete its home. An administrator must recreate only Nuremberg's disposable account and reviewed owned staging. After the attempt, archive evidence before removing staging; remove all experiment processes, roots, dependencies, checkout, bench, certificates and temporary ACL. Delete Nuremberg's disposable account/home; retain Ashburn's account and reverify its non-sudo boundary. This is the operator-approved account-inventory exception; all experiment cleanup assertions remain required. Warn before destructive disposal and check exact resolved paths and ownership. `verify_cleanup.py` verifies runner resources/evidence; account, privilege, dependency-prefix and ACL checks also require explicit operator evidence.

## Review boundary and local verification

The correction changes no runner, database schema, production app code, remote path, port, credential route, request cap, race/restore assertion or latency screen. README/DECISION_SHEET make the acquisition correction and account exception explicit. The remote A0–A11 matrix, mandatory Frappe 15.99.0 control, 30 warm/30 cold pairs, **400 attempted requests**, no retries and proposed unratified thresholds remain required. KAP-2 stays open; PR #71 remains draft and unmerged.

`test_acquisition.py` executes the actual shell filesystem-check block against local fixtures. It does not download archives or execute wrappers. The original command failed the MariaDB-layout acceptance and legacy-layout rejection tests (**2 failed, 4 passed**); after the one-line correction all **6 passed**. Additional cases reject missing SQL, a directory in place of SQL, a nonexecutable server and a missing plugin directory.

```sh
# Local verification only; never execute the acquisition command for this check.
bash -n spike/knowledge-kap2-two-host/acquire_mariadb.sh
python -m pytest spike/knowledge-kap2-two-host/test_acquisition.py -q
python -m compileall -q spike/knowledge-kap2-two-host
git diff --check
```

Fresh local loopback runner evidence is recorded in [LOCAL_VALIDATION.md](LOCAL_VALIDATION.md). Local MariaDB 10.11 cannot establish that Nuremberg's extracted MariaDB 11.8 binaries, bootstrap scripts, plugins or libraries work. That prerequisite remains part of the next separately authorized A0; stop if compatibility requires a further change. The [decision sheet](DECISION_SHEET.md) specifies the fresh exact-SHA authorization required for one new two-host attempt.

## 2026-10-24: help-status correction

The [second authorized attempt](https://github.com/EKvargas/episteck_home/pull/71#issuecomment-6132455875) ran the unchanged `6166594bd91482455440e8e938306769100136bd` acquisition once. All seven pinned archives extracted, the corrected SQL path and private-tool/library checks passed, and three version commands reported 11.8.6. The final `mariadb-install-db --help >/dev/null` returned 1 and stopped `set -eu`, before runner preflight or any database initialization. No matrix requests or latency measurements occurred.

The archived read-only diagnosis identifies the pinned upstream script SHA-256 as `7ce8954169bd124f1f1198ebe94dffb376b1501b5683cb140eebdb1b58bc8eae`: `--help` calls `usage()` at line 173; `usage()` prints `Usage: $0 [OPTIONS]` and exits 1 at line 118. The result archive hash matches the public attempt record (`37f6347ea5ca83fa0c37f9a38f9fa6a1de82000a04e9db89c292c52002fbe14f`). This is evidence of a check assumption, not proof that bootstrap/runtime works.

Only the final help check changes in this continuation. It captures the command's output and status without triggering `set -e`, requires **exactly exit 1**, and independently requires the Usage header, `--auth-root-authentication-method=normal|socket` and `--datadir` text. Empty/error/incomplete output and statuses 0, 2, 126 and 127 reject. There is no `|| true`, retry, alternate package or broader successful-status fallback. These markers verify help recognition, not the whole help document or runtime compatibility.

The pinned versions, package extraction, private prefix, wrappers, SQL/plugin checks, library checks and three version commands are unchanged from `6166594`. All six original package Python runners remain unchanged. Serving/recovery separation, A0–A11, paths, port, capacity gates and request/measurement budgets also remain unchanged.

Local behavioral tests execute the actual final shell section with a local help-command fixture. The initial regression run produced **2 failed, 13 passed** on the old check: valid exit-1 help was rejected, while unexpected exit 0 passed. After the correction and two further incomplete-output cases, **17 passed**. POSIX shell syntax and an actual local installed help-only call also passed. No MariaDB 11.8 package was acquired locally and no remote command was run.

The second attempt's preparation disposal is separate from A11: reviewed paths/listener were recorded absent, Nuremberg's account/home/prefix were removed, and Ashburn's account was intentionally retained without sudo. Both approved cleanup checkers returned `complete=false` because runner JSONL was absent; neither runner started. Preserve that result rather than converting it into a passed A11.

Review the [recovery findings](../../docs/architecture/reviews/2026-10-24-knowledge-kap2-recovery-review.md) and the final corrected commit before a fresh authorization. Production ratification, full admission staging, repeated writer-principal cutover, full Home authority-source coverage and later KAP gates remain open. The new attempt must still stop at any unexpected prerequisite failure.

**Verify:** `python -m pytest spike/knowledge-kap2-two-host -q`; `sh -n spike/knowledge-kap2-two-host/acquire_mariadb.sh`; `git diff --check` (Linux/WSL).
