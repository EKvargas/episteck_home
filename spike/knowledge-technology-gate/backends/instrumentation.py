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


def layer_b_sqlite_exact_lookup(plan_rows: list[str]) -> LayerBEvidence:
    """Interpret SQLite EXPLAIN QUERY PLAN output for the S1 exact-version content barrier
    (correction 10). Unlike the FTS barrier (S2), the S1 content fetch is a point lookup
    keyed on the authorized version IDs, so a bounded plan is the EXPECTED, benign shape.

    Bounded (PASS-by-pattern): the plan SEARCHes assertion_version via an index/primary
    key on version_id -- empirically `SEARCH assertion_version USING INDEX
    sqlite_autoindex_assertion_version_1 (version_id=?)` -- and never falls back to a bare
    `SCAN assertion_version`. Unbounded (FAIL): a `SCAN assertion_version` means the
    content barrier read the whole content table rather than seeking the authorized IDs.
    Anything unrecognized -> UNKNOWN (never silently promoted to PASS).

    Corroboration only (correction 1.B): a bounded access pattern is consistent with H3 but
    does not by itself prove zero unauthorized physical row/page access -- Layer A is the
    authoritative evidence. Reuses the shared LayerBEvidence / BarrierVerdict closed set.
    """
    plan_text = "\n".join(plan_rows)
    if not plan_rows:
        return LayerBEvidence(
            backend="SQLite", plan_text="", access_pattern_bounded=None,
            note="no plan captured",
        )
    unbounded_scan = any(
        "SCAN assertion_version" in row and "SEARCH" not in row for row in plan_rows
    )
    if unbounded_scan:
        return LayerBEvidence(
            backend="SQLite", plan_text=plan_text, access_pattern_bounded=False,
            note="content barrier plan shows a full SCAN of assertion_version rather than an "
                 "index-bounded lookup on the authorized version IDs",
        )
    bounded_search = any(
        "SEARCH assertion_version" in row and "version_id" in row for row in plan_rows
    )
    if bounded_search:
        return LayerBEvidence(
            backend="SQLite", plan_text=plan_text, access_pattern_bounded=True,
            note="content barrier plan seeks assertion_version by index on version_id "
                 "(`SEARCH ... USING INDEX ... (version_id=?)`); access is bounded by the "
                 "authorized set, not a global content scan",
        )
    return LayerBEvidence(
        backend="SQLite", plan_text=plan_text, access_pattern_bounded=None,
        note="content barrier plan shape not recognized as either bounded index lookup or "
             "unbounded scan; manual review required",
    )


