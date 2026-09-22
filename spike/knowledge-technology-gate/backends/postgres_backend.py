"""S1-PostgreSQL and S2-PostgreSQL (tsvector/GIN) realizations of the same logical model.

Implements the identical logical schema as sqlite_backend.py (correction 9): same
assertion versions, subjects, domains, suppression, classification/control revisions,
materialization bindings. Only the S2 full-text mechanism differs (tsvector/GIN instead
of FTS5), because that is what the experiment intentionally targets.

This module requires an already-available disposable PostgreSQL (see postgres_env.py). It
never provisions one. If `backends.postgres_env.detect_postgres()` reports unavailable,
this backend is not instantiated and the corresponding scenarios are recorded
NOT EXECUTED - ENVIRONMENT BLOCKED.

Connection configuration (correction 8) is explicit below, documented per setting.
"""
from __future__ import annotations

from .common import AuthorizedSet, CandidateRequirement, ContentAccessLog, KnowledgeBackend, PlannedMetadata
from .model import Corpus

# Documented PostgreSQL session configuration (correction 8).
#   autocommit=False, explicit transactions -- matches how a real service would batch
#     writes; no special tuning applied that wouldn't be present in ordinary operation.
#   No custom statement_timeout / work_mem override -- session uses server defaults so
#     the comparison reflects an out-of-the-box PostgreSQL, not a hand-tuned one.
PG_SESSION_NOTES = {
    "autocommit": False,
    "statement_timeout": "server default (unmodified)",
    "work_mem": "server default (unmodified)",
}

_SCHEMA = """
CREATE TABLE assertion_version (
    version_id TEXT PRIMARY KEY,
    partition_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    classification_revision INTEGER NOT NULL,
    control_revision INTEGER NOT NULL,
    applicable_from BIGINT NOT NULL,
    applicable_until BIGINT,
    replaces_version_id TEXT,
    content_text TEXT NOT NULL,
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content_text)) STORED
);
CREATE INDEX idx_av_partition ON assertion_version(partition_id, lifecycle_state);
CREATE INDEX idx_av_fts ON assertion_version USING GIN (content_tsv);

CREATE TABLE assertion_subject (
    version_id TEXT NOT NULL REFERENCES assertion_version(version_id),
    subject_person_id TEXT NOT NULL,
    PRIMARY KEY (version_id, subject_person_id)
);
CREATE INDEX idx_subj ON assertion_subject(subject_person_id, version_id);

CREATE TABLE assertion_domain (
    version_id TEXT NOT NULL REFERENCES assertion_version(version_id),
    domain TEXT NOT NULL,
    PRIMARY KEY (version_id, domain)
);
CREATE INDEX idx_dom ON assertion_domain(domain, version_id);

CREATE TABLE suppression (
    target_version_id TEXT PRIMARY KEY,
    partition_id TEXT NOT NULL,
    reason_family TEXT NOT NULL,
    effective_at BIGINT NOT NULL
);

CREATE TABLE materialization_binding (
    binding_id TEXT PRIMARY KEY,
    partition_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    derivation_family TEXT NOT NULL,
    classification_revision_at_build INTEGER NOT NULL,
    control_revision_at_build INTEGER NOT NULL,
    suppression_obligation BOOLEAN NOT NULL
);
CREATE INDEX idx_bind_source ON materialization_binding(source_version_id);
"""


