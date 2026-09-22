"""P8: grant/lifecycle change between selection and disclosure (H8).
P9: classification revision invalidates stale materialization (H6/B2).
P11: stale cache/index binding (H6).
"""
from __future__ import annotations

from home_stub.stub import Grant, HomeStub
from scenarios.orchestration import run_knowledge_query

AS_OF = 2_000_000_000
DOMAINS = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")


def test_p8_rt2_denies_after_authority_revoked_between_rt1_and_rt2(loaded_backend):
    """P8: RT#2 is a fresh re-evaluation, not a TTL check. If authority is revoked after
    RT#1 selected candidates but before disclosure, RT#2 must deny -- proving the change
    was detected AT the barrier, not by any cached expiry."""
    backend, corpus = loaded_backend
    p0 = corpus.persons[0]
    grants = tuple(Grant(p0, p0, d, "VIEW", corpus.partitions[0]) for d in DOMAINS) + (
        Grant(p0, p0, "KNOWLEDGE", "VIEW", corpus.partitions[0]),
    )
    home = HomeStub(grants=grants)

    # Interleave: mutate authority mid-flow by wrapping evaluate_plan. We simulate this by
    # running RT#1 manually via a two-step orchestration: run without revalidation (gets
    # candidates through RT#1), THEN revoke, THEN request revalidation-only via a second
    # full query using revalidate=True but with grants already gone -- this exercises RT#2
    # denying even though the candidate set was legitimately produced by a real RT#1.
    home.mutate_authority(revoke=grants)  # revoke BEFORE any call: proves RT#1 itself is live, not cached
    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF,
    )
    assert result.denied, "with authority already revoked, RT#1 itself must deny (fresh check, no stale cache)"

    # Now the direct RT#2-specific case: authority present through RT#1, revoked before
    # RT#2 fires. Orchestration's revalidate=True calls evaluate_plan a second time on the
    # SAME home instance, so mutating between is observable if we drive it manually.
    home2 = HomeStub(grants=grants)
    from home_stub.stub import AuthorizationOperation

    op = AuthorizationOperation(
        operation_id="p8-op", actor_person_id=p0, subject_person_ids=(p0,), domains=(DOMAINS[0],),
        action="VIEW", partition_id=corpus.partitions[0],
    )
    rt1 = home2.evaluate_plan((op,), version_pool={"p8-op": frozenset({"v1"})})
    assert rt1.all_allowed(), "RT#1 must allow while authority is intact"

    home2.mutate_authority(revoke=grants)  # revoke strictly between RT#1 and RT#2

    rt2 = home2.evaluate_plan((op,), version_pool={"p8-op": frozenset({"v1"})})
    assert not rt2.all_allowed(), "RT#2 must deny once authority changed -- proves fresh re-evaluation, not TTL"
    assert home2.home_auth_round_trip_count == 2


def test_p9_classification_revision_invalidates_binding_immediately(loaded_backend):
    """P9: a materialization binding built at classification_revision=1 whose SOURCE row
    was later bumped to classification_revision=2 must be detected stale IMMEDIATELY,
    without a rebuild -- H6/B2 SS10.3."""
    backend, corpus = loaded_backend
    stale_bindings = [
        b for b in corpus.bindings
        if any(
            a.version_id == b.source_version_id and a.classification_revision != b.classification_revision_at_build
            for a in corpus.assertions
        )
    ]
    assert stale_bindings, "fixture must include at least one stale-classification binding"
    stale = stale_bindings[0]

    is_current = backend.materialization_binding_current(stale.binding_id)
    assert is_current is False, "a binding whose source classification moved must report NOT current, detected via the binding record alone (no rebuild)"


def test_p9_fresh_binding_reports_current(loaded_backend):
    """Control group: a binding built at the CURRENT classification/control revision must
    report current -- proves the check isn't just always-false."""
    backend, corpus = loaded_backend
    fresh_bindings = [
        b for b in corpus.bindings
        if any(
            a.version_id == b.source_version_id and a.classification_revision == b.classification_revision_at_build
            and a.control_revision == b.control_revision_at_build
            for a in corpus.assertions
        )
    ]
    assert fresh_bindings, "fixture must include at least one fresh binding as a control"
    fresh = fresh_bindings[0]
    assert backend.materialization_binding_current(fresh.binding_id) is True


def test_p11_unknown_binding_fails_closed(loaded_backend):
    """P11: a binding_id that does not exist in the register must fail closed (return
    None / unknown), never silently treated as current."""
    backend, corpus = loaded_backend
    result = backend.materialization_binding_current("BIND-DOES-NOT-EXIST-999")
    assert result is None, "unknown binding state must be distinguishable from 'current' -- caller fails closed on None"
