# Nuremberg acquisition correction for architectural review

**Status (2026-10-12):** prepared locally for PR #71 review; no new remote attempt authorized or executed. The exact corrected head SHA is recorded in the PR body and continuation comment. Historical branches, worktrees and experiment comments are preserved.

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