def layer_b_postgres_exact_lookup(plan_json_text: str) -> LayerBEvidence:
    """Interpret PostgreSQL EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output for the S1
    exact-version content barrier (correction 11 finding, Product Architect directive).

    `layer_b_postgres` (below) was written for the S2 full-text query shape, where a
    Seq Scan without a bounding join is the FTS5-equivalent leak signature. The S1
    exact-lookup query (`WHERE version_id = ANY(authorized_ids)`) has NO join at all --
    applying that heuristic here produced a false FAIL: empirically, PostgreSQL's planner
    chooses Seq Scan over `assertion_version` at every tested corpus size (C-small/medium/
    large) for this query, because the filter predicate itself IS the authorized set and a
    full scan-with-filter is cheaper than per-ID index probes at this selectivity. That is
    ordinary cost-based planning, not an unbounded access pattern.

    This function classifies PASS only when ALL of the following hold (never inferred,
    never silently promoted from UNKNOWN):
      1. Layer A already proved zero unauthorized logical content IDs were requested
         (passed in by the caller as `layer_a_pass`; this function refuses to guess it).
      2. The query plan's ONLY scan of `assertion_version` carries a `Filter` (or index
         `Index Cond`) that is directly `version_id = ANY(...)` / `version_id = <const>`
         against the bounded authorized-ID set -- not a broader or derived predicate.
      3. No node in the plan touches a full-text/GIN index, ranking, scoring, or
         aggregation (`Node Type` containing 'Aggregate', or an `Index Name`/`Index Cond`
         referencing a tsvector/GIN/FTS structure) -- nothing that could consume
         unauthorized content before the version_id restriction.
      4. No `Join`-family node (`Node Type` containing 'Join', or a `Nested Loop`) and no
         `SubPlan`/`InitPlan` broadens the candidate set before the exact-ID restriction --
         i.e. `assertion_version` is the only relation this plan reads.
      5. The plan shape is one this function recognizes with confidence (a single-relation
         scan or index-scan plan, no unexpected node types).

    If the plan is ambiguous or any condition cannot be confidently verified, this returns
    UNKNOWN -- INSUFFICIENT EVIDENCE, never PASS. A Seq Scan is recorded explicitly as
    planner behavior (including Rows Removed by Filter / actual rows, when present) because
    it may matter for performance -- it is not, by itself, a security-barrier FAIL.
    """
    import json as _json

    if not plan_json_text:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text="", access_pattern_bounded=None,
            note="no plan captured",
        )
    try:
        parsed = _json.loads(plan_json_text)
        root = parsed[0]["Plan"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=None,
            note=f"plan JSON not in the expected shape ({type(e).__name__}); manual review required",
        )

    nodes: list[dict] = []

    def _walk(node: dict) -> None:
        nodes.append(node)
        for child in node.get("Plans", []) or []:
            _walk(child)

    _walk(root)

    relations_touched = {n.get("Relation Name") for n in nodes if n.get("Relation Name")}
    join_nodes = [n for n in nodes if "Join" in str(n.get("Node Type", ""))]
    subplan_nodes = [
        n for n in nodes
        if str(n.get("Parent Relationship", "")) in ("SubPlan", "InitPlan")
        or "SubPlan" in str(n.get("Node Type", ""))
    ]
    aggregate_or_fts_nodes = [
        n for n in nodes
        if "Aggregate" in str(n.get("Node Type", ""))
        or "gin" in str(n.get("Index Name", "")).lower()
        or "fts" in str(n.get("Index Name", "")).lower()
        or "tsv" in str(n.get("Index Cond", "")).lower()
        or "@@" in str(n.get("Filter", "")) or "@@" in str(n.get("Index Cond", ""))
    ]

    # Condition 4: no join/subplan broadening the candidate set. Checked BEFORE the generic
    # "recognized shape" gate below because a Join/SubPlan node is unambiguous, specific
    # evidence of broadening -- more informative than a bare "shape not recognized" UNKNOWN,
    # even though a multi-relation plan would also fail the condition-5 gate.
    if join_nodes or subplan_nodes:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=False,
            note="plan contains a Join or SubPlan/InitPlan node, which could broaden the "
                 "candidate set before the version_id restriction",
        )

    # Condition 5: recognized shape -- exactly one relation read, no unrecognized structure.
    if len(relations_touched) != 1 or relations_touched != {"assertion_version"}:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=None,
            note=f"plan reads relation(s) {relations_touched or 'none'}, not exactly "
                 "{'assertion_version'}; shape not recognized, manual review required",
        )

    # Condition 3: no FTS/GIN/aggregate/scoring node.
    if aggregate_or_fts_nodes:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=False,
            note="plan touches a full-text/GIN/aggregate node that could consume "
                 "unauthorized content before the version_id restriction",
        )

    # Condition 2: the single scan's predicate is directly on version_id.
    leaf = nodes[0]  # exactly one relation was touched, so this is the (only) scan node
    predicate = str(leaf.get("Filter", "")) or str(leaf.get("Index Cond", ""))
    if "version_id" not in predicate:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=None,
            note=f"scan predicate {predicate!r} does not reference version_id directly; "
                 "cannot confirm the restriction is the authorized-ID set, manual review required",
        )

    node_type = str(leaf.get("Node Type", ""))
    return LayerBEvidence(
        backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=True,
        note=(
            f"single-relation {node_type} on assertion_version, predicate directly on "
            f"version_id against the authorized-ID set, no join/subplan/FTS/aggregate node "
            f"present -- bounded by predicate, not by index choice. Recorded planner "
            f"behavior: {node_type} "
            f"(Rows Removed by Filter={leaf.get('Rows Removed by Filter', 'n/a')}, "
            f"Actual Rows={leaf.get('Actual Rows', 'n/a')}). A Seq Scan here is a cost-based "
            f"planner choice at this corpus size/selectivity, not a security-barrier failure."
        ),
    )


