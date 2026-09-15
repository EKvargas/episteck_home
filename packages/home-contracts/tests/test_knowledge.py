from __future__ import annotations

from datetime import UTC, datetime

import pytest

from episteck_home_contracts import (
    KnowledgeClaim,
    KnowledgeEpisode,
    KnowledgeProvenance,
    KnowledgeScope,
    KnowledgeScopeType,
    KnowledgeStatus,
)


def _hypothesis() -> KnowledgeClaim:
    return KnowledgeClaim(
        claim_id="claim-hypothesis",
        scope=KnowledgeScope(KnowledgeScopeType.PERSON, "PSN-B"),
        subject_person_ids=("PSN-B",),
        domain="NUTRITION",
        statement="Synthetic preference may be vegetarian",
        provenance=KnowledgeProvenance.AI_HYPOTHESIS,
        author_person_id=None,
        source_episode_id="episode-conversation",
        status=KnowledgeStatus.PROPOSED,
    )


def test_contract_enums_are_exact():
    assert {value.value for value in KnowledgeScopeType} == {"PERSON", "CIRCLE"}
    assert {value.value for value in KnowledgeProvenance} == {
        "USER_EXPLICIT",
        "USER_CONFIRMED",
        "IMPORTED_SOURCE",
        "PROFESSIONAL_PROVIDED",
        "SYSTEM_OBSERVED",
        "AI_HYPOTHESIS",
        "AI_SUMMARY",
        "DERIVED",
    }
    assert {value.value for value in KnowledgeStatus} == {
        "PROPOSED",
        "ACTIVE",
        "SUPERSEDED",
        "DISPUTED",
        "REVOKED",
        "EXPIRED",
    }


def test_episode_preserves_source_and_capture_time():
    captured = datetime(2026, 9, 15, tzinfo=UTC)
    episode = KnowledgeEpisode(
        "episode-conversation", "CONVERSATION", captured, "conversation:synthetic-1"
    )
    assert episode.captured_at is captured
    assert episode.source_ref == "conversation:synthetic-1"


def test_ai_hypothesis_cannot_be_active_without_confirmation():
    with pytest.raises(ValueError, match="AI_HYPOTHESIS must remain PROPOSED"):
        KnowledgeClaim(
            claim_id="claim-bad",
            scope=KnowledgeScope(KnowledgeScopeType.PERSON, "PSN-B"),
            subject_person_ids=("PSN-B",),
            domain="NUTRITION",
            statement="Synthetic hypothesis",
            provenance=KnowledgeProvenance.AI_HYPOTHESIS,
            author_person_id=None,
            source_episode_id="episode-source",
            status=KnowledgeStatus.ACTIVE,
        )


def test_hypothesis_confirmation_requires_explicit_confirmation_episode():
    with pytest.raises(ValueError, match="confirmation episode"):
        _hypothesis().confirm("claim-confirmed", "", "PSN-A")


def test_hypothesis_confirmation_creates_new_sourced_claim():
    hypothesis = _hypothesis()
    confirmed = hypothesis.confirm(
        "claim-confirmed", "episode-confirmation", "PSN-A"
    )
    assert confirmed.provenance is KnowledgeProvenance.USER_CONFIRMED
    assert confirmed.status is KnowledgeStatus.ACTIVE
    assert confirmed.source_episode_id == "episode-confirmation"
    assert confirmed.supersedes_claim_id == hypothesis.claim_id
    assert hypothesis.provenance is KnowledgeProvenance.AI_HYPOTHESIS
    assert hypothesis.status is KnowledgeStatus.PROPOSED


def test_lifecycle_transition_preserves_provenance_and_source():
    claim = _hypothesis()
    disputed = claim.transition(KnowledgeStatus.DISPUTED)
    assert disputed.provenance is KnowledgeProvenance.AI_HYPOTHESIS
    assert disputed.source_episode_id == claim.source_episode_id


def test_obvious_secret_material_is_rejected():
    with pytest.raises(ValueError, match="credentials and secrets"):
        KnowledgeClaim(
            claim_id="claim-secret",
            scope=KnowledgeScope(KnowledgeScopeType.PERSON, "PSN-B"),
            subject_person_ids=("PSN-B",),
            domain="KNOWLEDGE",
            statement="password=synthetic-do-not-store",
            provenance=KnowledgeProvenance.USER_EXPLICIT,
            author_person_id="PSN-B",
            source_episode_id="episode-form",
        )
