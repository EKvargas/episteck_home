"""CORRECTION 1 (Product Architect review of PR #33): adversarial proof that a Knowledge
authorization operation is genuinely all-or-nothing over the COMPLETE union
(subject, domain) requirement set -- not just the first domain, and not just the
requesting actor's own subject.

Uses a hand-built two-subject, two-domain assertion (rather than the seeded corpus, whose
multi-subject candidates are randomly distributed) so each case is deterministic and the
missing requirement is exactly known.
"""
from __future__ import annotations

from backends.model import AssertionVersion, Corpus, GrantRecord, LifecycleState
from backends.sqlite_backend import SQLiteKnowledgeBackend
from home_stub.stub import Grant, HomeStub
from scenarios.orchestration import run_knowledge_query

PARTITION = "PART-COMPLETE-REQ"
AS_OF = 2_000_000_000


def _two_subject_two_domain_corpus() -> Corpus:
    """One assertion naming subjects {P1, P2} and domains {NUTRITION, HEALTH} --
    disclosing it requires authorization for ALL FOUR (subject, domain) pairs plus the
    KNOWLEDGE-scope requirement for both subjects."""
    assertion = AssertionVersion(
        version_id="V-COMPOUND-1",
        partition_id=PARTITION,
        line_id="LINE-COMPOUND-1",
        subject_person_ids=("P1", "P2"),
        domains=("NUTRITION", "HEALTH"),
        content_text="synthetic compound assertion naming two subjects and two domains",
        lifecycle_state=LifecycleState.ADMITTED,
        classification_revision=1,
        control_revision=1,
        applicable_from=AS_OF - 1000,
        applicable_until=None,
    )
    return Corpus(
        seed=1, size_label="C-hand-built", partitions=(PARTITION,), persons=("P1", "P2"),
        circles=(), assertions=(assertion,), suppressions=(), bindings=(), grants=(),
    )


def _backend_with_corpus():
    corpus = _two_subject_two_domain_corpus()
    be = SQLiteKnowledgeBackend()
    be.load_corpus(corpus)
    return be, corpus


def test_missing_second_person_grant_denies_whole_operation():
    """Actor is authorized for P1 (both domains + KNOWLEDGE) but NOT for P2 at all --
    the whole compound operation must be denied, not disclosed with P2's requirement
    silently dropped."""
    be, corpus = _backend_with_corpus()
    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", PARTITION),
        Grant("P1", "P1", "HEALTH", "VIEW", PARTITION),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", PARTITION),
        # deliberately NO grants naming P2 as subject
    ))

    result = run_knowledge_query(
        backend=be, home=home, partition_id=PARTITION, actor_person_id="P1",
        subject_person_ids=("P1", "P2"), domains=("NUTRITION", "HEALTH"), as_of=AS_OF,
    )

    assert result.denied
    assert result.bundle is None
    assert result.missing_requirement is not None
    assert result.missing_requirement[0] == "P2", "must fail on the missing P2 requirement, not silently drop it"
    be.close()


def test_missing_second_domain_grant_denies_whole_operation():
    """Actor is authorized for BOTH subjects on NUTRITION + KNOWLEDGE, but not HEALTH --
    the whole operation must deny; the assertion must not become addressable merely
    because its NUTRITION-relevant content could be disclosed."""
    be, corpus = _backend_with_corpus()
    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", PARTITION),
        Grant("P1", "P2", "NUTRITION", "VIEW", PARTITION),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", PARTITION),
        Grant("P1", "P2", "KNOWLEDGE", "VIEW", PARTITION),
        # deliberately NO HEALTH grants
    ))

    result = run_knowledge_query(
        backend=be, home=home, partition_id=PARTITION, actor_person_id="P1",
        subject_person_ids=("P1", "P2"), domains=("NUTRITION", "HEALTH"), as_of=AS_OF,
    )

    assert result.denied
    assert result.bundle is None
    assert result.missing_requirement is not None
    assert result.missing_requirement[1] == "HEALTH", "must fail on the missing HEALTH requirement"
    be.close()


