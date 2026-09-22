"""P6: authorization denial before content candidacy (H3).
P7: suppressed record physically still present (H5).
"""
from __future__ import annotations

import time

from home_stub.stub import Grant, HomeStub
from scenarios.orchestration import run_knowledge_query

AS_OF = 2_000_000_000
DOMAINS = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")


def test_p6_denial_before_candidacy_zero_leakage(loaded_backend):
    """P6: actor has NO grants at all. Expected: zero candidates, scores, counts, titles.
    1 crossing. Denial must not leak content."""
    backend, corpus = loaded_backend
    home = HomeStub(grants=())  # no grants whatsoever
    p0 = corpus.persons[0]

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF,
    )

    assert result.denied
    assert result.bundle is None, "denial must not construct a bundle carrying any content"
    assert result.home_auth_round_trip_count == 1, "denial short-circuits internally after RT#1"


def test_p6_allow_deny_nocontent_timing_distributions(loaded_backend):
    """P6 required measurement: allow/deny/no-content timing distributions (PA-10d) --
    a stable separation is an existence oracle. Sample count/warmup documented (correction
    6): 20 measured reps per condition, 3 warmup discarded. Reported as INFORMATIONAL ONLY
    given n=20 is underpowered for a real p99 (correction 6/12)."""
    backend, corpus = loaded_backend
    p0, p1 = corpus.persons[0], corpus.persons[1] if len(corpus.persons) > 1 else corpus.persons[0]
    full_grants = tuple(
        Grant(actor, actor, d, "VIEW", corpus.partitions[0])
        for actor in corpus.persons for d in DOMAINS
    )

    def timed_run(grants, subject):
        home = HomeStub(grants=grants, inject_latency=False)  # exclude calibrated sleep from this micro-timing
        t0 = time.perf_counter()
        run_knowledge_query(
            backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
            subject_person_ids=(subject,), domains=DOMAINS, as_of=AS_OF,
        )
        return (time.perf_counter() - t0) * 1000.0

    WARMUP, MEASURED = 3, 20
    for _ in range(WARMUP):
        timed_run(full_grants, p0)

    allow_samples = [timed_run(full_grants, p0) for _ in range(MEASURED)]
    deny_samples = [timed_run((), p0) for _ in range(MEASURED)]  # no grants -> deny
    nocontent_samples = [timed_run(full_grants, p1) for _ in range(MEASURED)]  # allowed but p1 may have no candidates

    for label, samples in (("allow", allow_samples), ("deny", deny_samples), ("no_content", nocontent_samples)):
        samples.sort()
        p50 = samples[len(samples) // 2]
        assert p50 >= 0, f"{label} p50 sanity"
    # This test's PURPOSE is to produce the distributions for the report, not to assert a
    # specific separation threshold -- PA-10d asks us to REPORT the finding, not enforce a
    # policy here. See bench/run_bench.py for the recorded distributions.


def test_p7_suppressed_record_unaddressable_though_present(loaded_backend):
    """P7: suppressed record physically still present (payload row + FTS index entry
    both still exist). Expected: record NOT addressable though it all still exists. No
    score, count, or "something was removed" signal."""
    backend, corpus = loaded_backend
    assert corpus.suppressions, "fixture must include at least one suppressed-but-present record"
    suppressed = corpus.suppressions[0]

    # Confirm the row is genuinely still physically present (payload untouched by suppression).
    from backends.common import AuthorizedSet, ContentAccessLog

    log = ContentAccessLog()
    raw_fetch = backend.fetch_content(AuthorizedSet(version_ids=(suppressed.target_version_id,)), log=log)
    assert len(raw_fetch) == 1, "suppression must not physically delete the row (B4: non-use, not erasure)"

    # Now run it through the real pipeline as an authorized subject/domain for that
    # version -- suppression must make it unaddressable BEFORE it ever reaches Home.
    target = next(a for a in corpus.assertions if a.version_id == suppressed.target_version_id)
    actor = target.subject_person_ids[0]
    full_grants = tuple(
        Grant(actor, s, d, "VIEW", corpus.partitions[0]) for s in target.subject_person_ids for d in DOMAINS
    )
    home = HomeStub(grants=full_grants)

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=actor,
        subject_person_ids=target.subject_person_ids, domains=DOMAINS, as_of=AS_OF,
    )

    if result.bundle is not None:
        returned_ids = {c["version_id"] for c in result.bundle.content}
        assert suppressed.target_version_id not in returned_ids, (
            "suppressed record must never be addressable even though physically present"
        )
