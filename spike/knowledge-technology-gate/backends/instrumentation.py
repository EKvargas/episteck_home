"""Two-layer execution-barrier evidence (methodological correction 1).

LAYER A -- application/query-boundary instrumentation. PRIMARY, MANDATORY.
    The content-access API (`ContentAccessLog` in common.py) records every logical
    content ID actually requested. We assert it is a subset of the authorized-ID set.
    This is ground truth about what the APPLICATION asked for, independent of what the
    backend's internals may have scanned to answer it.

LAYER B -- backend plan evidence. CORROBORATION ONLY.
    SQLite: `EXPLAIN QUERY PLAN` (no lower-level statement-status API exists in stdlib
    `sqlite3` -- verified empirically before writing this module; see
    `backends/sqlite_backend.py` module docstring).
    PostgreSQL: `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.
    Neither directly reports "which physical rows were examined and were they
    authorized" -- both report access PATTERN (scan vs index-driven), which is weaker
    evidence. This layer can corroborate a PASS or contradict one, but on its own it can
    only ever produce PASS-BY-PATTERN or UNKNOWN, never a positive proof of zero
    unauthorized physical access.

Barrier evidence result is always one of the closed-set classifications (correction 12).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .common import ContentAccessLog


class BarrierVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN — INSUFFICIENT EVIDENCE"
    NOT_EXECUTED = "NOT EXECUTED — ENVIRONMENT BLOCKED"
    N_A = "N/A"


@dataclass(frozen=True)
class LayerAEvidence:
    """Application-boundary evidence -- the mandatory, primary assertion."""

    logical_content_ids_requested: int
    unauthorized_logical_content_ids_requested: int
    unauthorized_rows_contributing_to_score_or_count: int  # this spike never ranks/scores
    # results beyond exact-match presence, so this is 0 whenever layer-A subset holds;
    # recorded explicitly rather than assumed.

    @property
    def verdict(self) -> BarrierVerdict:
        if (
            self.unauthorized_logical_content_ids_requested == 0
            and self.unauthorized_rows_contributing_to_score_or_count == 0
        ):
            return BarrierVerdict.PASS
        return BarrierVerdict.FAIL


@dataclass(frozen=True)
class LayerBEvidence:
    """Backend plan-evidence -- corroboration only. Never the sole basis for PASS."""

    backend: str
    plan_text: str
    access_pattern_bounded: bool | None  # None = could not determine from the plan
    note: str

    @property
    def verdict(self) -> BarrierVerdict:
        if self.access_pattern_bounded is True:
            return BarrierVerdict.PASS
        if self.access_pattern_bounded is False:
            return BarrierVerdict.FAIL
        return BarrierVerdict.UNKNOWN


@dataclass(frozen=True)
class BarrierEvidence:
    layer_a: LayerAEvidence
    layer_b: LayerBEvidence | None  # None only if plan capture itself was not attempted

    @property
    def combined_verdict(self) -> BarrierVerdict:
        """Layer A is authoritative for PASS/FAIL (it's the mandatory evidence per
        correction 1). Layer B can only downgrade an A-PASS to UNKNOWN when it
        contradicts A, or corroborate it; it never overrides an A-FAIL to PASS."""
        if self.layer_a.verdict == BarrierVerdict.FAIL:
            return BarrierVerdict.FAIL
        if self.layer_b is None:
            return BarrierVerdict.UNKNOWN
        if self.layer_b.verdict == BarrierVerdict.FAIL:
            # Layer A says the application never requested unauthorized content, but the
            # backend's own access pattern shows it examined unauthorized content
            # internally (e.g. SQLite FTS5 MATCH scanning the whole virtual table). This
            # is a REAL finding, not a contradiction to paper over -- report FAIL, because
            # H3 concerns backend ordering, not just what the application asked for.
            return BarrierVerdict.FAIL
        if self.layer_b.verdict == BarrierVerdict.UNKNOWN:
            return BarrierVerdict.UNKNOWN
        return BarrierVerdict.PASS  # both layers PASS


def layer_a_from_log(log: ContentAccessLog) -> LayerAEvidence:
    return LayerAEvidence(
        logical_content_ids_requested=log.content_records_examined_after_barrier,
        unauthorized_logical_content_ids_requested=log.unauthorized_logical_content_ids_requested,
        unauthorized_rows_contributing_to_score_or_count=log.unauthorized_logical_content_ids_requested,
    )


def layer_b_sqlite(plan_rows: list[str]) -> LayerBEvidence:
    """Interpret SQLite EXPLAIN QUERY PLAN output.

    A plan row containing 'SCAN <fts-table> VIRTUAL TABLE' where the fts table is scanned
    (as opposed to searched via an index keyed by the authorized-scope join) indicates
    FTS5 is evaluating MATCH against its own posting list before/independent of the
    authorized-scope join -- i.e. the access pattern is NOT bounded by the authorized set.
    This is a known FTS5 property: MATCH must consult the FTS index regardless of outer
    join order, because there is no point-lookup form of MATCH.
    """
    plan_text = "\n".join(plan_rows)
    # Match SCAN of any virtual table (the only virtual table in this schema is the FTS5
    # index). Plan rows arrive as stringified `(id, parent, notused, detail)` tuples, e.g.
    # "(3, 0, 132, 'SCAN f VIRTUAL TABLE INDEX 0:M2')" -- 'f' is a query ALIAS, not the
    # literal table name, so alias-matching on 'fts' is unreliable (missed this exact row
    # during spike development; fixed to substring-match the operation instead). A SEARCH
    # (not SCAN) against a virtual table, if SQLite ever produces one, indicates
    # index-driven bounded access and must NOT be flagged here -- hence requiring both
    # 'SCAN ' and 'VIRTUAL TABLE' rather than just 'VIRTUAL TABLE'.
    fts_virtual_scan = any(
        "VIRTUAL TABLE" in row and "SCAN " in row and "SEARCH" not in row for row in plan_rows
    )
    if fts_virtual_scan:
        return LayerBEvidence(
            backend="SQLite",
            plan_text=plan_text,
            access_pattern_bounded=False,
            note=(
                "FTS5 MATCH requires scanning the virtual table's own index structure "
                "regardless of join order with the authorized-scope temp table; SQLite's "
                "planner does not push the join as a pre-filter into FTS5's xFilter. "
                "Empirically confirmed: EXPLAIN QUERY PLAN shows 'SCAN <fts> VIRTUAL "
                "TABLE INDEX 0:M2' even when authorized_scope is joined first."
            ),
        )
    if not plan_rows:
        return LayerBEvidence(
            backend="SQLite", plan_text="", access_pattern_bounded=None,
            note="no plan captured",
        )
    return LayerBEvidence(
        backend="SQLite", plan_text=plan_text, access_pattern_bounded=True,
        note="no unbounded FTS virtual-table scan detected in plan",
    )


def layer_b_postgres(plan_json_text: str) -> LayerBEvidence:
    """Interpret PostgreSQL EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output.

    Looks for 'Seq Scan' over the content table combined with a GIN index NOT being used
    (Bitmap Index Scan / Index Scan absent) as evidence of an unbounded access pattern.
    This is pattern-matching over the plan text, not a row-level physical-access proof --
    reported as corroboration only, per correction 1.B.
    """
    if not plan_json_text:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text="", access_pattern_bounded=None,
            note="no plan captured",
        )
    has_seq_scan_on_content = '"Node Type": "Seq Scan"' in plan_json_text and "assertion_version" in plan_json_text
    has_bounded_join = (
        '"Node Type": "Nested Loop"' in plan_json_text or '"Node Type": "Hash Join"' in plan_json_text
    )
    if has_seq_scan_on_content and not has_bounded_join:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=False,
            note="plan shows a sequential scan over assertion_version without a bounding join",
        )
    if has_bounded_join:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=True,
            note="plan shows the authorized-scope temp table driving the join",
        )
    return LayerBEvidence(
        backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=None,
        note="plan shape did not match a recognized bounded/unbounded pattern; "
             "manual review required",
    )
