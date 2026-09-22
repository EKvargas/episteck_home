"""S1-SQLite and S2-SQLite (FTS5) realizations of the one logical model (backends/model.py).

Correction 3 applied: stdlib `sqlite3` was probed before writing this (see
`instrumentation.py` docstring) and exposes NO low-level statement-status counter API.
Evidence here relies on (A) the mandatory application-boundary ContentAccessLog and
(B) `EXPLAIN QUERY PLAN` as corroboration only -- never claimed as physical-row-level
proof.

Correction 8: connection configuration is explicit and documented, not hand-tuned to make
SQLite win or lose. WAL mode is used because SQLite's own documentation recommends it for
concurrent readers/writer -- exactly this spike's P13 workload -- not because it favors
one comparison outcome.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .common import AuthorizedSet, ContentAccessLog, KnowledgeBackend, PlannedMetadata
from .model import Corpus

# Documented SQLite configuration (correction 8). Rationale per pragma:
#   journal_mode=WAL     -- SQLite docs: "WAL provides more concurrency as readers do not
#                            block writers and a writer does not block readers" -- the
#                            realistic shape for P13 (interactive reads concurrent with
#                            B4 cleanup writes). This is what a real service would use.
#   synchronous=NORMAL   -- SQLite docs: safe with WAL ("very good chance" durable across
#                            app crash; only OS crash + power loss can lose the most recent
#                            commit). FULL is the conservative alternative; NORMAL is
#                            SQLite's own documented recommendation for WAL mode.
#   busy_timeout=5000ms  -- avoids spurious SQLITE_BUSY under P13 contention; 5s is a
#                            generous, undramatic default, not tuned per-scenario.
SQLITE_PRAGMAS = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "busy_timeout": 5000,
}

_SCHEMA = """
CREATE TABLE assertion_version (
    version_id TEXT PRIMARY KEY,
    partition_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    classification_revision INTEGER NOT NULL,
    control_revision INTEGER NOT NULL,
    applicable_from INTEGER NOT NULL,
    applicable_until INTEGER,
    replaces_version_id TEXT,
    content_text TEXT NOT NULL
);
CREATE INDEX idx_av_partition ON assertion_version(partition_id, lifecycle_state);

CREATE TABLE assertion_subject (
    version_id TEXT NOT NULL,
    subject_person_id TEXT NOT NULL,
    PRIMARY KEY (version_id, subject_person_id)
);
CREATE INDEX idx_subj ON assertion_subject(subject_person_id, version_id);

CREATE TABLE assertion_domain (
    version_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    PRIMARY KEY (version_id, domain)
);
CREATE INDEX idx_dom ON assertion_domain(domain, version_id);

CREATE TABLE suppression (
    target_version_id TEXT PRIMARY KEY,
    partition_id TEXT NOT NULL,
    reason_family TEXT NOT NULL,
    effective_at INTEGER NOT NULL
);

CREATE TABLE materialization_binding (
    binding_id TEXT PRIMARY KEY,
    partition_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    derivation_family TEXT NOT NULL,
    classification_revision_at_build INTEGER NOT NULL,
    control_revision_at_build INTEGER NOT NULL,
    suppression_obligation INTEGER NOT NULL
);
CREATE INDEX idx_bind_source ON materialization_binding(source_version_id);