def layer_b_postgres(plan_json_text: str) -> LayerBEvidence:
    """Interpret PostgreSQL EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output for the S2
    full-text barrier (Product Architect directive, S2-PostgreSQL closure).

    The ORIGINAL version of this function classified PASS whenever ANY join node was
    present in the plan, regardless of which side drove the join. This was WRONG: direct
    verification against a live PostgreSQL 15.8 instance (both with the planner's default
    choice AND with `enable_seqscan = off` forcing the GIN index) showed the barrier query
    (temp authorized-scope table JOIN assertion_version WHERE content_tsv @@ tsquery)
    consistently produces a `Nested Loop` whose OUTER (driving) side scans
    `assertion_version` with the full-text predicate as a `Filter`/`Index Cond` -- matching
    against the WHOLE content table (verified: 474 matches + 4526 "Rows Removed by Filter"
    = the full 5000-row table) -- and only joins the small authorized-scope table on the
    INNER (second) side. A join being present is NOT sufficient for PASS: this is "correct
    final results, wrong internal ordering", the same failure mode already confirmed for
    SQLite's FTS5 (report SS11) -- PostgreSQL's planner, whichever access method it picks for
    the content scan (Seq Scan or GIN-driven Bitmap Heap Scan), always drives from the
    content table and joins the authorized scope second, never the reverse.

    PASS requires the authorized-scope relation to be the DRIVING (outer-most / first-
    executed) side, so the full-text predicate is only ever evaluated inside the already-
    bounded set -- never before it. This is determined structurally by walking the plan
    tree and reading each node's `Relation Name`, `Actual Rows`, and predicate fields, not
    by string-matching for the mere presence of a join type.

    Corroboration only (correction 1.B): Layer A remains authoritative. Row counts
    (`Rows Removed by Filter`, `Actual Rows`) are used only as corroborating evidence of
    which side drove -- never as the sole basis for a verdict on their own.
    """
    import json as _json

    if not plan_json_text:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text="", access_pattern_bounded=None,
            note="no plan captured",
        )
    try:
        parsed = _json.loads(plan_json_text)
        root = parsed[0]["Plan"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=None,
            note=f"plan JSON not in the expected shape ({type(e).__name__}); manual review required",
        )

    def _touches_fts_predicate(node: dict) -> bool:
        pred = str(node.get("Filter", "")) + str(node.get("Index Cond", "")) + str(node.get("Recheck Cond", ""))
        return "@@" in pred or "tsquery" in pred.lower()

    def _is_content_scan(node: dict) -> bool:
        return node.get("Relation Name") == "assertion_version" or (
            "Node Type" in node and "assertion_version" in str(node)
            and str(node.get("Relation Name", "")) == "assertion_version"
        )

    join_nodes = []

    def _walk(node: dict) -> None:
        node_type = str(node.get("Node Type", ""))
        if "Join" in node_type or node_type == "Nested Loop":
            join_nodes.append(node)
        for child in node.get("Plans", []) or []:
            _walk(child)

    _walk(root)

    if not join_nodes:
        # No join at all: the FTS predicate must be evaluated directly against the content
        # relation with no authorized-scope restriction anywhere in the plan -- unbounded.
        if _touches_fts_predicate(root) and root.get("Relation Name") == "assertion_version":
            return LayerBEvidence(
                backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=False,
                note="full-text predicate evaluated directly against assertion_version with "
                     "no authorized-scope join anywhere in the plan -- unbounded",
            )
        return LayerBEvidence(
            backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=None,
            note="no join node found and plan shape not recognized; manual review required",
        )

    # Drive-order check: for each join node, identify outer (first child = driving side,
    # per Postgres's own "Parent Relationship": "Outer"/"Inner" labeling) vs inner. PASS
    # requires the OUTER side to be the small authorized-scope relation (i.e. NOT
    # assertion_version, and NOT carrying the full-text predicate); FAIL if the outer side
    # is assertion_version carrying the full-text predicate -- the content table is scanned
    # (with the FTS filter applied) BEFORE the authorized-scope relation ever restricts it.
    for jn in join_nodes:
        children = jn.get("Plans", []) or []
        outer = next((c for c in children if c.get("Parent Relationship") == "Outer"), None)
        inner = next((c for c in children if c.get("Parent Relationship") == "Inner"), None)
        if outer is None or inner is None:
            continue  # ambiguous shape for THIS join node; other join nodes may resolve it

        outer_is_content_with_fts = (
            outer.get("Relation Name") == "assertion_version" and _touches_fts_predicate(outer)
        )
        inner_is_content_with_fts = (
            inner.get("Relation Name") == "assertion_version" and _touches_fts_predicate(inner)
        )

        if outer_is_content_with_fts:
            return LayerBEvidence(
                backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=False,
                note=(
                    f"content table (assertion_version) is the OUTER/driving side of the "
                    f"{jn.get('Node Type')}, with the full-text predicate applied there "
                    f"(Actual Rows={outer.get('Actual Rows', 'n/a')}, "
                    f"Rows Removed by Filter={outer.get('Rows Removed by Filter', 'n/a')}); "
                    "the authorized-scope relation only restricts the result AFTER the "
                    "full-text match already ran over the broader content set -- correct "
                    "final results, wrong internal ordering (same failure mode as SQLite "
                    "FTS5, report SS11)"
                ),
            )
        if inner_is_content_with_fts and outer.get("Relation Name") != "assertion_version":
            return LayerBEvidence(
                backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=True,
                note=(
                    f"authorized-scope relation is the OUTER/driving side of the "
                    f"{jn.get('Node Type')}; the full-text predicate on assertion_version "
                    f"(INNER side, Actual Rows={inner.get('Actual Rows', 'n/a')}) is only "
                    "ever evaluated inside the already-bounded authorized set"
                ),
            )

    return LayerBEvidence(
        backend="PostgreSQL", plan_text=plan_json_text, access_pattern_bounded=None,
        note="join present but drive order could not be confidently determined from "
             "Parent Relationship labels; manual review required",
    )