class PostgresKnowledgeBackend(KnowledgeBackend):
    name = "S1-PostgreSQL"

    def __init__(self, dsn: str, *, schema_name: str = "spike_kn"):
        import psycopg  # imported lazily so SQLite-only runs never require it installed+working

        self.dsn = dsn
        self.schema_name = schema_name
        self.conn = psycopg.connect(dsn, autocommit=False)
        with self.conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
            cur.execute(f"CREATE SCHEMA {schema_name}")
            cur.execute(f"SET search_path TO {schema_name}")
        self.conn.commit()
        with self.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema_name}")
            cur.execute(_SCHEMA)
        self.conn.commit()

    def load_corpus(self, corpus: Corpus) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {self.schema_name}")
            for a in corpus.assertions:
                cur.execute(
                    """INSERT INTO assertion_version
                       (version_id, partition_id, line_id, lifecycle_state,
                        classification_revision, control_revision, applicable_from,
                        applicable_until, replaces_version_id, content_text)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        a.version_id, a.partition_id, a.line_id, a.lifecycle_state.value,
                        a.classification_revision, a.control_revision, a.applicable_from,
                        a.applicable_until, a.replaces_version_id, a.content_text,
                    ),
                )
                for s in a.subject_person_ids:
                    cur.execute(
                        "INSERT INTO assertion_subject VALUES (%s,%s)", (a.version_id, s)
                    )
                for d in a.domains:
                    cur.execute(
                        "INSERT INTO assertion_domain VALUES (%s,%s)", (a.version_id, d)
                    )
            for s in corpus.suppressions:
                cur.execute(
                    "INSERT INTO suppression VALUES (%s,%s,%s,%s)",
                    (s.target_version_id, s.partition_id, s.reason_family, s.effective_at),
                )
            for b in corpus.bindings:
                cur.execute(
                    "INSERT INTO materialization_binding VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        b.binding_id, b.partition_id, b.source_version_id, b.derivation_family,
                        b.classification_revision_at_build, b.control_revision_at_build,
                        b.suppression_obligation,
                    ),
                )
        self.conn.commit()

    def plan_metadata(
        self, *, partition_id: str, subject_person_ids: tuple[str, ...], domains: tuple[str, ...],
        as_of: int,
    ) -> PlannedMetadata:
        """Security-metadata-only query -- SELECT list never includes content_text.

        CORRECTION 1 (Product Architect review of PR #33): returned
        `candidate_requirements` carries each candidate's COMPLETE subject/domain
        membership, not just the requested slice -- see sqlite_backend.py's identical
        correction for the full rationale (one logical schema, both realizations)."""
        with self.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {self.schema_name}")
            cur.execute(
                """
                SELECT DISTINCT av.version_id
                FROM assertion_version av
                JOIN assertion_subject asub ON asub.version_id = av.version_id
                JOIN assertion_domain adom ON adom.version_id = av.version_id
                WHERE av.partition_id = %s
                  AND av.lifecycle_state = 'ADMITTED'
                  AND (av.applicable_until IS NULL OR av.applicable_until > %s)
                  AND av.applicable_from <= %s
                  AND asub.subject_person_id = ANY(%s)
                  AND adom.domain = ANY(%s)
                  AND av.version_id NOT IN (SELECT target_version_id FROM suppression)
                """,
                (partition_id, as_of, as_of, list(subject_person_ids), list(domains)),
            )
            rows = cur.fetchall()
            candidate_ids = tuple(r[0] for r in rows)

            requirements: list[CandidateRequirement] = []
            for vid in candidate_ids:
                cur.execute("SELECT subject_person_id FROM assertion_subject WHERE version_id = %s", (vid,))
                subj_rows = cur.fetchall()
                cur.execute("SELECT domain FROM assertion_domain WHERE version_id = %s", (vid,))
                dom_rows = cur.fetchall()
                requirements.append(
                    CandidateRequirement(
                        version_id=vid,
                        subject_person_ids=tuple(r[0] for r in subj_rows),
                        domains=tuple(r[0] for r in dom_rows),
                    )
                )

        # rows_returned: logical candidate-row count, NOT a physical-access claim
        # (correction 9). See explain_plan_evidence() for Layer B corroboration.
        return PlannedMetadata(
            partition_id=partition_id, candidate_version_ids=candidate_ids,
            candidate_requirements=tuple(requirements), rows_returned=len(candidate_ids),
        )

    def fetch_content(self, authorized: AuthorizedSet, *, log: ContentAccessLog) -> list[dict]:
        log.authorized_ids_at_request_time = authorized.version_ids
        if not authorized.version_ids:
            return []
        with self.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {self.schema_name}")
            cur.execute(
                "SELECT version_id, content_text FROM assertion_version WHERE version_id = ANY(%s)",
                (list(authorized.version_ids),),
            )
            rows = cur.fetchall()
        for r in rows:
            log.record(r[0])
        return [{"version_id": r[0], "content_text": r[1]} for r in rows]

    def fetch_content_fulltext(
        self, authorized: AuthorizedSet, *, query: str, log: ContentAccessLog,
    ) -> list[dict]:
        """S2 barrier, explicit 3-step (correction 2), Postgres realization:
          1. authorized.version_ids already resolved.
          2. materialize into a bounded temp table (session-scoped, dropped after use).
          3. tsvector @@ plainto_tsquery joined ONLY against that temp table.
        """
        log.authorized_ids_at_request_time = authorized.version_ids
        if not authorized.version_ids:
            return []
        with self.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {self.schema_name}")
            cur.execute("DROP TABLE IF EXISTS pg_temp.authorized_scope")
            cur.execute("CREATE TEMP TABLE authorized_scope (version_id TEXT PRIMARY KEY)")
            cur.executemany(
                "INSERT INTO pg_temp.authorized_scope VALUES (%s)",
                [(v,) for v in authorized.version_ids],
            )
            cur.execute(
                """
                SELECT av.version_id, av.content_text
                FROM assertion_version av
                JOIN pg_temp.authorized_scope sc ON sc.version_id = av.version_id
                WHERE av.content_tsv @@ plainto_tsquery('english', %s)
                """,
                (query,),
            )
            rows = cur.fetchall()
            cur.execute("DROP TABLE pg_temp.authorized_scope")
        for r in rows:
            log.record(r[0])
        return [{"version_id": r[0], "content_text": r[1]} for r in rows]

    def explain_fulltext_barrier(self, query: str, sample_ids: tuple[str, ...]) -> str:
        """Backend plan-evidence layer (correction 1.B) -- corroboration only.

        Returns EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) as text for inspection. The spike
        report must state whether the plan shows a bounded (Index Scan/Bitmap driven by
        the temp table) or unbounded (Seq Scan over content_tsv) access pattern -- it must
        NOT claim to enumerate exact unauthorized rows examined, only the access pattern.
        """
        with self.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {self.schema_name}")
            cur.execute("DROP TABLE IF EXISTS pg_temp.authorized_scope_probe")
            cur.execute("CREATE TEMP TABLE authorized_scope_probe (version_id TEXT PRIMARY KEY)")
            cur.executemany(
                "INSERT INTO pg_temp.authorized_scope_probe VALUES (%s)",
                [(v,) for v in sample_ids],
            )
            cur.execute(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT av.version_id
                FROM assertion_version av
                JOIN pg_temp.authorized_scope_probe sc ON sc.version_id = av.version_id
                WHERE av.content_tsv @@ plainto_tsquery('english', %s)
                """,
                (query,),
            )
            (plan_json,) = cur.fetchone()
            cur.execute("DROP TABLE pg_temp.authorized_scope_probe")
        return str(plan_json)

    def suppressed_version_ids(self, partition_id: str) -> frozenset[str]:
        with self.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {self.schema_name}")
            cur.execute(
                "SELECT target_version_id FROM suppression WHERE partition_id = %s", (partition_id,)
            )
            rows = cur.fetchall()
        return frozenset(r[0] for r in rows)

    def materialization_binding_current(self, binding_id: str) -> bool | None:
        with self.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {self.schema_name}")
            cur.execute(
                """
                SELECT mb.classification_revision_at_build, mb.control_revision_at_build,
                       av.classification_revision, av.control_revision
                FROM materialization_binding mb
                JOIN assertion_version av ON av.version_id = mb.source_version_id
                WHERE mb.binding_id = %s
                """,
                (binding_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return row[0] == row[2] and row[1] == row[3]

    def close(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {self.schema_name} CASCADE")
        self.conn.commit()
        self.conn.close()