-- S2: FTS5 virtual table, content-linked (not a separate materialization -- Phase-1 SS6
-- "S2's classification": it lives in the same transaction, indexed by version_id.
CREATE VIRTUAL TABLE assertion_fts USING fts5(version_id UNINDEXED, content_text);
"""


class SQLiteKnowledgeBackend(KnowledgeBackend):
    name = "S1-SQLite"

    def __init__(self, path: str | Path = ":memory:", *, create_schema: bool | None = None):
        """`create_schema`: True forces creation (errors if tables exist), False assumes
        an existing schema (errors if they don't), None (default) auto-detects -- creates
        only when connecting to `:memory:` or a file that doesn't exist yet. This lets
        multiple connections open the SAME on-disk database (P13's concurrent
        readers/writer) without each one trying to recreate tables that already exist."""
        self.path = str(path)
        is_new_file = self.path == ":memory:" or not Path(self.path).exists()
        should_create = create_schema if create_schema is not None else is_new_file

        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        for pragma, value in SQLITE_PRAGMAS.items():
            self.conn.execute(f"PRAGMA {pragma}={value}")
        if should_create:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()
        self._query_log: list[tuple[str, float]] = []  # (sql, elapsed) via trace callback
        self._trace_enabled = False

    def enable_trace(self) -> None:
        """Correction 3: use only what stdlib actually exposes -- set_trace_callback."""
        self._trace_enabled = True
        self._query_log.clear()
        self.conn.set_trace_callback(lambda sql: self._query_log.append((sql, time.monotonic())))

    def disable_trace(self) -> None:
        self._trace_enabled = False
        self.conn.set_trace_callback(None)

    def load_corpus(self, corpus: Corpus) -> None:
        cur = self.conn.cursor()
        for a in corpus.assertions:
            cur.execute(
                "INSERT INTO assertion_version VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    a.version_id, a.partition_id, a.line_id, a.lifecycle_state.value,
                    a.classification_revision, a.control_revision, a.applicable_from,
                    a.applicable_until, a.replaces_version_id, a.content_text,
                ),
            )
            cur.execute(
                "INSERT INTO assertion_fts (version_id, content_text) VALUES (?,?)",
                (a.version_id, a.content_text),
            )
            for s in a.subject_person_ids:
                cur.execute("INSERT INTO assertion_subject VALUES (?,?)", (a.version_id, s))
            for d in a.domains:
                cur.execute("INSERT INTO assertion_domain VALUES (?,?)", (a.version_id, d))
        for s in corpus.suppressions:
            cur.execute(
                "INSERT INTO suppression VALUES (?,?,?,?)",
                (s.target_version_id, s.partition_id, s.reason_family, s.effective_at),
            )
        for b in corpus.bindings:
            cur.execute(
                "INSERT INTO materialization_binding VALUES (?,?,?,?,?,?,?)",
                (
                    b.binding_id, b.partition_id, b.source_version_id, b.derivation_family,
                    b.classification_revision_at_build, b.control_revision_at_build,
                    int(b.suppression_obligation),
                ),
            )
        self.conn.commit()

    def plan_metadata(
        self, *, partition_id: str, subject_person_ids: tuple[str, ...], domains: tuple[str, ...],
        as_of: int,
    ) -> PlannedMetadata:
        """Security-metadata-only query. Selects version_id + control columns; NEVER
        content_text -- H2's separability requirement, checked structurally by the SELECT
        list, not by convention."""
        cur = self.conn.cursor()
        subject_ph = ",".join("?" * len(subject_person_ids))
        domain_ph = ",".join("?" * len(domains))
        sql = f"""
            SELECT DISTINCT av.version_id
            FROM assertion_version av
            JOIN assertion_subject asub ON asub.version_id = av.version_id
            JOIN assertion_domain adom ON adom.version_id = av.version_id
            WHERE av.partition_id = ?
              AND av.lifecycle_state IN ('ADMITTED')
              AND (av.applicable_until IS NULL OR av.applicable_until > ?)
              AND av.applicable_from <= ?
              AND asub.subject_person_id IN ({subject_ph})
              AND adom.domain IN ({domain_ph})
              AND av.version_id NOT IN (SELECT target_version_id FROM suppression)
        """
        params = [partition_id, as_of, as_of, *subject_person_ids, *domains]
        rows = cur.execute(sql, params).fetchall()
        candidate_ids = tuple(r["version_id"] for r in rows)
        # rows_inspected: report the row count SQLite actually scanned per EXPLAIN QUERY
        # PLAN, corroboration layer (instrumentation.py) computes the precise figure;
        # here we report the returned-candidate count as the cheap in-band signal.
        return PlannedMetadata(
            partition_id=partition_id, candidate_version_ids=candidate_ids, rows_inspected=len(candidate_ids)
        )

    def fetch_content(self, authorized: AuthorizedSet, *, log: ContentAccessLog) -> list[dict]:
        log.authorized_ids_at_request_time = authorized.version_ids
        if not authorized.version_ids:
            return []
        cur = self.conn.cursor()
        ph = ",".join("?" * len(authorized.version_ids))
        rows = cur.execute(
            f"SELECT version_id, content_text FROM assertion_version WHERE version_id IN ({ph})",
            authorized.version_ids,
        ).fetchall()
        for r in rows:
            log.record(r["version_id"])
        return [dict(r) for r in rows]

    def fetch_content_fulltext(
        self, authorized: AuthorizedSet, *, query: str, log: ContentAccessLog,
    ) -> list[dict]:
        """S2 barrier, explicit 3-step (correction 2):
          1. authorized.version_ids already resolved from metadata/control state.
          2. materialize them into a bounded temp table.
          3. FTS MATCH joined ONLY against that temp table -- never a bare FTS5 MATCH over
             the whole virtual table, which would be a global posting-list walk.
        """
        log.authorized_ids_at_request_time = authorized.version_ids
        if not authorized.version_ids:
            return []
        cur = self.conn.cursor()
        cur.execute("DROP TABLE IF EXISTS temp.authorized_scope")
        cur.execute("CREATE TEMP TABLE authorized_scope (version_id TEXT PRIMARY KEY)")
        cur.executemany(
            "INSERT INTO temp.authorized_scope VALUES (?)",
            [(v,) for v in authorized.version_ids],
        )
        rows = cur.execute(
            """
            SELECT f.version_id, f.content_text
            FROM assertion_fts f
            JOIN temp.authorized_scope sc ON sc.version_id = f.version_id
            WHERE f.assertion_fts MATCH ?
            """,
            (query,),
        ).fetchall()
        cur.execute("DROP TABLE temp.authorized_scope")
        for r in rows:
            log.record(r["version_id"])
        return [dict(r) for r in rows]

    def explain_fulltext_barrier(self, query: str) -> list[str]:
        """Backend plan-evidence layer (correction 1.B) -- corroboration only."""
        cur = self.conn.cursor()
        cur.execute("DROP TABLE IF EXISTS temp.authorized_scope_probe")
        cur.execute("CREATE TEMP TABLE authorized_scope_probe (version_id TEXT PRIMARY KEY)")
        plan = cur.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT f.version_id FROM assertion_fts f
            JOIN temp.authorized_scope_probe sc ON sc.version_id = f.version_id
            WHERE f.assertion_fts MATCH ?
            """,
            (query,),
        ).fetchall()
        cur.execute("DROP TABLE temp.authorized_scope_probe")
        return [str(tuple(r)) for r in plan]

    def suppressed_version_ids(self, partition_id: str) -> frozenset[str]:
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT target_version_id FROM suppression WHERE partition_id = ?", (partition_id,)
        ).fetchall()
        return frozenset(r["target_version_id"] for r in rows)

    def materialization_binding_current(self, binding_id: str) -> bool | None:
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT mb.classification_revision_at_build, mb.control_revision_at_build,
                   av.classification_revision, av.control_revision
            FROM materialization_binding mb
            JOIN assertion_version av ON av.version_id = mb.source_version_id
            WHERE mb.binding_id = ?
            """,
            (binding_id,),
        ).fetchone()
        if row is None:
            return None
        return (
            row["classification_revision_at_build"] == row["classification_revision"]
            and row["control_revision_at_build"] == row["control_revision"]
        )

    def explain_metadata_plan(
        self, *, partition_id: str, subject_person_ids: tuple[str, ...], domains: tuple[str, ...],
        as_of: int,
    ) -> list[str]:
        cur = self.conn.cursor()
        subject_ph = ",".join("?" * len(subject_person_ids))
        domain_ph = ",".join("?" * len(domains))
        plan = cur.execute(
            f"""
            EXPLAIN QUERY PLAN
            SELECT DISTINCT av.version_id
            FROM assertion_version av
            JOIN assertion_subject asub ON asub.version_id = av.version_id
            JOIN assertion_domain adom ON adom.version_id = av.version_id
            WHERE av.partition_id = ?
              AND av.lifecycle_state IN ('ADMITTED')
              AND (av.applicable_until IS NULL OR av.applicable_until > ?)
              AND av.applicable_from <= ?
              AND asub.subject_person_id IN ({subject_ph})
              AND adom.domain IN ({domain_ph})
              AND av.version_id NOT IN (SELECT target_version_id FROM suppression)
            """,
            [partition_id, as_of, as_of, *subject_person_ids, *domains],
        ).fetchall()
        return [str(tuple(r)) for r in plan]

    def close(self) -> None:
        self.conn.close()