def test_missing_knowledge_scope_grant_denies_whole_operation():
    """Actor holds both domains for both subjects but never received the separate
    KNOWLEDGE-scope grant B1/B6 require in addition to per-domain authorization."""
    be, corpus = _backend_with_corpus()
    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", PARTITION),
        Grant("P1", "P2", "NUTRITION", "VIEW", PARTITION),
        Grant("P1", "P1", "HEALTH", "VIEW", PARTITION),
        Grant("P1", "P2", "HEALTH", "VIEW", PARTITION),
        # deliberately NO KNOWLEDGE-scope grants
    ))

    result = run_knowledge_query(
        backend=be, home=home, partition_id=PARTITION, actor_person_id="P1",
        subject_person_ids=("P1", "P2"), domains=("NUTRITION", "HEALTH"), as_of=AS_OF,
    )

    assert result.denied
    assert result.missing_requirement is not None
    assert result.missing_requirement[1] == "KNOWLEDGE", "must fail on the missing KNOWLEDGE scope requirement"
    be.close()


def test_partition_mismatch_denies():
    """A grant that names the wrong partition must not satisfy the requirement -- the
    partition is part of the trusted binding, not a filter parameter (H1)."""
    be, corpus = _backend_with_corpus()
    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", "WRONG-PARTITION"),
        Grant("P1", "P2", "NUTRITION", "VIEW", "WRONG-PARTITION"),
        Grant("P1", "P1", "HEALTH", "VIEW", "WRONG-PARTITION"),
        Grant("P1", "P2", "HEALTH", "VIEW", "WRONG-PARTITION"),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", "WRONG-PARTITION"),
        Grant("P1", "P2", "KNOWLEDGE", "VIEW", "WRONG-PARTITION"),
    ))

    result = run_knowledge_query(
        backend=be, home=home, partition_id=PARTITION, actor_person_id="P1",
        subject_person_ids=("P1", "P2"), domains=("NUTRITION", "HEALTH"), as_of=AS_OF,
    )

    assert result.denied, "grants scoped to a different partition must not satisfy the requirement"
    be.close()


def test_every_requirement_present_succeeds_and_content_addressable():
    """Control group: every (subject, domain) pair including KNOWLEDGE scope, correct
    partition -- the candidate must become addressable and its content disclosed."""
    be, corpus = _backend_with_corpus()
    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", PARTITION),
        Grant("P1", "P2", "NUTRITION", "VIEW", PARTITION),
        Grant("P1", "P1", "HEALTH", "VIEW", PARTITION),
        Grant("P1", "P2", "HEALTH", "VIEW", PARTITION),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", PARTITION),
        Grant("P1", "P2", "KNOWLEDGE", "VIEW", PARTITION),
    ))

    result = run_knowledge_query(
        backend=be, home=home, partition_id=PARTITION, actor_person_id="P1",
        subject_person_ids=("P1", "P2"), domains=("NUTRITION", "HEALTH"), as_of=AS_OF,
    )

    assert not result.denied, result.deny_reason
    assert result.bundle is not None
    returned_ids = {c["version_id"] for c in result.bundle.content}
    assert "V-COMPOUND-1" in returned_ids
    be.close()


def test_no_content_access_occurs_before_complete_operation_passes():
    """Even when the compound operation is denied, the content-access API must never
    have been called for the candidate -- the barrier must block BEFORE content access,
    not merely omit the result afterward."""
    be, corpus = _backend_with_corpus()
    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", PARTITION),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", PARTITION),
    ))

    # Monkeypatch fetch_content to detect any call -- the orchestration must never reach
    # this stage when Home denies the compound operation.
    original_fetch = be.fetch_content
    call_count = {"n": 0}

    def spy_fetch(*args, **kwargs):
        call_count["n"] += 1
        return original_fetch(*args, **kwargs)

    be.fetch_content = spy_fetch

    result = run_knowledge_query(
        backend=be, home=home, partition_id=PARTITION, actor_person_id="P1",
        subject_person_ids=("P1", "P2"), domains=("NUTRITION", "HEALTH"), as_of=AS_OF,
    )

    assert result.denied
    assert call_count["n"] == 0, "content access must never be attempted when the compound operation is denied"
    be.close()
